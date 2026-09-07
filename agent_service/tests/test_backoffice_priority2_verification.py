from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_service.contracts import ConversationMessage, Issue, IssueExtraction
from agent_service.extractor import IssueExtractor
from agent_service.graph import build_chat_model
from agent_service.operations.access import ActorContext
from agent_service.prompt_runtime import ExtractorPromptRuntime, GovernanceRuntime, ResolvedModelConfig
from agent_service.settings import RagSettings
from ai_ops_backoffice.api import create_app as create_backoffice_app
from ai_ops_backoffice.governance_domain import FileGovernanceRepository, GovernanceService
from ai_ops_backoffice.settings import BackofficeSettings
from knowledge_portal.api import create_app as create_portal_app
from knowledge_portal.models import PortalActor
from knowledge_portal.settings import PortalSettings


def _portal_settings(tmp_path: Path) -> PortalSettings:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "data_dir", tmp_path / "portal")
    object.__setattr__(settings, "release_artifact_dir", tmp_path / "portal" / "releases")
    object.__setattr__(settings, "drafts_dir", tmp_path / "portal" / "drafts")
    object.__setattr__(settings, "agent_api_url", None)
    return settings


def _backoffice_settings(tmp_path: Path, **overrides) -> BackofficeSettings:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    params = {
        "host": "127.0.0.1",
        "port": 8092,
        "service_token": "",
        "auth_mode": "HEADER",
        "ops_store_mode": "FILE",
        "ops_store_path": tmp_path / "events",
        "ops_taxonomy_path": data_dir / "ops" / "issue_taxonomy_v1.json",
        "ops_metrics_path": data_dir / "ops" / "metrics_definitions_v1.json",
        "ops_classification_rules_path": data_dir / "ops" / "issue_classification_rules.json",
        "ops_audit_store_mode": "FILE",
        "knowledge_portal_url": "http://127.0.0.1:8091",
        "agent_api_url": "http://127.0.0.1:8000",
        "adapter_api_url": "http://127.0.0.1:3978",
        "ticket_service_url": None,
        "default_owner_unit_id": "IT",
        "entra_tenant_id": None,
        "entra_client_id": None,
        "budget_store_path": tmp_path / "budgets.json",
        **overrides,
    }
    return BackofficeSettings(**params)


def backoffice_headers(role: str = "SYSTEM_ADMIN", user_id: str = "admin-1") -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": user_id,
        "X-Backoffice-User-Name": role,
        "X-Backoffice-Role": role,
        "X-Backoffice-Owner-Units": "IT",
        "X-Backoffice-Tenant-Id": "local-development",
    }


def portal_headers(role: str = "PLATFORM", user_id: str = "admin-portal") -> dict[str, str]:
    return {
        "X-Portal-User-Id": user_id,
        "X-Portal-User-Name": "Admin Portal",
        "X-Portal-Role": role,
        "X-Portal-Owner-Units": "IT",
    }


# =========================================================================
# REQ-013: 知識庫重新同步與發布流程驗證
# =========================================================================

@pytest.mark.asyncio
async def test_knowledge_portal_sync_endpoint_reindexes_and_creates_release(tmp_path: Path) -> None:
    """REQ-013: Verify Knowledge Portal /api/sync rebuilds published knowledge and returns evidence."""
    settings = _portal_settings(tmp_path)
    app = create_portal_app(settings)
    client = TestClient(app)

    # Call /api/sync
    sync_resp = client.post(
        "/api/sync",
        headers=portal_headers(),
        json={"scopeType": "ALL", "scopeIds": []},
    )
    assert sync_resp.status_code == 200
    data = sync_resp.json()
    assert "targetRelease" in data
    assert data["indexSettingVersion"] == "v1"
    assert "documentCount" in data
    assert isinstance(data["warnings"], list)


@pytest.mark.asyncio
async def test_backoffice_sync_job_end_to_end_triggers_portal_reindex(tmp_path: Path) -> None:
    """REQ-013: Verify Backoffice sync job calls /api/sync, transitions to COMPLETED, and records release info."""
    captured_requests = []

    def mock_transport_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        if request.url.path == "/api/sync":
            return httpx.Response(
                200,
                json={
                    "targetRelease": "release-2026-sync-001",
                    "indexSettingVersion": "v1",
                    "documentCount": 42,
                    "warnings": [],
                },
            )
        return httpx.Response(404)

    # Notice sync_adapter_url is omitted (None), so it defaults to knowledge_portal_url
    settings = _backoffice_settings(
        tmp_path,
        knowledge_portal_url="http://127.0.0.1:8091",
    )
    app = create_backoffice_app(
        settings,
        notification_transport=httpx.MockTransport(mock_transport_handler),
        sync_transport=httpx.MockTransport(mock_transport_handler),
    )
    client = TestClient(app)

    # Trigger a sync job via backoffice API
    sync_resp = client.post(
        "/api/sync-jobs",
        headers=backoffice_headers(),
        json={"scope_type": "ALL", "reason": "Full portal reindex request"},
    )
    assert sync_resp.status_code == 200
    job_id = sync_resp.json()["job"]["job_id"]

    # Background task ran in TestClient thread; verify job status
    jobs_resp = client.get(f"/api/sync-jobs/{job_id}", headers=backoffice_headers())
    assert jobs_resp.status_code == 200
    job = jobs_resp.json()["job"]

    assert job["status"] == "COMPLETED"
    assert job["target_release"] == "release-2026-sync-001"
    assert job["index_setting_version"] == "v1"
    assert job["document_count"] == 42
    assert job["error_summary"] is None


# =========================================================================
# REQ-022: 模型參數與 Fallback 治理機制驗證
# =========================================================================

def test_governance_model_parameters_peek_and_runtime_resolution(tmp_path: Path) -> None:
    """REQ-022: Verify peek_runtime_model and resolve_model expose all governed parameters."""
    gov_file = tmp_path / "governance.json"
    gov_svc = GovernanceService(FileGovernanceRepository(gov_file))
    actor = ActorContext(user_id="ai-admin", display_name="AI Admin", role="AI_ADMIN", owner_unit_ids=())

    # Create model candidate with custom parameters and fallback configuration
    created = gov_svc.create_model_candidate(
        config_id="issue-extractor-model",
        provider="google_genai",
        model_id="gemini-2.5-flash",
        component="issue_extractor",
        temperature=0.35,
        max_output_tokens=1024,
        timeout_seconds=45,
        retry=2,
        secret_ref="secret://gemini-key",
        region="asia-east1",
        pricing_version="v1",
        fallback_model_id="gemini-2.0-flash",
        fallback_on=("TIMEOUT", "RATE_LIMIT", "UNAVAILABLE"),
        change_reason="Configure governed extractor with 0.35 temperature and fallback",
        actor=actor,
    )
    approver = ActorContext(user_id="approver-1", display_name="Approver", role="AI_ADMIN", owner_unit_ids=())
    version_id = created["version"]["version_id"]
    gov_svc.run_model_eval(config_id="issue-extractor-model", version_id=version_id, actor=actor)
    gov_svc.approve_model(config_id="issue-extractor-model", version_id=version_id, reason="Approved", actor=approver)
    gov_svc.activate_model(config_id="issue-extractor-model", version_id=version_id, reason="Activated", actor=approver)

    # Verify peek_runtime_model returns the governed parameters
    peeked = gov_svc.peek_runtime_model("issue-extractor-model")
    assert peeked is not None
    assert peeked["temperature"] == 0.35
    assert peeked["maxOutputTokens"] == 1024
    assert peeked["timeoutSeconds"] == 45
    assert peeked["retry"] == 2
    assert peeked["fallbackModelId"] == "gemini-2.0-flash"
    assert set(peeked["fallbackOn"]) == {"TIMEOUT", "RATE_LIMIT", "UNAVAILABLE"}

    # Verify GovernanceRuntime.resolve_model correctly populates ResolvedModelConfig
    rag_settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "index.json",
        prompt_runtime_mode="GOVERNED",
        prompt_governance_store_path=gov_file,
    )
    runtime = GovernanceRuntime.from_settings(rag_settings)
    resolved = runtime.resolve_model(config_id="issue-extractor-model")

    assert resolved.source == "governance"
    assert resolved.temperature == 0.35
    assert resolved.max_output_tokens == 1024
    assert resolved.timeout_seconds == 45
    assert resolved.retry == 2
    assert resolved.fallback_model_id == "gemini-2.0-flash"
    assert "TIMEOUT" in resolved.fallback_on


def test_build_chat_model_accepts_and_configures_parameters() -> None:
    """REQ-022: Verify build_chat_model accepts temperature, timeout, max_retries without error."""
    # When model_name is None, it returns None
    assert build_chat_model(None) is None

    # Test initialization with keyword arguments
    model = build_chat_model(
        "google_genai:gemini-2.5-flash",
        temperature=0.2,
        timeout=30.0,
        max_retries=2,
    )
    assert model is not None


class _MockStructuredHandle:
    def __init__(self, invoker) -> None:
        self._invoker = invoker

    async def ainvoke(self, messages: list[Any]) -> IssueExtraction:
        return await self._invoker(messages)


class _MockFailingModel:
    def __init__(self, failure_exc: Exception) -> None:
        self.failure_exc = failure_exc
        self.call_count = 0

    def with_structured_output(self, _schema):
        async def _invoke(messages):
            self.call_count += 1
            raise self.failure_exc

        return _MockStructuredHandle(_invoke)


class _MockSuccessModel:
    def __init__(self, result: IssueExtraction) -> None:
        self.result = result
        self.call_count = 0

    def with_structured_output(self, _schema):
        async def _invoke(messages):
            self.call_count += 1
            return self.result

        return _MockStructuredHandle(_invoke)


class _MockRuntimeWithModel:
    def __init__(self, resolved_model: ResolvedModelConfig) -> None:
        self.resolved_model = resolved_model

    def resolve(self, *, tenant_id: str | None, conversation_id: str | None):
        from agent_service.prompt_runtime import ResolvedExtractorPrompt
        return ResolvedExtractorPrompt(
            template="Extract issues: {max_issues} keys: {faq_keys}",
            source="governance",
            version_id="pv-1",
            version="v1",
        )

    def resolve_model(self, *, config_id: str = "issue-extractor-model") -> ResolvedModelConfig:
        return self.resolved_model


@pytest.mark.asyncio
async def test_extractor_applies_fallback_model_on_primary_failure(tmp_path: Path, monkeypatch) -> None:
    """REQ-022: Verify extractor engages fallback_model_id when primary model fails with a configured trigger."""
    canned_issue = Issue(
        id=1,
        description="VPN connection reset by peer",
        isIT=True,
        readiness="READY",
        missingInfo=[],
        route="KNOWLEDGE",
        faqKey=None,
        ticketAction=None,
    )
    fallback_model_mock = _MockSuccessModel(IssueExtraction(issues=[canned_issue]))
    primary_model_mock = _MockFailingModel(asyncio.TimeoutError("LLM call timed out after 30s"))

    # Intercept build_chat_model in graph to return fallback_model_mock when fallback name requested
    def mock_build_chat_model(name: str, **kwargs):
        if "gemini-2.0-flash" in name:
            return fallback_model_mock
        return primary_model_mock

    monkeypatch.setattr("agent_service.graph.build_chat_model", mock_build_chat_model)

    resolved_config = ResolvedModelConfig(
        provider="google_genai",
        model_id="gemini-2.5-flash",
        model_name="google_genai:gemini-2.5-flash",
        source="governance",
        version_id="mv-001",
        temperature=0.2,
        timeout_seconds=30,
        retry=1,
        fallback_model_id="gemini-2.0-flash",
        fallback_on=("TIMEOUT", "RATE_LIMIT", "UNAVAILABLE"),
    )

    mock_runtime = _MockRuntimeWithModel(resolved_config)
    settings = RagSettings(data_dir=tmp_path, index_path=tmp_path / "index.json")
    extractor = IssueExtractor(
        settings,
        model=primary_model_mock,
        prompt_runtime=mock_runtime,
    )

    # Execute extraction
    outcome = await extractor.extract(
        text="VPN連線逾時失敗",
        history=[],
        faq_keys=[],
        conversation_id="conv-fb-1",
        tenant_id="tenant-1",
    )

    # Primary failed (call 1), Fallback succeeded (call 2)
    assert primary_model_mock.call_count == 1
    assert fallback_model_mock.call_count == 1
    assert outcome.llm_calls == 2
    assert outcome.model_fallback_applied is True
    assert "gemini-2.0-flash" in (outcome.model_used or "")
    assert len(outcome.issues) == 1
    assert outcome.issues[0].description == "VPN connection reset by peer"


@pytest.mark.asyncio
async def test_extractor_deterministic_fallback_when_all_models_fail(tmp_path: Path, monkeypatch) -> None:
    """REQ-022: Verify deterministic code fallback is used if both primary and fallback models fail."""
    primary_model_mock = _MockFailingModel(RuntimeError("503 Service Unavailable"))
    fallback_model_mock = _MockFailingModel(RuntimeError("Fallback 503 Service Unavailable"))

    def mock_build_chat_model(name: str, **kwargs):
        if "gemini-2.0-flash" in name:
            return fallback_model_mock
        return primary_model_mock

    monkeypatch.setattr("agent_service.graph.build_chat_model", mock_build_chat_model)

    resolved_config = ResolvedModelConfig(
        provider="google_genai",
        model_id="gemini-2.5-flash",
        model_name="google_genai:gemini-2.5-flash",
        source="governance",
        version_id="mv-001",
        fallback_model_id="gemini-2.0-flash",
        fallback_on=("TIMEOUT", "UNAVAILABLE"),
    )

    mock_runtime = _MockRuntimeWithModel(resolved_config)
    settings = RagSettings(data_dir=tmp_path, index_path=tmp_path / "index.json")
    extractor = IssueExtractor(
        settings,
        model=primary_model_mock,
        prompt_runtime=mock_runtime,
    )

    outcome = await extractor.extract(
        text="無法連線到主機",
        history=[],
        faq_keys=[],
        conversation_id="conv-fb-2",
        tenant_id="tenant-1",
    )

    # Primary failed and fallback failed -> deterministic fallback returned safely
    assert outcome.model_fallback_applied is False
    assert len(outcome.issues) == 1
    assert outcome.issues[0].route == "KNOWLEDGE"
    assert outcome.issues[0].description == "無法連線到主機"
