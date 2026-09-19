"""Tests for RAG v2 contextual chunk representation (spec §42)."""

from __future__ import annotations

import json
from pathlib import Path

from agent_service.retrieval import HybridIndex
from knowledge_core.contextual_representation import (
    CONTEXTUALIZATION_VERSION,
    apply_contextual_representation,
    build_contextual_representation,
    effective_retrieval_text,
)
from knowledge_core.document_models import DocumentChunk, DocumentMetadata


def _chunk(**overrides: object) -> DocumentChunk:
    defaults: dict[str, object] = {
        "chunk_id": "c1",
        "title": "VPN常見Q&A問答",
        "source_path": "sources/vpn.md",
        "content": "Permission denied (-455)\n可能原因為網路訊號不穩。",
        "source_aliases": ["FortiClient VPN"],
        "heading_path": ["常見錯誤", "登入問題"],
        "source_type": "MARKDOWN_PASTE",
        "metadata": DocumentMetadata(title="VPN常見Q&A問答", category="VPN", version="1"),
    }
    defaults.update(overrides)
    return DocumentChunk(**defaults)  # type: ignore[arg-type]


def test_retrieval_text_contains_title_heading_aliases() -> None:
    built = build_contextual_representation(_chunk())
    assert "文件：VPN常見Q&A問答" in built.context
    assert "別名：FortiClient VPN" in built.context
    assert "章節：常見錯誤 > 登入問題" in built.context
    assert "分類：VPN" in built.context
    assert "Permission denied (-455)" in built.retrieval_text
    assert built.version == CONTEXTUALIZATION_VERSION


def test_original_content_unchanged_after_apply() -> None:
    chunk = _chunk()
    original = chunk.content
    apply_contextual_representation(chunk)
    assert chunk.content == original
    assert chunk.retrieval_text is not None
    assert chunk.retrieval_context is not None


def test_context_never_replaces_citation_content() -> None:
    chunk = apply_contextual_representation(_chunk())
    assert "文件：" not in chunk.content
    assert chunk.content.startswith("Permission denied")


def test_v1_effective_retrieval_text_fallback() -> None:
    chunk = _chunk(retrieval_text=None, retrieval_context=None)
    assert effective_retrieval_text(chunk) == f"{chunk.title}\n{chunk.content}"


def test_index_save_marks_schema_v2_when_contextual() -> None:
    chunk = apply_contextual_representation(_chunk())
    index = HybridIndex([chunk], embedding_model=None)
    path = Path("/tmp/rag-v2-index-test.json")
    index.save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert payload["indexSchemaVersion"] == 2
    assert payload["contextualizationVersion"] == CONTEXTUALIZATION_VERSION
    reloaded = HybridIndex.load(path)
    assert reloaded.chunks[0].retrieval_text
    assert reloaded.chunks[0].content == chunk.content
