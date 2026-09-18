"""Structured LLM invocation for IssueExtractor."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from .contracts import ConversationMessage, IssueExtraction
from .execution_context import ExecutionContext
from .settings import RagSettings

logger = logging.getLogger(__name__)


def render_history(history: list[ConversationMessage], *, max_history_messages: int) -> str:
    bounded = history[-max_history_messages:] if history else []
    if not bounded:
        return "(none)"
    lines = [f"- {message.role}: {message.text}" for message in bounded]
    return "\n".join(lines)


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
    if model is None:
        raise RuntimeError("IssueExtractor model is not configured")
    system_prompt = system_prompt_template.format(
        max_issues=settings.max_issues_per_message,
        faq_keys=", ".join(faq_keys) if faq_keys else "(none configured)",
    )
    history_text = render_history(history, max_history_messages=settings.max_history_messages)
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
            timeout=float(resolved.timeout_seconds)
            if getattr(resolved, "timeout_seconds", None) is not None
            else None,
            max_retries=getattr(resolved, "retry", None),
        )
        return built or startup_model, resolved
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "IssueExtractor failed to build governed model %s (%s); using startup model",
            resolved.model_name,
            type(exc).__name__,
        )
        return startup_model, resolved
