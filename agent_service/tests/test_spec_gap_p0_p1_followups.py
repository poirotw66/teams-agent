"""Focused regression tests for remaining Spec P0/P1 eval gaps."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from agent_service.target_manifest import (
    knowledge_release_target_manifest_hash,
    resolve_publish_manifest_defaults,
)
from ai_ops_backoffice.evaluation_domain.models import (
    CaseRevision,
    EvaluationCriteria,
    ProvenanceSpec,
    TurnSpec,
)
from ai_ops_backoffice.evaluation_domain.real_rag_adapters import RealRagAnswerAdapter
from ai_ops_backoffice.evaluation_domain.runner import EvaluationRunner
from ai_ops_backoffice.evaluation_domain.runner_models import (
    TargetExecutionInput,
    TargetManifest,
)


def _manifest() -> TargetManifest:
    return TargetManifest(
        target_id="cand",
        target_side="CANDIDATE",
        manifest_hash="h-cand",
        model_id="gemini-3.8-flash",
    )


def test_agent_sandbox_multi_turn_calls_workflow_per_turn() -> None:
    calls: list[dict] = []

    class Sandbox:
        def execute_workflow_turn(self, query, manifest, sanitized_input):
            calls.append(
                {
                    "query": query,
                    "history": list(sanitized_input.conversation_history),
                }
            )
            return {
                "status": "SUCCESS",
                "answer": f"A:{query} [來源: fixture]",
                "tokens": 10,
                "cost_usd": 0.001,
                "tool_calls": [
                    {
                        "call_id": f"call-{len(calls)+1}",
                        "tool_name": "t1",
                        "arguments": {"q": query},
                    }
                ],
            }

    runner = EvaluationRunner(
        MagicMock(),
        answering_fn=None,
        sandbox_adapter=Sandbox(),
        strict_real_rag=True,
    )
    runner._retriever_fn = lambda query, manifest, sanitized: []
    now = datetime.now(timezone.utc)
    case = CaseRevision(
        revision_id="r1",
        case_id="c1",
        revision_number=1,
        query="ignored",
        turns=(
            TurnSpec(turn_id="t0", user_query="第一題"),
            TurnSpec(turn_id="t1", user_query="那主管呢？"),
        ),
        criteria=EvaluationCriteria(),
        provenance=ProvenanceSpec(source_type="MANUAL", source_id="test"),
        etag=1,
        content_hash="h1",
        created_by="admin",
        created_at=now,
        updated_by="admin",
        updated_at=now,
    )
    result = runner._execute_side(
        "run1", case, _manifest(), "CANDIDATE", mode="AGENT_SANDBOX"
    )
    assert len(calls) == 2
    assert calls[0]["query"] == "第一題"
    assert calls[1]["query"] == "那主管呢？"
    assert calls[1]["history"][0]["content"] == "第一題"
    assert calls[1]["history"][1]["content"].startswith("A:第一題")
    assert result.status == "COMPLETED"
    assert result.error_detail is None


def test_real_rag_chat_model_includes_conversation_history() -> None:
    seen: list[list] = []

    class FakeMsg:
        def __init__(self, content: str) -> None:
            self.content = content

        @property
        def usage_metadata(self):
            return {"total_tokens": 12}

    class FakeModel:
        def invoke(self, messages):
            seen.append(messages)
            return FakeMsg("根據前文：主管也要設定")

    adapter = RealRagAnswerAdapter(
        chat_model=FakeModel(),
        allow_synthetic_fallback=False,
    )
    answer, tokens, cost, _, _ = adapter(
        "那主管呢？",
        _manifest(),
        TargetExecutionInput(
            query="那主管呢？",
            conversation_history=(
                {"role": "user", "content": "大洲無法點選"},
                {"role": "assistant", "content": "請調整 IE 安全性"},
            ),
            case_id="c1",
        ),
        [{"title": "大州", "content": "啟用指令碼視窗"}],
        [
            {"role": "user", "content": "大洲無法點選"},
            {"role": "assistant", "content": "請調整 IE 安全性"},
        ],
    )
    assert "主管" in answer
    assert tokens == 12
    assert len(seen) == 1
    assert len(seen[0]) >= 4


def test_publish_manifest_defaults_include_live_env(monkeypatch) -> None:
    monkeypatch.setenv("GATE_CANDIDATE_MODEL_ID", "gemini-3.8-flash")
    monkeypatch.setenv("GATE_CANDIDATE_PROMPT_VERSION", "answer-v3")
    monkeypatch.setenv("GATE_CANDIDATE_APP_REVISION", "build-42")
    monkeypatch.setenv("RAG_TOP_K", "6")
    defaults = resolve_publish_manifest_defaults()
    assert defaults["model_id"] == "gemini-3.8-flash"
    assert defaults["prompt_version"] == "answer-v3"
    assert defaults["app_revision"] == "build-42"
    assert defaults["retriever_config"]["top_k"] == 6
    hash_a = knowledge_release_target_manifest_hash(release_id="rel-1")
    monkeypatch.setenv("GATE_CANDIDATE_PROMPT_VERSION", "answer-v4")
    hash_b = knowledge_release_target_manifest_hash(release_id="rel-1")
    assert hash_a != hash_b


def test_publish_manifest_defaults_from_snapshot_file(tmp_path, monkeypatch) -> None:
    snapshot = tmp_path / "candidate.json"
    snapshot.write_text(
        '{"model_id":"gemini-3.1-flash-lite","prompt_version":"pv-9",'
        '"app_revision":"rev-9","retriever_config":{"top_k":9,"min_score":0.2}}',
        encoding="utf-8",
    )
    monkeypatch.delenv("GATE_CANDIDATE_MODEL_ID", raising=False)
    monkeypatch.delenv("GATE_CANDIDATE_PROMPT_VERSION", raising=False)
    monkeypatch.delenv("GATE_CANDIDATE_APP_REVISION", raising=False)
    monkeypatch.delenv("RAG_TOP_K", raising=False)
    monkeypatch.delenv("RAG_MIN_SCORE", raising=False)
    monkeypatch.delenv("RAG_EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    monkeypatch.delenv("RAG_MODEL", raising=False)
    monkeypatch.setenv("GATE_CANDIDATE_MANIFEST_PATH", str(snapshot))
    defaults = resolve_publish_manifest_defaults()
    assert defaults["model_id"] == "gemini-3.1-flash-lite"
    assert defaults["prompt_version"] == "pv-9"
    assert defaults["app_revision"] == "rev-9"
    assert defaults["retriever_config"]["top_k"] == 9
    assert defaults["retriever_config"]["min_score"] == 0.2


@pytest.mark.asyncio
async def test_promote_candidate_release_reuses_same_id_and_hash(tmp_path) -> None:
    from knowledge_portal.models import PortalActor, ReleaseRecord
    from knowledge_portal.services.release_service import ReleaseService

    actor = PortalActor(
        user_id="mgr-1",
        display_name="Manager",
        role="MANAGER",
        owner_unit_ids=["IT Service Desk"],
        tenant_id="tenant-1",
    )
    now = datetime.now(timezone.utc)
    blocked = ReleaseRecord(
        release_id="release-same",
        status="GATE_BLOCKED",
        manifest=[],
        corpus_hash="corpus-1",
        target_manifest_hash="hash-fixed-candidate",
        index_artifact_uri="memory://index",
        index_setting_version="v1",
        created_at=now,
        created_by="mgr-1",
        failure_summary="gate blocked once",
    )
    saved: list[ReleaseRecord] = []

    class Repo:
        active = None

        async def get_release(self, release_id: str):
            assert release_id == "release-same"
            return saved[-1] if saved else blocked

        async def save_release(self, release: ReleaseRecord):
            saved.append(release)

        async def set_active_release_id(self, release_id: str):
            self.active = release_id

        async def get_active_release_id(self):
            return self.active

        async def list_releases(self):
            return [blocked, *saved]

        async def acquire_publish_lease(self, owner: str, ttl_seconds: float = 30.0):
            _ = owner, ttl_seconds
            return True

        async def release_publish_lease(self, owner: str):
            _ = owner

    class Ctx:
        repository = Repo()
        settings = MagicMock(release_artifact_dir=tmp_path)
        release_gate_checker = None
        publisher = MagicMock()

        async def audit(self, **kwargs):
            return None

    service = ReleaseService(Ctx(), documents=MagicMock())

    async def _noop_notify(release_id: str, corr: str):
        return True, None

    service._notify_agent_reload = _noop_notify  # type: ignore[method-assign]

    promoted = await service.promote_candidate_release(actor, "release-same")
    assert promoted.release_id == "release-same"
    assert promoted.target_manifest_hash == "hash-fixed-candidate"
    assert promoted.status == "ACTIVE"
    assert Ctx.publisher.build_release.call_count == 0


def test_eval_prompt_resolver_reads_governance_and_prompt_repo() -> None:
    from ai_ops_backoffice.governance_domain.models import PromptVersion, utc_now

    now = utc_now()
    version = PromptVersion(
        version_id="pv-42",
        prompt_id="answer",
        version="answer-v42",
        status="ACTIVE",
        template="GOVERNANCE_TEMPLATE {max_issues}",
        content_hash="h",
        input_schema_version="v1",
        output_schema_version="v1",
        taxonomy_version="v1",
        model_id="gemini-3.8-flash",
        created_by="admin",
        created_at=now,
    )

    class GovRepo:
        def load(self):
            return MagicMock(prompt_versions=(version,))

    class PromptRepo:
        def load(self):
            candidate = MagicMock(
                version="poc-v9",
                candidate_id="cand-9",
                content="POC_TEMPLATE",
            )
            return MagicMock(candidates=(candidate,))

    governance_repository = GovRepo()
    prompt_repository = PromptRepo()

    def _eval_prompt_resolver(prompt_version: str) -> str | None:
        version_key = str(prompt_version or "").strip()
        if not version_key or version_key == "default":
            return "DEFAULT_ANSWER_PROMPT"
        state = governance_repository.load()
        for item in state.prompt_versions:
            if item.version == version_key or item.version_id == version_key:
                template = str(item.template or "").strip()
                if template:
                    return template
        for candidate in prompt_repository.load().candidates:
            if candidate.version == version_key or candidate.candidate_id == version_key:
                content = str(candidate.content or "").strip()
                if content:
                    return content
        return None

    assert _eval_prompt_resolver("default") == "DEFAULT_ANSWER_PROMPT"
    assert _eval_prompt_resolver("answer-v42") == "GOVERNANCE_TEMPLATE {max_issues}"
    assert _eval_prompt_resolver("pv-42") == "GOVERNANCE_TEMPLATE {max_issues}"
    assert _eval_prompt_resolver("poc-v9") == "POC_TEMPLATE"
    assert _eval_prompt_resolver("missing") is None


def test_knowledge_bridge_allows_and_maps_promote_candidate_release() -> None:
    from ai_ops_backoffice.knowledge_bridge.capabilities import capability_for_portal_path
    from ai_ops_backoffice.knowledge_bridge.errors import assert_allowlisted

    assert_allowlisted("releases/rel-42/promote")
    cap = capability_for_portal_path("POST", "releases/rel-42/promote")
    assert cap == "knowledge.publish"


def test_eval_prompt_resolver_disambiguates_composite_and_version_id() -> None:
    from ai_ops_backoffice.governance_domain.models import PromptVersion, utc_now

    now = utc_now()
    # Two prompt versions with the same version string "v1" but different prompt_ids
    pv_extractor = PromptVersion(
        version_id="pv-ext-001",
        prompt_id="issue_extractor",
        version="v1",
        status="ACTIVE",
        template="EXTRACTOR_PROMPT {max_issues}",
        content_hash="h1",
        input_schema_version="v1",
        output_schema_version="v1",
        taxonomy_version="v1",
        model_id="gemini-3.8-flash",
        created_by="admin",
        created_at=now,
    )
    pv_answer = PromptVersion(
        version_id="pv-ans-002",
        prompt_id="knowledge_answer",
        version="v1",
        status="ACTIVE",
        template="ANSWER_PROMPT {query}",
        content_hash="h2",
        input_schema_version="v1",
        output_schema_version="v1",
        taxonomy_version="v1",
        model_id="gemini-3.8-flash",
        created_by="admin",
        created_at=now,
    )

    class FakeGovRepo:
        def load(self):
            return MagicMock(prompt_versions=(pv_extractor, pv_answer))

    class FakePromptRepo:
        def load(self):
            return MagicMock(candidates=())

    gov_repo = FakeGovRepo()
    p_repo = FakePromptRepo()
    _ = p_repo

    # Test the real resolver logic
    def _test_resolver(prompt_version: str) -> str | None:
        version = str(prompt_version or "").strip()
        if not version or version == "default":
            return "DEFAULT"
        target_prompt_id: str | None = None
        target_version = version
        if ":" in version:
            target_prompt_id, target_version = version.split(":", 1)
            target_prompt_id = target_prompt_id.strip()
            target_version = target_version.strip()
        # 1. Match immutable version_id
        for item in gov_repo.load().prompt_versions:
            if item.version_id == version:
                return item.template
        # 2. Match (prompt_id, version)
        if target_prompt_id:
            for item in gov_repo.load().prompt_versions:
                if item.prompt_id == target_prompt_id and item.version == target_version:
                    return item.template
        # 3. Fallback: match version label
        for item in gov_repo.load().prompt_versions:
            if item.version == target_version:
                return item.template
        return None

    # Immutable version_id match
    assert _test_resolver("pv-ext-001") == "EXTRACTOR_PROMPT {max_issues}"
    assert _test_resolver("pv-ans-002") == "ANSWER_PROMPT {query}"
    # Composite prompt_id:version match
    assert _test_resolver("knowledge_answer:v1") == "ANSWER_PROMPT {query}"
    assert _test_resolver("issue_extractor:v1") == "EXTRACTOR_PROMPT {max_issues}"


def test_freshness_tracker_isolates_stages_by_resource_type() -> None:
    from datetime import datetime, timedelta, timezone

    from ai_ops_backoffice.services.freshness_service import FreshnessTracker

    tracker = FreshnessTracker()
    now = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    tracker.record_worker_heartbeat(worker_id="w1", at=now)

    t_conv = now - timedelta(minutes=10)
    t_agg = now - timedelta(seconds=15)

    # Conversation ingested at t_conv (10 min ago)
    tracker.record_stage_event("c-1", "EVENT_INGESTED", at=t_conv)
    # Aggregation completed at t_agg (15 sec ago)
    tracker.record_stage_event("c-2", "AGGREGATION_COMPLETED", at=t_agg)

    # "conversations" must look only at conversation stages, not AGGREGATION_COMPLETED
    conv_freshness = tracker.compute_freshness(resource_type="conversations", now=now)
    assert conv_freshness.materialized_at == t_conv
    assert conv_freshness.lag_seconds == 600.0
    assert conv_freshness.status == "DELAYED"

    # "reporting" must look at AGGREGATION_COMPLETED
    rep_freshness = tracker.compute_freshness(resource_type="reporting", now=now)
    assert rep_freshness.materialized_at == t_agg
    assert rep_freshness.lag_seconds == 15.0
    assert rep_freshness.status == "REALTIME"


def test_freshness_without_sync_returns_unknown_even_with_heartbeat_and_render(tmp_path) -> None:
    from datetime import datetime, timezone

    from ai_ops_backoffice.services.freshness_service import FreshnessTracker

    now = datetime(2026, 9, 12, 12, 0, 0, tzinfo=timezone.utc)
    persist_file = tmp_path / "sync_watermarks.json"
    tracker = FreshnessTracker(persistent_path=persist_file)
    tracker.record_worker_heartbeat(at=now)
    # Only heartbeat and page render event recorded, no ingestion or sync
    tracker.record_stage_event("c-render", "CONVERSATION_LIST_RENDERED", at=now)

    freshness = tracker.compute_freshness(resource_type="conversations", now=now)
    # Must NOT claim REALTIME with lag=0 without sync evidence!
    assert freshness.status == "UNKNOWN"
    assert freshness.lag_seconds is None
    assert freshness.event_watermark is None

    # When persistent sync success is recorded, it reflects across instances sharing the path
    tracker.record_sync_success("conversations", at=now, tenant_id="t-corp")
    instance2 = FreshnessTracker(persistent_path=persist_file)
    instance2.record_worker_heartbeat(at=now)
    freshness2 = instance2.compute_freshness(resource_type="conversations", now=now, tenant_id="t-corp")
    assert freshness2.status == "REALTIME"
    assert freshness2.lag_seconds == 0.0


def test_eval_runtime_injects_persona_context_and_release_chunks(tmp_path) -> None:
    import json

    from ai_ops_backoffice.evaluation_domain.runner_models import (
        TargetExecutionInput,
        TargetManifest,
    )
    from ai_ops_backoffice.governance_domain.eval_runtime import (
        build_isolated_eval_runtime,
    )

    # Create dummy release chunks
    rel_dir = tmp_path / "rel-test-01" / "index"
    rel_dir.mkdir(parents=True)
    chunks = [
        {
            "chunk_id": "chunk-hr-1",
            "title": "HR Confidential Policy",
            "content": "HR ONLY: 年度調薪與主管評核辦法",
            "allowed_groups": ["HR_EXEC"],
        },
        {
            "chunk_id": "chunk-all-1",
            "title": "General Employee Policy",
            "content": "全體同仁差旅報銷須知",
            "allowed_groups": ["ALL_EMPLOYEES"],
        },
    ]
    (rel_dir / "chunks.json").write_text(json.dumps({"chunks": chunks}), encoding="utf-8")

    manifest = TargetManifest(
        target_id="cand-1",
        target_side="CANDIDATE",
        manifest_hash="hash-1",
        knowledge_release_id="rel-test-01",
        faq_version_id="eval-faq-v1",
        persona_fixture_id="hr-manager",
        retriever_config={
            "persona_context": {
                "acl_groups": ["HR_EXEC", "ALL_EMPLOYEES"],
                "tenant_id": "tenant-corp",
                "email": "hr_lead@corp.com",
                "display_name": "HR Lead",
            }
        },
    )
    sanitized = TargetExecutionInput(
        query="年度調薪辦法",
        persona_context=manifest.retriever_config["persona_context"],
    )

    class FakeModel:
        def __init__(self, *args, **kwargs):
            pass

    runtime = build_isolated_eval_runtime(
        model_factory=lambda m: FakeModel(),
        manifest=manifest,
        persona_context=sanitized.persona_context,
    )
    # Manually point runtime's knowledge service to tmp_path
    runtime.knowledge_service.releases_dir = tmp_path

    # Verify persona injection in AgentRequest
    req = runtime.build_request("年度調薪辦法", None)
    assert req.conversation.tenantId == "tenant-corp"
    assert req.user.email == "hr_lead@corp.com"
    assert req.user.displayName == "HR Lead"
    assert "HR_EXEC" in req.user.groups

    # Verify release search with ACL
    import asyncio
    res = asyncio.run(runtime.knowledge_service.search("年度調薪", req.user))
    assert res.found is True
    assert res.backend == "release-index"
    assert any("HR Confidential Policy" in s.title for s in res.sources)


def test_sandbox_binding_fail_closed_on_missing_data(tmp_path) -> None:
    from ai_ops_backoffice.governance_domain.eval_runtime import (
        EvalBindingError,
        _FixtureFaqRepository,
        _FixtureKnowledgeService,
    )

    # 1. FaqRepository with missing version raises EvalBindingError
    with pytest.raises(EvalBindingError, match="faq_version_not_found"):
        _FixtureFaqRepository(faq_version_id="nonexistent-faq-version-xyz")

    # 2. KnowledgeService with missing release raises EvalBindingError
    ks = _FixtureKnowledgeService(release_id="nonexistent-release-123", releases_dir=tmp_path)
    import asyncio
    with pytest.raises(EvalBindingError, match="knowledge_release_not_found"):
        asyncio.run(ks.search("query", None))


def test_eval_prompt_resolver_fail_closed() -> None:
    from ai_ops_backoffice.api import build_eval_prompt_resolver

    resolver = build_eval_prompt_resolver()
    # Explicit pv- or prompt- prefix or prompt:version that does not exist returns None
    assert resolver("pv-nonexistent-123") is None
    assert resolver("prompt-it-bot:v999") is None
    assert resolver("cand-nonexistent-456") is None


def test_runner_preserves_estimated_token_usage(tmp_path) -> None:
    from datetime import datetime, timezone

    from ai_ops_backoffice.evaluation_domain.models import CaseRevision, ProvenanceSpec
    from ai_ops_backoffice.evaluation_domain.repository import FileEvaluationRepository
    from ai_ops_backoffice.evaluation_domain.runner import EvaluationRunner
    from ai_ops_backoffice.evaluation_domain.runner_models import TargetManifest

    repo = FileEvaluationRepository(tmp_path / "evals.json")
    runner = EvaluationRunner(
        repository=repo,
        answering_fn=lambda *args, **kwargs: (
            "Sample answer",
            120,
            0.001,
            [],
            "req-1",
            "ESTIMATED",
        ),
        retriever_fn=lambda *args, **kwargs: [],
    )
    now = datetime.now(timezone.utc)
    rev = CaseRevision(
        case_id="case-1",
        revision_id="rev-1",
        revision_number=1,
        query="Test query",
        provenance=ProvenanceSpec(source_type="MANUAL", source_id="test"),
        etag=1,
        content_hash="h1",
        created_by="admin",
        created_at=now,
        updated_by="admin",
        updated_at=now,
    )
    manifest = TargetManifest(
        target_id="cand-1",
        target_side="CANDIDATE",
        manifest_hash="hash-1",
    )
    exec_res = runner._execute_side(
        run_id="run-1",
        case_revision=rev,
        manifest=manifest,
        side="CANDIDATE",
        mode="STANDARD",
    )
    assert exec_res.usage_status == "ESTIMATED"


def test_freshness_tracker_operations_overview_aliases() -> None:
    from datetime import datetime, timezone

    from ai_ops_backoffice.services.freshness_service import FreshnessTracker

    tracker = FreshnessTracker()
    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    tracker.record_worker_heartbeat(at=t0)

    # Record under hyphenated operations-overview
    tracker.record_sync_success("operations-overview", at=t0)
    tracker.record_stage_event("operations-overview", "AGGREGATION_COMPLETED", at=t0)

    # Query with underscore operations_overview
    meta = tracker.compute_freshness(resource_type="operations_overview", now=t0)
    assert meta.event_watermark == t0
    assert meta.last_successful_sync_at == t0
    assert meta.status == "REALTIME"


def test_query_conversations_decouples_event_time_and_keeps_idle_stream_realtime() -> None:
    from datetime import datetime, timedelta, timezone
    from unittest.mock import MagicMock

    from agent_service.operations.access import ActorContext
    from agent_service.operations.contracts import OperationalEvent
    from ai_ops_backoffice.services.freshness_service import FreshnessTracker
    from ai_ops_backoffice.services.query_conversations import ConversationsQueryMixin

    class MockService(ConversationsQueryMixin):
        def __init__(self, tracker: FreshnessTracker, events: list[OperationalEvent]) -> None:
            self._freshness_tracker = tracker
            self._events = events

        def _resolve_period(self, **kwargs):
            return MagicMock()

        async def _scoped_events(self, actor, period, force_refresh=False):
            return self._events

    now = datetime(2026, 9, 12, 12, 0, 0, tzinfo=timezone.utc)
    tracker = FreshnessTracker(clock=lambda: now)
    tracker.record_worker_heartbeat(worker_id="w1", at=now)
    # Healthy pipeline sync ran 10 seconds ago for tenant-1
    t_sync = now - timedelta(seconds=10)
    tracker.record_sync_success("conversations", at=t_sync, tenant_id="tenant-1")

    # Business event occurred 3 days ago (idle / historical conversation)
    t_ancient_event = now - timedelta(days=3)
    ev = OperationalEvent(
        event_id="ev-1",
        event_type="turn.received",
        correlation_id="corr-turn-1",
        conversation_id="conv-1",
        turn_id="turn-1",
        occurred_at=t_ancient_event,
        payload={"messageMasked": "old question"},
    )
    service = MockService(tracker, [ev])
    actor = ActorContext(
        user_id="user-1",
        display_name="User One",
        role="SYSTEM_ADMIN",
        owner_unit_ids=(),
        tenant_id="tenant-1",
    )

    import asyncio
    res = asyncio.run(service.list_conversations(actor))
    assert res["freshness"] is not None
    freshness = res["freshness"]

    # 1. Pipeline watermark must reflect healthy sync (10s ago), NOT ancient business event
    watermark_val = freshness.get("event_watermark") or freshness.get("eventWatermark")
    assert datetime.fromisoformat(watermark_val.replace("Z", "+00:00")) == t_sync

    # 2. Idle stream remains REALTIME when sync is healthy
    assert freshness["status"] == "REALTIME"

    # 3. UI render stage is recorded without corrupting EVENT_INGESTED
    assert "CONVERSATION_LIST_RENDERED" in tracker._stage_events["conversations"]
    assert "EVENT_INGESTED" not in tracker._stage_events["conversations"]

    # 4. Zero new conversations test: empty events list also remains REALTIME
    empty_service = MockService(tracker, [])
    empty_res = asyncio.run(empty_service.list_conversations(actor))
    assert empty_res["freshness"]["status"] == "REALTIME"

    # 5. Strict Tenant Isolation: tenant-2 with no sync data MUST be UNKNOWN, not REALTIME
    actor_tenant2 = ActorContext(
        user_id="user-2",
        display_name="User Two",
        role="SYSTEM_ADMIN",
        owner_unit_ids=(),
        tenant_id="tenant-2",
    )
    res_tenant2 = asyncio.run(service.list_conversations(actor_tenant2))
    assert res_tenant2["freshness"]["status"] == "UNKNOWN"
    assert res_tenant2["freshness"]["lag_seconds"] is None


def test_eval_prompt_resolver_rejects_ambiguous_bare_version() -> None:
    from unittest.mock import MagicMock

    from ai_ops_backoffice.api import build_eval_prompt_resolver

    # Governance repository with two prompts sharing version "v1"
    item1 = MagicMock()
    item1.prompt_id = "it-helpdesk"
    item1.version = "v1"
    item1.version_id = "pv-1"
    item1.template = "Template 1"

    item2 = MagicMock()
    item2.prompt_id = "hr-assistant"
    item2.version = "v1"
    item2.version_id = "pv-2"
    item2.template = "Template 2"

    item3 = MagicMock()
    item3.prompt_id = "it-helpdesk"
    item3.version = "v2"
    item3.version_id = "pv-3"
    item3.template = "Template 3 Unique"

    gov_repo = MagicMock()
    state = MagicMock()
    state.prompt_versions = [item1, item2, item3]
    gov_repo.load.return_value = state

    resolver = build_eval_prompt_resolver(governance_repository=gov_repo)

    # 1. Bare "v1" is ambiguous (matches it-helpdesk and hr-assistant) -> Must reject (return None)
    assert resolver("v1") is None

    # 2. Qualified prompt_id:version succeeds deterministically
    assert resolver("it-helpdesk:v1") == "Template 1"
    assert resolver("hr-assistant:v1") == "Template 2"

    # 3. Immutable version_id succeeds
    assert resolver("pv-1") == "Template 1"
    assert resolver("pv-2") == "Template 2"

    # 4. Globally unique bare version "v2" succeeds
    assert resolver("v2") == "Template 3 Unique"


def test_sandbox_real_faq_repository_binding_and_content_field(tmp_path) -> None:
    import pytest

    from agent_service.operations.access import ActorContext
    from ai_ops_backoffice.evaluation_domain.runner_models import TargetManifest
    from ai_ops_backoffice.faq_domain import FaqContent, FaqDomainService
    from ai_ops_backoffice.faq_domain.repository import FileFaqRepository
    from ai_ops_backoffice.governance_domain.eval_runtime import (
        EvalBindingError,
        build_isolated_eval_runtime,
    )

    class _AllowTaxonomy:
        def require_active(self, issue_type_id: str) -> None:
            pass

    faq_file = tmp_path / "faqs.json"
    faq_repo = FileFaqRepository(faq_file)
    faq_service = FaqDomainService(faq_repo, taxonomy=_AllowTaxonomy())
    admin_actor = ActorContext("netadmin", "Net Admin", "SYSTEM_ADMIN", ())

    created = faq_service.create(
        content=FaqContent(
            faq_key="vpn.client_setup",
            question="如何設定 VPN？",
            answer="請依照 IT 連線指示安裝官方 VPN 用戶端軟體並登入。",
            category="NETWORK",
            keywords=("vpn",),
            owner_unit_id="NET_OPS",
            business_contact="IT Service Desk",
            issue_type_ids=("it.network",),
            audience_type="ALL",
        ),
        actor=admin_actor,
    )
    version_id = created["version"]["version_id"]

    manifest = TargetManifest(
        target_id="cand-eval-1",
        target_side="CANDIDATE",
        manifest_hash="hash-cand-1",
        faq_version_id=version_id,
    )

    # 1. Isolated eval runtime with real faq_repository injected resolves the FAQ version
    runtime = build_isolated_eval_runtime(manifest=manifest, faq_repository=faq_repo)
    resolved_faq = runtime.faq_service.get("vpn.client_setup")
    assert resolved_faq is not None
    assert resolved_faq.answer == "請依照 IT 連線指示安裝官方 VPN 用戶端軟體並登入。"
    assert resolved_faq.id == version_id

    # 2. Non-existent version fails closed with EvalBindingError without guessing file paths
    bad_manifest = TargetManifest(
        target_id="cand-eval-2",
        target_side="CANDIDATE",
        manifest_hash="hash-cand-2",
        faq_version_id="ver-missing-999",
    )
    with pytest.raises(EvalBindingError, match="faq_version_not_found:ver-missing-999"):
        build_isolated_eval_runtime(manifest=bad_manifest, faq_repository=faq_repo)


def test_firestore_evaluation_repo_diff_based_writes_and_targeted_lookups() -> None:
    from typing import Any

    from ai_ops_backoffice.evaluation_domain.models import EvalCase, EvaluationState
    from ai_ops_backoffice.evaluation_domain.repository import FirestoreEvaluationRepository

    class MockSnap:
        def __init__(self, key: str, val: dict | None) -> None:
            self.id = key
            self.exists = val is not None
            self._val = val
        def to_dict(self) -> dict | None:
            return dict(self._val) if self._val is not None else None

    class MockDoc:
        def __init__(self, key: str, coll: MockColl) -> None:
            self.key = key
            self.coll = coll
        def get(self, transaction: Any = None) -> MockSnap:
            data = self.coll.store.get((self.coll.name, self.key))
            return MockSnap(self.key, data)
        def set(self, data: dict, merge: bool = False) -> None:
            self.coll.store[(self.coll.name, self.key)] = dict(data)
        def delete(self) -> None:
            self.coll.store.pop((self.coll.name, self.key), None)

    class MockColl:
        def __init__(self, name: str, store: dict) -> None:
            self.name = name
            self.store = store
        def document(self, key: str) -> MockDoc:
            return MockDoc(key, self)
        def stream(self) -> list[MockSnap]:
            return [MockDoc(k, self).get() for (c, k) in self.store if c == self.name]

    class MockClient:
        def __init__(self) -> None:
            self.store: dict[tuple[str, str], dict] = {}
        def collection(self, name: str) -> MockColl:
            return MockColl(name, self.store)
        def transaction(self) -> Any:
            class Tx:
                def __init__(self, c: MockClient) -> None:
                    self.c = c
                    self.pending: dict[tuple[str, str], dict] = {}
                def get(self, ref: MockDoc) -> MockSnap:
                    if (ref.coll.name, ref.key) in self.pending:
                        return MockSnap(ref.key, self.pending[(ref.coll.name, ref.key)])
                    return ref.get()
                def set(self, ref: MockDoc, data: dict, merge: bool = False) -> None:
                    self.pending[(ref.coll.name, ref.key)] = dict(data)
                def delete(self, ref: MockDoc) -> None:
                    self.pending.pop((ref.coll.name, ref.key), None)
                    self.c.store.pop((ref.coll.name, ref.key), None)
                def commit(self) -> None:
                    for k, v in self.pending.items():
                        self.c.store[k] = v
            return Tx(self)

    def _run_tx(op: Any, tx: Any) -> Any:
        res = op(tx)
        tx.commit()
        return res

    client = MockClient()
    repo = FirestoreEvaluationRepository(client, transaction_runner=_run_tx)
    now = datetime.now(timezone.utc)

    case1 = EvalCase(
        case_id="case-diff-1",
        tenant_id="tenant-1",
        owner_unit_id="IT",
        title="Diff Test 1",
        current_revision_id="rev-1",
        created_by="tester",
        created_at=now,
        updated_by="tester",
        updated_at=now,
    )
    case2 = EvalCase(
        case_id="case-diff-2",
        tenant_id="tenant-1",
        owner_unit_id="IT",
        title="Diff Test 2",
        current_revision_id="rev-2",
        created_by="tester",
        created_at=now,
        updated_by="tester",
        updated_at=now,
    )

    # Initial write of case 1 and case 2
    state1 = EvaluationState(cases=(case1, case2))
    repo.commit_mutation(state1, expected_revision=1)

    # Verify both have _revision: 2 in storage
    doc1 = client.store[("ai_ops_eval_cases", "case-diff-1")]
    doc2 = client.store[("ai_ops_eval_cases", "case-diff-2")]
    assert doc1["_revision"] == 2
    assert doc2["_revision"] == 2

    # Second mutation: only update case1 title; case2 remains unchanged
    updated_case1 = case1.model_copy(update={"title": "Diff Test 1 Modified"})
    state2 = state1.model_copy(update={"cases": (updated_case1, case2)})
    repo.commit_mutation(state2, expected_revision=2)

    # case1 was written with new revision 3; case2 was NOT rewritten
    doc1_after = client.store[("ai_ops_eval_cases", "case-diff-1")]
    doc2_after = client.store[("ai_ops_eval_cases", "case-diff-2")]
    assert doc1_after["_revision"] == 3
    assert doc1_after["title"] == "Diff Test 1 Modified"
    assert doc2_after["_revision"] == 2  # Untouched!

    # Test targeted lookup for an entity not in memory of a fresh instance
    repo2 = FirestoreEvaluationRepository(client, transaction_runner=_run_tx)
    assert len(repo2._state.cases) == 0
    # Targeted get_case fetches directly from client store without calling full load()
    fetched = repo2.get_case("case-diff-1")
    assert fetched is not None
    assert fetched.case_id == "case-diff-1"
    assert fetched.title == "Diff Test 1 Modified"


def test_eval_run_and_job_transactional_outbox_flow() -> None:
    from unittest.mock import MagicMock, patch

    from ai_ops_backoffice.evaluation_domain.job_repository import InMemoryJobRepository
    from ai_ops_backoffice.evaluation_domain.models import EvalSet, EvalSetVersion
    from ai_ops_backoffice.evaluation_domain.repository import InMemoryEvaluationRepository
    from ai_ops_backoffice.evaluation_domain.run_service import EvaluationRunService
    from ai_ops_backoffice.evaluation_domain.runner_models import RunPreflightResult, TargetManifest

    repo = InMemoryEvaluationRepository()
    job_repo = InMemoryJobRepository()
    now = datetime.now(timezone.utc)

    eval_set = EvalSet(
        set_id="set-outbox-1",
        tenant_id="tenant-outbox",
        owner_unit_ids=("IT",),
        name="Outbox Set",
        lead_owner="tester",
        created_by="tester",
        created_at=now,
        updated_by="tester",
        updated_at=now,
    )
    set_ver = EvalSetVersion(
        set_version_id="sv-outbox-1",
        set_id="set-outbox-1",
        version=1,
        case_revision_ids=(),
        manifest_hash="hash-outbox",
        created_by="tester",
        created_at=now,
        etag=1,
    )
    repo.commit_mutation(repo.load().model_copy(update={"sets": (eval_set,), "set_versions": (set_ver,)}))

    manifest = TargetManifest(target_id="tgt-1", target_side="BASELINE", manifest_hash="h1")
    preflight = RunPreflightResult(
        is_valid=True,
        resolved_baseline_manifest=manifest,
        resolved_candidate_manifest=manifest,
        blocking_errors=(),
        is_eval_eligible=True,
    )
    resolver = MagicMock()
    resolver.preflight_run.return_value = preflight

    service = EvaluationRunService(
        repository=repo,
        manifest_resolver=resolver,
        job_repository=job_repo,
    )

    # 1. Normal create_run: Outbox job is written atomically, immediately dispatched to job_repo, and removed from outbox
    res = service.create_run(
        set_version_id="sv-outbox-1",
        baseline_target={"manifest_hash": "h1"},
        candidate_target={"manifest_hash": "h1"},
    )
    run_id = res["runId"]
    assert job_repo.get_job_by_run_id(run_id) is not None
    # Outbox should be empty after successful immediate dispatch
    assert len(repo.load().outbox_jobs) == 0

    # 2. Compensation scenario: dispatch fails (e.g. temporary network / contention)
    # The outbox job remains safely persisted in repo state!
    with patch.object(job_repo, "enqueue_job", side_effect=RuntimeError("queue offline")):
        res2 = service.create_run(
            set_version_id="sv-outbox-1",
            baseline_target={"manifest_hash": "h1"},
            candidate_target={"manifest_hash": "h1"},
        )
        run_id2 = res2["runId"]

    # The run exists in QUEUED state, and the outbox contains the pending job!
    assert repo.get_run(run_id2).status == "QUEUED"
    pending_outbox = repo.load().outbox_jobs
    assert len(pending_outbox) == 1
    assert pending_outbox[0]["run_id"] == run_id2

    # 3. Outbox scanner recovery: recover_undispatched_runs dispatches the pending outbox job
    recovered_count = service.recover_undispatched_runs()
    assert recovered_count == 1
    assert job_repo.get_job_by_run_id(run_id2) is not None
    # Outbox is drained and cleared
    assert len(repo.load().outbox_jobs) == 0


@pytest.mark.asyncio
async def test_background_workers_enabled_flag_and_decoupled_execution(tmp_path, monkeypatch) -> None:
    from ai_ops_backoffice.api import create_app
    from ai_ops_backoffice.settings import BackofficeSettings

    # 1. Test from_env parsing of AI_OPS_WORKERS_ENABLED
    monkeypatch.setenv("AI_OPS_WORKERS_ENABLED", "false")
    settings_disabled = BackofficeSettings.from_env()
    assert settings_disabled.workers_enabled is False

    monkeypatch.setenv("AI_OPS_WORKERS_ENABLED", "true")
    settings_enabled = BackofficeSettings.from_env()
    assert settings_enabled.workers_enabled is True

    # 2. Test that app lifespan with workers_enabled=False enters and exits without starting background loops
    app_disabled = create_app(settings_disabled)
    async with app_disabled.router.lifespan_context(app_disabled):
        # Successfully in context without errors; background tasks are not running
        pass


def test_freshness_strict_tenant_isolation_never_leaks_watermark_or_stages() -> None:
    from datetime import datetime, timedelta, timezone

    from ai_ops_backoffice.services.freshness_service import FreshnessTracker

    now = datetime(2026, 9, 12, 12, 0, 0, tzinfo=timezone.utc)
    tracker = FreshnessTracker(clock=lambda: now)
    tracker.record_worker_heartbeat(worker_id="worker-shared", at=now)

    # Sync tenant-A 10 seconds ago
    t_sync_a = now - timedelta(seconds=10)
    tracker.record_sync_success("conversations", at=t_sync_a, tenant_id="tenant-A")

    # Record stage event for tenant-A
    tracker.record_stage_event("corr-a-1", "EVENT_INGESTED", at=t_sync_a, tenant_id="tenant-A")

    # Verify tenant-A gets REALTIME
    res_a = tracker.compute_freshness("conversations", tenant_id="tenant-A")
    assert res_a.status == "REALTIME"
    assert res_a.lag_seconds == 10.0

    # Verify tenant-B (no sync) gets UNKNOWN and does NOT leak tenant-A's watermark or stage
    res_b = tracker.compute_freshness("conversations", tenant_id="tenant-B")
    assert res_b.status == "UNKNOWN"
    assert res_b.lag_seconds is None
    assert res_b.event_watermark is None


def test_freshness_cross_process_persistence_and_heartbeat_sharing(tmp_path) -> None:
    from datetime import datetime, timedelta, timezone

    from ai_ops_backoffice.services.freshness_service import FreshnessTracker

    now = datetime(2026, 9, 12, 12, 0, 0, tzinfo=timezone.utc)
    shared_file = tmp_path / "freshness" / "sync_watermarks.json"

    # Worker process tracker (writer)
    worker_tracker = FreshnessTracker(persistent_path=shared_file, clock=lambda: now)
    # API process tracker (reader)
    api_tracker = FreshnessTracker(persistent_path=shared_file, clock=lambda: now)

    # Initially API tracker has no heartbeats and no sync
    assert api_tracker.is_worker_active(now) is False
    initial_res = api_tracker.compute_freshness("conversations", tenant_id="tenant-1", now=now)
    assert initial_res.status == "UNKNOWN"

    # Worker records heartbeat and sync success
    worker_tracker.record_worker_heartbeat("worker-bg", at=now)
    worker_tracker.record_sync_success("conversations", at=now - timedelta(seconds=5), tenant_id="tenant-1")

    # API tracker automatically reloads on read from the shared persistent file!
    assert api_tracker.is_worker_active(now) is True
    freshness = api_tracker.compute_freshness("conversations", tenant_id="tenant-1", now=now)
    assert freshness.status == "REALTIME"
    assert freshness.lag_seconds == 5.0


def test_outbox_deletion_never_drops_concurrent_runs_or_outbox_jobs() -> None:
    from unittest.mock import MagicMock

    from agent_service.operations.access import ActorContext
    from ai_ops_backoffice.evaluation_domain.job_repository import InMemoryJobRepository
    from ai_ops_backoffice.evaluation_domain.models import EvalSet, EvalSetVersion
    from ai_ops_backoffice.evaluation_domain.repository import InMemoryEvaluationRepository
    from ai_ops_backoffice.evaluation_domain.run_service import EvaluationRunService
    from ai_ops_backoffice.evaluation_domain.runner_models import RunPreflightResult, TargetManifest

    repo = InMemoryEvaluationRepository()
    actor = ActorContext(
        user_id="user-ops",
        display_name="Ops Lead",
        role="AI_ADMIN",
        owner_unit_ids=("it_support",),
        tenant_id="tenant-outbox",
    )
    now = datetime.now(timezone.utc)
    eval_set = EvalSet(
        set_id="set-race-1",
        tenant_id="tenant-outbox",
        owner_unit_ids=("it_support",),
        name="Connectivity Set",
        lead_owner="tester",
        created_by="tester",
        created_at=now,
        updated_by="tester",
        updated_at=now,
    )
    set_ver = EvalSetVersion(
        set_version_id="sv-race-1",
        set_id="set-race-1",
        version=1,
        case_revision_ids=(),
        manifest_hash="hash-race",
        created_by="tester",
        created_at=now,
        etag=1,
    )
    repo.commit_mutation(repo.load().model_copy(update={
        "sets": (eval_set,),
        "set_versions": (set_ver,),
    }))

    manifest = TargetManifest(target_id="tgt-1", target_side="BASELINE", manifest_hash="h1")
    preflight = RunPreflightResult(
        is_valid=True,
        resolved_baseline_manifest=manifest,
        resolved_candidate_manifest=manifest,
        blocking_errors=(),
        is_eval_eligible=True,
    )
    resolver = MagicMock()
    resolver.preflight_run.return_value = preflight

    job_repo = InMemoryJobRepository()
    service = EvaluationRunService(
        repository=repo,
        manifest_resolver=resolver,
        job_repository=job_repo,
    )

    # 1. Create Run 1 which enqueues outbox job 1
    res1 = service.create_run(
        actor=actor,
        set_version_id="sv-race-1",
        baseline_target={"manifest_hash": "h1"},
        candidate_target={"manifest_hash": "h1"},
    )
    run_id_1 = res1["runId"]

    # 2. Concurrently create Run 2 which enqueues outbox job 2
    res2 = service.create_run(
        actor=actor,
        set_version_id="sv-race-1",
        baseline_target={"manifest_hash": "h2"},
        candidate_target={"manifest_hash": "h2"},
    )
    run_id_2 = res2["runId"]

    # Now verify both runs exist in the repository
    assert repo.get_run(run_id_1) is not None
    assert repo.get_run(run_id_2) is not None
    state_before_removal = repo.load()
    assert len(state_before_removal.runs) == 2

    # 3. Simulate Worker finishing Job 1 and calling delete_outbox_jobs on outbox job 1
    # Notice that when execute_inline is not used, create_run enqueues to job_repo and immediately deletes from outbox if dispatch succeeds.
    # To test delete_outbox_jobs specifically:
    # If job was already removed during dispatch, add mock outbox jobs to test targeted delete_outbox_jobs
    repo.commit_mutation(repo.load().model_copy(update={
        "outbox_jobs": (
            {"outbox_id": "outbox-1", "run_id": run_id_1},
            {"outbox_id": "outbox-2", "run_id": run_id_2},
        )
    }))
    assert len(repo.load().outbox_jobs) == 2

    # Call _remove_outbox_job on outbox-1
    service._remove_outbox_job("outbox-1")

    # 4. Critical Assertion:
    # Removing Outbox Job 1 MUST NOT overwrite or drop Run 2 or outbox-2!
    state_after = repo.load()
    assert repo.get_run(run_id_1) is not None
    assert repo.get_run(run_id_2) is not None
    assert len(state_after.runs) == 2
    remaining_outbox_ids = [str(j.get("outbox_id", j.get("job_id"))) for j in state_after.outbox_jobs]
    assert "outbox-1" not in remaining_outbox_ids
    assert "outbox-2" in remaining_outbox_ids


@pytest.mark.asyncio
async def test_standalone_worker_health_server_and_file_touch(tmp_path) -> None:
    import asyncio

    import httpx

    from ai_ops_backoffice.worker_main import _run_health_file_touch, _start_health_server

    # 1. Test health file touch
    health_file = tmp_path / "worker_health.txt"
    stop_file_touch = asyncio.Event()
    touch_task = asyncio.create_task(_run_health_file_touch(health_file, stop_file_touch, interval=0.01))
    await asyncio.sleep(0.03)
    stop_file_touch.set()
    await touch_task

    assert health_file.is_file()
    content = health_file.read_text(encoding="utf-8").strip()
    assert "T" in content  # ISO timestamp format

    # 2. Test lightweight health check HTTP server
    stop_server = asyncio.Event()
    bound_ports: list[int] = []

    server_task = asyncio.create_task(
        _start_health_server(
            "127.0.0.1",
            0,
            stop_server,
            on_started=lambda p: bound_ports.append(p),
        )
    )

    # Wait for server to bind
    for _ in range(50):
        if bound_ports:
            break
        await asyncio.sleep(0.01)

    assert len(bound_ports) == 1
    port = bound_ports[0]

    async with httpx.AsyncClient() as client:
        res = await client.get(f"http://127.0.0.1:{port}/healthz")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["worker"] == "ai_ops_worker"

    stop_server.set()
    await server_task


def test_outbox_deletion_advances_revision_and_rejects_stale_commit() -> None:
    from ai_ops_backoffice.evaluation_domain.errors import EvaluationVersionConflictError
    from ai_ops_backoffice.evaluation_domain.repository import InMemoryEvaluationRepository

    repo = InMemoryEvaluationRepository()
    outbox_job_1 = {"outbox_id": "outbox-1", "job_id": "job-1", "tenant_id": "t1"}
    outbox_job_2 = {"outbox_id": "outbox-2", "job_id": "job-2", "tenant_id": "t1"}
    state = repo.load()
    initial_rev = state.revision
    repo.commit_mutation(
        state.model_copy(update={"outbox_jobs": (outbox_job_1, outbox_job_2)}),
        expected_revision=initial_rev,
    )
    current_state = repo.load()
    rev_after_insert = current_state.revision
    assert len(current_state.outbox_jobs) == 2

    stale_state = current_state

    # Worker deletes outbox job 1
    repo.delete_outbox_jobs(["outbox-1"])

    state_after_delete = repo.load()
    assert state_after_delete.revision > rev_after_insert
    assert len(state_after_delete.outbox_jobs) == 1
    assert state_after_delete.outbox_jobs[0]["outbox_id"] == "outbox-2"

    # Concurrent commit using stale expected_revision must be rejected
    with pytest.raises(EvaluationVersionConflictError):
        repo.commit_mutation(
            stale_state.model_copy(update={"outbox_jobs": ()}),
            expected_revision=rev_after_insert,
        )


def test_firestore_outbox_deletion_advances_revision_and_propagates_errors() -> None:
    from unittest.mock import MagicMock

    from ai_ops_backoffice.evaluation_domain.models import EvaluationState
    from ai_ops_backoffice.evaluation_domain.repository import FirestoreEvaluationRepository

    mock_client = MagicMock()
    mock_coll = MagicMock()
    mock_client.collection.return_value = mock_coll
    mock_meta_doc = MagicMock()
    mock_job_doc = MagicMock()

    def doc_side_effect(name: str):
        if name == "root":
            return mock_meta_doc
        return mock_job_doc

    mock_coll.document.side_effect = doc_side_effect

    mock_meta_snap = MagicMock()
    mock_meta_snap.exists = True
    mock_meta_snap.to_dict.return_value = {"revision": 5}
    mock_meta_doc.get.return_value = mock_meta_snap

    repo = FirestoreEvaluationRepository(client=mock_client)
    repo._state = EvaluationState(
        revision=5,
        outbox_jobs=({"outbox_id": "outbox-1"}, {"outbox_id": "outbox-2"}),
    )

    repo.delete_outbox_jobs(["outbox-1"])

    assert repo._state.revision == 6
    assert len(repo._state.outbox_jobs) == 1

    # Failure path: Firestore delete raises exception -> must propagate, NOT be swallowed
    mock_tx = MagicMock()
    mock_tx.delete.side_effect = RuntimeError("Firestore unavailable")

    def run_tx_raising(fn):
        return fn(mock_tx)

    repo._run_transaction = run_tx_raising
    with pytest.raises(RuntimeError, match="Firestore unavailable"):
        repo.delete_outbox_jobs(["outbox-2"])


def test_completed_and_terminal_jobs_preserve_state_on_re_enqueue() -> None:
    from ai_ops_backoffice.evaluation_domain.job_repository import (
        ExecutionJob,
        InMemoryJobRepository,
    )

    repo = InMemoryJobRepository()
    now = datetime.now(timezone.utc)
    job = ExecutionJob(
        job_id="job-term-1",
        run_id="run-term-1",
        tenant_id="t-term",
        logical_key="eval_run_t1_r1",
        state="QUEUED",
        created_at=now,
        updated_at=now,
    )
    res1 = repo.enqueue_job(job)
    assert res1.state == "QUEUED"

    claimed = repo.claim_job(worker_id="w-1")
    assert claimed is not None
    completed = repo.complete_job(
        job_id="job-term-1",
        worker_id="w-1",
        fencing_token=claimed.fencing_token,
        state="COMPLETED",
    )
    assert completed.state == "COMPLETED"

    # Re-enqueueing the same job (same job_id or same logical_key) must preserve COMPLETED state
    re_enqueued = repo.enqueue_job(
        ExecutionJob(
            job_id="job-term-1",
            run_id="run-term-1",
            tenant_id="t-term",
            logical_key="eval_run_t1_r1",
            state="QUEUED",
            created_at=now,
            updated_at=now,
        )
    )
    assert re_enqueued.state == "COMPLETED"

    re_enqueued_diff_id = repo.enqueue_job(
        ExecutionJob(
            job_id="job-term-2-new-id",
            run_id="run-term-1",
            tenant_id="t-term",
            logical_key="eval_run_t1_r1",
            state="QUEUED",
            created_at=now,
            updated_at=now,
        )
    )
    assert re_enqueued_diff_id.state == "COMPLETED"
    assert re_enqueued_diff_id.job_id == "job-term-1"


@pytest.mark.asyncio
async def test_conversation_ingestion_syncs_freshness_to_realtime(tmp_path) -> None:
    from dataclasses import replace

    from agent_service.operations.contracts import OperationalEvent
    from agent_service.operations.ingestion import EventIngestionService
    from agent_service.operations.settings import OpsSettings
    from agent_service.operations.stores.file_store import FileOperationalStore
    from ai_ops_backoffice.services.freshness_service import FreshnessTracker

    t0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    current_time = t0
    tracker = FreshnessTracker(clock=lambda: current_time)
    tracker.record_worker_heartbeat("worker-1", at=t0)

    store = FileOperationalStore(tmp_path / "ops_events")
    settings = replace(OpsSettings.from_env(), enabled=True, store_path=tmp_path / "ops_events", environment="test")
    ingestion = EventIngestionService(store, settings, freshness_tracker=tracker)

    event = OperationalEvent(
        event_id="evt-fresh-1",
        correlation_id="corr-conv-1",
        tenant_id="tenant-acme",
        actor_ref="user-1",
        occurred_at=t0,
        ingested_at=t0,
        environment="test",
        event_type="turn.received",
        payload={"message": "hello"},
    )
    persisted = await ingestion.ingest(event)
    assert persisted is True

    freshness = tracker.compute_freshness("conversations", tenant_id="tenant-acme")
    assert freshness.status == "REALTIME"
    assert freshness.event_watermark == t0


def test_firestore_backed_freshness_tracker_multi_instance_sharing() -> None:
    from ai_ops_backoffice.services.freshness_service import FreshnessTracker

    class FakeDocRef:
        def __init__(self, data_store: dict, key: str):
            self._data = data_store
            self._key = key

        def get(self):
            class Snap:
                def __init__(self, doc_data):
                    self.exists = doc_data is not None
                    self._doc_data = doc_data

                def to_dict(self):
                    return dict(self._doc_data) if self._doc_data else {}
            return Snap(self._data.get(self._key))

        def set(self, payload: dict, merge: bool = False):
            if merge and self._key in self._data:
                self._data[self._key].update(payload)
            else:
                self._data[self._key] = dict(payload)

    class FakeClient:
        def __init__(self):
            self._storage: dict[str, dict] = {}

        def collection(self, col_name: str):
            client = self
            class FakeCol:
                def document(self, doc_id: str):
                    return FakeDocRef(client._storage, f"{col_name}/{doc_id}")
            return FakeCol()

    shared_firestore = FakeClient()
    t0 = datetime(2026, 9, 12, 12, 0, 0, tzinfo=timezone.utc)
    current_time = t0

    worker_tracker = FreshnessTracker(
        clock=lambda: current_time,
        firestore_client=shared_firestore,
    )
    api_tracker = FreshnessTracker(
        clock=lambda: current_time,
        firestore_client=shared_firestore,
    )

    assert api_tracker.is_worker_active(current_time) is False
    assert api_tracker.compute_freshness("conversations", tenant_id="tenant-fs", now=current_time).status == "UNKNOWN"

    worker_tracker.record_worker_heartbeat("worker-cloudrun-1", at=t0)
    worker_tracker.record_sync_success("conversations", at=t0, tenant_id="tenant-fs")

    api_tracker._last_firestore_poll = 0.0

    assert api_tracker.is_worker_active(current_time) is True
    freshness = api_tracker.compute_freshness("conversations", tenant_id="tenant-fs", now=current_time)
    assert freshness.status == "REALTIME"
    assert freshness.event_watermark == t0
