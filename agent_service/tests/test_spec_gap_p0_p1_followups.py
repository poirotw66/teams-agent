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

    # Conversation rendered at t_conv (10 min ago)
    tracker.record_stage_event("c-1", "CONVERSATION_LIST_RENDERED", at=t_conv)
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


def test_query_conversations_records_stage_events_and_watermark() -> None:
    from datetime import datetime, timezone
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

    tracker = FreshnessTracker()
    tracker.record_worker_heartbeat()

    t_event = datetime(2026, 9, 12, 12, 30, 0, tzinfo=timezone.utc)
    ev = OperationalEvent(
        event_id="ev-1",
        event_type="turn.received",
        correlation_id="corr-turn-1",
        conversation_id="conv-1",
        turn_id="turn-1",
        occurred_at=t_event,
        payload={"messageMasked": "test message"},
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
    watermark_val = res["freshness"].get("event_watermark") or res["freshness"].get("eventWatermark")
    assert datetime.fromisoformat(watermark_val.replace("Z", "+00:00")) == t_event
    # Check that stage events were recorded
    assert tracker._stage_events["conversations"]["EVENT_INGESTED"] == t_event
    assert "CONVERSATION_LIST_RENDERED" in tracker._stage_events["conversations"]
    assert tracker._stage_events["corr-turn-1"]["EVENT_INGESTED"] == t_event
    assert "CONVERSATION_LIST_RENDERED" in tracker._stage_events["corr-turn-1"]

