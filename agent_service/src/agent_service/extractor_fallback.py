"""Fallback and model-switch policy for IssueExtractor."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.language_models import BaseChatModel

from .contracts import ConversationMessage, IssueExtraction
from .execution_context import ExecutionContext

logger = logging.getLogger(__name__)

CallExtractorModel = Callable[..., Awaitable[IssueExtraction]]


def classify_model_error(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if (
        isinstance(exc, (TimeoutError, asyncio.TimeoutError))
        or "timeout" in name
        or "timed out" in msg
    ):
        return "TIMEOUT"
    if "ratelimit" in name or "rate_limit" in msg or "429" in msg or "resourceexhausted" in name:
        return "RATE_LIMIT"
    if (
        "unavailable" in name
        or "connect" in name
        or any(code in msg for code in ("500", "502", "503", "504"))
    ):
        return "UNAVAILABLE"
    return "ERROR"


async def try_fallback_model(
    *,
    call_model: CallExtractorModel,
    fallback_model_id: str,
    resolved_model: Any,
    timeout_val: float | None,
    text: str,
    history: list[ConversationMessage],
    faq_keys: list[str],
    template: str,
    execution_context: ExecutionContext | None,
    correlation_id: str | None,
) -> tuple[IssueExtraction | None, str | None]:
    try:
        from .graph import build_chat_model

        fallback_name = fallback_model_id
        if ":" not in fallback_name and getattr(resolved_model, "provider", None):
            fallback_name = f"{resolved_model.provider}:{fallback_name}"

        fallback_chat_model = build_chat_model(
            fallback_name,
            temperature=getattr(resolved_model, "temperature", None),
            max_tokens=getattr(resolved_model, "max_output_tokens", None),
            timeout=timeout_val,
            max_retries=getattr(resolved_model, "retry", None),
        )
        if fallback_chat_model is not None:
            raw = await call_model(
                text=text,
                history=history,
                faq_keys=faq_keys,
                system_prompt_template=template,
                model=fallback_chat_model,
                execution_context=execution_context,
                timeout_seconds=timeout_val,
            )
            return raw, fallback_name
    except Exception as fallback_exc:  # noqa: BLE001
        logger.error(
            "IssueExtractor fallback model %s failed with %s; using deterministic fallback. correlation_id=%s",
            fallback_model_id,
            type(fallback_exc).__name__,
            correlation_id,
        )
    return None, None


async def invoke_model_with_fallback(
    *,
    call_model: CallExtractorModel,
    text: str,
    history: list[ConversationMessage],
    faq_keys: list[str],
    template: str,
    active_model: BaseChatModel | None,
    resolved_model: Any,
    execution_context: ExecutionContext | None,
    timeout_val: float | None,
    initial_model_used: str | None,
    correlation_id: str | None,
) -> tuple[IssueExtraction | None, int, bool, str | None]:
    try:
        raw = await call_model(
            text=text,
            history=history,
            faq_keys=faq_keys,
            system_prompt_template=template,
            model=active_model,
            execution_context=execution_context,
            timeout_seconds=timeout_val,
        )
        return raw, 1, False, initial_model_used
    except Exception as exc:  # noqa: BLE001 - never let one bad call fail the request
        trigger = classify_model_error(exc)
        fallback_model_id = getattr(resolved_model, "fallback_model_id", None)
        fallback_on = tuple(getattr(resolved_model, "fallback_on", ()) or ())

        can_fallback = bool(fallback_model_id) and (not fallback_on or trigger in fallback_on)
        if can_fallback:
            logger.warning(
                "IssueExtractor primary model call failed with trigger '%s' (%s); attempting fallback model %s. correlation_id=%s",
                trigger,
                type(exc).__name__,
                fallback_model_id,
                correlation_id,
            )
            raw, fallback_name = await try_fallback_model(
                call_model=call_model,
                fallback_model_id=fallback_model_id,
                resolved_model=resolved_model,
                timeout_val=timeout_val,
                text=text,
                history=history,
                faq_keys=faq_keys,
                template=template,
                execution_context=execution_context,
                correlation_id=correlation_id,
            )
            if raw is not None:
                return raw, 2, True, fallback_name
            return None, 2, False, initial_model_used

        logger.error(
            "IssueExtractor LLM call failed with %s; using deterministic fallback. correlation_id=%s",
            type(exc).__name__,
            correlation_id,
        )
        return None, 1, False, initial_model_used
