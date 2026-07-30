"""指令参数解析。"""

import re
from typing import Any, Dict


def parse_args(text: str) -> Dict[str, Any]:
    """解析 `/nai` 指令参数。

    支持 `--style=` / `--size=` / `--n=` 标志，其余作为 prompt。
    """
    args: Dict[str, Any] = {"prompt": "", "n": None, "style": None, "size": None}
    flags = re.findall(r"--(\w+)=([^\s]+)", text)
    for key, value in flags:
        if key in args:
            args[key] = value
    prompt = re.sub(r"--\w+=[^\s]+", "", text).strip()
    args["prompt"] = prompt
    return args
