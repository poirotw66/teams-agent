"""Tests for read-only GCS mirror document inventory."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_service.knowledge_mirror_inventory import (
    MirrorDocumentNotFound,
    attach_mirror_documents,
    list_mirrored_release_documents,
    preview_mirrored_document,
)
from agent_service.settings import RagSettings


def _write_release(cache_root: Path, release_id: str) -> Path:
    release_dir = cache_root / "tenants" / "default" / "releases" / release_id
    (release_dir / "catalog").mkdir(parents=True)
    (release_dir / "manifest.json").write_text(
        json.dumps(
            {
                "releaseId": release_id,
                "documents": [
                    {
                        "document_id": "doc-web",
                        "version_id": "ver-web-1",
                        "title": "",
                        "source_path": "sources/doc-web.md",
                        "content_state": "ACTIVE",
                    },
                    {
                        "document_id": "doc-vpn",
                        "version_id": "ver-vpn-1",
                        "title": "VPN 跳板機連線異常",
                        "source_path": "sources/doc-vpn.md",
                        "content_state": "ACTIVE",
                    },
                    {"title": "missing-id"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (release_dir / "index").mkdir(parents=True)
    (release_dir / "index" / "chunks.json").write_text(
        json.dumps(
            {
                "chunks": [
                    {
                        "chunk_id": "chk-web-1",
                        "document_id": "doc-web",
                        "title": "樹精靈 WEB-登入異常",
                        "content": "# 樹精靈 WEB\n\n無法登入時請重開瀏覽器。",
                        "source_path": "sources/doc-web.md",
                        "token_count": 18,
                        "vector": [0.1, 0.2],
                    },
                    {
                        "chunk_id": "chk-vpn-1",
                        "document_id": "doc-vpn",
                        "title": "VPN 跳板機連線異常",
                        "content": "請改走內網跳板。",
                        "source_path": "sources/doc-vpn.md",
                        "token_count": 8,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (release_dir / "catalog" / "service_catalog.json").write_text(
        json.dumps(
            {
                "services": [
                    {
                        "documentId": "doc-web",
                        "officialName": "樹精靈 WEB-登入異常",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return release_dir


def test_list_mirrored_release_documents_uses_manifest_and_catalog(
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "knowledge_cache"
    _write_release(cache_root, "release-cloud")

    documents = list_mirrored_release_documents(
        cache_root=cache_root,
        tenant_id="default",
        release_id="release-cloud",
    )

    assert documents == [
        {
            "documentId": "doc-web",
            "title": "樹精靈 WEB-登入異常",
            "versionId": "ver-web-1",
            "sourcePath": "sources/doc-web.md",
            "contentState": "ACTIVE",
        },
        {
            "documentId": "doc-vpn",
            "title": "VPN 跳板機連線異常",
            "versionId": "ver-vpn-1",
            "sourcePath": "sources/doc-vpn.md",
            "contentState": "ACTIVE",
        },
    ]


def test_list_mirrored_release_documents_empty_when_mirror_missing(
    tmp_path: Path,
) -> None:
    documents = list_mirrored_release_documents(
        cache_root=tmp_path / "knowledge_cache",
        tenant_id="default",
        release_id="release-missing",
    )
    assert documents == []


def test_attach_mirror_documents_uses_settings_cache(tmp_path: Path) -> None:
    cache_root = tmp_path / "knowledge_cache"
    _write_release(cache_root, "release-cloud")
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        knowledge_release_cache_dir=cache_root,
        knowledge_release_tenant_id="default",
    )

    payload = attach_mirror_documents(
        {"alignedWithCloud": True},
        settings=settings,
        release_id="release-cloud",
    )

    assert payload["alignedWithCloud"] is True
    documents = payload["documents"]
    assert isinstance(documents, list)
    assert len(documents) == 2
    first = documents[0]
    assert isinstance(first, dict)
    assert first["documentId"] == "doc-web"


def test_preview_mirrored_document_strips_vectors_and_maps_chunks(
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "knowledge_cache"
    _write_release(cache_root, "release-cloud")
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        knowledge_release_cache_dir=cache_root,
        knowledge_release_tenant_id="default",
    )

    preview = preview_mirrored_document(
        settings=settings,
        release_id="release-cloud",
        document_id="doc-web",
    )

    assert preview["documentId"] == "doc-web"
    assert preview["title"] == "樹精靈 WEB-登入異常"
    assert preview["chunkCount"] == 1
    chunks = preview["chunks"]
    assert isinstance(chunks, list)
    chunk = chunks[0]
    assert isinstance(chunk, dict)
    assert chunk["id"] == "chk-web-1"
    assert chunk["content"] == "# 樹精靈 WEB\n\n無法登入時請重開瀏覽器。"
    assert "vector" not in chunk
    assert chunk["quality_issues"] == []


def test_preview_mirrored_document_missing_id_raises(tmp_path: Path) -> None:
    cache_root = tmp_path / "knowledge_cache"
    _write_release(cache_root, "release-cloud")
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        knowledge_release_cache_dir=cache_root,
        knowledge_release_tenant_id="default",
    )

    with pytest.raises(MirrorDocumentNotFound):
        preview_mirrored_document(
            settings=settings,
            release_id="release-cloud",
            document_id="doc-missing",
        )
