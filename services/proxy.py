"""
本地 OpenAI Images 兼容代理（供陪伴等插件调用）。
"""

import base64
import time
from typing import Any, Callable, Optional

from aiohttp import web
from astrbot.api import logger

from ..core.constants import LOG_TAG, PLUGIN_NAME, PROXY_HOST
from ..core.errors import format_generate_error


class LocalProxyServer:
    """在 127.0.0.1:port 上暴露 /v1/images/* 代理。"""

    def __init__(
        self,
        *,
        port: int,
        api_key_getter: Callable[[], str],
        session_ready: Callable[[], bool],
        generate_fn: Callable,
        default_style: str,
        base_url: str,
    ) -> None:
        self.port = port
        self.api_key_getter = api_key_getter
        self.session_ready = session_ready
        self.generate_fn = generate_fn
        self.default_style = default_style
        self.base_url = base_url
        self.runner: Optional[web.AppRunner] = None

    async def start(self) -> None:
        logger.info(f"{LOG_TAG} [proxy:start] 准备启动 {PROXY_HOST}:{self.port}")
        app = web.Application()
        app.router.add_post("/v1/images/generations", self.handle_generations)
        app.router.add_post("/v1/images/edits", self.handle_edits)
        app.router.add_get("/v1/images/generations", self.handle_health)
        app.router.add_get("/v1/proxy_status", self.handle_health)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, PROXY_HOST, self.port)
        await site.start()
        logger.info(
            f"{LOG_TAG} [proxy:start] 启动成功 | "
            f"http://{PROXY_HOST}:{self.port}/v1/images/generations"
        )

    async def stop(self) -> None:
        if not self.runner:
            return
        logger.info(f"{LOG_TAG} [proxy:stop] 正在关闭代理")
        try:
            await self.runner.cleanup()
            logger.info(f"{LOG_TAG} [proxy:stop] 代理已停止")
        except Exception as e:
            logger.warning(f"{LOG_TAG} [proxy:stop] 停止异常: {e!r}")
        finally:
            self.runner = None

    async def handle_health(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "plugin": PLUGIN_NAME,
                "base_url": self.base_url,
                "token_configured": bool(self.api_key_getter()),
            }
        )

    async def handle_generations(self, request: web.Request) -> web.Response:
        logger.info(
            f"{LOG_TAG} [proxy:gen] 收到 POST {request.path} from {request.remote}"
        )
        if not self.api_key_getter() or not self.session_ready():
            return web.json_response(
                {
                    "error": {
                        "message": "NAI 插件未配置 image_gen_key",
                        "type": "invalid_request_error",
                    }
                },
                status=400,
            )
        try:
            body = await request.json()
        except Exception as e:
            return web.json_response(
                {
                    "error": {
                        "message": f"invalid json: {e!r}",
                        "type": "invalid_request_error",
                    }
                },
                status=400,
            )
        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            return web.json_response(
                {
                    "error": {
                        "message": "prompt is required",
                        "type": "invalid_request_error",
                    }
                },
                status=400,
            )
        size = body.get("size") or "1024x1024"
        return await self._generate_and_respond(prompt, size, tag="proxy:gen")

    async def handle_edits(self, request: web.Request) -> web.Response:
        """图生图降级为文生图（丢弃参考图）。"""
        logger.info(
            f"{LOG_TAG} [proxy:edit] 收到 POST {request.path} from {request.remote}"
        )
        if not self.api_key_getter() or not self.session_ready():
            return web.json_response(
                {
                    "error": {
                        "message": "NAI 插件未配置 image_gen_key",
                        "type": "invalid_request_error",
                    }
                },
                status=400,
            )
        prompt = ""
        size = "1024x1024"
        try:
            reader = await request.multipart()
            async for part in reader:
                if part.name is None:
                    continue
                if part.name == "prompt":
                    prompt = (await part.text()).strip()
                elif part.name == "size":
                    raw = (await part.text() or "").strip()
                    if raw:
                        size = raw
                elif part.name in ("image", "mask", "image[]", "mask[]"):
                    await part.read()
        except Exception as e:
            return web.json_response(
                {
                    "error": {
                        "message": f"invalid multipart: {e!r}",
                        "type": "invalid_request_error",
                    }
                },
                status=400,
            )
        if not prompt:
            return web.json_response(
                {
                    "error": {
                        "message": "prompt is required",
                        "type": "invalid_request_error",
                    }
                },
                status=400,
            )
        logger.info(
            f"{LOG_TAG} [proxy:edit] 降级到纯文生图 | prompt='{prompt[:80]}' size={size}"
        )
        return await self._generate_and_respond(prompt, size, tag="proxy:edit")

    async def _generate_and_respond(
        self, prompt: str, size: str, tag: str
    ) -> web.Response:
        try:
            img_bytes, reason = await self.generate_fn(
                prompt, self.default_style, size
            )
        except Exception as e:
            logger.warning(f"{LOG_TAG} [{tag}] generate 异常: {e!r}")
            return web.json_response(
                {
                    "error": {
                        "message": f"generate exception: {e!r}",
                        "type": "internal_error",
                    }
                },
                status=500,
            )
        if not img_bytes:
            user_msg = format_generate_error(reason)
            status = 504 if reason == "timeout" else 502
            return web.json_response(
                {
                    "error": {
                        "message": f"generate failed: {reason}",
                        "user_message": user_msg,
                        "type": "upstream_error",
                    }
                },
                status=status,
            )
        b64 = base64.b64encode(img_bytes).decode()
        return web.json_response(
            {"created": int(time.time()), "data": [{"b64_json": b64}]}
        )
