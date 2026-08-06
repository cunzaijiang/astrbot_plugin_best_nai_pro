"""
AstrBot 魔法绘图插件 v0.3.5

功能：
- 基于 OpenAI 兼容 API 的 NovelAI 文生图
- 自然语言提示词转译
- 多风格 / 画师预设 / NSFW 开关
- 本地 Images 代理（陪伴插件）
- Studio Web 调试面板（文生图 / 局部重绘）
- 提示词反推（/反推：三级降级 PNG 元数据 / LLM+Danbooru / LLM 视觉）

作者: 存在酱
版本: 0.3.5
日期: 2026-08-06
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import aiohttp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, MessageEventResult, filter
from astrbot.api.message_components import Image as Img
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star, register
from astrbot.api.web import error_response, json_response
from astrbot.api.web import request as web_request

from .core.constants import (
    AVAILABLE_MODELS,
    DEFAULT_NEGATIVE,
    IMAGE_GEN_BASE_URL_DEFAULT,
    IMAGE_SIZES,
    IMAGE_STYLES,
    LOG_TAG,
    NSFW_FULL_MODEL,
    NSFW_SAFE_MODEL,
    PAGE_API_PREFIX,
    PLUGIN_NAME,
    PROXY_HOST,
    PROXY_PORT,
)
from .core.errors import format_generate_error
from .core.parse import parse_args
from .core.tag_extractor import TagExtractor
from .services.generator import GenerateService
from .services.proxy import LocalProxyServer
from .services.translator import TranslateService


@register(
    "astrbot_plugin_best_nai_pro",
    "存在酱",
    "基于 OpenAI 兼容 API 的 NovelAI 生图插件",
    "0.3.5",
)
class NAIGenerateImagePlugin(Star):
    """魔法绘图 — AstrBot 插件入口。"""

    def __init__(self, context: Context, config: dict):
        super().__init__(context, config)
        logger.info(f"{LOG_TAG} [init] 插件实例化开始")

        self.conf = config
        self.base_url: str = (
            (config.get("base_url") or IMAGE_GEN_BASE_URL_DEFAULT).strip()
            or IMAGE_GEN_BASE_URL_DEFAULT
        )
        self.image_gen_key: str = (config.get("image_gen_key") or "").strip()
        self.image_style: str = config.get("image_style") or "vertical"
        self.image_size: str = config.get("image_size") or "竖图"
        self.artist_presets: list = config.get("artist_presets") or []
        self._session_artist: dict = {}
        self.nsfw_safe_model = NSFW_SAFE_MODEL
        self.nsfw_full_model = NSFW_FULL_MODEL
        self.model: str = config.get("model") or self.nsfw_full_model
        self.nsfw_enabled: bool = self.model == self.nsfw_full_model

        try:
            self.steps: int = int(config.get("steps") or 28)
        except (TypeError, ValueError):
            self.steps = 28
        try:
            self.scale: float = float(config.get("scale") or 5)
        except (TypeError, ValueError):
            self.scale = 5.0
        try:
            self.seed: int = int(config.get("seed") or 0)
        except (TypeError, ValueError):
            self.seed = 0

        self.quality: bool = bool(config.get("quality", True))
        self.uc_preset: str = config.get("uc_preset") or "light"
        self.variety_boost: bool = bool(config.get("variety_boost", False))
        try:
            self.cfg_rescale: float = max(
                0.0, min(1.0, float(config.get("cfg_rescale") or 0))
            )
        except (TypeError, ValueError):
            self.cfg_rescale = 0.0
        self.sampler: str = config.get("sampler") or "k_euler_ancestral"
        self.noise_schedule: str = config.get("noise_schedule") or "karras"
        neg = config.get("negative")
        self.negative: str = neg if neg else DEFAULT_NEGATIVE
        self.enable_template: bool = bool(config.get("enable_template", True))
        self.character_preset: str = (config.get("character_preset") or "").strip()
        self.default_outfit: str = (config.get("default_outfit") or "").strip()
        try:
            self.outfit_cache_ttl_seconds: int = max(
                0, min(86400, int(config.get("outfit_cache_ttl_seconds") or 3600))
            )
        except (TypeError, ValueError):
            self.outfit_cache_ttl_seconds = 3600
        self.enable_translate: bool = bool(config.get("enable_translate", False))
        self.translate_provider: str = (config.get("translate_provider") or "").strip()
        self.enable_llm_tool: bool = bool(config.get("enable_llm_tool", False))
        try:
            self.max_tokens: int = int(config.get("max_tokens") or 100000)
        except (TypeError, ValueError):
            self.max_tokens = 100000
        try:
            self.proxy_port: int = int(config.get("proxy_port") or PROXY_PORT)
        except (TypeError, ValueError):
            self.proxy_port = PROXY_PORT

        # ── 提示词反推（/反推）配置 ──
        self.danbooru_api_url: str = (config.get("danbooru_api_url") or "").strip()
        self.retag_provider: str = (config.get("retag_provider") or "").strip()
        self.retag_show_source: bool = bool(config.get("retag_show_source", True))

        self._session: Optional[aiohttp.ClientSession] = None
        self.translator = TranslateService(
            context,
            enabled=self.enable_translate,
            provider_id=self.translate_provider,
        )
        self.generator = GenerateService(
            session=None,
            base_url=self.base_url,
            api_key=self.image_gen_key,
            model=self.model,
            steps=self.steps,
            scale=self.scale,
            sampler=self.sampler,
            noise_schedule=self.noise_schedule,
            negative=self.negative,
            seed=self.seed,
            quality=self.quality,
            uc_preset=self.uc_preset,
            variety_boost=self.variety_boost,
            cfg_rescale=self.cfg_rescale,
            max_tokens=self.max_tokens,
            enable_template=self.enable_template,
            character_preset=self.character_preset,
            default_outfit=self.default_outfit,
            outfit_cache_ttl=self.outfit_cache_ttl_seconds,
            translator=self.translator,
            artist_presets=self.artist_presets,
            session_artist=self._session_artist,
        )
        self.proxy = LocalProxyServer(
            port=self.proxy_port,
            api_key_getter=lambda: self.image_gen_key,
            session_ready=lambda: bool(self._session),
            generate_fn=self._generate_one,
            default_style=self.image_style,
            base_url=self.base_url,
        )

        logger.info(
            f"{LOG_TAG} [init] 配置加载完成 | "
            f"token={'已配置' if self.image_gen_key else '未配置'} | "
            f"base_url={self.base_url} | style={self.image_style} | "
            f"size={self.image_size} | model={self.model} | "
            f"proxy_port={self.proxy_port} max_tokens={self.max_tokens}"
        )

    # ---- lifecycle ----
    async def initialize(self):
        logger.info(f"{LOG_TAG} [initialize] 阶段开始")
        try:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=180)
            )
            self.generator.session = self._session
            logger.info(f"{LOG_TAG} [initialize] aiohttp session 创建成功")
        except Exception as e:
            logger.error(f"{LOG_TAG} [initialize] session 创建失败: {e!r}")

        await self.proxy.stop()
        last_err = None
        for attempt in range(1, 4):
            try:
                await self.proxy.start()
                last_err = None
                break
            except Exception as e:
                last_err = e
                logger.warning(
                    f"{LOG_TAG} [initialize] 代理启动失败 attempt={attempt}/3: {e!r}"
                )
                if attempt < 3:
                    await asyncio.sleep(1.0)
        if last_err is not None:
            logger.error(f"{LOG_TAG} [initialize] 代理最终启动失败: {last_err!r}")

        try:
            self.context.register_web_api(
                f"{PAGE_API_PREFIX}/config",
                self._studio_get_config,
                ["GET"],
                "魔法绘图 Studio：获取配置",
            )
            self.context.register_web_api(
                f"{PAGE_API_PREFIX}/generate",
                self._studio_generate,
                ["POST"],
                "魔法绘图 Studio：生图",
            )
            self.context.register_web_api(
                f"{PAGE_API_PREFIX}/save_cache",
                self._studio_save_cache,
                ["POST"],
                "魔法绘图 Studio：保存缓存",
            )
            self.context.register_web_api(
                f"{PAGE_API_PREFIX}/load_cache",
                self._studio_load_cache,
                ["GET"],
                "魔法绘图 Studio：加载缓存",
            )
            logger.info(
                f"{LOG_TAG} [initialize] Studio Web API 已注册 | prefix={PAGE_API_PREFIX}"
            )
        except Exception as e:
            logger.warning(f"{LOG_TAG} [initialize] 注册 Studio Web API 失败: {e!r}")

        logger.info(
            f"{LOG_TAG} [initialize] 完成 | token={'OK' if self.image_gen_key else 'MISSING'} | "
            f"proxy={'UP' if self.proxy.runner else 'DOWN'}"
        )

    async def terminate(self):
        logger.info(f"{LOG_TAG} [terminate] 阶段开始")
        try:
            await self.proxy.stop()
        except Exception as e:
            logger.warning(f"{LOG_TAG} [terminate] 关闭代理异常: {e!r}")
        if self._session and not self._session.closed:
            try:
                await self._session.close()
            except Exception as e:
                logger.warning(f"{LOG_TAG} [terminate] session 关闭异常: {e!r}")
        self.generator.outfit_cache_clear()
        logger.info(f"{LOG_TAG} [terminate] 完成")

    # ---- helpers ----
    def _persist_config(self, key: str, value: Any) -> None:
        try:
            self.conf[key] = value
            saved = False
            if hasattr(self.conf, "save_config") and callable(self.conf.save_config):
                self.conf.save_config()
                saved = True
            elif hasattr(self.context, "save_config"):
                self.context.save_config(self.conf)
                saved = True
            if not saved:
                logger.warning(f"{LOG_TAG} [persist_config] 原生保存不可用，仅更新内存")
            logger.info(f"{LOG_TAG} [persist_config] 已保存 | {key}={value}")
        except Exception as e:
            logger.warning(f"{LOG_TAG} [persist_config] 保存失败: {e!r}")

    async def _get_image_bytes(self, event: AstrMessageEvent) -> Optional[bytes]:
        """从消息事件中提取第一张图片的 bytes。

        兼容本地文件路径和远程 URL，同时支持从引用消息（reply）中提取图片。
        四级兜底：当前消息组件 -> message_obj.message -> 引用消息里的图 -> aiocqhttp CQ:image 原文。
        """
        import os as _os

        async def _fetch_image_comp(comp) -> Optional[bytes]:
            """从单个 Image 组件获取 bytes。"""
            try:
                # 优先用 convert_to_file_path（AstrBot 标准方式，自动处理 URL 下载和本地文件）
                if hasattr(comp, "convert_to_file_path"):
                    file_path = await comp.convert_to_file_path()
                    if file_path and _os.path.isfile(file_path):
                        with open(file_path, "rb") as f:
                            return f.read()

                # 备用：直接读 file/path 属性
                file_path = getattr(comp, "file", None) or getattr(comp, "path", None)
                if file_path and isinstance(file_path, str):
                    file_path = file_path.replace("file://", "")
                    if _os.path.isfile(file_path):
                        with open(file_path, "rb") as f:
                            return f.read()

                # 备用：远程 URL
                url = getattr(comp, "url", None)
                if url and isinstance(url, str) and url.startswith("http"):
                    async with aiohttp.ClientSession(
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as session:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                return await resp.read()
            except Exception as e:
                logger.warning(f"{LOG_TAG} [retag] 获取图片组件失败: {e}")
            return None

        try:
            # 获取完整消息链（event.get_messages() 比 event.message.chain 更可靠）
            try:
                full_chain = event.get_messages()
            except Exception:
                full_chain = getattr(event.message_obj, "message", None) or []

            # 1. 当前消息的图片组件
            for comp in full_chain:
                if isinstance(comp, Img):
                    data = await _fetch_image_comp(comp)
                    if data:
                        return data

            # 2. 遍历 message_obj.message 作为补充
            msg_obj_chain = (
                getattr(getattr(event, "message_obj", None), "message", None) or []
            )
            for comp in msg_obj_chain:
                if isinstance(comp, Img):
                    data = await _fetch_image_comp(comp)
                    if data:
                        return data

            # 3. 引用消息（reply）中的图片
            try:
                from astrbot.api.message_components import Reply as AstrReply

                for chain in (full_chain, msg_obj_chain):
                    for comp in chain:
                        if isinstance(comp, AstrReply):
                            inner_chain = (
                                getattr(comp, "chain", None)
                                or getattr(comp, "message", None)
                                or []
                            )
                            if hasattr(inner_chain, "chain"):
                                inner_chain = inner_chain.chain
                            for inner_comp in (inner_chain or []):
                                if isinstance(inner_comp, Img):
                                    data = await _fetch_image_comp(inner_comp)
                                    if data:
                                        return data
            except ImportError:
                pass

            # 4. aiocqhttp 原始事件中的图片（QQ 平台兜底）
            try:
                import re as _re

                raw = getattr(event, "raw_message", None) or getattr(
                    event, "_raw_event", None
                )
                if raw is None:
                    msg_obj = getattr(event, "message_obj", None)
                    raw = getattr(msg_obj, "raw_message", None) if msg_obj else None
                if isinstance(raw, str):
                    img_matches = _re.findall(r"\[CQ:image,[^\]]*url=([^,\]]+)", raw)
                    for url in img_matches:
                        url = url.strip()
                        if url.startswith("http"):
                            async with aiohttp.ClientSession(
                                timeout=aiohttp.ClientTimeout(total=30)
                            ) as session:
                                async with session.get(url) as resp:
                                    if resp.status == 200:
                                        return await resp.read()
            except Exception as e:
                logger.debug(f"{LOG_TAG} [retag] 从原始事件提取图片失败: {e}")

        except Exception as e:
            logger.warning(f"{LOG_TAG} [retag] 获取图片失败: {e}")
        return None

    async def _generate_one(
        self, prompt: str, style: str, size: str, session_key: str = ""
    ):
        # 保持 generator 与插件状态同步
        self.generator.api_key = self.image_gen_key
        self.generator.base_url = self.base_url.rstrip("/")
        self.generator.model = self.model
        self.generator.steps = self.steps
        self.generator.scale = self.scale
        self.generator.sampler = self.sampler
        self.generator.noise_schedule = self.noise_schedule
        self.generator.negative = self.negative
        self.generator.seed = self.seed
        self.generator.quality = self.quality
        self.generator.uc_preset = self.uc_preset
        self.generator.variety_boost = self.variety_boost
        self.generator.cfg_rescale = self.cfg_rescale
        self.generator.max_tokens = self.max_tokens
        self.generator.enable_template = self.enable_template
        self.generator.character_preset = self.character_preset
        self.generator.default_outfit = self.default_outfit
        self.generator.outfit_cache_ttl = self.outfit_cache_ttl_seconds
        self.generator.artist_presets = self.artist_presets
        self.translator.enabled = self.enable_translate
        self.translator.provider_id = self.translate_provider
        return await self.generator.generate_one(prompt, style, size, session_key)

    # ---- Studio Web API ----
    async def _studio_save_cache(self) -> Any:
        try:
            body = await web_request.json(default={})
        except Exception:
            return error_response("请求体解析失败", status_code=400)
        try:
            cache_dir = Path("data") / PLUGIN_NAME
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / "panel_cache.json").write_text(
                json.dumps(body, ensure_ascii=False), encoding="utf-8"
            )
            return json_response({"status": "ok"})
        except Exception as e:
            return error_response(f"缓存保存失败: {e!r}", status_code=500)

    async def _studio_load_cache(self) -> Any:
        try:
            cache_file = Path("data") / PLUGIN_NAME / "panel_cache.json"
            if not cache_file.exists():
                return json_response({"status": "ok", "data": None})
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            return json_response({"status": "ok", "data": data})
        except Exception as e:
            logger.warning(f"{LOG_TAG} [studio_cache] 加载失败: {e!r}")
            return json_response({"status": "ok", "data": None})

    async def _studio_get_config(self) -> Any:
        return json_response(
            {
                "image_gen_key": "已配置" if self.image_gen_key else "未配置",
                "base_url": self.base_url,
                "image_style": self.image_style,
                "image_size": self.image_size,
                "artist_presets": self.artist_presets,
                "model": self.model,
                "steps": self.steps,
                "scale": self.scale,
                "seed": self.seed,
                "quality": self.quality,
                "uc_preset": self.uc_preset,
                "variety_boost": self.variety_boost,
                "cfg_rescale": self.cfg_rescale,
                "sampler": self.sampler,
                "noise_schedule": self.noise_schedule,
                "negative": self.negative,
                "enable_template": self.enable_template,
                "character_preset": self.character_preset,
                "default_outfit": self.default_outfit,
                "enable_translate": self.enable_translate,
                "translate_provider": self.translate_provider,
                "proxy_port": self.proxy_port,
                "max_tokens": self.max_tokens,
                "image_styles_options": IMAGE_STYLES,
                "image_size_options": {
                    k: v for k, v in IMAGE_SIZES.items() if k in ("竖图", "横图", "方图")
                },
                "model_options": list(AVAILABLE_MODELS),
                "default_negative": DEFAULT_NEGATIVE,
            }
        )

    async def _studio_generate(self) -> Any:
        try:
            body = await web_request.json(default={})
        except Exception:
            return error_response("请求体解析失败", status_code=400)

        mode = (body.get("mode") or "txt2img").strip().lower()
        if mode not in ("txt2img", "inpaint"):
            mode = "txt2img"

        nai_prompt = (body.get("nai_prompt") or "").strip()
        nl_prompt = (body.get("nl_prompt") or "").strip()
        if not nai_prompt and not nl_prompt:
            return error_response("请至少填写一个提示词", status_code=400)

        style = body.get("style") or self.image_style
        size = body.get("size") or "竖图"

        def _opt_int(key: str) -> Optional[int]:
            val = body.get(key)
            if val is None or val == "":
                return None
            try:
                return int(val)
            except (TypeError, ValueError):
                return None

        def _opt_float(key: str) -> Optional[float]:
            val = body.get(key)
            if val is None or val == "":
                return None
            try:
                return float(val)
            except (TypeError, ValueError):
                return None

        def _opt_str(key: str) -> Optional[str]:
            val = body.get(key)
            if val is None or val == "":
                return None
            return str(val)

        def _opt_bool(key: str) -> Optional[bool]:
            val = body.get(key)
            if val is None:
                return None
            if isinstance(val, bool):
                return val
            if isinstance(val, str):
                return val.lower() in ("true", "1", "yes")
            return bool(val)

        inpaint_payload = None
        if mode == "inpaint":
            raw_inpaint = body.get("inpaint") or {}
            if not isinstance(raw_inpaint, dict):
                return error_response("inpaint 参数格式错误", status_code=400)
            image = (raw_inpaint.get("image") or "").strip()
            mask = (raw_inpaint.get("mask") or "").strip()
            if not image or not mask:
                return error_response("局部重绘需要原图和遮罩", status_code=400)
            strength = raw_inpaint.get("strength", 1.0)
            try:
                strength = float(strength)
            except (TypeError, ValueError):
                strength = 1.0
            strength = max(0.01, min(1.0, strength))
            inpaint_payload = {
                "image": image,
                "mask": mask,
                "strength": strength,
                "add_original_image": True,
            }
            seed_ip = raw_inpaint.get("seed")
            try:
                if seed_ip not in (None, "", 0, "0"):
                    inpaint_payload["seed"] = int(seed_ip)
            except (TypeError, ValueError):
                pass
            # size 优先用前端根据图片算出的 [W,H]
            size_override = body.get("size_array") or raw_inpaint.get("size")
            if isinstance(size_override, list) and len(size_override) == 2:
                size = size_override

        translated_nl = ""
        if nl_prompt:
            translated = await self.translator.translate(nl_prompt, force=True)
            translated_nl = translated if translated else nl_prompt

        parts = [p for p in [nai_prompt, translated_nl] if p]
        full_prompt = ", ".join(parts)
        merge_info = {
            "mode": mode,
            "nai_prompt": nai_prompt,
            "nl_prompt": nl_prompt,
            "translated_nl": translated_nl,
            "full_prompt": full_prompt,
        }

        self.generator.api_key = self.image_gen_key
        self.generator.base_url = self.base_url.rstrip("/")
        self.generator.max_tokens = self.max_tokens

        img_bytes, reason = await self.generator.generate_custom(
            full_prompt,
            style,
            size,
            steps=_opt_int("steps"),
            scale=_opt_float("scale"),
            sampler=_opt_str("sampler"),
            noise_schedule=_opt_str("noise_schedule"),
            negative=_opt_str("negative"),
            model=_opt_str("model"),
            custom_artists=_opt_str("custom_artists"),
            character_preset="",
            enable_template=False,
            enable_translate=False,
            seed=_opt_int("seed"),
            quality=_opt_bool("quality"),
            uc_preset=_opt_str("uc_preset"),
            variety_boost=_opt_bool("variety_boost"),
            cfg_rescale=_opt_float("cfg_rescale"),
            inpaint=inpaint_payload,
            skip_artists=(mode == "inpaint"),
        )
        if not img_bytes:
            return json_response(
                {
                    "status": "error",
                    "message": format_generate_error(reason or "unknown"),
                    "reason": reason,
                },
                status_code=502,
            )
        return json_response(
            {
                "status": "ok",
                "data": [{"b64_json": base64.b64encode(img_bytes).decode()}],
                "merge_info": merge_info,
                "elapsed_info": "1 张",
                "mode": mode,
            }
        )

    # ---- commands ----
    @filter.command("nai")
    async def nai(self, event: AstrMessageEvent):
        """使用 NovelAI 生成图片。

        用法: /nai <提示词> [--style=风格] [--size=尺寸]
        """
        text = event.message_str or ""
        sender = event.get_sender_id() if hasattr(event, "get_sender_id") else "?"
        logger.info(f"{LOG_TAG} [cmd:nai] sender={sender} text='{text[:100]}'")

        if not text.strip():
            yield event.plain_result(
                "用法: /nai <提示词> "
                "[--style=vertical|comicDoujin|r18|lolita25d|anime|galgame|custom] "
                "[--size=竖图|横图|方图]"
            )
            return

        args = parse_args(text)
        prompt = args["prompt"]
        if not prompt:
            yield event.plain_result("请提供提示词。")
            return
        if not self.image_gen_key:
            yield event.plain_result("未配置 image_gen_key，请先在插件配置中填写 token。")
            return

        style = args["style"] or self.image_style
        size_cn = args["size"] or self.image_size
        if style not in IMAGE_STYLES and style != "custom":
            yield event.plain_result(
                f"未知风格: {style}\n可选: {', '.join(IMAGE_STYLES.keys())}"
            )
            return

        yield event.plain_result(
            f"提示词: {prompt}\n风格: {IMAGE_STYLES.get(style, style)}，比例: {size_cn}"
        )

        sender_id = event.get_sender_id() if hasattr(event, "get_sender_id") else ""
        img_bytes, reason = await self._generate_one(prompt, style, size_cn, sender_id)
        if img_bytes:
            yield event.chain_result([Img.fromBytes(img_bytes)])
        else:
            yield event.plain_result(format_generate_error(reason))

    def _resolve_retag_provider_id(self) -> Optional[str]:
        """选出反推用的 provider ID（留空回退默认 provider）。"""
        chosen = (self.retag_provider or "").strip()
        try:
            if chosen:
                prov = self.context.get_provider_by_id(chosen)
                if prov:
                    return chosen
                logger.warning(
                    f"{LOG_TAG} [retag] provider '{chosen}' 不存在，回退默认"
                )
            prov = self.context.get_using_provider()
            if prov is not None:
                try:
                    return prov.meta().id  # type: ignore[attr-defined]
                except Exception:
                    pass
                cfg = getattr(prov, "provider_config", None)
                if cfg and isinstance(cfg, dict):
                    return cfg.get("id")
            return None
        except Exception as e:
            logger.warning(f"{LOG_TAG} [retag] 选择 provider 异常: {e!r}")
            return None

    async def _retag_llm_chat(
        self, mode: str, image_bytes: bytes, prompt: str
    ) -> Optional[str]:
        """反推 LLM 回调：封装 context.llm_generate，支持图片输入。

        Args:
            mode: "describe"（输出中文描述）| "tags"（直接输出 Danbooru tag）
            image_bytes: 图片字节
            prompt: 发给 LLM 的 user 文本

        Returns:
            LLM 文本响应；provider 未配置或调用失败返回 None（触发降级）
        """
        pid = self._resolve_retag_provider_id()
        if not pid:
            logger.warning(f"{LOG_TAG} [retag] 无可用 provider，LLM 视觉跳过")
            return None

        from .core.tag_extractor import _VISION_DESC_PROMPT, _VISION_SYSTEM_PROMPT

        system_prompt = (
            _VISION_DESC_PROMPT if mode == "describe" else _VISION_SYSTEM_PROMPT
        )

        # image_bytes 写临时文件，llm_generate 的 image_urls 支持本地路径
        import os as _os
        import tempfile as _tempfile

        tmp_path = ""
        try:
            suffix = ".png" if image_bytes[:4] == b"\x89PNG" else ".jpg"
            fd, tmp_path = _tempfile.mkstemp(suffix=suffix, prefix="retag_")
            with _os.fdopen(fd, "wb") as f:
                f.write(image_bytes)

            kwargs: dict = {"image_urls": [tmp_path]}

            logger.info(
                f"{LOG_TAG} [retag] LLM 调用 | provider='{pid}' mode={mode} "
                f"img={len(image_bytes)}B"
            )
            response = await self.context.llm_generate(
                chat_provider_id=pid,
                prompt=prompt,
                system_prompt=system_prompt,
                **kwargs,
            )
            text = getattr(response, "completion_text", "") or ""
            if not text and hasattr(response, "result_chain") and response.result_chain:
                buf = []
                for comp in response.result_chain:
                    txt = getattr(comp, "text", None)
                    if txt:
                        buf.append(txt)
                text = "".join(buf)
            return text.strip() if text else None
        except Exception as e:
            logger.warning(f"{LOG_TAG} [retag] LLM 调用失败: {e!r}")
            return None
        finally:
            if tmp_path:
                try:
                    _os.remove(tmp_path)
                except Exception:
                    pass

    @filter.command("反推")
    async def cmd_retag(self, event: AstrMessageEvent):
        """提示词反推：从图片自动反推 Danbooru 风格的 NAI 提示词。

        用法：
            回复一张图片并发送 /反推
            或者在发图时同时发送 /反推

        反推策略（自动三级降级）：
            1. 📦 PNG 元数据  - 最快最准，仅 AI 生成图有
            2. 🔍 LLM 描述 + Danbooru API 检索 - 需配置 danbooru_api_url + 反推 provider
            3. 🤖 LLM 视觉识别 - 需配置反推 provider（retag_provider）
        """
        image_bytes = await self._get_image_bytes(event)
        if not image_bytes:
            try:
                full_chain = event.get_messages()
            except Exception:
                full_chain = getattr(event.message_obj, "message", None) or []
            chain2 = (
                getattr(getattr(event, "message_obj", None), "message", None) or []
            )
            logger.warning(
                f"{LOG_TAG} [retag] 未找到图片 | "
                f"get_messages 类型={[type(c).__name__ for c in full_chain]} | "
                f"message_obj.message 类型={[type(c).__name__ for c in chain2]} | "
                f"raw_message={str(getattr(event, 'raw_message', getattr(getattr(event, 'message_obj', None), 'raw_message', None)))[:200]}"
            )
            yield event.plain_result(
                "❌ 未检测到图片\n"
                "请回复一张图片并发送 /反推，或同时发图和指令"
            )
            return

        yield event.plain_result("🔍 正在反推 tag，请稍候...")

        extractor = TagExtractor(
            danbooru_api_url=self.danbooru_api_url,
            llm_chat=self._retag_llm_chat,
        )

        result = await extractor.extract(image_bytes)

        if result.source == "failed" or not result.prompt:
            yield event.plain_result(
                "❌ 反推失败\n"
                "元数据：未找到\n"
                "Danbooru API："
                + ("未配置" if not self.danbooru_api_url else "无结果")
                + "\nLLM 视觉："
                + (
                    "未配置反推 provider（retag_provider）"
                    if not self._resolve_retag_provider_id()
                    else "无结果"
                )
                + "\n\n提示：\n"
                "· 配置 danbooru_api_url 启用语义检索\n"
                "· 配置 retag_provider（选一个支持视觉的 LLM 供应商）启用 LLM 视觉识别"
            )
            return

        # 来源标签
        source_labels = {
            "metadata": "📦 PNG 元数据",
            "danbooru_api": "🔍 LLM 描述 + Danbooru 检索",
            "llm": "🤖 LLM 视觉识别",
        }
        source_label = source_labels.get(result.source, result.source)

        lines = []
        if self.retag_show_source:
            lines.append(f"来源：{source_label}")
        lines.append(f"\n✅ 正向 Prompt（共 {len(result.tags)} 个 tag）：")
        lines.append(result.prompt)
        if result.negative_prompt:
            lines.append("\n❌ 负向 Prompt：")
            lines.append(result.negative_prompt)
        lines.append("\n💡 可直接用于 /nai <prompt>")

        yield event.plain_result("\n".join(lines))

    @filter.llm_tool()
    async def NAI_Generate_Image(
        self,
        event: AstrMessageEvent,
        prompt: str,
        style: str,
        size_cn: str,
    ) -> MessageEventResult:
        """用 NovelAI 生成 1 张图片。

        Args:
            prompt(string): NAI 标签风格提示词，逗号分隔。
            style(string): vertical / comicDoujin / r18 / lolita25d / anime / galgame / custom
            size_cn(string): 竖图 / 横图 / 方图
        """
        if not self.enable_llm_tool:
            yield "生图工具已被管理员禁用，请在插件设置中开启 enable_llm_tool"
            return
        if not prompt:
            yield "生成失败，提示词不应为空"
            return
        if not self.image_gen_key:
            yield "生成失败，未配置 image_gen_key"
            return
        if style not in IMAGE_STYLES and style != "custom":
            yield f"未知风格: {style}\n可选: {', '.join(IMAGE_STYLES.keys())}"
            return
        if size_cn not in IMAGE_SIZES:
            yield f"未知尺寸: {size_cn}\n可选: {', '.join(k for k in IMAGE_SIZES if k in ('竖图','横图','方图'))}"
            return

        yield f"提示词: {prompt}\n风格: {IMAGE_STYLES.get(style, style)}，比例: {size_cn}"
        img_bytes, reason = await self._generate_one(prompt, style, size_cn)
        if not img_bytes:
            yield f"生成失败：{format_generate_error(reason)}"
            return

        yield MessageChain([Plain("[图片已生成]"), Img.fromBytes(img_bytes)])
        try:
            save_dir = Path("./data/NAI_tool_generated_images")
            save_dir.mkdir(parents=True, exist_ok=True)
            name = (
                f"NAI_generated_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                f"_{hashlib.md5(prompt.encode()).hexdigest()[:8]}.png"
            )
            save_path = save_dir / name
            save_path.write_bytes(img_bytes)
            yield f"图片保存成功！本地路径：{save_path}"
        except Exception as e:
            logger.warning(f"{LOG_TAG} [tool:save] 保存失败: {e}")

    @filter.command("nsfw_on")
    async def nsfw_on(self, event: AstrMessageEvent):
        """开启 NSFW（full 模型）。"""
        self.nsfw_enabled = True
        self.model = self.nsfw_full_model
        self.generator.model = self.model
        self._persist_config("model", self.model)
        yield event.plain_result(f"✅ NSFW 模式已开启，当前模型: {self.model}")

    @filter.command("nsfw_off")
    async def nsfw_off(self, event: AstrMessageEvent):
        """关闭 NSFW（curated 模型）。"""
        self.nsfw_enabled = False
        self.model = self.nsfw_safe_model
        self.generator.model = self.model
        self._persist_config("model", self.model)
        yield event.plain_result(f"✅ NSFW 模式已关闭，当前模型: {self.model}")

    @filter.command("画师")
    async def artist(self, event: AstrMessageEvent):
        """切换会话画师预设（仅 custom 风格生效）。

        用法: /画师 | /画师 0 | /画师 1 | /画师 名称
        """
        session_key = (
            event.get_sender_id() if hasattr(event, "get_sender_id") else "default"
        )
        text = (event.message_str or "").strip()
        args = text.split()[1:] if text.split() else []
        presets = self.artist_presets

        if not args:
            if not presets:
                yield event.plain_result(
                    "当前未配置任何画师预设。\n"
                    "请在 WebUI 配置 artist_presets 字段\n"
                    "⚠️ 画师预设仅在风格为「自定义」时生效"
                )
                return
            lines = ["  0. 关闭画师串"]
            current = self._session_artist.get(session_key, "")
            for i, p in enumerate(presets, 1):
                name = p.split(":", 1)[0] if isinstance(p, str) else f"预设{i}"
                active = " ✅" if (current == name or (not current and i == 1)) else ""
                lines.append(f"  {i}. {name}{active}")
            if current == "none":
                status = "当前：已关闭画师串"
            elif current:
                status = f"当前：{current}"
            else:
                first = (
                    presets[0].split(":", 1)[0]
                    if isinstance(presets[0], str)
                    else "预设1"
                )
                status = f"当前：默认（{first}）"
            yield event.plain_result(
                "🎨 画师预设列表（仅自定义风格生效）：\n"
                + "\n".join(lines)
                + f"\n\n{status}"
            )
            return

        arg = args[0]
        if arg.lower() in ("none", "关闭", "0"):
            self._session_artist[session_key] = "none"
            yield event.plain_result("✅ 已关闭画师串")
            return
        if arg.lower() in ("reset", "重置"):
            self._session_artist.pop(session_key, None)
            yield event.plain_result("✅ 已恢复使用默认画师串")
            return
        if arg.isdigit():
            idx = int(arg) - 1
            if idx < 0 or idx >= len(presets):
                yield event.plain_result(f"❌ 序号超出范围，当前共 {len(presets)} 个预设")
                return
            p = presets[idx]
            name = p.split(":", 1)[0] if isinstance(p, str) else f"预设{idx + 1}"
            self._session_artist[session_key] = name
            yield event.plain_result(f"✅ 已切换画师串：{name}")
            return

        matched = None
        for p in presets:
            name = p.split(":", 1)[0] if isinstance(p, str) else ""
            if name.lower() == arg.lower():
                matched = name
                break
        if matched:
            self._session_artist[session_key] = matched
            yield event.plain_result(f"✅ 已切换画师串：{matched}")
        else:
            yield event.plain_result(f"❌ 未找到预设「{arg}」，发送 /画师 查看列表")

    @filter.command("imgstatus")
    async def imgstatus(self, event: AstrMessageEvent):
        """检查生图服务状态。"""
        yield event.plain_result("正在检查生图服务...")

        proxy_ok = False
        proxy_msg = ""
        try:
            if not self._session:
                proxy_msg = "（aiohttp session 未初始化）"
            else:
                async with self._session.get(
                    f"http://{PROXY_HOST}:{self.proxy_port}/v1/proxy_status",
                    timeout=aiohttp.ClientTimeout(total=3),
                ) as resp:
                    proxy_ok = resp.status == 200
        except Exception as e:
            proxy_msg = f"（{type(e).__name__}）"

        self.generator.api_key = self.image_gen_key
        self.generator.base_url = self.base_url.rstrip("/")
        ok, latency = await self.generator.check_status()

        lines = [
            f"本地代理 127.0.0.1:{self.proxy_port}: "
            f"{'✅ 在线' if proxy_ok else '❌ 离线'} {proxy_msg}"
        ]
        if ok:
            lines.append(f"上游 {self.base_url}: ✅ 延迟约 {latency}ms")
        else:
            lines.append(f"上游 {self.base_url}: ❌ 不可用")
        lines.append(f"模型: {self.model} | NSFW: {'开' if self.nsfw_enabled else '关'}")
        lines.append(f"风格: {IMAGE_STYLES.get(self.image_style, self.image_style)}")
        yield event.plain_result("\n".join(lines))
