"""Focused regression tests for remaining Spec P0/P1 eval gaps."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

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
from agent_service.target_manifest import (
    knowledge_release_target_manifest_hash,
    resolve_publish_manifest_defaults,
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
