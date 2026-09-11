from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from agent_service.documents import DocumentChunk
from agent_service.retrieval import HybridIndex
from .errors import EvaluationValidationError
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
    for ch in cjk_chars:
        tokens.append(ch)
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
        # 1. Extract configuration from manifest
        retriever_cfg = manifest.retriever_config or {}
        top_k = int(retriever_cfg.get("top_k", 5))
        min_score = float(retriever_cfg.get("min_score", 0.1))
        excluded_sources = set(retriever_cfg.get("excluded_sources", []))
        excluded_chunk_ids = set(retriever_cfg.get("excluded_chunk_ids", []))

        user_groups = set(sanitized_input.persona_context.get("acl_groups") or ["ALL_EMPLOYEES"])
        acl_policy = manifest.acl_policy.upper()

        # 2. Try loading production HybridIndex from release
        raw_chunks: list[dict[str, Any]] = []
        if manifest.knowledge_release_id and self._releases_dir:
            rel_dir = self._releases_dir / manifest.knowledge_release_id
            cand1 = rel_dir / "index" / "chunks.json"
            cand2 = rel_dir / "chunks.json"
            chosen = cand1 if cand1.is_file() else (cand2 if cand2.is_file() else None)
            if chosen:
                try:
                    data = json.loads(chosen.read_text(encoding="utf-8"))
                    raw_chunks = list(data.get("chunks", []))
                except Exception as exc:
                    logger.warning("Failed loading release chunks from %s: %s", chosen, exc)
        elif self._corpus_provider:
            raw_chunks = list(self._corpus_provider(manifest.target_id))

        if not raw_chunks:
            return []

        # 3. Build HybridIndex with DocumentChunk objects
        chunk_map: dict[str, dict[str, Any]] = {}
        doc_chunks: list[DocumentChunk] = []
        for item in raw_chunks:
            cid = str(item.get("chunk_id", ""))
            chunk_map[cid] = item
            groups = item.get("allowed_groups") or item.get("acl_groups")
            doc_chunk = DocumentChunk(
                chunk_id=cid,
                title=str(item.get("title", "")),
                source_path=str(item.get("source_path", item.get("source_id", cid))),
                content=str(item.get("content", "")),
                classification=str(item.get("classification", "internal")),
                allowed_groups=list(groups) if groups else None,
                document_id=item.get("document_id") or item.get("source_id"),
                version_id=item.get("version_id"),
                release_id=item.get("release_id"),
                section=item.get("section"),
                page=item.get("page"),
                source_type=item.get("source_type"),
            )
            doc_chunks.append(doc_chunk)

        try:
            hybrid_index = HybridIndex(doc_chunks)
            if acl_policy == "STRICT":
                search_groups = user_groups
            else:
                search_groups = set(user_groups)
                for c in doc_chunks:
                    if c.allowed_groups:
                        search_groups.update(c.allowed_groups)
            search_results = hybrid_index.search(query, top_k * 3, groups=search_groups)
        except Exception as exc:
            logger.warning("HybridIndex search failed: %s", exc)
            return []

        scored_chunks: list[dict[str, Any]] = []
        for res in search_results:
            c = res.chunk
            raw = chunk_map.get(c.chunk_id, {})
            source_id = str(raw.get("source_id") or c.document_id or c.source_path)

            if c.chunk_id in excluded_chunk_ids or source_id in excluded_sources or c.source_path in excluded_sources:
                continue

            if res.score < min_score:
                continue

            scored_chunks.append({
                "chunk_id": c.chunk_id,
                "source_id": source_id,
                "source_path": c.source_path,
                "title": c.title,
                "content": c.content,
                "score": round(res.score, 4),
                "evidence_id": raw.get("evidence_id") or c.chunk_id,
            })
            if len(scored_chunks) >= top_k:
                break

        return scored_chunks


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
        version = (manifest.prompt_version or "").strip()
        if version and self._prompt_resolver is not None:
            resolved = self._prompt_resolver(version)
            if resolved:
                return resolved
        from agent_service.knowledge import ANSWER_PROMPT

        return ANSWER_PROMPT

    def _resolve_chat_model(self, manifest: TargetManifest) -> Any | None:
        model_id = (manifest.model_id or "").strip()
        if model_id and self._model_factory is not None:
            built = self._model_factory(model_id)
            if built is not None:
                return built
        return self._chat_model

    def _priced_cost(
        self,
        *,
        model_id: str | None,
        total_tokens: int | None,
        prompt_chars: int,
        answer_chars: int,
    ) -> float:
        from agent_service.usage import estimate_cost_usd

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
        # 1. External model invoker callable
        if self._model_invoker:
            res = self._model_invoker(
                query,
                manifest,
                sanitized_input,
                retrieved_evidence,
                conversation_history or [],
            )
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

        # 2. Target-manifest-aware LangChain chat model
        chat_model = self._resolve_chat_model(manifest)
        if chat_model:
            from langchain_core.messages import HumanMessage, SystemMessage

            prompt_template = self._resolve_prompt_template(manifest)
            context = "\n\n".join(
                f"[{ev.get('title') or ev.get('source_id') or f'S{i}'}]\n{ev.get('content', '')}"
                for i, ev in enumerate(retrieved_evidence, start=1)
            )
            try:
                system_content = prompt_template.format(question=query, context=context)
            except (KeyError, ValueError):
                system_content = f"{prompt_template}\n\n問題：{query}\n\n依據：\n{context}"
            messages = [
                SystemMessage(content=system_content),
                HumanMessage(
                    content=f"使用者原始問題：{query}\n請根據上述已授權知識內容直接回答。"
                ),
            ]
            response = chat_model.invoke(messages)
            answer = response.content if hasattr(response, "content") else str(response)
            usage = getattr(response, "usage_metadata", None) or {}
            tokens = usage.get("total_tokens")
            req_id = getattr(response, "id", None) or getattr(
                response, "response_metadata", {}
            ).get("id")
            prompt_chars = len(query) + sum(
                len(e.get("content", "")) for e in retrieved_evidence
            )
            cost = self._priced_cost(
                model_id=manifest.model_id,
                total_tokens=tokens,
                prompt_chars=prompt_chars,
                answer_chars=len(str(answer)),
            )
            return answer, tokens, cost, [], req_id

        # 3. If no real model is configured and synthetic fallback is not allowed: fail-fast!
        if not self._allow_synthetic_fallback:
            raise EvaluationValidationError(
                "REAL_RAG execution requires a registered real model invoker or chat model. "
                "Synthetic answer generation is rejected in formal REAL_RAG evaluation (Spec 6.2)."
            )

        # 4. Grounded synthesis fallback (only when allow_synthetic_fallback=True)
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
        cost = self._priced_cost(
            model_id=manifest.model_id or "synthetic-local",
            total_tokens=estimated_tokens,
            prompt_chars=prompt_len,
            answer_chars=len(answer),
        )
        return answer, estimated_tokens, cost, [], None


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
