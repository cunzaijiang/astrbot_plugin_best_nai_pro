"""
API 错误码 → 用户可读提示。
参考 API 接入文档错误码约定。
"""

from typing import Callable, Dict


def _code_msg(template: str) -> Callable[[str, str], str]:
    return lambda status, message: template.format(s=status, m=message)


_ERROR_CODE_MAP: Dict[str, Callable[[str, str], str]] = {
    "MODEL_REQUIRED": _code_msg("🚫 缺少模型名。请在插件配置中检查 model 设置。\n({s}) {m}"),
    "MODEL_NOT_SUPPORTED": _code_msg(
        "🚫 模型不支持。请检查插件配置的 model 是否在 /v1/models 列表中。\n({s}) {m}"
    ),
    "REQUEST_VALIDATION_ERROR": _code_msg(
        "🚫 参数校验失败。请检查提示词、尺寸、步数等参数是否合法。\n({s}) {m}"
    ),
    "UPSTREAM_INVALID_REQUEST": _code_msg(
        "🚫 图像服务拒绝了请求。可能是提示词含敏感词或参数不合法。\n({s}) {m}"
    ),
    "MAX_TOKENS_EXCEEDED": _code_msg(
        "🚫 本次生成费用超出 token 上限。请降低 steps 或减小尺寸。\n({s}) {m}"
    ),
    "AUTH_REQUIRED": _code_msg("🔑 密钥缺失。请在插件配置中填入 image_gen_key。\n({s}) {m}"),
    "AUTH_INVALID": _code_msg("🔑 密钥无效或已被禁用。请检查 image_gen_key 是否正确。\n({s}) {m}"),
    "UPSTREAM_AUTH_FAILED": _code_msg(
        "🔧 上游 NovelAI 鉴权失败。API 服务的 NovelAI 凭据可能有问题。\n({s}) {m}"
    ),
    "UPSTREAM_SERVER_ERROR": _code_msg("🔧 上游 NovelAI 服务器错误。请稍后重试。\n({s}) {m}"),
    "UPSTREAM_ERROR": _code_msg(
        "🔧 上游图像生成失败。可能是 NovelAI 服务异常或未返回图片。\n({s}) {m}"
    ),
    "SERVICE_BUSY": _code_msg("🐌 服务繁忙，请求频率或并发超限。请稍后重试。\n({s}) {m}"),
    "UPSTREAM_RATE_LIMITED": _code_msg("🐌 上游 NovelAI 限流。请稍后重试。\n({s}) {m}"),
    "INTERNAL_ERROR": _code_msg(
        "🔥 API 内部错误。请稍后重试，如持续出现请联系服务提供方。\n({s}) {m}"
    ),
    "UPSTREAM_API_KEY_MISSING": _code_msg(
        "🔥 服务端未配置 API 凭据。请联系服务提供方。\n({s}) {m}"
    ),
    "SERVICE_NOT_READY": _code_msg("💤 服务尚未就绪。请稍后重试。\n({s}) {m}"),
    "UPSTREAM_NETWORK_ERROR": _code_msg("📡 无法连接图像服务。请稍后重试。\n({s}) {m}"),
}

_SIMPLE_MAP = {
    "no_token": "❌ 插件未配置 image_gen_key，请先在插件管理面板填入 token。",
    "no_session": "❌ 插件 session 未初始化，请重载插件。",
    "timeout": "⏱ 生图超时（超过 180 秒）。可能原因：API 服务繁忙、提示词过长、或网络不稳。",
    "empty_response": "📭 上游返回 200 但内容为空，可能是接口限流或临时异常。",
    "exception": "💥 生图过程发生未捕获异常，请查看 AstrBot 日志获取详情。",
}


def format_generate_error(reason: str) -> str:
    """把 _generate_one 返回的 reason 翻译成给用户的中文报错。

    reason 格式: "http_4xx | HTTP 400 | ERROR_CODE | error message"
    或简短 reason: "no_token" / "timeout" / 等
    """
    if reason in _SIMPLE_MAP:
        return _SIMPLE_MAP[reason]

    parts = reason.split(" | ")
    base_reason = parts[0] if parts else reason
    err_code = ""
    err_msg = ""
    http_status = ""
    for part in parts[1:]:
        if part.startswith("HTTP "):
            http_status = part
        elif part in _ERROR_CODE_MAP:
            err_code = part
        else:
            err_msg = part

    if err_code and err_code in _ERROR_CODE_MAP:
        return _ERROR_CODE_MAP[err_code](http_status, err_msg)

    if base_reason.startswith("http_4xx"):
        return f"🚫 请求被拒绝（{http_status}）\n{err_code or '未知错误码'}: {err_msg}"
    if base_reason.startswith("http_5xx"):
        return (
            f"🔥 API 服务器内部错误（{http_status}）\n"
            f"{err_code or '未知错误码'}: {err_msg}\n请稍后重试。"
        )
    if base_reason.startswith("http_other"):
        return f"⚠️ 上游返回非预期状态码（{http_status}）\n{err_msg}"
    return f"❓ 生图失败（原因: {reason}）"
