# -*- coding: utf-8 -*-
"""
Tag 反推模块。

三级降级策略：
  1. PNG 元数据（tEXt chunk）-> 最快最准，仅 AI 生成图有
  2. LLM 中文描述 + Danbooru API 语义检索 -> 需配置 danbooru_api_url + 反推 provider
  3. LLM 视觉识别           -> 需配置反推 provider，最慢但通用

LLM 调用通过注入的 llm_chat 回调完成（由 main.py 用 AstrBot context.llm_generate 实现），
本模块不依赖具体 LLM SDK，仅负责编排与降级。
"""

import asyncio
import json
import struct
import zlib
from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Optional

import aiohttp

try:
    from astrbot.api import logger
except ImportError:
    import logging
    logger = logging.getLogger("魔法绘图")


# ── LLM 回调类型 ──────────────────────────────────────────────────────────────
# mode: "describe"（输出中文描述，供 Danbooru API 检索）| "tags"（直接输出 Danbooru tag）
# 返回 LLM 文本响应，失败返回 None
LlmChatFn = Callable[[str, bytes, str], Awaitable[Optional[str]]]

# ── 结果数据类 ────────────────────────────────────────────────────────────────

@dataclass
class TagExtractionResult:
    source: str                          # "metadata" | "danbooru_api" | "llm" | "failed"
    prompt: str                          # 完整正向 prompt（逗号分隔）
    tags: List[str] = field(default_factory=list)
    negative_prompt: str = ""            # 负向 prompt（仅 metadata 来源可能有）
    raw_metadata: Optional[dict] = None  # 原始元数据 dict


# ── PNG 元数据解析 ─────────────────────────────────────────────────────────────

def _parse_png_text_chunks(data: bytes) -> dict:
    """纯标准库解析 PNG tEXt / iTXt chunk，返回 {keyword: value} 字典。"""
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        return {}

    chunks = {}
    pos = 8
    while pos + 8 <= len(data):
        length = struct.unpack('>I', data[pos:pos+4])[0]
        chunk_type = data[pos+4:pos+8]
        chunk_data = data[pos+8:pos+8+length]
        pos += 12 + length  # length + type(4) + data + crc(4)

        if chunk_type == b'tEXt':
            # tEXt: keyword\x00value (latin-1)
            try:
                null_idx = chunk_data.index(b'\x00')
                keyword = chunk_data[:null_idx].decode('latin-1')
                value = chunk_data[null_idx+1:].decode('latin-1')
                chunks[keyword] = value
            except Exception:
                pass

        elif chunk_type == b'iTXt':
            # iTXt: keyword\x00compression_flag\x00compression_method\x00language\x00translated_keyword\x00text
            try:
                null_idx = chunk_data.index(b'\x00')
                keyword = chunk_data[:null_idx].decode('latin-1')
                rest = chunk_data[null_idx+1:]
                comp_flag = rest[0]
                # comp_method = rest[1]
                rest = rest[2:]
                # skip language tag and translated keyword (two more null-terminated fields)
                for _ in range(2):
                    ni = rest.index(b'\x00')
                    rest = rest[ni+1:]
                if comp_flag == 1:
                    text = zlib.decompress(rest).decode('utf-8')
                else:
                    text = rest.decode('utf-8')
                chunks[keyword] = text
            except Exception:
                pass

        elif chunk_type == b'zTXt':
            try:
                null_idx = chunk_data.index(b'\x00')
                keyword = chunk_data[:null_idx].decode('latin-1')
                compressed = chunk_data[null_idx+2:]  # skip null + compression method byte
                value = zlib.decompress(compressed).decode('latin-1')
                chunks[keyword] = value
            except Exception:
                pass

        elif chunk_type == b'IEND':
            break

    return chunks


def _extract_from_metadata(image_bytes: bytes) -> Optional[TagExtractionResult]:
    """
    尝试从 PNG 元数据中提取 prompt。

    支持格式：
    - NAI 格式：tEXt["Comment"] = JSON {"prompt": "...", "uc": "..."}
    - SD WebUI 格式：tEXt["parameters"] = "prompt\nNegative prompt: ...\nSteps: ..."
    - 通用格式：tEXt["prompt"] / tEXt["Description"]
    """
    try:
        chunks = _parse_png_text_chunks(image_bytes)
    except Exception as e:
        logger.debug(f"[魔法绘图/retag] PNG chunk 解析失败: {e}")
        return None

    if not chunks:
        return None

    # ── NAI 格式（Comment = JSON）──
    if 'Comment' in chunks:
        try:
            meta = json.loads(chunks['Comment'])
            prompt = meta.get('prompt') or meta.get('Description') or ''
            uc = meta.get('uc') or meta.get('negative_prompt') or ''
            if prompt:
                tags = [t.strip() for t in prompt.split(',') if t.strip()]
                logger.info(f"[魔法绘图/retag] 从 NAI 元数据提取到 {len(tags)} 个 tag")
                return TagExtractionResult(
                    source="metadata",
                    prompt=prompt,
                    tags=tags,
                    negative_prompt=uc,
                    raw_metadata=meta,
                )
        except (json.JSONDecodeError, AttributeError):
            # Comment 不是 JSON，按普通文本尝试
            text = chunks['Comment'].strip()
            if text:
                tags = [t.strip() for t in text.split(',') if t.strip()]
                return TagExtractionResult(source="metadata", prompt=text, tags=tags)

    # ── SD WebUI 格式（parameters = 纯文本）──
    if 'parameters' in chunks:
        raw = chunks['parameters']
        lines = raw.split('\n')
        prompt_lines = []
        neg_lines = []
        in_neg = False
        for line in lines:
            if line.startswith('Negative prompt:'):
                in_neg = True
                neg_part = line[len('Negative prompt:'):].strip()
                if neg_part:
                    neg_lines.append(neg_part)
            elif in_neg and not line.startswith('Steps:') and not line.startswith('Size:'):
                neg_lines.append(line)
            elif not in_neg:
                prompt_lines.append(line)
            else:
                break  # 遇到 Steps: 等参数行停止
        prompt = ', '.join(' '.join(prompt_lines).split(','))
        prompt = ', '.join(t.strip() for t in prompt.split(',') if t.strip())
        neg = ', '.join(t.strip() for t in ', '.join(neg_lines).split(',') if t.strip())
        if prompt:
            tags = [t.strip() for t in prompt.split(',') if t.strip()]
            logger.info(f"[魔法绘图/retag] 从 SD 元数据提取到 {len(tags)} 个 tag")
            return TagExtractionResult(
                source="metadata",
                prompt=prompt,
                tags=tags,
                negative_prompt=neg,
                raw_metadata={'raw': raw},
            )

    # ── 通用备用字段 ──
    for key in ('prompt', 'Description', 'UserComment'):
        if key in chunks and chunks[key].strip():
            text = chunks[key].strip()
            tags = [t.strip() for t in text.split(',') if t.strip()]
            if tags:
                logger.info(f"[魔法绘图/retag] 从 PNG[{key}] 提取到 {len(tags)} 个 tag")
                return TagExtractionResult(source="metadata", prompt=text, tags=tags)

    return None


# ── Danbooru API 检索 ─────────────────────────────────────────────────────────

async def _danbooru_health_check(base_url: str, timeout: float = 10.0) -> bool:
    """探活：检查 Danbooru API 服务是否可用。快速返回，不阻塞。"""
    base_url = base_url.rstrip('/')
    # 尝试几个常见的 health 端点
    for path in ('/health', '/api/health', '/ping'):
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as session:
                async with session.get(f"{base_url}{path}") as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        # 返回的是 JSON 且包含 ok/status 字段才算健康
                        if len(text) < 5000:  # 排除返回 HTML 页面的情况
                            try:
                                data = json.loads(text)
                                status = data.get('status') or data.get('ok') or data.get('healthy')
                                if status:
                                    logger.info(f"[魔法绘图/retag] Danbooru API 健康检查通过: {path}")
                                    return True
                            except (json.JSONDecodeError, AttributeError):
                                pass
        except Exception:
            continue
    # 所有 health 端点都不行，尝试直接发一个轻量级 search 请求探活
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            async with session.post(
                f"{base_url}/api/search",
                json={"query": "1girl", "limit": 1},
            ) as resp:
                if resp.status == 200:
                    logger.info("[魔法绘图/retag] Danbooru API 探活通过（/api/search 冒烟）")
                    return True
    except Exception as e:
        logger.warning(f"[魔法绘图/retag] Danbooru API 探活失败: {e}")
    return False


async def _extract_via_danbooru_api(
    query: str,
    base_url: str,
    timeout: float = 30.0,
    search_limit: int = 30,
    related_limit: int = 20,
    seed_count: int = 8,
    show_nsfw: bool = True,
) -> Optional[TagExtractionResult]:
    """调用 DanbooruSearchOnline API 做语义检索。
    兼容 https://sakizuki-danboorusearch.hf.space 接口格式。
    """
    base_url = base_url.rstrip('/')
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            # /api/search — POST
            search_resp = await session.post(
                f"{base_url}/api/search",
                json={"query": query, "limit": search_limit},
            )
            if search_resp.status != 200:
                logger.warning(f"[魔法绘图/retag] Danbooru /api/search 返回 {search_resp.status}")
                return None

            search_data = await search_resp.json()

            # 兼容两种返回格式：
            # 1. {"results": [...], "tags_sfw": "...", "tags_all": "..."}
            # 2. 直接返回 list
            if isinstance(search_data, dict):
                results_raw = search_data.get('results') or []
            elif isinstance(search_data, list):
                results_raw = search_data
            else:
                return None

            if not results_raw:
                return None

            # 提取 tag，过滤 NSFW（如需要）
            tags = []
            for item in results_raw:
                if isinstance(item, dict):
                    tag = item.get('tag') or item.get('name') or ''
                    if not show_nsfw and item.get('nsfw') not in (None, '0', 0, False):
                        continue
                elif isinstance(item, str):
                    tag = item
                else:
                    continue
                if tag:
                    tags.append(tag)

            if not tags:
                return None

            # /api/related — POST，取 top-N seed tag 做共现推荐
            seed_tags = tags[:seed_count]
            try:
                related_resp = await session.post(
                    f"{base_url}/api/related",
                    json={"tags": seed_tags, "limit": related_limit},
                )
                if related_resp.status == 200:
                    related_data = await related_resp.json()
                    # related 直接返回 list
                    related_items = related_data if isinstance(related_data, list) else related_data.get('results', [])
                    existing = set(tags)
                    for item in related_items:
                        if isinstance(item, dict):
                            t = item.get('tag') or item.get('name') or ''
                            if not show_nsfw and item.get('nsfw') not in (None, '0', 0, False):
                                continue
                        else:
                            t = str(item)
                        if t and t not in existing:
                            tags.append(t)
                            existing.add(t)
            except Exception as e:
                logger.debug(f"[魔法绘图/retag] /api/related 失败（忽略）: {e}")

            prompt = ', '.join(tags)
            logger.info(f"[魔法绘图/retag] Danbooru API 检索到 {len(tags)} 个 tag")
            return TagExtractionResult(source="danbooru_api", prompt=prompt, tags=tags)

    except asyncio.TimeoutError:
        logger.warning(f"[魔法绘图/retag] Danbooru API 请求超时")
        return None
    except Exception as e:
        logger.warning(f"[魔法绘图/retag] Danbooru API 请求失败: {e}")
        return None


# ── LLM 视觉反推 ──────────────────────────────────────────────────────────────

# 直接输出 tag（无 Danbooru API 时使用）
_VISION_SYSTEM_PROMPT = """你是专业的 NovelAI 图片 Tag 分析专家。请分析这张图片，输出 Danbooru 格式的英文 tag。
规则：
- 直接输出 tag，用英文逗号分隔，不要解释，不要加任何前缀或序号
- 标签顺序：画质 > 人物数量 > 角色特征（发色/发型/瞳色）> 服装 > 动作/姿势 > 场景/背景 > 光影/风格
- 使用标准 Danbooru tag（如 1girl, long hair, blue eyes, school uniform 等）
- 如有已知角色，写出角色名（如 hatsune miku）
- 输出 30~50 个 tag"""

# 输出中文描述（有 Danbooru API 时使用，描述再送 API 检索精准 tag）
_VISION_DESC_PROMPT = """请用中文详细描述这张图片的内容，包括：
- 人物数量、性别、已知角色名
- 发色、发型、瞳色等外貌特征
- 服装、配饰
- 动作、姿势、表情
- 场景、背景、光影
不要输出英文 tag，只用中文自然语言描述，越详细越好。"""

# describe 模式发给 LLM 的 user prompt
_DESC_USER_PROMPT = "请描述这张图片。"
# tags 模式发给 LLM 的 user prompt
_TAGS_USER_PROMPT = "请分析这张图片并输出 Danbooru tag。"


async def _llm_describe_image(
    image_bytes: bytes,
    llm_chat: LlmChatFn,
) -> Optional[str]:
    """调用视觉 LLM，让其输出图片的中文描述（用于后续 Danbooru API 检索）。

    LLM 调用细节由 llm_chat 回调封装（见 main.py 的 _retag_llm_chat）。
    """
    if not llm_chat:
        return None
    try:
        desc = await llm_chat("describe", image_bytes, _DESC_USER_PROMPT)
        if desc:
            desc = desc.strip()
            logger.info(f"[魔法绘图/retag] LLM 图片描述: {desc[:80]}...")
            return desc
    except Exception as e:
        logger.warning(f"[魔法绘图/retag] LLM 描述图片失败: {e}")
    return None


async def _extract_via_llm(
    image_bytes: bytes,
    llm_chat: LlmChatFn,
) -> Optional[TagExtractionResult]:
    """调用视觉 LLM 识别图片并反推 tag。"""
    if not llm_chat:
        return None
    try:
        content = await llm_chat("tags", image_bytes, _TAGS_USER_PROMPT)
        if not content:
            return None
        content = content.strip()
        tags = [t.strip() for t in content.split(',') if t.strip()]
        if not tags:
            return None
        prompt = ', '.join(tags)
        logger.info(f"[魔法绘图/retag] LLM 视觉识别到 {len(tags)} 个 tag")
        return TagExtractionResult(source="llm", prompt=prompt, tags=tags)
    except asyncio.TimeoutError:
        logger.warning("[魔法绘图/retag] LLM 视觉请求超时")
        return None
    except Exception as e:
        logger.warning(f"[魔法绘图/retag] LLM 视觉请求失败: {e}")
        return None


# ── 主入口 ────────────────────────────────────────────────────────────────────

class TagExtractor:
    """三级降级 Tag 反推器。"""

    def __init__(
        self,
        danbooru_api_url: str = "",
        llm_chat: Optional[LlmChatFn] = None,
    ):
        self.danbooru_api_url = danbooru_api_url.rstrip('/') if danbooru_api_url else ""
        self.llm_chat = llm_chat

    async def extract(self, image_bytes: bytes) -> TagExtractionResult:
        """
        执行三级降级反推。

        流程：
          1. PNG 元数据 -> 直接读 prompt（AI 生成图专属）
          2. LLM 看图出中文描述 + Danbooru API 检索精准 tag（需同时配置 danbooru_api_url 和反推 provider）
          3. LLM 直接输出 tag（仅配置了反推 provider）

        Returns:
            TagExtractionResult，source 标明来源：
            - "metadata"     : 从 PNG 元数据直接读取
            - "danbooru_api" : LLM 描述 + Danbooru API 语义检索
            - "llm"          : LLM 视觉直接识别
            - "failed"       : 全部失败
        """
        # ── Level 1: PNG 元数据 ──
        result = _extract_from_metadata(image_bytes)
        if result:
            return result
        logger.info("[魔法绘图/retag] 元数据无结果，尝试 LLM + Danbooru API")

        # ── Level 2: LLM 看图描述 -> Danbooru API 检索（两者都配了才走这条路）──
        if self.danbooru_api_url and self.llm_chat:
            # 先探活，服务不可用则直接跳过
            api_available = await _danbooru_health_check(self.danbooru_api_url)
            if not api_available:
                logger.info("[魔法绘图/retag] Danbooru API 不可用，跳过")
            else:
                desc = await _llm_describe_image(image_bytes, self.llm_chat)
                if desc:
                    result = await _extract_via_danbooru_api(
                        query=desc,
                        base_url=self.danbooru_api_url,
                        timeout=90.0,
                    )
                    if result:
                        return result
                    logger.info("[魔法绘图/retag] Danbooru API 无结果，降级到 LLM 直接识别")

        # ── Level 3: LLM 直接输出 tag ──
        result = await _extract_via_llm(image_bytes, self.llm_chat)
        if result:
            return result

        logger.warning("[魔法绘图/retag] 三级降级全部失败")
        return TagExtractionResult(source="failed", prompt="", tags=[])

    async def extract_with_query(self, image_bytes: bytes, query: str = "") -> TagExtractionResult:
        """
        带文字 query 的反推（用于文字 -> tag 模式，不依赖图片）。
        优先级同上，但 Level 2 Danbooru API 会用 query 做语义检索。
        """
        # Level 1: PNG 元数据
        result = _extract_from_metadata(image_bytes)
        if result:
            return result

        # Level 2: Danbooru API（需要 query）
        if self.danbooru_api_url and query:
            result = await _extract_via_danbooru_api(
                query=query,
                base_url=self.danbooru_api_url,
            )
            if result:
                return result
            logger.info("[魔法绘图/retag] Danbooru API 无结果，降级到 LLM")

        # Level 3: LLM 视觉
        result = await _extract_via_llm(image_bytes, self.llm_chat)
        if result:
            return result

        return TagExtractionResult(source="failed", prompt="", tags=[])
