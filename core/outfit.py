"""服装缓存池：具体服装词 / 换装动词 / 抽出片段。"""

from typing import Tuple

# 命中即视为「具体服装」的关键词
OUTFIT_CONCRETE_TOKENS = (
    "裙", "裤", "衣", "上衣", "下装", "外套", "衬衫", "T恤", "罩衫", "卫衣",
    "汉服", "校服", "旗袍", "和服", "西装", "风衣", "夹克", "毛衣", "针织衫",
    "连衣裙", "半裙", "短裙", "长裙", "牛仔裤", "阔腿裤", "喇叭裤", "运动裤",
    "皮衣", "羽绒服", "棉衣", "大衣",
    "靴", "鞋", "袜", "丝袜", "帽", "围巾", "手套", "披风", "斗篷",
    "JK", "jk", "洛丽塔", "lolita",
)

# 命中即视为「换装动作」的关键词
OUTFIT_CHANGE_KEYWORDS = (
    "换上新", "换了新", "换上", "今天穿", "今晚穿", "早上穿",
    "刚换上", "新换了", "换了件", "换了条", "穿上了",
)


def has_specific_outfit(prompt: str) -> bool:
    """源 prompt 中是否包含具体服装词。"""
    return any(tok in prompt for tok in OUTFIT_CONCRETE_TOKENS)


def detect_outfit_change(prompt: str) -> bool:
    """源 prompt 中是否出现换装动作关键词。"""
    return any(kw in prompt for kw in OUTFIT_CHANGE_KEYWORDS)


def extract_outfit_excerpt(prompt: str, max_chars: int = 200) -> str:
    """从源 prompt 中抽出服装相关片段。"""
    candidates = []
    for tok in OUTFIT_CONCRETE_TOKENS:
        idx = prompt.find(tok)
        if idx >= 0:
            candidates.append((idx, tok))
    for kw in OUTFIT_CHANGE_KEYWORDS:
        idx = prompt.find(kw)
        if idx >= 0:
            candidates.append((idx, kw))
    if not candidates:
        return ""
    candidates.sort()
    idx, marker = candidates[0]
    start = max(0, idx - 30)
    end = min(len(prompt), idx + len(marker) + max_chars)
    excerpt = prompt[start:end].strip()
    cut_at = -1
    for sep in ("。", "！", "？", "；", "\n", "，", ",", ";", ":"):
        pos = excerpt.find(sep, len(marker) + 20)
        if pos > 0 and (cut_at < 0 or pos < cut_at):
            cut_at = pos
    if cut_at > 0:
        excerpt = excerpt[: cut_at + 1]
    return excerpt.strip() or prompt[idx:end].strip()


def resolve_outfit_context(
    prompt: str,
    *,
    cache_get,
    cache_set,
    cache_ttl: int,
    default_outfit: str,
) -> Tuple[str, str, bool]:
    """决定要追加的服装上下文。

    Returns:
        (outfit_text, source, use_default_outfit)
        source ∈ {"prompt", "cache", "none"}
    """
    is_specific = has_specific_outfit(prompt)
    is_change = detect_outfit_change(prompt)

    if is_specific or is_change:
        excerpt = extract_outfit_excerpt(prompt)
        if excerpt:
            if cache_ttl > 0:
                cache_set(excerpt)
            return excerpt, "prompt", False

    if cache_ttl > 0:
        cached = cache_get()
        if cached:
            return cached, "cache", False

    if default_outfit:
        return "", "none", True

    return "", "none", False
