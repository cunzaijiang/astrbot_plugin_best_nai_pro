"""
自然语言提示词 → NAI 标签转译服务。
"""

import re
from typing import Any, Optional

from astrbot.api import logger

from ..core.constants import LOG_TAG, TRANSLATE_SYSTEM_PROMPT


class TranslateService:
    """通过 AstrBot provider 把自然语言转成 SD/NAI 标签。"""

    def __init__(
        self,
        context: Any,
        *,
        enabled: bool = False,
        provider_id: str = "",
    ) -> None:
        self.context = context
        self.enabled = enabled
        self.provider_id = (provider_id or "").strip()

    def resolve_provider_id(self) -> Optional[str]:
        """选出转译用的 provider ID。"""
        chosen = (self.provider_id or "").strip()
        try:
            if chosen:
                prov = self.context.get_provider_by_id(chosen)
                if prov:
                    return chosen
                logger.warning(
                    f"{LOG_TAG} [translate] provider '{chosen}' 不存在，回退默认"
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
            logger.warning(f"{LOG_TAG} [translate] 选择 provider 异常: {e!r}")
            return None

    async def translate(self, prompt: str, *, force: bool = False) -> str:
        """转译自然语言 prompt。

        Args:
            prompt: 原始提示词
            force: True 时忽略 enabled 开关（面板独立转译用）

        Returns:
            转译后的标签串；失败时原样返回 prompt
        """
        if not force and not self.enabled:
            return prompt
        if not prompt or not prompt.strip():
            return prompt

        provider_id = self.resolve_provider_id()
        if not provider_id:
            logger.warning(f"{LOG_TAG} [translate] 没有可用 provider，跳过转译")
            return prompt

        logger.info(
            f"{LOG_TAG} [translate] 开始 | provider='{provider_id}' "
            f"in_len={len(prompt)} preview='{prompt[:60]}...'"
        )

        response = None
        try:
            llm_generate = getattr(self.context, "llm_generate", None)
            if llm_generate is not None:
                response = await llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                    system_prompt=TRANSLATE_SYSTEM_PROMPT,
                    temperature=0.4,
                )
        except AttributeError:
            llm_generate = None
        except Exception as e:
            logger.warning(
                f"{LOG_TAG} [translate] context.llm_generate 异常: {e!r}，尝试 fallback"
            )

        if response is None:
            try:
                prov = self.context.get_provider_by_id(provider_id)
                if prov is None:
                    logger.warning(
                        f"{LOG_TAG} [translate] provider '{provider_id}' 不可用"
                    )
                    return prompt
                try:
                    response = await prov.text_chat(
                        prompt=prompt,
                        system_prompt=TRANSLATE_SYSTEM_PROMPT,
                        temperature=0.4,
                    )
                except TypeError:
                    response = await prov.text_chat(prompt=prompt)
            except Exception as e:
                logger.warning(f"{LOG_TAG} [translate] 调用 provider 异常: {e!r}")
                return prompt

        translated = ""
        if response is not None:
            translated = getattr(response, "completion_text", "") or ""
            if not translated and hasattr(response, "result_chain") and response.result_chain:
                buf = []
                for comp in response.result_chain:
                    txt = getattr(comp, "text", None)
                    if txt:
                        buf.append(txt)
                translated = "".join(buf)

        translated = translated.strip().strip("\"'` ")
        if translated.startswith("```"):
            translated = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", translated)
            translated = translated.rstrip("`").strip()
        translated = " ".join(translated.split())
        translated = re.sub(
            r"^\s*(Output|输出|翻译结果|Here is the translation)[^:：]*[:：]\s*",
            "",
            translated,
            flags=re.IGNORECASE,
        )

        if not translated:
            logger.warning(f"{LOG_TAG} [translate] provider 返回空内容，原样透传")
            return prompt

        logger.info(
            f"{LOG_TAG} [translate] 完成 | out_len={len(translated)} "
            f"preview='{translated[:60]}...'"
        )
        return translated
