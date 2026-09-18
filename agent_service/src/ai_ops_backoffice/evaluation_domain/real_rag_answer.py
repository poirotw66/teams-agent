"""Answer-path helpers for RealRagAnswerAdapter."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .errors import EvaluationValidationError
from .runner_models import TargetExecutionInput, TargetManifest
from .tool_fixture_models import ToolCallTrace


def normalize_model_invoker_result(
    res: Any,
) -> tuple[str, int | None, float, list[ToolCallTrace], str | None] | None:
    if isinstance(res, tuple):
        if len(res) == 5:
            return res[0], res[1], res[2], list(res[3]), res[4]
        if len(res) == 4:
            return res[0], res[1], res[2], [], res[3]
        if len(res) == 3:
            return res[0], res[1], res[2], [], None
    elif isinstance(res, dict):
        return (
            res.get("answer", ""),
            res.get("tokens"),
            float(res.get("cost", 0.0)),
            list(res.get("tool_calls", [])),
            res.get("request_id") or res.get("provider_request_id"),
        )
    return None


def invoke_chat_model_answer(
    *,
    chat_model: Any,
    query: str,
    manifest: TargetManifest,
    sanitized_input: TargetExecutionInput,
    retrieved_evidence: list[dict[str, Any]],
    conversation_history: list[dict[str, str]] | None,
    prompt_template: str,
    priced_cost: Callable[..., float],
) -> tuple[str, int | None, float, list[ToolCallTrace], str | None]:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    context = "\n\n".join(
        f"[{ev.get('title') or ev.get('source_id') or f'S{i}'}]\n{ev.get('content', '')}"
        for i, ev in enumerate(retrieved_evidence, start=1)
    )
    try:
        system_content = prompt_template.format(question=query, context=context)
    except (KeyError, ValueError):
        system_content = f"{prompt_template}\n\n問題：{query}\n\n依據：\n{context}"
    history = list(conversation_history or [])
    if not history:
        history = [
            {"role": str(item.get("role") or ""), "content": str(item.get("content") or "")}
            for item in (getattr(sanitized_input, "conversation_history", None) or ())
            if isinstance(item, dict)
        ]
    messages: list[Any] = [SystemMessage(content=system_content)]
    for item in history:
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        if role in {"assistant", "ai", "model"}:
            messages.append(AIMessage(content=content))
        else:
            messages.append(HumanMessage(content=content))
    messages.append(
        HumanMessage(content=f"使用者原始問題：{query}\n請根據上述已授權知識內容直接回答。")
    )
    response = chat_model.invoke(messages)
    answer = response.content if hasattr(response, "content") else str(response)
    usage = getattr(response, "usage_metadata", None) or {}
    tokens = usage.get("total_tokens")
    req_id = getattr(response, "id", None) or getattr(response, "response_metadata", {}).get("id")
    history_chars = sum(len(str(item.get("content") or "")) for item in history)
    prompt_chars = (
        len(query) + history_chars + sum(len(e.get("content", "")) for e in retrieved_evidence)
    )
    cost = priced_cost(
        model_id=manifest.model_id,
        total_tokens=tokens,
        prompt_chars=prompt_chars,
        answer_chars=len(str(answer)),
    )
    return answer, tokens, cost, [], req_id


def synthesize_fallback_answer(
    *,
    query: str,
    manifest: TargetManifest,
    retrieved_evidence: list[dict[str, Any]],
    allow_synthetic_fallback: bool,
    priced_cost: Callable[..., float],
) -> tuple[str, int | None, float, list[ToolCallTrace], str | None]:
    if not allow_synthetic_fallback:
        raise EvaluationValidationError(
            "REAL_RAG execution requires a registered real model invoker or chat model. "
            "Synthetic answer generation is rejected in formal REAL_RAG evaluation (Spec 6.2)."
        )
    if not retrieved_evidence:
        return (
            f"抱歉，目前的知識庫中沒有找到與「{query}」相關的已授權資訊。",
            85,
            0.0,
            [],
            None,
        )
    citations: list[str] = []
    facts: list[str] = []
    for idx, ev in enumerate(retrieved_evidence[:3], start=1):
        title = ev.get("title") or ev.get("source_id") or f"文件{idx}"
        content = ev.get("content", "").strip()
        citations.append(f"[{title}]")
        facts.append(content)
    answer_body = " ".join(facts)
    citation_str = " ".join(dict.fromkeys(citations))
    answer = f"根據相關規範，{answer_body} (依據來源：{citation_str})"
    prompt_len = len(query) + sum(len(e.get("content", "")) for e in retrieved_evidence)
    estimated_tokens = int((prompt_len + len(answer)) / 2)
    cost = priced_cost(
        model_id=manifest.model_id or "synthetic-local",
        total_tokens=estimated_tokens,
        prompt_chars=prompt_len,
        answer_chars=len(answer),
    )
    return answer, estimated_tokens, cost, [], None
