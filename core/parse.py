"""指令参数解析。"""

import re
from typing import Any, Dict


def parse_args(text: str) -> Dict[str, Any]:
    """解析 `/nai` 指令参数。

    支持 `--style=` / `--size=` / `--n=` 标志，其余作为 prompt。
    `text` 通常是 AstrBot 剥掉唤醒符后的 `nai <prompt>`，但保险起见也兼容
    唤醒符未被框架剥离的情况（如 `!nai` / `#nai` / `/nai` 等）。剥离开头到
    命令名 `nai` 为止的所有非空白前缀，避免把 `nai` 当提示词传给上游。
    """
    args: Dict[str, Any] = {"prompt": "", "n": None, "style": None, "size": None}
    flags = re.findall(r"--(\w+)=([^\s]+)", text)
    for key, value in flags:
        if key in args:
            args[key] = value
    prompt = re.sub(r"--\w+=[^\s]+", "", text).strip()
    # 剥离开头到命令名 nai 的前缀：唤醒符可能已被框架剥掉（text="nai ..."），
    # 也可能未剥（text="/nai ..."、"!nai"、"#nai" 等）。匹配任意非空白前缀 + nai。
    prompt = re.sub(r"^[^\s]*nai\b\s*", "", prompt, flags=re.IGNORECASE).strip()
    args["prompt"] = prompt
    return args
