from __future__ import annotations

import asyncio
from pathlib import Path

from agent_service.operations.audit import build_audit_event
from agent_service.operations.contracts import OperationalEvent, utc_now
from agent_service.operations.ingestion import EventIngestionService
from agent_service.operations.masking import mask_text, redact_secrets
from agent_service.operations.settings import OpsSettings
from agent_service.operations.stores.memory_store import MemoryOperationalStore

_SYNTHETIC_SECRET = "synthetic-review-only-932"


def _settings() -> OpsSettings:
    return OpsSettings(
        enabled=True,
        store_mode="MEMORY",
        store_path=Path("/tmp/ops-privacy-boundary-unused"),
        taxonomy_path=Path("/tmp/ops-privacy-boundary-unused"),
        metrics_path=Path("/tmp/ops-privacy-boundary-unused"),
        environment="test",
        default_retention_days=365,
        transcript_retention_days=365,
        audit_retention_days=1095,
        async_emit=True,
        classification_rules_path=Path("/tmp/ops-privacy-boundary-unused"),
        firestore_project=None,
        firestore_database=None,
        firestore_collection="operational_events",
        bigquery_enabled=False,
        bigquery_project=None,
        bigquery_dataset="ai_ops_analytics",
        bigquery_table="operational_events",
        audit_store_mode="MEMORY",
        audit_firestore_collection="audit_events",
    )


def test_ingestion_removes_credentials_from_nested_serialized_event() -> None:
    store = MemoryOperationalStore()
    ingestion = EventIngestionService(store, _settings())
    event = OperationalEvent(
        event_id="privacy-event-1",
        event_type="issue.classified",
        occurred_at=utc_now(),
        correlation_id="privacy-correlation-1",
        payload={
            "changes": [
                {
                    "secret": _SYNTHETIC_SECRET,
                    "nested": {
                        "API_KEY": _SYNTHETIC_SECRET,
                        "normalizedDescription": f"VPN password={_SYNTHETIC_SECRET}",
                    },
                },
                {
                    "fallback": "upstream error: token=" + _SYNTHETIC_SECRET,
                    "tuple": (
                        {"accessToken": _SYNTHETIC_SECRET},
                        "OTP=" + _SYNTHETIC_SECRET,
                    ),
                },
            ],
            "totalTokens": 31,
            "inputTokens": 13,
            "outputTokens": 18,
            "toolContextTokens": 5,
            "cachedInputTokens": 3,
            "reasoningTokens": 7,
            "usageSource": "provider-reported",
        },
    )

    async def run() -> OperationalEvent:
        assert await ingestion.ingest(event) is True
        persisted, _ = await store.list_events(limit=10)
        return persisted[0]

    persisted_event = asyncio.run(run())
    serialized = persisted_event.model_dump_json()
    assert _SYNTHETIC_SECRET not in serialized
    assert persisted_event.payload["totalTokens"] == 31
    assert persisted_event.payload["inputTokens"] == 13
    assert persisted_event.payload["outputTokens"] == 18
    assert persisted_event.payload["toolContextTokens"] == 5
    assert persisted_event.payload["cachedInputTokens"] == 3
    assert persisted_event.payload["reasoningTokens"] == 7
    assert persisted_event.payload["usageSource"] == "provider-reported"
    assert persisted_event.payload["changes"][0]["secret"] == "[REDACTED_CREDENTIAL]"  # type: ignore[index]
    assert persisted_event.masking_policy_version == "v2"
    assert persisted_event.payload["maskingPolicyVersion"] == "v2"


def test_redaction_is_stable_and_preserves_non_sensitive_data() -> None:
    payload = {
        "message": "VPN connection timed out",
        "details": [{"code": "NETWORK_UNREACHABLE"}, ("retry", 2)],
        "totalTokens": 42,
        "inputTokens": 10,
        "outputTokens": 32,
        "toolContextTokens": 4,
        "cachedInputTokens": 2,
        "reasoningTokens": 6,
        "usageSource": "estimated",
    }
    once = redact_secrets(payload)

    assert once == payload
    assert redact_secrets(once) == once


def test_metrics_clean_string_credentials_without_distorting_metadata_identifiers() -> None:
    redacted = redact_secrets(
        {
            "totalTokens": f"password={_SYNTHETIC_SECRET}",
            "toolContextTokens": 12,
            "cachedInputTokens": 4,
            "reasoningTokens": 8,
            "usageSource": "provider-tokenized",
            "pricingVersion": "max_tokens-v1",
            "sourceId": "tokenized-source-42",
            "model": "max_tokens",
            "resultToken": "COST_ESTIMATE",
        }
    )

    assert redacted["totalTokens"] == "[REDACTED_CREDENTIAL]"
    assert redacted["toolContextTokens"] == 12
    assert redacted["cachedInputTokens"] == 4
    assert redacted["reasoningTokens"] == 8
    assert redacted["usageSource"] == "provider-tokenized"
    assert redacted["pricingVersion"] == "max_tokens-v1"
    assert redacted["sourceId"] == "tokenized-source-42"
    assert redacted["model"] == "max_tokens"
    assert redacted["resultToken"] == "COST_ESTIMATE"


def test_reveal_can_show_authorized_pii_but_never_a_detected_credential() -> None:
    assert mask_text("user@example.test", reveal=True).text == "user@example.test"
    credential = mask_text(f"VPN password={_SYNTHETIC_SECRET}", reveal=True)

    assert credential.text == "[REDACTED_CREDENTIAL]"
    assert credential.contains_credential is True


def test_free_text_password_help_is_preserved_but_assigned_credential_is_not() -> None:
    help_text = (
        "請確認 VPN 密碼未鎖定後再試一次。password reset 步驟請依知識庫操作。"
        "我的密碼是什麼？"
    )

    assert mask_text(help_text).text == help_text
    assert redact_secrets({"answerMasked": help_text}) == {"answerMasked": help_text}
    for instruction in ("password reset", "password recovery steps", "How to change password?"):
        assert mask_text(instruction).text == instruction
    assert (
        mask_text(f"VPN password={_SYNTHETIC_SECRET}").text
        == "[REDACTED_CREDENTIAL]"
    )


def test_common_explicit_credential_value_formats_are_removed() -> None:
    credential_texts = (
        f"我的密碼是 {_SYNTHETIC_SECRET}",
        f"password is {_SYNTHETIC_SECRET}",
        f"password {_SYNTHETIC_SECRET}",
        "password SENSITIVE_MARKER",
        "password abc123",
        'password "syntheticvalue"',
        "OTP 123456",
        "verification code 123456",
        "OTP=" + _SYNTHETIC_SECRET,
        "驗證碼為 123456",
        '{"password":"' + _SYNTHETIC_SECRET + '"}',
    )

    for text in credential_texts:
        masked = mask_text(text)
        assert masked.text == "[REDACTED_CREDENTIAL]"
        assert masked.contains_credential is True
        assert _SYNTHETIC_SECRET not in masked.text
        assert mask_text(text, reveal=True).text == masked.text


def test_ingestion_marks_new_policy_and_preserves_legacy_source_policy() -> None:
    store = MemoryOperationalStore()
    ingestion = EventIngestionService(store, _settings())
    legacy_event = OperationalEvent(
        event_id="privacy-legacy-policy",
        event_type="turn.received",
        occurred_at=utc_now(),
        correlation_id="privacy-legacy-correlation",
        masking_policy_version="v1",
        payload={"maskingPolicyVersion": "v1", "messageMasked": "password reset"},
    )

    async def run() -> OperationalEvent:
        assert await ingestion.ingest(legacy_event) is True
        persisted, _ = await store.list_events(limit=10)
        return persisted[0]

    persisted_event = asyncio.run(run())
    assert persisted_event.masking_policy_version == "v2"
    assert persisted_event.payload["maskingPolicyVersion"] == "v2"
    assert persisted_event.payload["sourceMaskingPolicyVersion"] == "v1"
    assert legacy_event.masking_policy_version == "v1"
    assert legacy_event.payload["maskingPolicyVersion"] == "v1"


def test_audit_redacts_nested_before_after_reason_and_error_text() -> None:
    audit = build_audit_event(
        actor_id="auditor.demo",
        actor_role="AUDITOR",
        action="config.changed",
        target_type="config",
        target_id="model-policy-v1",
        before={"changes": [{"Secret": _SYNTHETIC_SECRET}]},
        after={
            "changes": [
                {
                    "nested": {"credential": _SYNTHETIC_SECRET},
                    "error": f"fallback failed: api key={_SYNTHETIC_SECRET}",
                }
            ]
        },
        reason=f"VPN password={_SYNTHETIC_SECRET}",
        result="FAILED",
    )

    serialized = audit.model_dump_json()
    assert _SYNTHETIC_SECRET not in serialized
    assert audit.actor_id == "auditor.demo"
    assert audit.target_id == "model-policy-v1"
    assert audit.reason == "[REDACTED_CREDENTIAL]"
    assert audit.before == {"changes": [{"Secret": "[REDACTED_CREDENTIAL]"}]}
