"""Model control plane: one effective model, delayed switches for embedding and file search."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent_service.model_control import adopt_embedding_index, apply_file_search_model
from agent_service.operations.access import ActorContext
from agent_service.prompt_runtime import GovernanceRuntime
from agent_service.settings import RagSettings
from ai_ops_backoffice.governance_domain.errors import GovernanceTransitionError
from ai_ops_backoffice.governance_domain.repository import FileGovernanceRepository
from ai_ops_backoffice.governance_domain.service import GovernanceService
from ai_ops_backoffice.services.runtime_models import runtime_models_from_ready


def _actors() -> tuple[ActorContext, ActorContext]:
    author = ActorContext(
        user_id="author", display_name="Author", role="AI_ADMIN", owner_unit_ids=()
    )
    approver = ActorContext(
        user_id="approver", display_name="Approver", role="AI_ADMIN", owner_unit_ids=()
    )
    return author, approver


def _approve(
    service: GovernanceService,
    *,
    config_id: str,
    model_id: str,
    component: str,
    fallback: str | None = None,
) -> str:
    author, approver = _actors()
    created = service.create_model_candidate(
        config_id=config_id,
        provider="google_genai",
        model_id=model_id,
        component=component,
        temperature=0.0,
        max_output_tokens=1024,
        timeout_seconds=30,
        retry=1,
        secret_ref="secret://gemini-key",
        region="asia-east1",
        pricing_version="v1",
        fallback_model_id=fallback,
        fallback_on=("TIMEOUT",) if fallback else (),
        change_reason="prepare a governed model",
        actor=author,
    )
    version_id = created["version"]["version_id"]
    service.run_model_eval(config_id=config_id, version_id=version_id, actor=author)
    service.approve_model(
        config_id=config_id, version_id=version_id, reason="static checks passed", actor=approver
    )
    return version_id


def test_chat_model_takes_effect_on_the_next_resolve(tmp_path) -> None:
    gov_file = tmp_path / "governance.json"
    service = GovernanceService(FileGovernanceRepository(gov_file))
    version_id = _approve(
        service,
        config_id="rag-answer-model",
        model_id="gemini-3.5-flash",
        component="rag-answer",
        fallback="gemini-3.1-flash-lite",
    )
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "index.json",
        model="google_genai:gemini-3.1-flash-lite",
        prompt_runtime_mode="GOVERNED",
        prompt_governance_store_path=gov_file,
    )
    runtime = GovernanceRuntime.from_settings(settings)
    assert runtime.resolve_model(config_id="rag-answer-model").source == "settings_baseline"

    service.activate_model(
        config_id="rag-answer-model",
        version_id=version_id,
        reason="switch the next answer",
        actor=_actors()[1],
    )
    resolved = runtime.resolve_model(config_id="rag-answer-model")
    assert resolved.source == "governance"
    assert resolved.model_id == "gemini-3.5-flash"
    assert resolved.version_id == version_id


def test_model_lookup_failure_keeps_settings_baseline(tmp_path) -> None:
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "index.json",
        model="google_genai:gemini-3.1-flash-lite",
        prompt_runtime_mode="GOVERNED",
        prompt_governance_store_path=tmp_path / "missing-governance.json",
    )
    runtime = GovernanceRuntime.from_settings(settings)
    runtime._governance.peek_runtime_model = lambda _config_id: (_ for _ in ()).throw(
        RuntimeError("store down")
    )
    resolved = runtime.resolve_model(config_id="rag-answer-model")
    assert resolved.source == "settings_baseline"
    assert resolved.model_id == "gemini-3.1-flash-lite"


def test_embedding_schedule_does_not_switch_until_complete(tmp_path) -> None:
    service = GovernanceService(FileGovernanceRepository(tmp_path / "governance.json"))
    version_id = _approve(
        service,
        config_id="embedding-model",
        model_id="gemini-embedding-2",
        component="embedding",
    )
    author = _actors()[0]
    with pytest.raises(GovernanceTransitionError):
        service.activate_model(
            config_id="embedding-model",
            version_id=version_id,
            reason="do not hot swap",
            actor=author,
        )

    service.schedule_model(
        config_id="embedding-model", version_id=version_id, reason="rebuild first", actor=author
    )
    assert service.peek_runtime_model("embedding-model") is None
    schedule = service.peek_model_schedule("embedding-model")
    assert schedule["scheduleStatus"] == "queued"
    assert schedule["scheduledModelId"] == "gemini-embedding-2"

    service.fail_schedule(
        config_id="embedding-model", version_id=version_id, reason="index mismatch", actor=author
    )
    assert service.peek_runtime_model("embedding-model") is None
    assert service.peek_model_schedule("embedding-model")["scheduleStatus"] == "failed"

    service.schedule_model(
        config_id="embedding-model", version_id=version_id, reason="retry rebuild", actor=author
    )
    service.complete_schedule(
        config_id="embedding-model",
        version_id=version_id,
        actor=author,
        reason="index loaded",
    )
    peeked = service.peek_runtime_model("embedding-model")
    assert peeked is not None
    assert peeked["modelId"] == "gemini-embedding-2"


def test_file_search_schedule_does_not_switch_until_apply(tmp_path) -> None:
    service = GovernanceService(FileGovernanceRepository(tmp_path / "governance.json"))
    version_id = _approve(
        service,
        config_id="file-search-model",
        model_id="gemini-3.5-flash",
        component="file-search",
        fallback="gemini-3.5-flash-lite",
    )
    actor = _actors()[0]
    service.schedule_model(
        config_id="file-search-model", version_id=version_id, reason="refresh client", actor=actor
    )
    assert service.peek_runtime_model("file-search-model") is None

    missing = SimpleNamespace(
        state=SimpleNamespace(knowledge_router=SimpleNamespace(get_service=lambda _name: None))
    )
    refused = apply_file_search_model(missing, "gemini-3.5-flash")
    assert refused.applied is False

    client = SimpleNamespace(model="gemini-3.5-flash-lite")
    app = SimpleNamespace(
        state=SimpleNamespace(
            knowledge_router=SimpleNamespace(
                get_service=lambda name: client if name == "GEMINI_FILE_SEARCH" else None
            )
        )
    )
    applied = apply_file_search_model(app, "gemini-3.5-flash")
    assert applied.applied is True
    assert client.model == "gemini-3.5-flash"
    assert service.peek_runtime_model("file-search-model") is None


def test_embedding_adopt_refuses_mismatched_index(tmp_path) -> None:
    index_path = tmp_path / "chunks.json"
    index_path.write_text(
        json.dumps({"version": 1, "embeddingModel": "gemini-embedding-2", "chunks": []}),
        encoding="utf-8",
    )
    sentinel = object()
    app = SimpleNamespace(
        state=SimpleNamespace(
            index=sentinel,
            knowledge_index_path=index_path,
            knowledge_release_id=None,
            knowledge_router=None,
            rag_model=None,
        )
    )
    settings = RagSettings(data_dir=tmp_path / "empty-data", index_path=index_path)
    result = adopt_embedding_index(app, settings, "other-embedding")
    assert result.adopted is False
    assert app.state.index is sentinel


def test_catalog_keeps_old_embedding_effective_while_scheduled(tmp_path) -> None:
    gov_file = tmp_path / "governance.json"
    service = GovernanceService(FileGovernanceRepository(gov_file))
    version_id = _approve(
        service,
        config_id="embedding-model",
        model_id="gemini-embedding-2",
        component="embedding",
    )
    service.schedule_model(
        config_id="embedding-model",
        version_id=version_id,
        reason="wait for reindex",
        actor=_actors()[0],
    )
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "index.json",
        embedding_model="gemini-embedding-old",
        prompt_runtime_mode="GOVERNED",
        prompt_governance_store_path=gov_file,
    )
    catalog = GovernanceRuntime.from_settings(settings).effective_model_catalog(
        embedding_model="gemini-embedding-old"
    )
    embedding = next(item for item in catalog["items"] if item["role"] == "embedding")
    assert embedding["model"] == "gemini-embedding-old"
    assert embedding["source"] == "settings_baseline"
    assert embedding["scheduleStatus"] == "queued"
    assert embedding["scheduledModel"] == "gemini-embedding-2"


def test_runtime_models_prefer_effective_catalog() -> None:
    catalog = runtime_models_from_ready(
        {
            "knowledgeMode": "HYBRID",
            "modelCatalog": {
                "runtimeMode": "GOVERNED",
                "governed": True,
                "controlPlaneReady": True,
                "items": [
                    {
                        "role": "agent",
                        "model": "google_genai:gemini-3.5-flash",
                        "source": "governance",
                    }
                ],
            },
        }
    )
    assert catalog["controlPlaneReady"] is True
    assert catalog["items"][0]["source"] == "governance"
