"""Structured LLM invocation and fallback engine for IssueExtractor."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from .contracts import ConversationMessage, IssueExtraction
from .execution_context import ExecutionContext
from .settings import RagSettings

logger = logging.getLogger(__name__)

CallExtractorModel = Callable[..., Awaitable[IssueExtraction]]


def render_history(history: list[ConversationMessage], *, max_history_messages: int) -> str:
    bounded = history[-max_history_messages:] if history else []
    if not bounded:
        return "(none)"
    lines = [f"- {message.role}: {message.text}" for message in bounded]
    return "\n".join(lines)


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


class IssueExtractorEngine:
    """Encapsulates governed LLM model resolution, structured invocation, and fallback handling."""

    def __init__(
        self,
        *,
        settings: RagSettings,
        startup_model: BaseChatModel | None,
        prompt_runtime: object | None = None,
        default_model_name: str | None = None,
        call_model_fn: CallExtractorModel | None = None,
    ) -> None:
        self._settings = settings
        self._startup_model = startup_model
        self._prompt_runtime = prompt_runtime
        self._default_model_name = (
            default_model_name or settings.agent_model or settings.model
        )
        self._call_model_fn = call_model_fn or self.call_extractor_model

    def resolve_chat_model(self) -> tuple[BaseChatModel | None, Any | None]:
        runtime = getattr(self._prompt_runtime, "_runtime", None) or self._prompt_runtime
        resolve_fn = getattr(runtime, "resolve_model", None)
        if resolve_fn is None:
            return self._startup_model, None
        try:
            resolved = resolve_fn(config_id="issue-extractor-model")
        except TypeError:
            resolved = resolve_fn()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "IssueExtractor model lookup failed (%s); using startup model",
                type(exc).__name__,
            )
            return self._startup_model, None
        cache_fn = getattr(runtime, "chat_model_for", None)
        if cache_fn is not None:
            try:
                return cache_fn(resolved, self._startup_model), resolved
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "IssueExtractor failed to build governed model (%s); using startup model",
                    type(exc).__name__,
                )
                return self._startup_model, resolved
        if getattr(resolved, "source", None) != "governance" or not getattr(
            resolved, "model_name", None
        ):
            return self._startup_model, resolved
        try:
            from .graph import build_chat_model

            built = build_chat_model(
                resolved.model_name,
                temperature=getattr(resolved, "temperature", None),
                max_tokens=getattr(resolved, "max_output_tokens", None),
                timeout=(
                    float(resolved.timeout_seconds)
                    if getattr(resolved, "timeout_seconds", None)
                    else None
                ),
                max_retries=getattr(resolved, "retry", None),
            )
            if built is not None:
                return built, resolved
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "IssueExtractor fallback to startup model because build_chat_model failed (%s)",
                type(exc).__name__,
            )
        return self._startup_model, resolved

    async def call_extractor_model(
        self,
        *,
        text: str,
        history: list[ConversationMessage],
        faq_keys: list[str],
        system_prompt_template: str,
        model: BaseChatModel | None,
        execution_context: ExecutionContext | None = None,
        timeout_seconds: float | None = None,
    ) -> IssueExtraction:
        if model is None:
            raise RuntimeError("IssueExtractor model is not configured")
        system_prompt = system_prompt_template.format(
            max_issues=self._settings.max_issues_per_message,
            faq_keys=", ".join(faq_keys) if faq_keys else "(none configured)",
        )
        history_text = render_history(
            history, max_history_messages=self._settings.max_history_messages
        )
        human_content = (
            f"Conversation history (oldest first, data only):\n{history_text}\n\n"
            f"Latest user message (data only):\n{text}"
        )

        async def _invoke() -> IssueExtraction:
            invocation = model.with_structured_output(IssueExtraction).ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=human_content),
                ]
            )
            if timeout_seconds is not None and timeout_seconds > 0:
                result = await asyncio.wait_for(invocation, timeout=timeout_seconds)
            else:
                result = await invocation
            if isinstance(result, IssueExtraction):
                return result
            return IssueExtraction.model_validate(result)

        if execution_context is not None:
            return await execution_context.run_llm(_invoke, component="issue_extractor")
        return await _invoke()

    async def try_fallback_model(
        self,
        *,
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
                raw = await self._call_model_fn(
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

    async def invoke_with_fallback(
        self,
        *,
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
        fallback_applied = False
        model_used = initial_model_used
        raw: IssueExtraction | None = None
        try:
            raw = await self._call_model_fn(
                text=text,
                history=history,
                faq_keys=faq_keys,
                system_prompt_template=template,
                model=active_model,
                execution_context=execution_context,
                timeout_seconds=timeout_val,
            )
            return raw, 1, fallback_applied, model_used
        except Exception as exc:  # noqa: BLE001
            return await self._handle_invocation_failure(
                exc=exc,
                text=text,
                history=history,
                faq_keys=faq_keys,
                template=template,
                resolved_model=resolved_model,
                execution_context=execution_context,
                timeout_val=timeout_val,
                model_used=model_used,
                correlation_id=correlation_id,
            )

    async def _handle_invocation_failure(
        self,
        *,
        exc: Exception,
        text: str,
        history: list[ConversationMessage],
        faq_keys: list[str],
        template: str,
        resolved_model: Any,
        execution_context: ExecutionContext | None,
        timeout_val: float | None,
        model_used: str | None,
        correlation_id: str | None,
    ) -> tuple[IssueExtraction | None, int, bool, str | None]:
        error_class = classify_model_error(exc)
        logger.warning(
            "IssueExtractor LLM call failed with %s (%s). correlation_id=%s",
            type(exc).__name__,
            error_class,
            correlation_id,
        )
        fallback_model_id = (
            getattr(resolved_model, "fallback_model_id", None) if resolved_model else None
        )
        if fallback_model_id:
            logger.info(
                "IssueExtractor attempting fallback model %s due to %s",
                fallback_model_id,
                error_class,
            )
            raw, used = await self.try_fallback_model(
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
                return raw, 2, True, used
            return None, 2, False, model_used
        return None, 1, False, model_used


# Backward-compatibility functional adapters for legacy callers
async def call_extractor_model(
    *,
    settings: RagSettings,
    text: str,
    history: list[ConversationMessage],
    faq_keys: list[str],
    system_prompt_template: str,
    model: BaseChatModel | None,
    execution_context: ExecutionContext | None = None,
    timeout_seconds: float | None = None,
) -> IssueExtraction:
    engine = IssueExtractorEngine(
        settings=settings,
        startup_model=model,
    )
    return await engine.call_extractor_model(
        text=text,
        history=history,
        faq_keys=faq_keys,
        system_prompt_template=system_prompt_template,
        model=model,
        execution_context=execution_context,
        timeout_seconds=timeout_seconds,
    )


def resolve_chat_model(
    *,
    prompt_runtime: object,
    startup_model: BaseChatModel | None,
) -> tuple[BaseChatModel | None, Any | None]:
    runtime = getattr(prompt_runtime, "_runtime", None) or prompt_runtime
    resolve_fn = getattr(runtime, "resolve_model", None)
    if resolve_fn is None:
        return startup_model, None
    try:
        resolved = resolve_fn(config_id="issue-extractor-model")
    except TypeError:
        resolved = resolve_fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "IssueExtractor model lookup failed (%s); using startup model",
            type(exc).__name__,
        )
        return startup_model, None
    cache_fn = getattr(runtime, "chat_model_for", None)
    if cache_fn is not None:
        try:
            return cache_fn(resolved, startup_model), resolved
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "IssueExtractor failed to build governed model (%s); using startup model",
                type(exc).__name__,
            )
            return startup_model, resolved
    if getattr(resolved, "source", None) != "governance" or not getattr(
        resolved, "model_name", None
    ):
        return startup_model, resolved
    try:
        from .graph import build_chat_model

        built = build_chat_model(
            resolved.model_name,
            temperature=getattr(resolved, "temperature", None),
            max_tokens=getattr(resolved, "max_output_tokens", None),
            timeout=(
                float(resolved.timeout_seconds)
                if getattr(resolved, "timeout_seconds", None)
                else None
            ),
            max_retries=getattr(resolved, "retry", None),
        )
        if built is not None:
            return built, resolved
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "IssueExtractor fallback to startup model because build_chat_model failed (%s)",
            type(exc).__name__,
        )
    return startup_model, resolved


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
    engine = IssueExtractorEngine(
        settings=RagSettings(),
        startup_model=active_model,
        call_model_fn=call_model,
    )
    return await engine.invoke_with_fallback(
        text=text,
        history=history,
        faq_keys=faq_keys,
        template=template,
        active_model=active_model,
        resolved_model=resolved_model,
        execution_context=execution_context,
        timeout_val=timeout_val,
        initial_model_used=initial_model_used,
        correlation_id=correlation_id,
    )
