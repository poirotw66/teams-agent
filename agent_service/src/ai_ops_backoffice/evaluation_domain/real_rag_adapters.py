from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ai_ops_backoffice.ports.answer_prompt import get_default_answer_prompt

from .errors import EvaluationValidationError
from .real_rag_answer import (
    invoke_chat_model_answer,
    normalize_model_invoker_result,
    synthesize_fallback_answer,
)
from .real_rag_retrieve import build_document_chunks, load_raw_chunks, score_retrieved_chunks
from .runner_models import TargetExecutionInput, TargetManifest
from .tool_fixture_models import ToolCallTrace
from .tool_fixtures import ToolFixtureService

logger = logging.getLogger(__name__)


def tokenize_cjk_and_words(text: str) -> list[str]:
    """Tokenizes text into words and CJK bigrams for robust exact and semantic retrieval matching."""
    tokens: list[str] = []
    # Match standard alphanumeric words
    word_tokens = [t.lower() for t in re.findall(r"[a-zA-Z0-9_\-]+", text) if len(t) > 1]
    tokens.extend(word_tokens)

    # Match CJK characters and form unigrams and bigrams
    cjk_chars = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
    tokens.extend(cjk_chars)
    for i in range(len(cjk_chars) - 1):
        tokens.append("".join(cjk_chars[i : i + 2]))

    return tokens or [text.lower()]


class RealRagRetrieverAdapter:
    """Formal, reusable retrieval pipeline adapter for REAL_RAG evaluation.
    
    Loads pinned knowledge release artifacts, applies ACL and retriever configs,
    and returns verified evidence chunks using the production BM25 HybridIndex pipeline (Spec 6.1).
    """

    def __init__(
        self,
        releases_dir: Path | None = None,
        *,
        corpus_provider: Callable[[str], list[dict[str, Any]]] | None = None,
    ) -> None:
        self._releases_dir = releases_dir
        self._corpus_provider = corpus_provider

    def __call__(
        self,
        query: str,
        manifest: TargetManifest,
        sanitized_input: TargetExecutionInput,
    ) -> list[dict[str, Any]]:
        retriever_cfg = manifest.retriever_config or {}
        top_k = int(retriever_cfg.get("top_k", 5))
        min_score = float(retriever_cfg.get("min_score", 0.1))
        excluded_sources = set(retriever_cfg.get("excluded_sources", []))
        excluded_chunk_ids = set(retriever_cfg.get("excluded_chunk_ids", []))
        user_groups = set(
            sanitized_input.persona_context.get("acl_groups") or ["ALL_EMPLOYEES"]
        )
        raw_chunks = load_raw_chunks(
            manifest=manifest,
            releases_dir=self._releases_dir,
            corpus_provider=self._corpus_provider,
        )
        if not raw_chunks:
            return []
        chunk_map, doc_chunks = build_document_chunks(raw_chunks)
        return score_retrieved_chunks(
            query=query,
            doc_chunks=doc_chunks,
            chunk_map=chunk_map,
            user_groups=user_groups,
            acl_policy=manifest.acl_policy.upper(),
            top_k=top_k,
            min_score=min_score,
            excluded_sources=excluded_sources,
            excluded_chunk_ids=excluded_chunk_ids,
        )


class RealRagAnswerAdapter:
    """Formal answering pipeline adapter for REAL_RAG evaluation.

    Applies target manifest prompt/model when provided, records governed pricing,
    and rejects synthetic answers in strict formal mode (Spec 6.1–6.2).
    """

    def __init__(
        self,
        *,
        model_invoker: Callable[..., Any] | None = None,
        chat_model: Any | None = None,
        model_factory: Callable[[str], Any] | None = None,
        prompt_resolver: Callable[[str], str | None] | None = None,
        cost_estimator: Callable[..., float | None] | None = None,
        allow_synthetic_fallback: bool = False,
    ) -> None:
        self._model_invoker = model_invoker
        self._chat_model = chat_model
        self._model_factory = model_factory
        self._prompt_resolver = prompt_resolver
        self._cost_estimator = cost_estimator
        self._allow_synthetic_fallback = allow_synthetic_fallback

    def is_real_model_configured(self) -> bool:
        if self._model_invoker or self._chat_model:
            return True
        if self._model_factory is None:
            return False
        # Factory alone is not enough: it must be able to produce a live model.
        try:
            probed = self._model_factory("") or self._model_factory("probe")
        except Exception:
            return False
        return probed is not None

    def _resolve_prompt_template(self, manifest: TargetManifest) -> str:
        version = (manifest.prompt_version or "").strip() or "default"
        if self._prompt_resolver is not None:
            resolved = self._prompt_resolver(version)
            if resolved:
                return resolved
            if version != "default":
                raise EvaluationValidationError(
                    f"REAL_RAG rejected: prompt_version '{version}' could not be resolved. "
                    "Silent fallback to another prompt is prohibited."
                )
        if version != "default":
            raise EvaluationValidationError(
                f"REAL_RAG rejected: prompt_version '{version}' requires a registered prompt resolver."
            )
        return get_default_answer_prompt()

    def _resolve_chat_model(self, manifest: TargetManifest) -> Any | None:
        model_id = (manifest.model_id or "").strip()
        if model_id and self._model_factory is not None:
            built = self._model_factory(model_id)
            if built is not None:
                return built
            raise EvaluationValidationError(
                f"REAL_RAG rejected: model_id '{model_id}' could not be constructed. "
                "Silent fallback to another model is prohibited."
            )
        if model_id and self._chat_model is not None:
            # Shared chat model is only allowed when it matches the requested id.
            default_name = str(getattr(self._chat_model, "model_name", "") or "")
            if default_name and default_name != model_id:
                raise EvaluationValidationError(
                    f"REAL_RAG rejected: requested model '{model_id}' does not match "
                    f"bound chat model '{default_name}'."
                )
        return self._chat_model

    def _priced_cost(
        self,
        *,
        model_id: str | None,
        total_tokens: int | None,
        prompt_chars: int,
        answer_chars: int,
    ) -> float:
        from operations_core.usage import estimate_cost_usd

        total = total_tokens
        if total is None or total <= 0:
            total = max(1, int((prompt_chars + answer_chars) / 4))
        ratio = prompt_chars / max(1, prompt_chars + answer_chars)
        input_tokens = max(0, int(total * ratio))
        output_tokens = max(0, total - input_tokens)
        model_name = (model_id or "").strip() or "unknown"
        estimator = self._cost_estimator or estimate_cost_usd
        priced = estimator(model_name, input_tokens, output_tokens)
        return float(priced) if priced is not None else 0.0

    def __call__(
        self,
        query: str,
        manifest: TargetManifest,
        sanitized_input: TargetExecutionInput,
        retrieved_evidence: list[dict[str, Any]],
        conversation_history: list[dict[str, str]] | None = None,
    ) -> tuple[str, int | None, float, list[ToolCallTrace], str | None]:
        """Returns (answer, actual_tokens_or_none, cost_usd, tool_calls, provider_request_id)."""
        if self._model_invoker:
            normalized = normalize_model_invoker_result(
                self._model_invoker(
                    query,
                    manifest,
                    sanitized_input,
                    retrieved_evidence,
                    conversation_history or [],
                )
            )
            if normalized is not None:
                return normalized

        chat_model = self._resolve_chat_model(manifest)
        if chat_model:
            return invoke_chat_model_answer(
                chat_model=chat_model,
                query=query,
                manifest=manifest,
                sanitized_input=sanitized_input,
                retrieved_evidence=retrieved_evidence,
                conversation_history=conversation_history,
                prompt_template=self._resolve_prompt_template(manifest),
                priced_cost=self._priced_cost,
            )

        return synthesize_fallback_answer(
            query=query,
            manifest=manifest,
            retrieved_evidence=retrieved_evidence,
            allow_synthetic_fallback=self._allow_synthetic_fallback,
            priced_cost=self._priced_cost,
        )


class RealAgentSandboxAdapter:
    """Formal agent sandbox adapter for AGENT_SANDBOX evaluation mode.
    
    Executes real planning/tool selection while intercepting mutations and side effects (Spec 6.3).
    """

    def __init__(
        self,
        tool_fixture_service: ToolFixtureService,
        *,
        workflow_executor: Any | None = None,
    ) -> None:
        self._fixture_service = tool_fixture_service
        self._workflow_executor = workflow_executor

    def is_real_workflow_configured(self) -> bool:
        return self._workflow_executor is not None

    def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        attempt: int = 1,
    ) -> ToolCallTrace:
        return self._fixture_service.execute_sandbox_tool(
            tool_name=tool_name,
            arguments=arguments,
            attempt=attempt,
        )

    def execute_workflow_turn(
        self,
        query: str,
        manifest: TargetManifest,
        sanitized_input: TargetExecutionInput,
    ) -> Any:
        if self._workflow_executor is not None:
            return self._workflow_executor(query, manifest, sanitized_input)
        raise EvaluationValidationError("No workflow executor configured for agent sandbox.")
