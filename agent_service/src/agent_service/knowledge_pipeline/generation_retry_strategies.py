"""Individual generation retry strategies (false-NONE, coverage, visual)."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel

from agent_service.execution_context import ExecutionContext
from agent_service.llm_call_counter import LlmCallCounter
from agent_service.retrieval import SearchResult

from .generation_retry_invoke import invoke_structured_retry
from .generator import (
    should_keep_prior_after_visual_retry,
    should_retry_error_coverage,
    should_retry_false_none,
    should_retry_procedure_coverage,
    should_retry_ticket_intake_coverage,
    should_retry_visual_evidence,
)
from .grounding import (
    error_branch_codes_in_text,
    missing_procedure_steps,
    missing_visual_evidence_plates,
    procedure_steps_in_text,
    visual_evidence_plates_in_text,
)
from .models import StructuredKnowledgeAnswer
from .ticket_intake import (
    missing_ticket_intake_fields,
    ticket_intake_field_labels,
    ticket_intake_fields_in_text,
)

logger = logging.getLogger(__name__)


async def maybe_retry_false_none(
    host: Any,
    *,
    state: Any,
    results: list[SearchResult],
    answer_model: BaseChatModel,
    context: str,
    marker_to_chunk_ids: dict[str, list[str]],
    chunk_content_by_id: dict[str, str],
    response: StructuredKnowledgeAnswer,
    answer: str,
    counter: LlmCallCounter,
    execution_context: ExecutionContext | None,
) -> tuple[StructuredKnowledgeAnswer, str]:
    confidence_label, _ = host.evaluate_retrieval_confidence(state)
    if not should_retry_false_none(
        answerability=response.answerability,
        results=results,
        confidence_label=confidence_label,
        answer=answer,
        claims=response.claims,
        resolved_issue_query=state.resolved_issue_query,
    ):
        return response, answer
    # Narrow retry: only when high-confidence retrieval + lexical overlap
    # still produced NONE / empty claims. Soften instruction so legitimate
    # NONE remains allowed when evidence cannot answer the question.
    logger.info(
        "Retrying knowledge generation after likely false NONE "
        "(confidence=%s results=%d)",
        confidence_label,
        len(results),
    )
    response, answer = await invoke_structured_retry(
        host,
        answer_model=answer_model,
        question=state.resolved_issue_query,
        context=context,
        human_content=(
            f"已解析問題：{state.resolved_issue_query}\n"
            "上方檢索結果與問題有詞彙重疊。請再檢查一次："
            "若文件已直接描述可支持的事實（例如角色權限範圍、錯誤碼處置），"
            "請以 PARTIAL 或 FULL 作答並標註 [S#] 與真實 chunkId；"
            "若文件仍不足以回答該問題，必須再次回傳 answerability=NONE，"
            "不得用相關但答非所問的內容硬答。"
        ),
        component="knowledge_answer_retry",
        counter=counter,
        execution_context=execution_context,
        marker_to_chunk_ids=marker_to_chunk_ids,
        chunk_content_by_id=chunk_content_by_id,
    )
    logger.info(
        "Knowledge retry candidate answer=%r answerability=%s claims=%s unknowns=%s",
        answer,
        response.answerability,
        response.claims,
        response.unknowns,
    )
    return response, answer


async def maybe_retry_error_coverage(
    host: Any,
    *,
    state: Any,
    answer_model: BaseChatModel,
    context: str,
    marker_to_chunk_ids: dict[str, list[str]],
    chunk_content_by_id: dict[str, str],
    response: StructuredKnowledgeAnswer,
    answer: str,
    counter: LlmCallCounter,
    execution_context: ExecutionContext | None,
) -> tuple[StructuredKnowledgeAnswer, str]:
    context_error_codes = error_branch_codes_in_text(context)
    if not should_retry_error_coverage(
        answerability=response.answerability,
        resolved_issue_query=state.resolved_issue_query,
        context_error_codes=context_error_codes,
        answer=answer,
    ):
        return response, answer
    codes_csv = ", ".join(f"({code})" for code in context_error_codes)
    logger.info(
        "Retrying knowledge generation for incomplete error-code coverage "
        "(codes=%s)",
        context_error_codes,
    )
    response, answer = await invoke_structured_retry(
        host,
        answer_model=answer_model,
        question=state.resolved_issue_query,
        context=context,
        human_content=(
            f"已解析問題：{state.resolved_issue_query}\n"
            f"知識內容包含錯誤碼分支：{codes_csv}。"
            "請依「條件／錯誤碼 → 處置 → 完成或升級條件」重新作答，"
            "逐項覆蓋這些分支；不得只給通用排查步驟，"
            "也不得引用 [UX-AUDIT]/[TEST] 測試文件。"
        ),
        component="knowledge_answer_error_coverage",
        counter=counter,
        execution_context=execution_context,
        marker_to_chunk_ids=marker_to_chunk_ids,
        chunk_content_by_id=chunk_content_by_id,
    )
    logger.info(
        "Knowledge error-coverage retry answer=%r answerability=%s claims=%s",
        answer,
        response.answerability,
        response.claims,
    )
    return response, answer


async def maybe_retry_procedure_coverage(
    host: Any,
    *,
    state: Any,
    answer_model: BaseChatModel,
    context: str,
    marker_to_chunk_ids: dict[str, list[str]],
    chunk_content_by_id: dict[str, str],
    response: StructuredKnowledgeAnswer,
    answer: str,
    counter: LlmCallCounter,
    execution_context: ExecutionContext | None,
) -> tuple[StructuredKnowledgeAnswer, str]:
    context_procedure_steps = procedure_steps_in_text(context)
    if not should_retry_procedure_coverage(
        answerability=response.answerability,
        resolved_issue_query=state.resolved_issue_query,
        context_procedure_steps=context_procedure_steps,
        answer=answer,
    ):
        return response, answer
    missing_steps = missing_procedure_steps(answer, context_procedure_steps)
    missing_csv = ", ".join(missing_steps)
    logger.info(
        "Retrying knowledge generation for incomplete procedure coverage "
        "(missing=%s)",
        missing_steps,
    )
    response, answer = await invoke_structured_retry(
        host,
        answer_model=answer_model,
        question=state.resolved_issue_query,
        context=context,
        human_content=(
            f"已解析問題：{state.resolved_issue_query}\n"
            "此題需要可執行步驟／視覺順序，不可只給高階大綱。"
            f"知識內容已包含但回答仍缺的關鍵步驟：{missing_csv}。"
            "請依來源保留共同步驟與平台特有步驟、完成狀態；"
            "先保完整再精簡用字，勿合併省略。"
        ),
        component="knowledge_answer_procedure_coverage",
        counter=counter,
        execution_context=execution_context,
        marker_to_chunk_ids=marker_to_chunk_ids,
        chunk_content_by_id=chunk_content_by_id,
    )
    logger.info(
        "Knowledge procedure-coverage retry answer=%r answerability=%s claims=%s",
        answer,
        response.answerability,
        response.claims,
    )
    return response, answer


async def maybe_retry_ticket_intake_coverage(
    host: Any,
    *,
    state: Any,
    answer_model: BaseChatModel,
    context: str,
    marker_to_chunk_ids: dict[str, list[str]],
    chunk_content_by_id: dict[str, str],
    response: StructuredKnowledgeAnswer,
    answer: str,
    counter: LlmCallCounter,
    execution_context: ExecutionContext | None,
) -> tuple[StructuredKnowledgeAnswer, str]:
    context_ticket_fields = ticket_intake_fields_in_text(context)
    if not should_retry_ticket_intake_coverage(
        answerability=response.answerability,
        resolved_issue_query=state.resolved_issue_query,
        context_ticket_fields=context_ticket_fields,
        answer=answer,
    ):
        return response, answer
    missing_fields = missing_ticket_intake_fields(answer, context_ticket_fields)
    missing_csv = ", ".join(ticket_intake_field_labels(missing_fields))
    logger.info(
        "Retrying knowledge generation for incomplete ticket-intake coverage "
        "(missing=%s)",
        missing_fields,
    )
    response, answer = await invoke_structured_retry(
        host,
        answer_model=answer_model,
        question=state.resolved_issue_query,
        context=context,
        human_content=(
            f"已解析問題：{state.resolved_issue_query}\n"
            "來源已列出建立工單前必填欄位，不可只複製最短話術。"
            "請先告知無法自助／需由資訊人員處理，再以有序清單列出工單確認欄位。"
            f"知識內容已包含但回答仍缺的欄位：{missing_csv}。"
        ),
        component="knowledge_answer_ticket_intake_coverage",
        counter=counter,
        execution_context=execution_context,
        marker_to_chunk_ids=marker_to_chunk_ids,
        chunk_content_by_id=chunk_content_by_id,
    )
    logger.info(
        "Knowledge ticket-intake retry answer=%r answerability=%s claims=%s",
        answer,
        response.answerability,
        response.claims,
    )
    return response, answer


async def maybe_retry_visual_evidence(
    host: Any,
    *,
    state: Any,
    answer_model: BaseChatModel,
    context: str,
    marker_to_chunk_ids: dict[str, list[str]],
    chunk_content_by_id: dict[str, str],
    response: StructuredKnowledgeAnswer,
    answer: str,
    counter: LlmCallCounter,
    execution_context: ExecutionContext | None,
) -> tuple[StructuredKnowledgeAnswer, str]:
    context_visual_plates = visual_evidence_plates_in_text(context)
    context_procedure_steps = procedure_steps_in_text(context)
    if not should_retry_visual_evidence(
        answerability=response.answerability,
        resolved_issue_query=state.resolved_issue_query,
        context_visual_plates=context_visual_plates,
        answer=answer,
    ):
        return response, answer
    missing_plates = missing_visual_evidence_plates(answer, context_visual_plates)
    missing_csv = ", ".join(missing_plates[:8])
    answer_before_visual = answer
    response_before_visual = response
    logger.info(
        "Retrying knowledge generation for incomplete visual evidence coverage "
        "(missing=%s)",
        missing_plates,
    )
    response, answer = await invoke_structured_retry(
        host,
        answer_model=answer_model,
        question=state.resolved_issue_query,
        context=context,
        human_content=(
            f"已解析問題：{state.resolved_issue_query}\n"
            "此題要求依來源操作章節與 Visual Evidence／手冊頁說明順序。"
            f"知識內容已有但回答未對照的章節或頁碼標記：{missing_csv}。"
            "請在步驟中標出章節編號與手冊頁（例如第 1 章／手冊第 2 頁），"
            "平台特有步驟（如 Intune）須列為獨立步驟；"
            "並保留重啟、第二次驗證、進入收件匣等完成狀態，不可省略。"
        ),
        component="knowledge_answer_visual_evidence",
        counter=counter,
        execution_context=execution_context,
        marker_to_chunk_ids=marker_to_chunk_ids,
        chunk_content_by_id=chunk_content_by_id,
    )
    # Do not keep a visual retry that drops previously covered procedure steps.
    if should_keep_prior_after_visual_retry(
        context_procedure_steps=context_procedure_steps,
        answer=answer,
    ):
        logger.info(
            "Visual-evidence retry dropped procedure steps; keeping prior answer"
        )
        return response_before_visual, answer_before_visual
    logger.info(
        "Knowledge visual-evidence retry answer=%r answerability=%s claims=%s",
        answer,
        response.answerability,
        response.claims,
    )
    return response, answer


__all__ = [
    "maybe_retry_error_coverage",
    "maybe_retry_false_none",
    "maybe_retry_procedure_coverage",
    "maybe_retry_ticket_intake_coverage",
    "maybe_retry_visual_evidence",
]
