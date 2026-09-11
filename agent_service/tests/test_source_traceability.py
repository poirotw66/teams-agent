from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agent_service.documents import DocumentChunk
from agent_service.knowledge import HybridKnowledgeService
from agent_service.retrieval import HybridIndex, SearchResult
from agent_service.settings import RagSettings
from agent_service.source_refs import hydrate_index_sources, make_source_ref_id
from ai_ops_backoffice.services.source_trace import SourceTraceResolver


def _write_release(root: Path) -> tuple[Path, str]:
    release_id = "release-test"
    release = root / release_id
    (release / "index").mkdir(parents=True)
    (release / "sources").mkdir()
    (release / "sources" / "doc-vpn.md").write_text(
        "# VPN\n\n## 解鎖\n\n請聯繫服務台。", encoding="utf-8"
    )
    manifest = {
        "releaseId": release_id,
        "documents": [
            {
                "document_id": "doc-vpn",
                "version_id": "ver-doc-vpn-2",
                "title": "VPN",
                "content_hash": "hash",
                "source_path": "sources/doc-vpn.md",
                "source_type": "PDF",
            }
        ],
    }
    (release / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    chunk = DocumentChunk(
        chunk_id="chunk-vpn",
        title="VPN",
        source_path="sources/doc-vpn.md",
        content="## 解鎖\n\n請聯繫服務台。",
    )
    HybridIndex([chunk]).save(release / "index" / "chunks.json")
    return root, release_id


def test_release_hydration_carries_version_into_citation(tmp_path: Path) -> None:
    releases, release_id = _write_release(tmp_path)
    index = HybridIndex.load(releases / release_id / "index" / "chunks.json")
    hydrate_index_sources(index.chunks, release_dir=releases, release_id=release_id)

    settings = RagSettings(data_dir=tmp_path, index_path=tmp_path / "index.json")
    citation = HybridKnowledgeService(settings, index, release_id=release_id)._citation_for(
        SearchResult(index.chunks[0], 1.0, 1.0)
    )

    assert citation.documentId == "doc-vpn"
    assert citation.versionId == "ver-doc-vpn-2"
    assert citation.releaseId == release_id
    assert citation.sourceRefId == make_source_ref_id(
        release_id=release_id,
        document_id="doc-vpn",
        version_id="ver-doc-vpn-2",
        chunk_id="chunk-vpn",
        source_path="sources/doc-vpn.md",
    )
    assert citation.sourceType == "PDF"
    assert citation.evidence == "## 解鎖\n\n請聯繫服務台。"


def test_backoffice_resolves_legacy_chunk_to_versioned_source(tmp_path: Path) -> None:
    releases, release_id = _write_release(tmp_path)
    resolver = SourceTraceResolver(releases)
    event = SimpleNamespace(
        event_type="knowledge.retrieved",
        payload={
            "title": "VPN",
            "chunkId": "chunk-vpn",
            "releaseId": release_id,
        },
    )

    refs = resolver.references_for_events([event])
    assert refs[0]["traceStatus"] == "LEGACY_UNVERIFIED"
    assert refs[0]["documentId"] == "doc-vpn"
    assert refs[0]["versionId"] == "ver-doc-vpn-2"
    assert refs[0]["sourceType"] == "PDF"

    source = resolver.resolve_source_ref(refs[0]["sourceRefId"])
    assert source is not None
    preview = resolver.preview_payload(source)
    assert preview["message"] == "原始檔尚未保存，目前顯示發布時使用的轉換內容。"
    assert "請聯繫服務台" in preview["evidence"]["excerpt"]
