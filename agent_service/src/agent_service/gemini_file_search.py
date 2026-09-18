"""Gemini File Search Knowledge Service adapter — SPIKE ONLY (spec §8.3).

Per spec §8.3, Gemini File Search is *only* a candidate adapter behind
``KNOWLEDGE_SERVICE_MODE=GEMINI_FILE_SEARCH``. It must not replace
``HybridKnowledgeService`` (spec §8.2) as the default in this phase, and
this phase only requires a technical spike (create a store, upload a few
test documents, run Traditional Chinese queries, inspect sources, test a
metadata filter, test document deletion, compare error-code/專有名詞 recall)
rather than a full File Search document-sync platform.

The ``google-genai`` SDK is treated as an optional, spike-only dependency
(pyproject ``[project.optional-dependencies].spike``). It is imported lazily
inside ``search()`` so importing this module — and running the rest of the
test suite — never requires it to be installed.
"""

from __future__ import annotations

import logging

from .contracts import AgentRequest, KnowledgeResult, UserContext
from .execution_context import (
    ExecutionContext,
    RequestDeadlineExceeded,
    RequestModelBudgetExceeded,
    RequestOperationTimedOut,
)
from .file_search_acl import filter_for
from .file_search_registry import FileSearchDocumentRegistry
from .file_search_usage import FileSearchUsage, estimate_cost, extract_usage, log_fields
from .gemini_file_search_grounding import (
    GROUNDING_SYSTEM_INSTRUCTION,
    GeminiGroundingChunk,
    canonicalize_legacy_terms,
    grounding_chunks,
    response_text,
)
from .gemini_file_search_result import (
    citations_from_chunks,
    empty_miss_result,
    grounded_answer_result,
    images_for,
    limit_result,
    with_retrieval_trace,
)
from .gemini_file_search_sdk import import_genai
from .knowledge import answer_indicates_insufficient_information
from .llm_call_counter import LlmCallCounter
from .usage_events import extract_file_search_usage_from_result

logger = logging.getLogger(__name__)

__all__ = [
    "GROUNDING_SYSTEM_INSTRUCTION",
    "GeminiFileSearchKnowledgeService",
    "GeminiGroundingChunk",
]


class GeminiFileSearchKnowledgeService:
    """Candidate Knowledge Service adapter backed by Gemini File Search.

    NOT the default. Selected only when
    ``settings.knowledge_service_mode == "GEMINI_FILE_SEARCH"``.
    """

    def __init__(
        self,
        api_key: str | None,
        file_search_store: str,
        model: str = "gemini-3.5-flash-lite",
        top_k: int = 4,
        registry: FileSearchDocumentRegistry | None = None,
        max_images: int = 2,
        enforce_acl: bool = True,
    ) -> None:
        if not file_search_store:
            raise ValueError("file_search_store is required (GEMINI_FILE_SEARCH_STORE).")
        self.api_key = api_key
        self.file_search_store = file_search_store
        self.model = model
        self.top_k = top_k
        self.registry = registry
        self.max_images = max_images
        self.enforce_acl = enforce_acl
        self._client = None

        # Usage/cost of the most recent search() call, mirroring
        # HybridKnowledgeService's last_llm_call_count convention
        # (knowledge.py) rather than inventing a third exposure pattern.
        self.last_usage: FileSearchUsage | None = None
        self.last_cost_usd: float | None = None

        if not enforce_acl:
            # Loudly logged per Task 17 requirement C: disabling ACL
            # enforcement must never be a quiet default.
            logger.warning(
                "GeminiFileSearchKnowledgeService constructed with "
                "enforce_acl=False: no metadata_filter will be derived from "
                "the caller's groups, so every document in "
                "file_search_store=%s is visible to every caller regardless "
                "of allowed_groups. This must never be the default in "
                "production.",
                file_search_store,
            )

    def _get_client(self):
        genai, _types = import_genai()
        if self._client is None:
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _resolve_title(self, slug: str) -> str:
        """Map a grounding chunk's ASCII upload slug to its real title."""
        if self.registry is None:
            return slug
        title = self.registry.title_for(slug)
        return title if title is not None else slug

    def _with_trace(
        self,
        result: KnowledgeResult,
        *,
        query: str,
        chunks: list[GeminiGroundingChunk],
        request: AgentRequest | None,
        execution_context: ExecutionContext | None,
        decision: str,
        terminal_reason: str | None,
    ) -> KnowledgeResult:
        return with_retrieval_trace(
            result,
            query=query,
            chunks=chunks,
            request=request,
            execution_context=execution_context,
            decision=decision,
            terminal_reason=terminal_reason,
            registry=self.registry,
            resolve_title=self._resolve_title,
        )

    def _effective_metadata_filter(
        self,
        user_context: UserContext,
        metadata_filter: str | None,
    ) -> str | None:
        if not self.enforce_acl:
            return metadata_filter
        if metadata_filter is not None:
            raise ValueError(
                "GeminiFileSearchKnowledgeService.search: a caller-supplied "
                "metadata_filter cannot be combined with ACL enforcement "
                "(enforce_acl=True) because AND-combining filter strings "
                "was never verified against a live File Search store "
                "(docs/gemini-file-search-spike.md finding 9). Passing a "
                "filter here could silently widen access past the "
                "caller's groups. Narrow via allowed_groups at upload "
                "time instead, or construct with enforce_acl=False if "
                "you are enforcing ACL elsewhere."
            )
        return filter_for(user_context.groups)

    async def _generate_content(
        self,
        *,
        query: str,
        effective_filter: str | None,
        call_counter: LlmCallCounter | None,
        execution_context: ExecutionContext | None,
    ) -> object:
        _genai, types = import_genai()
        client = self._get_client()
        file_search_tool = types.Tool(
            file_search=types.FileSearch(
                file_search_store_names=[self.file_search_store],
                top_k=self.top_k,
                metadata_filter=effective_filter,
            )
        )

        async def _generate() -> object:
            return await client.aio.models.generate_content(
                model=self.model,
                contents=query,
                config=types.GenerateContentConfig(
                    tools=[file_search_tool],
                    # Required, not optional. Verified in the 2026-08-06 spike:
                    # with File Search's own default prompting the model answers
                    # company questions from general knowledge — it appended
                    # 「但通常VPN連線問題可能與以下幾個方面有關」 to a correct
                    # "not documented" reply, and on another probe mixed in steps
                    # belonging to a different document. Both breach §8.4/§17.
                    # Re-running the same probe with these rules produced a clean
                    # refusal. See docs/gemini-file-search-spike.md finding 4.
                    system_instruction=GROUNDING_SYSTEM_INSTRUCTION,
                ),
            )

        if execution_context is not None:
            return await execution_context.run_llm(
                _generate,
                component="gemini_file_search",
                model=self.model,
                usage_from_result=extract_file_search_usage_from_result,
            )
        if call_counter is not None:
            call_counter.increment()
        return await _generate()

    def _record_usage(self, response: object, *, correlation_id: str | None) -> None:
        usage = extract_usage(response)
        self.last_usage = usage
        self.last_cost_usd = estimate_cost(usage, self.model)
        logger.info(
            "File Search query usage: correlation_id=%s input_tokens=%s "
            "output_tokens=%s total_tokens=%s estimated_cost_usd=%s usage=%s",
            correlation_id,
            usage.input_tokens,
            usage.output_tokens,
            usage.total_tokens,
            self.last_cost_usd,
            log_fields(usage, self.model),
        )

    def _build_grounded_result(
        self,
        *,
        query: str,
        chunks: list[GeminiGroundingChunk],
        answer: str,
        request: AgentRequest | None,
        execution_context: ExecutionContext | None,
    ) -> KnowledgeResult:
        sources = citations_from_chunks(
            chunks,
            registry=self.registry,
            resolve_title=self._resolve_title,
            request=request,
        )
        return self._with_trace(
            grounded_answer_result(
                answer=answer,
                sources=sources,
                images=images_for(chunks, registry=self.registry, max_images=self.max_images),
            ),
            query=query,
            chunks=chunks,
            request=request,
            execution_context=execution_context,
            decision="GROUNDED_ANSWER",
            terminal_reason=None,
        )

    def _limit_trace(
        self,
        *,
        query: str,
        request: AgentRequest | None,
        execution_context: ExecutionContext | None,
        terminal_reason: str,
        decision: str,
    ) -> KnowledgeResult:
        return self._with_trace(
            limit_result(terminal_reason),
            query=query,
            chunks=[],
            request=request,
            execution_context=execution_context,
            decision=decision,
            terminal_reason=terminal_reason,
        )

    def _result_from_response(
        self,
        response: object,
        *,
        query: str,
        request: AgentRequest | None,
        execution_context: ExecutionContext | None,
        correlation_id: str | None,
    ) -> KnowledgeResult:
        self._record_usage(response, correlation_id=correlation_id)
        chunks = grounding_chunks(response)
        if not chunks:
            return self._with_trace(
                empty_miss_result(),
                query=query,
                chunks=[],
                request=request,
                execution_context=execution_context,
                decision="NO_GROUNDING",
                terminal_reason="NO_RELEVANT_EVIDENCE",
            )
        answer = canonicalize_legacy_terms(response_text(response), chunks)
        if answer_indicates_insufficient_information(answer):
            return self._with_trace(
                empty_miss_result(),
                query=query,
                chunks=chunks,
                request=request,
                execution_context=execution_context,
                decision="INSUFFICIENT_INFORMATION",
                terminal_reason="UNGROUNDED_ANSWER",
            )
        return self._build_grounded_result(
            query=query,
            chunks=chunks,
            answer=answer,
            request=request,
            execution_context=execution_context,
        )

    async def search(
        self,
        query: str,
        user_context: UserContext,
        *,
        correlation_id: str | None = None,
        call_counter: LlmCallCounter | None = None,
        execution_context: ExecutionContext | None = None,
        metadata_filter: str | None = None,
        request: AgentRequest | None = None,
    ) -> KnowledgeResult:
        """Run a grounded query against the configured File Search store."""
        effective_filter = self._effective_metadata_filter(user_context, metadata_filter)
        try:
            response = await self._generate_content(
                query=query,
                effective_filter=effective_filter,
                call_counter=call_counter,
                execution_context=execution_context,
            )
        except RequestModelBudgetExceeded:
            return self._limit_trace(
                query=query,
                request=request,
                execution_context=execution_context,
                terminal_reason="BUDGET_EXCEEDED",
                decision="BUDGET_LIMIT",
            )
        except (RequestDeadlineExceeded, RequestOperationTimedOut):
            return self._limit_trace(
                query=query,
                request=request,
                execution_context=execution_context,
                terminal_reason="DEADLINE_EXCEEDED",
                decision="DEADLINE_LIMIT",
            )
        return self._result_from_response(
            response,
            query=query,
            request=request,
            execution_context=execution_context,
            correlation_id=correlation_id,
        )
