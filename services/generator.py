"""
OpenAI 兼容 Chat Completions 生图服务。
按 API 接入文档：外层 model + 内层 json.dumps(NAI payload)。
"""

import asyncio
import json
import struct
import time
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from astrbot.api import logger

from ..core.constants import (
    DEFAULT_ARTISTS,
    DEFAULT_NEGATIVE,
    IMAGE_SIZES,
    LOG_TAG,
)
from ..core.image import extract_image_from_content, extract_seeds
from ..core.outfit import resolve_outfit_context
from .translator import TranslateService


class GenerateService:
    """封装文生图全流程：outfit → 转译 → 模板 → 画师串 → API。"""

    def __init__(
        self,
        *,
        session: Optional[aiohttp.ClientSession],
        base_url: str,
        api_key: str,
        model: str,
        steps: int,
        scale: float,
        sampler: str,
        noise_schedule: str,
        negative: str,
        seed: int,
        quality: bool,
        uc_preset: str,
        variety_boost: bool,
        cfg_rescale: float,
        max_tokens: int,
        enable_template: bool,
        character_preset: str,
        default_outfit: str,
        outfit_cache_ttl: int,
        translator: TranslateService,
        artist_presets: Optional[List[str]] = None,
        session_artist: Optional[Dict[str, str]] = None,
    ) -> None:
        self.session = session
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model
        self.steps = steps
        self.scale = scale
        self.sampler = sampler
        self.noise_schedule = noise_schedule
        self.negative = negative or DEFAULT_NEGATIVE
        self.seed = seed
        self.quality = quality
        self.uc_preset = uc_preset
        self.variety_boost = variety_boost
        self.cfg_rescale = cfg_rescale
        self.max_tokens = max_tokens
        self.enable_template = enable_template
        self.character_preset = character_preset or ""
        self.default_outfit = default_outfit or ""
        self.outfit_cache_ttl = outfit_cache_ttl
        self.translator = translator
        self.artist_presets = artist_presets or []
        self.session_artist = session_artist if session_artist is not None else {}

        self.outfit_cache_text: Optional[str] = None
        self.outfit_cache_expires_at: Optional[float] = None

    # ---- outfit cache ----
    def outfit_cache_get(self) -> Optional[str]:
        if self.outfit_cache_text is None:
            return None
        if (
            self.outfit_cache_expires_at is not None
            and time.monotonic() > self.outfit_cache_expires_at
        ):
            self.outfit_cache_clear()
            return None
        return self.outfit_cache_text

    def outfit_cache_set(self, text: str) -> None:
        cleaned = (text or "").strip()
        if not cleaned:
            return
        self.outfit_cache_text = cleaned
        if self.outfit_cache_ttl > 0:
            self.outfit_cache_expires_at = time.monotonic() + self.outfit_cache_ttl
        else:
            self.outfit_cache_expires_at = None

    def outfit_cache_clear(self) -> None:
        self.outfit_cache_text = None
        self.outfit_cache_expires_at = None

    # ---- resolvers ----
    def resolve_size(self, size: Any) -> List[int]:
        if isinstance(size, list) and len(size) == 2:
            try:
                return [int(size[0]), int(size[1])]
            except (TypeError, ValueError):
                return [832, 1216]
        if isinstance(size, str) and "x" in size.lower():
            try:
                w, h = size.lower().split("x", 1)
                return [int(w), int(h)]
            except Exception:
                pass
        return IMAGE_SIZES.get(size, [832, 1216])

    def resolve_artists(self, style: str, session_key: str = "") -> str:
        if style != "custom":
            return DEFAULT_ARTISTS.get(style, DEFAULT_ARTISTS["vertical"])

        if session_key and session_key in self.session_artist:
            preset_name = self.session_artist[session_key]
            if preset_name == "none":
                return ""
            for preset in self.artist_presets:
                name = preset.split(":", 1)[0] if isinstance(preset, str) else ""
                if name == preset_name:
                    return preset.split(":", 1)[1] if ":" in preset else ""

        if self.artist_presets:
            preset = self.artist_presets[0]
            return preset.split(":", 1)[1] if ":" in preset else ""
        return ""

    def build_full_prompt(self, user_prompt: str, character_preset: Optional[str] = None) -> str:
        preset = self.character_preset if character_preset is None else character_preset
        if not self.enable_template or not preset:
            return user_prompt.strip()
        return f"{preset}, {user_prompt.strip()}"

    # ---- API call ----
    def _build_request(
        self,
        final_prompt: str,
        size_array: List[int],
        *,
        steps: int,
        scale: float,
        sampler: str,
        noise_schedule: str,
        negative: str,
        model: str,
        seed: int,
        quality: bool,
        uc_preset: str,
        variety_boost: bool,
        cfg_rescale: float,
        max_tokens: int,
        token: str,
        inpaint: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, Dict[str, str], Dict[str, Any]]:
        nai_payload: Dict[str, Any] = {
            "prompt": final_prompt,
            "negative_prompt": negative,
            "size": size_array,
            "steps": steps,
            "scale": scale,
            "sampler": sampler,
            "noise_schedule": noise_schedule,
            "image_format": "png",
            "n_samples": 1,
            "uc_preset": uc_preset,
        }
        if quality:
            nai_payload["quality"] = True
        if variety_boost:
            nai_payload["variety_boost"] = True
        if cfg_rescale > 0:
            nai_payload["cfg_rescale"] = cfg_rescale
        if seed and seed > 0:
            nai_payload["seed"] = seed
        if inpaint:
            # API 文档 §20.2：局部重绘；add_original_image 避免 mask 外变黑
            ip = dict(inpaint)
            if "add_original_image" not in ip:
                ip["add_original_image"] = True
            nai_payload["inpaint"] = ip

        request_body = {
            "model": model,
            "messages": [{"role": "user", "content": json.dumps(nai_payload)}],
            "stream": False,
            "max_tokens": max_tokens,
        }
        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        return url, headers, request_body

    async def _post_generate(
        self,
        url: str,
        headers: Dict[str, str],
        request_body: Dict[str, Any],
        tag: str = "generate",
    ) -> Tuple[Optional[bytes], str, List[Optional[int]]]:
        if not self.session:
            return None, "no_session", []
        start = time.perf_counter()
        try:
            async with self.session.post(
                url,
                json=request_body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=180),
            ) as resp:
                elapsed = time.perf_counter() - start
                if resp.status != 200:
                    err_code = ""
                    err_msg = ""
                    try:
                        err_body = await resp.json()
                        err_obj = err_body.get("error", {})
                        err_code = err_obj.get("code", "")
                        err_msg = err_obj.get("message", "")
                    except Exception:
                        try:
                            err_msg = (await resp.text())[:500]
                        except Exception:
                            pass
                    if 400 <= resp.status < 500:
                        reason = "http_4xx"
                    elif 500 <= resp.status < 600:
                        reason = "http_5xx"
                    else:
                        reason = "http_other"
                    parts = [reason, f"HTTP {resp.status}"]
                    if err_code:
                        parts.append(err_code)
                    if err_msg:
                        parts.append(err_msg)
                    full_reason = " | ".join(parts)
                    logger.warning(
                        f"{LOG_TAG} [{tag}] 失败 | reason={reason} "
                        f"status={resp.status} code={err_code} "
                        f"msg={err_msg[:200]} elapsed={elapsed:.2f}s"
                    )
                    return None, full_reason, []

                resp_data = await resp.json()
                content = (
                    resp_data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                if not content:
                    return None, "empty_response", []
                img_bytes = extract_image_from_content(content)
                seeds = extract_seeds(content)
                if not img_bytes:
                    logger.warning(
                        f"{LOG_TAG} [{tag}] 响应中未找到图片 | "
                        f"content='{content[:200]}'"
                    )
                    return None, "empty_response", []
                width = height = 0
                if len(img_bytes) >= 24 and img_bytes[:8] == b"\x89PNG\r\n\x1a\n":
                    width = struct.unpack(">I", img_bytes[16:20])[0]
                    height = struct.unpack(">I", img_bytes[20:24])[0]
                logger.info(
                    f"{LOG_TAG} [{tag}] 成功 | png={width}x{height} "
                    f"bytes={len(img_bytes)} seeds={seeds} elapsed={elapsed:.2f}s"
                )
                return img_bytes, "ok", seeds
        except asyncio.TimeoutError:
            return None, "timeout", []
        except Exception as e:
            logger.warning(f"{LOG_TAG} [{tag}] 异常: {e!r}")
            return None, "exception", []

    async def generate_one(
        self,
        prompt: str,
        style: str,
        size: str,
        session_key: str = "",
    ) -> Tuple[Optional[bytes], str]:
        """命令 / 代理 / LLM 工具用的标准生图。"""
        if not self.api_key:
            return None, "no_token"
        if not self.session:
            return None, "no_session"

        outfit_ctx, outfit_source, use_default = resolve_outfit_context(
            prompt,
            cache_get=self.outfit_cache_get,
            cache_set=self.outfit_cache_set,
            cache_ttl=self.outfit_cache_ttl,
            default_outfit=self.default_outfit,
        )
        if outfit_ctx:
            effective = (
                f"{prompt.rstrip()}\n\n"
                f"[延续上文穿搭或当前默认服装] {outfit_ctx}"
            )
            logger.info(
                f"{LOG_TAG} [outfit] source={outfit_source} "
                f"preview='{outfit_ctx[:60]}...'"
            )
        else:
            effective = prompt

        translated = await self.translator.translate(effective)
        full_prompt = self.build_full_prompt(translated)
        if use_default and self.default_outfit:
            full_prompt = f"{full_prompt}, {self.default_outfit}"

        artists = self.resolve_artists(style, session_key)
        final_prompt = f"{artists}, {full_prompt}" if artists else full_prompt
        size_array = self.resolve_size(size)

        logger.info(
            f"{LOG_TAG} [generate] style={style} size={size} "
            f"outfit={outfit_source if outfit_ctx else 'none'} "
            f"prompt='{final_prompt[:60]}...'"
        )

        url, headers, body = self._build_request(
            final_prompt,
            size_array,
            steps=self.steps,
            scale=self.scale,
            sampler=self.sampler,
            noise_schedule=self.noise_schedule,
            negative=self.negative,
            model=self.model,
            seed=self.seed,
            quality=self.quality,
            uc_preset=self.uc_preset,
            variety_boost=self.variety_boost,
            cfg_rescale=self.cfg_rescale,
            max_tokens=self.max_tokens,
            token=self.api_key,
        )
        img, reason, _seeds = await self._post_generate(url, headers, body, tag="generate")
        return img, reason

    async def generate_custom(
        self,
        prompt: str,
        style: str,
        size: str,
        *,
        steps: Optional[int] = None,
        scale: Optional[float] = None,
        sampler: Optional[str] = None,
        noise_schedule: Optional[str] = None,
        negative: Optional[str] = None,
        model: Optional[str] = None,
        custom_artists: Optional[str] = None,
        session_key: str = "",
        character_preset: Optional[str] = None,
        enable_template: Optional[bool] = None,
        enable_translate: Optional[bool] = None,
        token_override: Optional[str] = None,
        seed: Optional[int] = None,
        quality: Optional[bool] = None,
        uc_preset: Optional[str] = None,
        variety_boost: Optional[bool] = None,
        cfg_rescale: Optional[float] = None,
        inpaint: Optional[Dict[str, Any]] = None,
        skip_artists: bool = False,
    ) -> Tuple[Optional[bytes], str]:
        """面板用：全参数可覆盖的生图 / 局部重绘。"""
        token = token_override or self.api_key
        if not token:
            return None, "no_token"
        if not self.session:
            return None, "no_session"

        _steps = self.steps if steps is None else steps
        _scale = self.scale if scale is None else scale
        _sampler = self.sampler if sampler is None else sampler
        _noise = self.noise_schedule if noise_schedule is None else noise_schedule
        _negative = self.negative if negative is None else negative
        _model = self.model if model is None else model
        _enable_template = self.enable_template if enable_template is None else enable_template
        _enable_translate = (
            self.translator.enabled if enable_translate is None else enable_translate
        )
        _seed = self.seed if seed is None else seed
        _quality = self.quality if quality is None else quality
        _uc = self.uc_preset if uc_preset is None else uc_preset
        _variety = self.variety_boost if variety_boost is None else variety_boost
        _cfg = self.cfg_rescale if cfg_rescale is None else cfg_rescale
        _char = self.character_preset if character_preset is None else character_preset

        if skip_artists or inpaint:
            artists = ""
        elif custom_artists is not None:
            artists = custom_artists
        else:
            artists = self.resolve_artists(style, session_key)

        if _enable_translate:
            base_prompt = await self.translator.translate(prompt.strip(), force=True)
        else:
            base_prompt = prompt.strip()

        if _enable_template and _char and not inpaint:
            full_prompt = f"{_char}, {base_prompt}"
        else:
            full_prompt = base_prompt

        final_prompt = f"{artists}, {full_prompt}" if artists else full_prompt
        size_array = self.resolve_size(size)

        logger.info(
            f"{LOG_TAG} [generate:custom] style={style} size={size} "
            f"steps={_steps} scale={_scale} sampler={_sampler} "
            f"model={_model} inpaint={'Y' if inpaint else 'N'} "
            f"prompt='{final_prompt[:60]}...'"
        )

        url, headers, body = self._build_request(
            final_prompt,
            size_array,
            steps=_steps,
            scale=_scale,
            sampler=_sampler,
            noise_schedule=_noise,
            negative=_negative,
            model=_model,
            seed=_seed,
            quality=_quality,
            uc_preset=_uc,
            variety_boost=_variety,
            cfg_rescale=_cfg,
            max_tokens=self.max_tokens,
            token=token,
            inpaint=inpaint,
        )
        img, reason, _seeds = await self._post_generate(
            url, headers, body, tag="generate:custom"
        )
        return img, reason

    async def check_status(self) -> Tuple[bool, int]:
        """GET /v1/models 探测上游。"""
        if not self.session:
            return False, -1
        start = time.perf_counter()
        try:
            url = f"{self.base_url}/v1/models"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with self.session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                latency = int((time.perf_counter() - start) * 1000)
                ok = resp.status == 200
                logger.info(
                    f"{LOG_TAG} [status] {'可用' if ok else '不可用'} | "
                    f"status={resp.status} latency={latency}ms"
                )
                return ok, latency
        except Exception as e:
            logger.warning(f"{LOG_TAG} [status] 检查失败: {e!r}")
            return False, -1
