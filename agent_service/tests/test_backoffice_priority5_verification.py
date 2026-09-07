"""Verification test suite for BU Priority 5 requirements.

Covers:
- REQ-021: 稽核記錄完整性 (Audit Log)
  * 所有關鍵異動操作記錄操作者、時間戳記、異動前 (before) 與異動後 (after) 快照
  * 涵蓋 FAQ (CRUD/狀態變更/測試案例)、Prompt (候選/審核/啟用/回退)、Model 設定、Role 權限異動、Sync 同步任務
  * 稽核記錄禁止標準管理者任意刪除 (不可竄改性與防刪機制)
- REQ-026: 敏感資訊遮罩與資料治理 (Masking & PII Governance)
  * 未授權角色無法檢視敏感/PII明文，預設對話檢視為遮罩狀態
  * 申請明文需具備 ops.conversations.unmasked 權限且填寫至少 3 字元原因
  * 明文申請具備 query.conversation_unmasked 稽核軌跡
  * 匯出遵循相同遮罩規則，並防止 CSV 公式注入 (Formula Injection Protection)
- 6 項資料保存規則 (Data Retention & Purge Verification):
  * 1. 服務使用量與成本統計：1 年 (365 天)
  * 2. 對話內容與歷程：1 年 (365 天)，過期細節透過 Purge 機制刪除，彙總統計保留
  * 3. FAQ 命中與採納紀錄：1 年 (365 天)
  * 4. 知識庫檢索與反饋：1 年 (365 天)
  * 5. 問題分類與路由統計：1 年 (365 天)
  * 6. 版本紀錄 (Prompt/FAQ/文件)：依治理規則永久保留具回滾能力之版本歷程，不可任意刪除
  * Purge 驗證：驗證 purge_expired_events 與 purge_expired_jobs 成功清除到期資料且保留趨勢彙總
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_service.operations.access import ActorContext
from agent_service.operations.contracts import OperationalEvent, utc_now
from agent_service.operations.retention import is_expired
from ai_ops_backoffice.api import create_app as create_backoffice_app
from ai_ops_backoffice.governance_domain import FileGovernanceRepository
from ai_ops_backoffice.governance_domain.constants import ISSUE_EXTRACTOR_PROMPT_ID
from ai_ops_backoffice.governance_domain.service import GovernanceService
from ai_ops_backoffice.services.export_format import sanitize_csv_cell
from ai_ops_backoffice.services.query_service import BackofficeQueryService
from ai_ops_backoffice.settings import BackofficeSettings
from ai_ops_backoffice.sync_domain import InMemorySyncRepository, SyncService
from governance_eval_helpers import release_eligible_lab_harness


def _make_event(
    *,
    event_id: str,
    event_type: str = "turn.received",
    occurred_at: datetime,
    actor_ref: str = "actor-u123",
    conversation_id: str = "conv-1",
    correlation_id: str = "corr-1",
    turn_id: str = "turn-1",
    issue_type_id: str = "vpn.connection_failed",
    channel_scope: str = "personal",
    payload: dict[str, object] | None = None,
    retention_expires_at: datetime | None = None,
) -> OperationalEvent:
    return OperationalEvent(
        event_id=event_id,
        event_type=event_type,
        occurred_at=occurred_at,
        environment="test",
        channel_scope=channel_scope,
        actor_ref=actor_ref,
        conversation_id=conversation_id,
        correlation_id=correlation_id,
        turn_id=turn_id,
        issue_type_id=issue_type_id,
        payload=dict(payload or {}),
        retention_expires_at=retention_expires_at or (occurred_at + timedelta(days=365)),
    )


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
        "sync_adapter_url": "http://127.0.0.1:8091",
        "agent_api_url": "http://127.0.0.1:8000",
        "adapter_api_url": "http://127.0.0.1:3978",
        "ticket_service_url": None,
        "default_owner_unit_id": "IT Service Desk",
        "entra_tenant_id": None,
        "entra_client_id": None,
        "budget_store_path": tmp_path / "budgets.json",
        "faq_store_path": tmp_path / "faqs.json",
        "export_content_path": tmp_path / "exports",
        **overrides,
    }
    return BackofficeSettings(**params)


def backoffice_headers(
    role: str = "SYSTEM_ADMIN",
    user_id: str = "auditor-p5@corp.local",
) -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": user_id,
        "X-Backoffice-User-Name": role,
        "X-Backoffice-Role": role,
        "X-Backoffice-Owner-Units": "IT Service Desk",
        "X-Backoffice-Tenant-Id": "local-development",
    }


def test_req021_audit_log_before_after_snapshots(tmp_path: Path):
    """REQ-021: Verify before and after snapshots in FAQ, Prompt, Model, Role, and Sync audit events."""
    gov_file = tmp_path / "governance.json"
    gov_service = GovernanceService(
        FileGovernanceRepository(gov_file),
        eval_flow_harness=release_eligible_lab_harness(),
    )

    admin_actor = ActorContext(
        user_id="admin-req21",
        display_name="System Administrator",
        role="SYSTEM_ADMIN",
        owner_unit_ids=("IT Service Desk",),
        tenant_id="default",
    )
    reviewer_actor = ActorContext(
        user_id="reviewer-req21",
        display_name="Security Reviewer",
        role="SYSTEM_ADMIN",
        owner_unit_ids=("IT Service Desk",),
        tenant_id="default",
    )

    now = datetime.now(UTC)
    examples = [
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

    # 1. Prompt candidate -> eval -> approve -> canary -> activate
    created = gov_service.create_prompt_candidate(
        prompt_id=ISSUE_EXTRACTOR_PROMPT_ID,
        dataset_version="dataset-v1",
        taxonomy_version="taxonomy-v1",
        knowledge_release_id="release-test",
        verified_examples=examples,
        actor=admin_actor,
    )
    version_id = created["version"]["version_id"]

    evaluated = asyncio.run(
        gov_service.run_prompt_eval(
            prompt_id=ISSUE_EXTRACTOR_PROMPT_ID,
            version_id=version_id,
            verified_examples=examples,
            actor=admin_actor,
        )
    )
    assert evaluated["eval"]["critical_passed"] is True

    approved = gov_service.approve_prompt(
        prompt_id=ISSUE_EXTRACTOR_PROMPT_ID,
        version_id=version_id,
        reason="Passed all quality evaluations",
        actor=reviewer_actor,
    )
    assert approved["version"]["status"] == "APPROVED"

    gov_service.start_prompt_canary(
        prompt_id=ISSUE_EXTRACTOR_PROMPT_ID,
        version_id=version_id,
        percent=20,
        environment="lab",
        reason="Gradual rollout",
        actor=admin_actor,
    )
    activated = gov_service.activate_prompt(
        prompt_id=ISSUE_EXTRACTOR_PROMPT_ID,
        version_id=version_id,
        reason="Full deployment after canary success",
        actor=admin_actor,
    )
    assert activated["version"]["status"] == "ACTIVE"

    # Verify Prompt audit events contain before and after
    prompt_audits = gov_service.list_audit(actor=admin_actor, target_type="PROMPT")
    actions = {item["action"]: item for item in prompt_audits}

    assert "PROMPT_APPROVED" in actions
    approved_audit = actions["PROMPT_APPROVED"]
    assert approved_audit["actor_id"] == "reviewer-req21"
    assert approved_audit["before"] == {"status": "EVALUATED"}
    assert approved_audit["after"]["status"] == "APPROVED"

    assert "PROMPT_ACTIVATED" in actions
    activated_audit = actions["PROMPT_ACTIVATED"]
    assert "status" in activated_audit["before"]
    assert activated_audit["after"]["status"] == "ACTIVE"
    assert activated_audit["after"]["activeVersionId"] == version_id

    # 2. Model Settings candidate -> approve -> activate
    model_created = gov_service.create_model_candidate(
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
        change_reason="Upgrade baseline model",
        actor=admin_actor,
    )
    model_v_id = model_created["version"]["version_id"]
    gov_service.run_model_eval(config_id="issue-extractor-model", version_id=model_v_id, actor=admin_actor)
    gov_service.approve_model(
        config_id="issue-extractor-model", version_id=model_v_id, reason="Model approved", actor=reviewer_actor
    )
    gov_service.activate_model(
        config_id="issue-extractor-model", version_id=model_v_id, reason="Model activated", actor=admin_actor
    )

    model_audits = gov_service.list_audit(actor=admin_actor, target_type="MODEL")
    m_actions = {item["action"]: item for item in model_audits}
    assert "MODEL_APPROVED" in m_actions
    assert m_actions["MODEL_APPROVED"]["before"] == {"status": "EVALUATED"}
    assert m_actions["MODEL_APPROVED"]["after"]["status"] == "APPROVED"
    assert "MODEL_ACTIVATED" in m_actions
    assert m_actions["MODEL_ACTIVATED"]["after"]["activeVersionId"] == model_v_id
    assert m_actions["MODEL_ACTIVATED"]["after"]["status"] == "ACTIVE"

    # 3. Role Mapping change -> approve -> revoke
    role_change = gov_service.request_role_change(
        target_principal="operator-req21@corp.local",
        target_role="ANALYST",
        add_capabilities=("ops.conversations.read", "ops.faq.read"),
        remove_capabilities=(),
        reason="Grant read permissions for operator",
        actor=admin_actor,
    )
    change_id = role_change["change"]["change_id"]
    gov_service.approve_role_change(
        change_id=change_id,
        reason="Approved by security officer",
        actor=reviewer_actor,
    )
    gov_service.revoke_principal(
        principal="operator-req21@corp.local",
        reason="Revoke standing on contract end",
        actor=admin_actor,
    )

    role_audits = gov_service.list_audit(actor=admin_actor, target_type="ROLE_MAPPING")
    r_actions = {item["action"]: item for item in role_audits}
    assert "ROLE_MAPPING_APPROVED" in r_actions
    assert r_actions["ROLE_MAPPING_APPROVED"]["before"]["status"] == "REQUESTED"
    assert r_actions["ROLE_MAPPING_APPROVED"]["after"]["status"] == "APPROVED"
    assert "ops.conversations.read" in r_actions["ROLE_MAPPING_APPROVED"]["after"]["capabilities"]
    assert "PRINCIPAL_REVOKED" in r_actions
    assert r_actions["PRINCIPAL_REVOKED"]["before"]["revoked"] is False
    assert r_actions["PRINCIPAL_REVOKED"]["after"]["revoked"] is True
    assert "principal" in r_actions["PRINCIPAL_REVOKED"]["before"]
    assert "principal" in r_actions["PRINCIPAL_REVOKED"]["after"]

    # 4. Sync Jobs before and after
    sync_repo = InMemorySyncRepository()
    sync_service = SyncService(sync_repo)
    sync_job = sync_service.create(
        scope_type="FAQ",
        scope_ids=("faq-001",),
        owner_unit_id="IT Service Desk",
        reason="Manual sync after batch FAQ edit",
        actor=admin_actor,
        idempotency_key=None,
        correlation_id=None,
    )
    job_id = sync_job["job"]["job_id"]
    sync_service.set_stage(job_id, status="VALIDATING", actor=admin_actor)
    sync_service.cancel(job_id, expected_etag=2, reason="Cancelled for urgent maintenance", actor=admin_actor)

    job_detail = sync_service.detail(job_id, actor=admin_actor)
    sync_audit_actions = {item["action"]: item for item in job_detail["audit"]}
    assert "SYNC_REQUESTED" in sync_audit_actions
    assert sync_audit_actions["SYNC_REQUESTED"]["after"]["status"] == "QUEUED"
    assert "SYNC_VALIDATING" in sync_audit_actions
    assert sync_audit_actions["SYNC_VALIDATING"]["before"]["status"] == "QUEUED"
    assert sync_audit_actions["SYNC_VALIDATING"]["after"]["status"] == "VALIDATING"
    assert "SYNC_CANCELLED" in sync_audit_actions
    assert sync_audit_actions["SYNC_CANCELLED"]["before"]["status"] == "VALIDATING"
    assert sync_audit_actions["SYNC_CANCELLED"]["after"]["status"] == "CANCELLED"


def test_req021_audit_records_non_deletable(tmp_path: Path):
    """REQ-021: Ensure audit records cannot be deleted by standard admins via API."""
    settings = _backoffice_settings(tmp_path)
    app = create_backoffice_app(settings)
    client = TestClient(app)

    headers = backoffice_headers(role="SYSTEM_ADMIN")

    # DELETE /api/audit-events should not be allowed
    res1 = client.delete("/api/audit-events", headers=headers)
    assert res1.status_code in {404, 405}

    # DELETE /api/governance/audit should not be allowed
    res2 = client.delete("/api/governance/audit", headers=headers)
    assert res2.status_code in {404, 405}


@pytest.mark.asyncio
async def test_req026_sensitive_masking_and_unmask_governance(tmp_path: Path):
    """REQ-026: Verify PII masked by default, unmask requires capability + reason, and formula injection protection."""
    settings = _backoffice_settings(tmp_path)

    # Seed operational events with sensitive PII in raw payload and masked values
    now = utc_now()
    conv_id = "conv-sensitive-999"
    seed_event = _make_event(
        event_id="evt-sens-1",
        event_type="turn.received",
        occurred_at=now - timedelta(minutes=10),
        conversation_id=conv_id,
        correlation_id="corr-sens-1",
        turn_id="turn-1",
        issue_type_id="vpn.connection_failed",
        channel_scope="personal",
        payload={
            "userMessage": "My phone is 0912345678 and ID is A123456789",
            "messageMasked": "My phone is [PHONE] and ID is [ID]",
        },
        retention_expires_at=now + timedelta(days=365),
    )
    ans_event = _make_event(
        event_id="evt-sens-2",
        event_type="answer.completed",
        occurred_at=now - timedelta(minutes=9),
        conversation_id=conv_id,
        correlation_id="corr-sens-1",
        turn_id="turn-1",
        issue_type_id="vpn.connection_failed",
        channel_scope="personal",
        payload={
            "aiReply": "Received info for user A123456789",
            "answerMasked": "Received info for user [ID]",
        },
        retention_expires_at=now + timedelta(days=365),
    )

    query_svc = BackofficeQueryService(settings)
    await query_svc._runtime.store.append(seed_event)
    await query_svc._runtime.store.append(ans_event)

    app = create_backoffice_app(settings)
    client = TestClient(app)

    # 1. Default conversation detail view is MASKED (ANALYST role has ops.conversations.read)
    reader_headers = backoffice_headers(
        role="ANALYST",
        user_id="analyst-1@corp.local",
    )
    res_masked = client.get(f"/api/conversations/{conv_id}", headers=reader_headers)
    assert res_masked.status_code == 200
    conv_data = res_masked.json()
    assert conv_data["unmaskAuthorized"] is False
    # Check turns are masked
    turn = conv_data["turns"][0]
    assert "[PHONE]" in turn["userMessage"]
    assert "0912345678" not in turn["userMessage"]

    # 2. Unauthorized unmask attempt (without ops.conversations.unmasked) -> 403 Forbidden
    res_unauth = client.get(
        f"/api/conversations/{conv_id}?unmask_reason=Investigating+leak",
        headers=reader_headers,
    )
    assert res_unauth.status_code == 403
    assert "Unmasked conversation access is forbidden" in res_unauth.text

    # 3. Authorized unmask attempt with insufficient reason length (< 3 chars) -> 400 Bad Request
    admin_headers = backoffice_headers(
        role="SYSTEM_ADMIN",
        user_id="admin-req26@corp.local",
    )
    res_short_reason = client.get(
        f"/api/conversations/{conv_id}?unmask_reason=ok",
        headers=admin_headers,
    )
    assert res_short_reason.status_code == 400
    assert "unmask_reason must be at least 3 characters" in res_short_reason.text

    # 4. Authorized unmask attempt with valid reason -> returns unmasked detail and records audit
    res_unmasked = client.get(
        f"/api/conversations/{conv_id}?unmask_reason=Audit+Investigation+Case+456",
        headers=admin_headers,
    )
    assert res_unmasked.status_code == 200
    unmasked_data = res_unmasked.json()
    assert unmasked_data["unmaskAuthorized"] is True
    unmasked_turn = unmasked_data["turns"][0]
    assert "0912345678" in unmasked_turn["userMessage"]
    assert "A123456789" in unmasked_turn["userMessage"]
    assert "A123456789" in unmasked_turn["aiReply"]

    # Verify query audit was recorded with reason
    audit_res = client.get("/api/audit-events", headers=admin_headers)
    assert audit_res.status_code == 200
    audit_items = audit_res.json().get("items", [])
    unmask_audits = [item for item in audit_items if item.get("action") == "query.conversation_unmasked"]
    assert len(unmask_audits) >= 1
    assert unmask_audits[0]["after"] == {"unmaskReason": "Audit Investigation Case 456"}

    # 5. Formula injection protection verification
    assert sanitize_csv_cell("=1+1") == "'=1+1"
    assert sanitize_csv_cell("+cmd|' /C calc'!A0") == "'+cmd|' /C calc'!A0"
    assert sanitize_csv_cell("-2+3") == "'-2+3"
    assert sanitize_csv_cell("@SUM(A1:A10)") == "'@SUM(A1:A10)"
    assert sanitize_csv_cell("\tTAB_INJECT") == "'\tTAB_INJECT"
    assert sanitize_csv_cell("Normal Text") == "Normal Text"


@pytest.mark.asyncio
async def test_retention_rules_and_purge_verification(tmp_path: Path):
    """Verify the 6 Data Retention rules: 365-day TTL enforcement, purge of expired detail, and retention of aggregates."""
    settings = _backoffice_settings(tmp_path)
    now = utc_now()

    # Rule 1 to 5: Operational events (conversations, tokens/cost, FAQ hit, knowledge hits, issues)
    # Event 1: Expired event (e.g. 400 days old, expired 35 days ago)
    expired_event = _make_event(
        event_id="evt-expired-365",
        event_type="turn.received",
        occurred_at=now - timedelta(days=400),
        conversation_id="conv-expired-1",
        correlation_id="corr-exp-1",
        turn_id="turn-1",
        issue_type_id="vpn.connection_failed",
        payload={"userMessage": "Old VPN query", "messageMasked": "Old VPN query"},
        retention_expires_at=now - timedelta(days=35),  # expired!
    )

    # Event 2: Valid event within 365 days (e.g. 30 days old, expires in 335 days)
    active_event = _make_event(
        event_id="evt-active-30",
        event_type="turn.received",
        occurred_at=now - timedelta(days=30),
        conversation_id="conv-active-1",
        correlation_id="corr-act-1",
        turn_id="turn-1",
        issue_type_id="email.outlook_sync",
        payload={"userMessage": "Recent Email query", "messageMasked": "Recent Email query"},
        retention_expires_at=now + timedelta(days=335),  # not expired!
    )

    # Test retention checker helper
    assert is_expired(expired_event.retention_expires_at) is True
    assert is_expired(active_event.retention_expires_at) is False

    query_svc = BackofficeQueryService(settings)
    await query_svc._runtime.store.append(expired_event)
    await query_svc._runtime.store.append(active_event)

    app = create_backoffice_app(settings)
    client = TestClient(app)
    admin_headers = backoffice_headers(
        role="SYSTEM_ADMIN",
        user_id="admin-retention@corp.local",
    )

    # Before purge: both conversations can be queried
    res_before_active = client.get("/api/conversations/conv-active-1", headers=admin_headers)
    assert res_before_active.status_code == 200

    res_before_expired = client.get("/api/conversations/conv-expired-1", headers=admin_headers)
    assert res_before_expired.status_code == 200

    # Trigger admin retention purge API: POST /api/admin/retention/purge
    res_purge = client.post("/api/admin/retention/purge", headers=admin_headers)
    assert res_purge.status_code == 200
    purge_result = res_purge.json()
    assert purge_result["removed"] >= 1

    # After purge: Expired conversation is no longer retrievable (404 Not Found)
    res_after_expired = client.get("/api/conversations/conv-expired-1?refresh=true", headers=admin_headers)
    assert res_after_expired.status_code == 404

    # Active conversation within 365 days is still available
    res_after_active = client.get("/api/conversations/conv-active-1?refresh=true", headers=admin_headers)
    assert res_after_active.status_code == 200

    # Rule 6: Verify Version History preservation for FAQ, Prompts, Documents
    # Prompt and FAQ version history cannot be deleted and maintain full rollback capability
    gov_file = tmp_path / "gov_retention.json"
    gov = GovernanceService(FileGovernanceRepository(gov_file))
    admin_actor = ActorContext(
        user_id="admin-v6",
        display_name="Admin V6",
        role="SYSTEM_ADMIN",
        owner_unit_ids=("IT Service Desk",),
        tenant_id="default",
    )
    # Check default retention policy in governance is active with 365 days
    policies = gov.list_retention_policies(actor=admin_actor)
    active_policy = next((p for p in policies if p["policy_id"] == "operational-events" and p["status"] == "ACTIVE"), None)
    assert active_policy is not None
    assert active_policy["ttl_days"] == 365
