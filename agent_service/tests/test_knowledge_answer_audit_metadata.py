"""Unit tests for knowledge answer audit metadata (spec §4)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI

from agent_service.routers.chat_support import (
    build_response,
    resolve_knowledge_audit_context,
)
from agent_service.service_scope_evidence import (
    configure_service_scope_from_documents,
    reset_service_scope_catalog,
)
from agent_service.settings import RagSettings


def test_sandbox_selection_is_not_cloud_production_answer(tmp_path: Path) -> None:
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="bucket",
        knowledge_release_selection_mode="LOCAL_SANDBOX",
        knowledge_active_release_id="sandbox-1",
    )
    app = FastAPI()
    app.state.knowledge_release_id = "sandbox-1"
    syncer = MagicMock()
    syncer.status = SimpleNamespace(
        selection_mode=SimpleNamespace(value="LOCAL_SANDBOX"),
        last_successful_sync_at="2026-09-22T00:00:00+00:00",
        loaded_release_id="sandbox-1",
    )
    app.state.knowledge_release_syncer = syncer

    audit = resolve_knowledge_audit_context(app, settings)
    assert audit["knowledge_release_id"] == "sandbox-1"
    assert audit["knowledge_selection_mode"] == "LOCAL_SANDBOX"
    assert audit["knowledge_last_successful_sync_at"] == "2026-09-22T00:00:00+00:00"
    assert audit["is_cloud_production_answer"] is False
    assert audit["knowledge_acl_decision"] == "PUBLIC_DEFAULT"

    response = build_response(
        {
            "final_response": "測試答案",
            **{k: v for k, v in audit.items() if v is not None},
        },
        "corr-1",
        channel="playground",
        app=app,
        resolved_settings=settings,
    )
    assert response.knowledgeReleaseId == "sandbox-1"
    assert response.knowledgeSelectionMode == "LOCAL_SANDBOX"
    assert response.knowledgeLastSuccessfulSyncAt == "2026-09-22T00:00:00+00:00"
    assert response.isCloudProductionAnswer is False
    assert response.knowledgeAclDecision == "PUBLIC_DEFAULT"


def test_follow_cloud_gcs_may_mark_cloud_production_answer(tmp_path: Path) -> None:
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="bucket",
        knowledge_release_selection_mode="FOLLOW_CLOUD",
    )
    app = FastAPI()
    app.state.knowledge_release_id = "release-cloud"
    syncer = MagicMock()
    status = SimpleNamespace(
        selection_mode=SimpleNamespace(value="FOLLOW_CLOUD"),
        last_successful_sync_at="2026-09-22T01:00:00+00:00",
        loaded_release_id="release-cloud",
        runtime_inventory_complete=True,
        behind_cloud=False,
    )
    status.to_public_dict = lambda: {
        "alignedWithCloud": True,
        "matchesCloudProduction": True,
    }
    syncer.status = status
    app.state.knowledge_release_syncer = syncer

    audit = resolve_knowledge_audit_context(app, settings)
    assert audit["is_cloud_production_answer"] is True
    assert audit["knowledge_selection_mode"] == "FOLLOW_CLOUD"

    response = build_response(
        {
            "final_response": "正式鏡像答案",
            **{k: v for k, v in audit.items() if v is not None},
        },
        "corr-2",
        channel="playground",
        app=app,
        resolved_settings=settings,
    )
    assert response.isCloudProductionAnswer is True
    assert response.knowledgeReleaseId == "release-cloud"


def test_follow_cloud_index_only_is_not_cloud_production_answer(tmp_path: Path) -> None:
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="bucket",
        knowledge_release_selection_mode="FOLLOW_CLOUD",
    )
    app = FastAPI()
    app.state.knowledge_release_id = "release-legacy"
    syncer = MagicMock()
    status = SimpleNamespace(
        selection_mode=SimpleNamespace(value="FOLLOW_CLOUD"),
        last_successful_sync_at="2026-09-22T01:00:00+00:00",
        loaded_release_id="release-legacy",
        runtime_inventory_complete=False,
        behind_cloud=True,
    )
    status.to_public_dict = lambda: {
        "alignedWithCloud": False,
        "matchesCloudProduction": False,
        "indexOnlyMirror": True,
    }
    syncer.status = status
    app.state.knowledge_release_syncer = syncer

    audit = resolve_knowledge_audit_context(app, settings)
    assert audit["is_cloud_production_answer"] is False


def test_audit_prefers_in_flight_pinned_release_id(tmp_path: Path) -> None:
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="bucket",
        knowledge_release_selection_mode="FOLLOW_CLOUD",
    )
    app = FastAPI()
    app.state.knowledge_release_id = "release-new"
    execution_context = SimpleNamespace(pinned_knowledge_release_id="release-old")
    audit = resolve_knowledge_audit_context(
        app,
        settings,
        execution_context=execution_context,
    )
    assert audit["knowledge_release_id"] == "release-old"


def test_pinned_selection_is_not_cloud_production_answer(tmp_path: Path) -> None:
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        knowledge_release_store_mode="GCS",
        knowledge_release_gcs_bucket="bucket",
        knowledge_release_selection_mode="PINNED",
        knowledge_active_release_id="release-pin",
    )
    app = FastAPI()
    app.state.knowledge_release_id = "release-pin"
    audit = resolve_knowledge_audit_context(app, settings)
    assert audit["knowledge_selection_mode"] == "PINNED"
    assert audit["is_cloud_production_answer"] is False


def test_audit_includes_catalog_version_and_group_acl_decision(tmp_path: Path) -> None:
    reset_service_scope_catalog()
    try:
        configure_service_scope_from_documents(
            [
                {
                    "document_id": "doc-seat",
                    "title": "座位搬遷需求",
                    "source_aliases": ["座位調度試驗別名"],
                }
            ],
            schema_version=1,
            release_id="release-cat",
            source="catalog/service_catalog.json",
        )
        settings = RagSettings(
            data_dir=tmp_path,
            index_path=tmp_path / "chunks.json",
            knowledge_release_store_mode="FILE",
            knowledge_release_selection_mode="LOCAL_SANDBOX",
            knowledge_active_release_id="sandbox-1",
        )
        app = FastAPI()
        app.state.knowledge_release_id = "sandbox-1"
        audit = resolve_knowledge_audit_context(
            app,
            settings,
            user_groups=["grp_it", "grp_public"],
        )
        assert audit["is_cloud_production_answer"] is False
        assert audit["knowledge_acl_decision"] == "GROUP_FILTERED"
        assert audit["service_catalog_version"] is not None
        assert "schema:1" in str(audit["service_catalog_version"])
        assert "release-cat" in str(audit["service_catalog_version"])

        response = build_response(
            {
                "final_response": "範圍內答案",
                **{k: v for k, v in audit.items() if v is not None},
            },
            "corr-3",
            channel="playground",
            app=app,
            resolved_settings=settings,
        )
        assert response.serviceCatalogVersion == audit["service_catalog_version"]
        assert response.knowledgeAclDecision == "GROUP_FILTERED"
        assert response.isCloudProductionAnswer is False
    finally:
        reset_service_scope_catalog()
