"""图片与 seed 解析（API 文档 §13）。"""

import base64
import json
import re
from typing import List, Optional

_IMG_DATA_URI_RE = re.compile(r"!\[[^\]]*\]\((data:image/[^;)]+;base64,[^)]+)\)")
_SEED_RE = re.compile(r"<!--\s*seeds:(\[.*?\])\s*-->")


def extract_image_from_content(content: str) -> Optional[bytes]:
    """从 chat completion 的 message content 中提取 base64 图片。"""
    matches = _IMG_DATA_URI_RE.findall(content or "")
    if not matches:
        return None
    data_uri = matches[0]
    _, _, payload = data_uri.partition(",")
    try:
        return base64.b64decode(payload)
    except Exception:
        return None


def extract_seeds(content: str) -> List[Optional[int]]:
    """解析 content 末尾的 <!-- seeds:[...] --> 注释。"""
    match = _SEED_RE.search(content or "")
    if not match:
        return []
    try:
        return list(json.loads(match.group(1)))
    except Exception:
        return []
