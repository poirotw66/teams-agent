from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_service.extractor import SYSTEM_PROMPT, IssueExtractor
from agent_service.prompt_runtime import ExtractorPromptRuntime, GovernanceRuntime
from agent_service.settings import RagSettings
from agent_service.operations.access import ActorContext
from ai_ops_backoffice.governance_domain import FileGovernanceRepository, GovernanceService
from ai_ops_backoffice.governance_domain.constants import ISSUE_EXTRACTOR_PROMPT_ID
from ai_ops_backoffice.governance_domain.helpers import content_hash


AI = ActorContext("ai-admin", "AI Admin", "AI_ADMIN", ())
APPROVER = ActorContext("approver", "Approver", "AI_ADMIN", ())


def _gov(tmp_path: Path) -> GovernanceService:
    from governance_eval_helpers import release_eligible_lab_harness

    return GovernanceService(
        FileGovernanceRepository(tmp_path / "governance.json"),
        eval_flow_harness=release_eligible_lab_harness(),
    )


def _examples(now: datetime) -> list[dict]:
    return [
        {
            "status": "VERIFIED",
            "dataset_version": "dataset-v1",
            "created_at": now.isoformat(),
            "text": "VPN 無法連線",
            "expected_route": "KNOWLEDGE",
            "label": "POSITIVE",
        },
        {
            "status": "VERIFIED",
            "dataset_version": "dataset-v1",
            "created_at": now.isoformat(),
            "text": "Outlook 寄信失敗",
            "expected_route": "KNOWLEDGE",
            "label": "POSITIVE",
        },
        {
            "status": "VERIFIED",
            "dataset_version": "dataset-v1",
            "created_at": now.isoformat(),
            "text": "今天天氣如何",
            "expected_route": "NON_IT",
            "label": "NEGATIVE",
        },
    ]


def _settings(tmp_path: Path, **overrides) -> RagSettings:
    values = {
        "data_dir": tmp_path,
        "index_path": tmp_path / "index.json",
        "prompt_runtime_mode": "GOVERNED",
        "prompt_governance_store_path": tmp_path / "governance.json",
        "ticket_service_mode": "HTTP",
        "ticket_service_base_url": "http://127.0.0.1:9",
        "feedback_enabled": True,
    }
    values.update(overrides)
    return RagSettings(**values)


def test_code_baseline_mode_ignores_governance(tmp_path: Path) -> None:
    runtime = ExtractorPromptRuntime.from_settings(
        _settings(tmp_path, prompt_runtime_mode="CODE_BASELINE")
    )
    resolved = runtime.resolve(tenant_id="t1", conversation_id="c1")
    assert resolved.source == "code_baseline"
    assert resolved.template == SYSTEM_PROMPT
    assert resolved.content_hash == content_hash(SYSTEM_PROMPT)


def test_governed_mode_falls_back_when_store_empty(tmp_path: Path) -> None:
    runtime = ExtractorPromptRuntime.from_settings(_settings(tmp_path))
    resolved = runtime.resolve(tenant_id="t1", conversation_id="c1")
    assert resolved.source == "code_baseline"
    assert resolved.template == SYSTEM_PROMPT


def test_governed_mode_uses_active_pointer(tmp_path: Path) -> None:
    svc = _gov(tmp_path)
    active = svc.list_prompts(actor=AI)[0]["active"]
    runtime = ExtractorPromptRuntime.from_settings(_settings(tmp_path))
    resolved = runtime.resolve(tenant_id="tenant-a", conversation_id="conv-1")
    assert resolved.source == "governance"
    assert resolved.version_id == active["version_id"]
    assert resolved.template == SYSTEM_PROMPT
    assert resolved.canary is False


def test_peek_runtime_prompt_selects_canary_by_sticky_bucket(tmp_path: Path) -> None:
    svc = _gov(tmp_path)
    baseline = svc.list_prompts(actor=AI)[0]["active"]["version_id"]
    now = datetime.now(UTC)
    examples = _examples(now)
    created = svc.create_prompt_candidate(
        prompt_id=ISSUE_EXTRACTOR_PROMPT_ID,
        dataset_version="dataset-v1",
        taxonomy_version="taxonomy-v1",
        knowledge_release_id=None,
        verified_examples=examples,
        actor=AI,
    )
    version_id = created["version"]["version_id"]
    svc.run_prompt_eval(
        prompt_id=ISSUE_EXTRACTOR_PROMPT_ID,
        version_id=version_id,
        verified_examples=examples,
        actor=AI,
    )
    svc.approve_prompt(
        prompt_id=ISSUE_EXTRACTOR_PROMPT_ID,
        version_id=version_id,
        reason="approve",
        actor=APPROVER,
    )
    svc.start_prompt_canary(
        prompt_id=ISSUE_EXTRACTOR_PROMPT_ID,
        version_id=version_id,
        percent=99,
        environment="lab",
        reason="canary",
        actor=APPROVER,
    )
    canary_hit = svc.peek_runtime_prompt(
        ISSUE_EXTRACTOR_PROMPT_ID, tenant="tenant", conversation_id="almost-always-canary"
    )
    assert canary_hit is not None
    assert canary_hit["canary"] is True
    assert canary_hit["versionId"] == version_id
    # Force an out-of-bucket conversation by scanning sticky buckets.
    selected_active = None
    for index in range(300):
        peeked = svc.peek_runtime_prompt(
            ISSUE_EXTRACTOR_PROMPT_ID,
            tenant="tenant",
            conversation_id=f"conv-{index}",
        )
        assert peeked is not None
        if not peeked["canary"]:
            selected_active = peeked
            break
    assert selected_active is not None
    assert selected_active["versionId"] == baseline


@pytest.mark.asyncio
async def test_extractor_uses_resolved_prompt_template(tmp_path: Path) -> None:
    class _Handle:
        def __init__(self, calls: list) -> None:
            self.calls = calls

        async def ainvoke(self, messages):
            self.calls.append(messages)
            from agent_service.contracts import Issue, IssueExtraction

            return IssueExtraction(
                issues=[
                    Issue(
                        id=1,
                        description="VPN",
                        isIT=True,
                        readiness="READY",
                        missingInfo=[],
                        route="KNOWLEDGE",
                        faqKey=None,
                        ticketAction=None,
                    )
                ]
            )

    class _Model:
        def __init__(self) -> None:
            self.calls: list = []

        def with_structured_output(self, _schema):
            return _Handle(self.calls)

    class _Runtime:
        def resolve(self, *, tenant_id, conversation_id):
            from agent_service.prompt_runtime import ResolvedExtractorPrompt

            return ResolvedExtractorPrompt(
                template="CUSTOM PROMPT {max_issues} keys={faq_keys}",
                source="governance",
                version_id="v-test",
                version="abc123",
                content_hash="hash",
                canary=False,
            )

    model = _Model()
    extractor = IssueExtractor(
        _settings(tmp_path, prompt_runtime_mode="CODE_BASELINE"),
        model,
        prompt_runtime=_Runtime(),
    )
    outcome = await extractor.extract(
        text="VPN",
        history=[],
        faq_keys=["VPN_FAQ"],
        conversation_id="c1",
        tenant_id="t1",
    )
    assert outcome.prompt_source == "governance"
    assert outcome.prompt_version_id == "v-test"
    system_message = model.calls[0][0].content
    assert "CUSTOM PROMPT 3 keys=VPN_FAQ" == system_message


def test_governance_runtime_flags_and_model_fail_safe(tmp_path: Path) -> None:
    store = tmp_path / "governance.json"
    svc = GovernanceService(FileGovernanceRepository(store))
    svc.list_flags(actor=AI)
    runtime = GovernanceRuntime.from_settings(
        _settings(tmp_path, prompt_governance_store_path=store)
    )
    assert runtime.ticket_enabled() is True
    assert runtime.handoff_enabled() is True
    assert runtime.feedback_enabled() is True
    assert runtime.cost_display_enabled() is True
    model = runtime.resolve_model()
    assert model.source in {"governance", "settings_baseline"}

    created = svc.create_flag_candidate(
        flag_id="ticket_mode",
        value="DISABLED",
        environment="lab",
        expires_at=None,
        reason="disable tickets",
        actor=AI,
    )
    version_id = created["version"]["version_id"]
    svc.approve_flag(
        flag_id="ticket_mode", version_id=version_id, reason="approve", actor=APPROVER
    )
    svc.activate_flag(
        flag_id="ticket_mode", version_id=version_id, reason="activate", actor=APPROVER
    )
    assert runtime.ticket_enabled() is False

    code_runtime = GovernanceRuntime.from_settings(
        _settings(tmp_path, prompt_runtime_mode="CODE_BASELINE")
    )
    assert code_runtime.ticket_enabled() is True
    assert code_runtime.resolve_prompt(tenant_id="t", conversation_id="c").source == "code_baseline"
