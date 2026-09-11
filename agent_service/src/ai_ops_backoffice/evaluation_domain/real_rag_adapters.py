from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

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
    and returns verified evidence chunks (Spec 6.1).
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
        chunks: list[dict[str, Any]] = []

        # 1. Load corpus from pinned release or external provider
        if manifest.knowledge_release_id and self._releases_dir:
            rel_dir = self._releases_dir / manifest.knowledge_release_id
            index_path = rel_dir / "index" / "chunks.json"
            if not index_path.is_file():
                index_path = rel_dir / "chunks.json"
            if index_path.is_file():
                try:
                    data = json.loads(index_path.read_text(encoding="utf-8"))
                    chunks = list(data.get("chunks", []))
                except Exception as exc:
                    logger.warning("Failed loading release chunks from %s: %s", index_path, exc)
        elif self._corpus_provider:
            chunks = list(self._corpus_provider(manifest.target_id))

        if not chunks:
            return []

        # 2. Extract configuration from manifest
        retriever_cfg = manifest.retriever_config or {}
        top_k = int(retriever_cfg.get("top_k", 5))
        min_score = float(retriever_cfg.get("min_score", 0.1))
        excluded_sources = set(retriever_cfg.get("excluded_sources", []))
        excluded_chunk_ids = set(retriever_cfg.get("excluded_chunk_ids", []))

        # 3. ACL Filtering
        user_groups = set(sanitized_input.persona_context.get("acl_groups") or ["ALL_EMPLOYEES"])
        acl_policy = manifest.acl_policy.upper()

        # 4. Score and filter chunks
        query_tokens = tokenize_cjk_and_words(query)
        scored_chunks: list[dict[str, Any]] = []

        for chunk in chunks:
            chunk_id = str(chunk.get("chunk_id", ""))
            source_id = str(chunk.get("source_id") or chunk.get("source_path", ""))

            # Exclusion checks for negative / canary testing
            if chunk_id in excluded_chunk_ids or source_id in excluded_sources:
                continue

            # ACL check
            chunk_groups = chunk.get("acl_groups")
            if chunk_groups and acl_policy == "STRICT":
                if not any(g in user_groups for g in chunk_groups):
                    continue

            content = str(chunk.get("content", ""))
            title = str(chunk.get("title", ""))
            search_text = f"{title}\n{content}".lower()

            matches = sum(1 for tok in query_tokens if tok in search_text)
            if matches == 0:
                continue

            score = round(matches / max(len(query_tokens), 1), 4)
            if score < min_score:
                continue

            scored_chunks.append({
                "chunk_id": chunk_id,
                "source_id": source_id,
                "source_path": chunk.get("source_path", source_id),
                "title": title,
                "content": content,
                "score": score,
                "evidence_id": chunk.get("evidence_id") or chunk_id,
            })

        scored_chunks.sort(key=lambda c: c["score"], reverse=True)
        return scored_chunks[:top_k]


class RealRagAnswerAdapter:
    """Formal answering pipeline adapter for REAL_RAG evaluation.
    
    Generates grounded answers based on retrieved evidence, prompt version,
    and records token usage or UNKNOWN status (Spec 6.2).
    """

    def __init__(
        self,
        *,
        model_invoker: Callable[..., tuple[str, int | None, float, str | None]] | None = None,
    ) -> None:
        self._model_invoker = model_invoker

    def __call__(
        self,
        query: str,
        manifest: TargetManifest,
        sanitized_input: TargetExecutionInput,
        retrieved_evidence: list[dict[str, Any]],
        conversation_history: list[dict[str, str]] | None = None,
    ) -> tuple[str, int | None, float, list[ToolCallTrace], str | None]:
        """Returns (answer, actual_tokens_or_none, cost_usd, tool_calls, provider_request_id)."""
        # If external model invoker configured (e.g. Gemini client in live app)
        if self._model_invoker:
            answer, tokens, cost, req_id = self._model_invoker(
                query,
                manifest,
                sanitized_input,
                retrieved_evidence,
                conversation_history or [],
            )
            return answer, tokens, cost, [], req_id

        # Deterministic grounded synthesis adhering to manifest instructions
        req_id = f"req_{uuid.uuid4().hex[:12]}"
        if not retrieved_evidence:
            return (
                f"抱歉，目前的知識庫中沒有找到與「{query}」相關的已授權資訊。",
                85,
                0.00003,
                [],
                req_id,
            )

        # Build citations and synthesis
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

        # Calculate tokens: ~1 token per 2 characters of prompt + output
        prompt_len = len(query) + sum(len(e.get("content", "")) for e in retrieved_evidence)
        estimated_tokens = int((prompt_len + len(answer)) / 2)
        cost = round(estimated_tokens * 0.0000003, 6)

        return answer, estimated_tokens, cost, [], req_id


class RealAgentSandboxAdapter:
    """Formal agent sandbox adapter for AGENT_SANDBOX evaluation mode.
    
    Executes real planning/tool selection while intercepting mutations and side effects (Spec 6.3).
    """

    def __init__(self, tool_fixture_service: ToolFixtureService) -> None:
        self._fixture_service = tool_fixture_service

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
