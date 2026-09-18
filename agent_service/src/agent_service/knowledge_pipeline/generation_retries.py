"""Retry loops for grounded answer generation (coverage / false-NONE)."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from agent_service.execution_context import ExecutionContext
from agent_service.llm_call_counter import LlmCallCounter
from agent_service.retrieval import SearchResult
from agent_service.security_policies import strip_unknown_policy_markers

from .generator import (
    should_keep_prior_after_visual_retry,
    should_retry_error_coverage,
    should_retry_false_none,
    should_retry_procedure_coverage,
    should_retry_visual_evidence,
)
from .grounding import (
    error_branch_codes_in_text,
    missing_procedure_steps,
    missing_visual_evidence_plates,
    normalize_composite_citation_markers,
    procedure_steps_in_text,
    remap_claim_marker_ids_to_chunk_ids,
    repair_structured_answer,
    visual_evidence_plates_in_text,
)
from .models import StructuredKnowledgeAnswer
from .prompts import ANSWER_PROMPT

logger = logging.getLogger(__name__)


def _normalize_retry_response(
    response: StructuredKnowledgeAnswer,
    *,
    marker_to_chunk_ids: dict[str, list[str]],
    chunk_content_by_id: dict[str, str],
) -> tuple[StructuredKnowledgeAnswer, str]:
    repaired = repair_structured_answer(response)
    repaired.claims = remap_claim_marker_ids_to_chunk_ids(
        repaired.claims,
        marker_to_chunk_ids=marker_to_chunk_ids,
        chunk_content_by_id=chunk_content_by_id,
    )
    answer = normalize_composite_citation_markers(repaired.answer.strip())
    return repaired, strip_unknown_policy_markers(answer)


async def apply_generation_retries(
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
    enable_generation_retries: bool = True,
) -> tuple[StructuredKnowledgeAnswer, str]:
    if not enable_generation_retries:
        return response, answer
    confidence_label, _ = host.evaluate_retrieval_confidence(state)
    if should_retry_false_none(
        answerability=response.answerability,
        results=results,
        confidence_label=confidence_label,
        answer=answer,
        claims=response.claims,
        resolved_issue_query=state.resolved_issue_query,
    ):
        # Narrow retry: only when high-confidence retrieval + lexical overlap
        # still produced NONE / empty claims. Soften instruction so legitimate
        # NONE remains allowed when evidence cannot answer the question.
        async def _invoke_answer_retry() -> StructuredKnowledgeAnswer:
            return await answer_model.with_structured_output(
                StructuredKnowledgeAnswer
            ).ainvoke(
                [
                    SystemMessage(
                        content=ANSWER_PROMPT.format(
                            question=state.resolved_issue_query,
                            context=context,
                        )
                    ),
                    HumanMessage(
                        content=(
                            f"已解析問題：{state.resolved_issue_query}\n"
                            "上方檢索結果與問題有詞彙重疊。請再檢查一次："
                            "若文件已直接描述可支持的事實（例如角色權限範圍、錯誤碼處置），"
                            "請以 PARTIAL 或 FULL 作答並標註 [S#] 與真實 chunkId；"
                            "若文件仍不足以回答該問題，必須再次回傳 answerability=NONE，"
                            "不得用相關但答非所問的內容硬答。"
                        )
                    ),
                ]
            )

        logger.info(
            "Retrying knowledge generation after likely false NONE "
            "(confidence=%s results=%d)",
            confidence_label,
            len(results),
        )
        response = await host.invoke_llm(
            _invoke_answer_retry,
            component="knowledge_generate_retry",
            execution_context=execution_context,
            counter=counter,
        )
        response, answer = _normalize_retry_response(
            response,
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
    context_error_codes = error_branch_codes_in_text(context)
    if should_retry_error_coverage(
        answerability=response.answerability,
        resolved_issue_query=state.resolved_issue_query,
        context_error_codes=context_error_codes,
        answer=answer,
    ):
        codes_csv = ", ".join(f"({code})" for code in context_error_codes)

        async def _invoke_error_coverage_retry() -> StructuredKnowledgeAnswer:
            return await answer_model.with_structured_output(
                StructuredKnowledgeAnswer
            ).ainvoke(
                [
                    SystemMessage(
                        content=ANSWER_PROMPT.format(
                            question=state.resolved_issue_query,
                            context=context,
                        )
                    ),
                    HumanMessage(
                        content=(
                            f"已解析問題：{state.resolved_issue_query}\n"
                            f"知識內容包含錯誤碼分支：{codes_csv}。"
                            "請依「條件／錯誤碼 → 處置 → 完成或升級條件」重新作答，"
                            "逐項覆蓋這些分支；不得只給通用排查步驟，"
                            "也不得引用 [UX-AUDIT]/[TEST] 測試文件。"
                        )
                    ),
                ]
            )

        logger.info(
            "Retrying knowledge generation for incomplete error-code coverage "
            "(codes=%s)",
            context_error_codes,
        )
        response = await host.invoke_llm(
            _invoke_error_coverage_retry,
            component="knowledge_generate_error_coverage",
            execution_context=execution_context,
            counter=counter,
        )
        response, answer = _normalize_retry_response(
            response,
            marker_to_chunk_ids=marker_to_chunk_ids,
            chunk_content_by_id=chunk_content_by_id,
        )

        logger.info(
            "Knowledge error-coverage retry answer=%r answerability=%s claims=%s",
            answer,
            response.answerability,
            response.claims,
        )
    context_procedure_steps = procedure_steps_in_text(context)
    if should_retry_procedure_coverage(
        answerability=response.answerability,
        resolved_issue_query=state.resolved_issue_query,
        context_procedure_steps=context_procedure_steps,
        answer=answer,
    ):
        missing_steps = missing_procedure_steps(answer, context_procedure_steps)
        missing_csv = ", ".join(missing_steps)

        async def _invoke_procedure_coverage_retry() -> StructuredKnowledgeAnswer:
            return await answer_model.with_structured_output(
                StructuredKnowledgeAnswer
            ).ainvoke(
                [
                    SystemMessage(
                        content=ANSWER_PROMPT.format(
                            question=state.resolved_issue_query,
                            context=context,
                        )
                    ),
                    HumanMessage(
                        content=(
                            f"已解析問題：{state.resolved_issue_query}\n"
                            "此題需要可執行步驟／視覺順序，不可只給高階大綱。"
                            f"知識內容已包含但回答仍缺的關鍵步驟：{missing_csv}。"
                            "請依來源保留共同步驟與平台特有步驟、完成狀態；"
                            "先保完整再精簡用字，勿合併省略。"
                        )
                    ),
                ]
            )

        logger.info(
            "Retrying knowledge generation for incomplete procedure coverage "
            "(missing=%s)",
            missing_steps,
        )
        response = await host.invoke_llm(
            _invoke_procedure_coverage_retry,
            component="knowledge_generate_procedure_coverage",
            execution_context=execution_context,
            counter=counter,
        )
        response, answer = _normalize_retry_response(
            response,
            marker_to_chunk_ids=marker_to_chunk_ids,
            chunk_content_by_id=chunk_content_by_id,
        )

        logger.info(
            "Knowledge procedure-coverage retry answer=%r answerability=%s claims=%s",
            answer,
            response.answerability,
            response.claims,
        )
    context_visual_plates = visual_evidence_plates_in_text(context)
    if should_retry_visual_evidence(
        answerability=response.answerability,
        resolved_issue_query=state.resolved_issue_query,
        context_visual_plates=context_visual_plates,
        answer=answer,
    ):
        missing_plates = missing_visual_evidence_plates(answer, context_visual_plates)
        missing_csv = ", ".join(missing_plates[:8])
        answer_before_visual = answer
        response_before_visual = response

        async def _invoke_visual_evidence_retry() -> StructuredKnowledgeAnswer:
            return await answer_model.with_structured_output(
                StructuredKnowledgeAnswer
            ).ainvoke(
                [
                    SystemMessage(
                        content=ANSWER_PROMPT.format(
                            question=state.resolved_issue_query,
                            context=context,
                        )
                    ),
                    HumanMessage(
                        content=(
                            f"已解析問題：{state.resolved_issue_query}\n"
                            "此題要求依來源操作章節與 Visual Evidence／手冊頁說明順序。"
                            f"知識內容已有但回答未對照的章節或頁碼標記：{missing_csv}。"
                            "請在步驟中標出章節編號與手冊頁（例如第 1 章／手冊第 2 頁），"
                            "平台特有步驟（如 Intune）須列為獨立步驟；"
                            "並保留重啟、第二次驗證、進入收件匣等完成狀態，不可省略。"
                        )
                    ),
                ]
            )

        logger.info(
            "Retrying knowledge generation for incomplete visual evidence coverage "
            "(missing=%s)",
            missing_plates,
        )
        response = await host.invoke_llm(
            _invoke_visual_evidence_retry,
            component="knowledge_generate_visual_evidence",
            execution_context=execution_context,
            counter=counter,
        )
        response, answer = _normalize_retry_response(
            response,
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
            answer = answer_before_visual
            response = response_before_visual
        else:
            logger.info(
                "Knowledge visual-evidence retry answer=%r answerability=%s claims=%s",
                answer,
                response.answerability,
                response.claims,
            )
    return response, answer

__all__ = ["apply_generation_retries"]
