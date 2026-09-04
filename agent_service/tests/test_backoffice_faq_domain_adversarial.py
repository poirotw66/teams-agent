from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from pydantic import ValidationError
from test_backoffice_faq_domain import (
    ActiveTaxonomy,
    AllowFaqAuthority,
    FakeFirestoreClient,
    add_required_tests,
    approve,
    content,
    run_fake_transaction,
    service,
)

from agent_service.operations.access import ActorContext
from agent_service.operations.masking import MASKING_POLICY_VERSION
from ai_ops_backoffice.faq_domain import (
    FaqAuthorizationError,
    FaqDomainService,
    FaqIdempotencyConflictError,
    FaqVersionConflictError,
    FileFaqRepository,
    FirestoreFaqRepository,
    InMemoryFaqRepository,
)
from ai_ops_backoffice.faq_domain.authorization import (
    AccessPolicyAuthorization,
    PocOnlySelfApprovalException,
)
from ai_ops_backoffice.faq_domain.models import FaqAuditEvent, FaqTestCase

WRITER = ActorContext("writer", "Writer", "KNOWLEDGE_ADMIN", ("it",))
REVIEWER = ActorContext("reviewer", "Reviewer", "KNOWLEDGE_ADMIN", ("it",))


def test_masking_provenance_uses_current_policy_for_new_cases_and_preserves_persisted_data():
    legacy = dict(
        test_case_id="legacy", faq_id="faq", version_id="version", kind="POSITIVE",
        utterance="historical example", expected_match=True, created_by="writer",
        created_at=datetime.now(UTC), masking_policy_version="v1",
    )
    assert FaqTestCase.model_validate(legacy, context={"persisted": True}).masking_policy_version == "v1"
    new = FaqTestCase.model_validate({**legacy, "utterance": "password: current-secret"})
    assert new.utterance == "[REDACTED_CREDENTIAL]"
    assert new.masking_policy_version == MASKING_POLICY_VERSION


@pytest.fixture(params=["memory", "file", "firestore_fake"])
def repository(request, tmp_path):
    if request.param == "file":
        return FileFaqRepository(tmp_path / "faq.json")
    if request.param == "firestore_fake":
        return FirestoreFaqRepository(
            FakeFirestoreClient(), transaction_runner=run_fake_transaction
        )
    return InMemoryFaqRepository()


def test_nested_return_values_cannot_mutate_repository_or_idempotency(repository):
    svc = service(repository)
    result = svc.create(content=content(), actor=WRITER, idempotency_key="same")
    faq_id = result["faq"]["faq_id"]
    result["version"]["content"]["answer"] = "external mutation"
    result["faq"]["etag"] = 99
    replay = svc.create(content=content(), actor=WRITER, idempotency_key="same")
    assert replay["version"]["content"]["answer"] == "原文固定答案"
    assert replay["faq"]["etag"] == 1
    event = repository.list_audit(faq_id)[0]
    event.after["nested"] = {"answer": "external mutation"}
    assert "nested" not in repository.list_audit(faq_id)[0].after
    replay["version"]["content"]["answer"] = "another mutation"
    assert svc.create(content=content(), actor=WRITER, idempotency_key="same") == {
        "faq": repository.get_faq(faq_id).model_dump(mode="json"),
        "version": repository.get_version(replay["version"]["version_id"]).model_dump(mode="json"),
    }


def test_replay_is_actor_bound_and_different_secret_inputs_conflict(repository):
    svc = service(repository)
    created = svc.create(content=content(), actor=WRITER, idempotency_key="owned")
    with pytest.raises(FaqIdempotencyConflictError):
        svc.create(content=content(), actor=REVIEWER, idempotency_key="owned")
    revoked = ActorContext("writer", "Writer", "KNOWLEDGE_ADMIN", ())
    with pytest.raises(FaqAuthorizationError):
        svc.create(content=content(), actor=revoked, idempotency_key="owned")
    kwargs = dict(
        faq_id=created["faq"]["faq_id"], version_id=created["version"]["version_id"],
        kind="POSITIVE", expected_audience_group_ids=("employees",), actor=WRITER,
        expected_etag=1, idempotency_key="test-owned",
    )
    first = svc.add_test(utterance="password: first-value", **kwargs)
    assert first["test"]["utterance"] == "[REDACTED_CREDENTIAL]"
    with pytest.raises(FaqIdempotencyConflictError):
        svc.add_test(utterance="password: different-value", **kwargs)


def test_validated_updates_and_source_contract(repository):
    svc = service(repository)
    with pytest.raises(ValidationError):
        svc.create(content=content().model_copy(update={"audience_group_ids": ()}), actor=WRITER)
    with pytest.raises(ValidationError, match="timezone"):
        svc.create(content=content().model_copy(update={"effective_at": datetime(2026, 1, 1)}), actor=WRITER)
    created = svc.create(content=content(), actor=WRITER)
    with pytest.raises(ValidationError):
        svc._replace(repository.get_faq(created["faq"]["faq_id"]), status="INVALID")
    with pytest.raises(ValidationError, match="source_correlation_id"):
        svc.add_test(
            faq_id=created["faq"]["faq_id"], version_id=created["version"]["version_id"],
            kind="POSITIVE", utterance="example", expected_audience_group_ids=("employees",),
            actor=WRITER, expected_etag=1, source_type="CONVERSATION",
        )
    assert repository.get_faq(created["faq"]["faq_id"]).etag == 1


def test_transfer_needs_new_owner_and_default_review_capability_denies(repository):
    svc = service(repository)
    created = svc.create(content=content(), actor=WRITER)
    with pytest.raises(FaqAuthorizationError):
        svc.edit(faq_id=created["faq"]["faq_id"], content=content().model_copy(update={"owner_unit_id": "finance"}), actor=WRITER, expected_etag=1)
    faq = add_required_tests(svc, created["faq"], created["version"], WRITER)
    submitted = svc.submit(faq_id=faq["faq_id"], version_id=created["version"]["version_id"], actor=WRITER, expected_etag=faq["etag"])
    default = FaqDomainService(repository, taxonomy=ActiveTaxonomy())
    with pytest.raises(FaqAuthorizationError):
        default.review(faq_id=faq["faq_id"], version_id=created["version"]["version_id"], actor=REVIEWER, approve=True, reason="reviewed", expected_etag=submitted["faq"]["etag"])


def test_audit_and_lifecycle_reasons_never_persist_credentials(repository):
    event = FaqAuditEvent(
        audit_id="audit", action="FAQ_APPROVED", actor_id="reviewer", actor_role="KNOWLEDGE_ADMIN",
        faq_id="faq", occurred_at=datetime.now(UTC), reason="password: reason-secret",
        before={"nested": [{"clientSecret": "nested-secret"}]},
        after={"note": "Bearer header-secret"},
    )
    serialized = event.model_dump_json()
    assert all(secret not in serialized for secret in ("reason-secret", "nested-secret", "header-secret"))
    svc = service(repository)
    created = svc.create(content=content(), actor=WRITER)
    faq = add_required_tests(svc, created["faq"], created["version"], WRITER)
    submitted = svc.submit(faq_id=faq["faq_id"], version_id=created["version"]["version_id"], actor=WRITER, expected_etag=faq["etag"])
    approved = svc.review(
        faq_id=faq["faq_id"], version_id=created["version"]["version_id"], actor=REVIEWER,
        approve=True, reason="api key: review-secret", expected_etag=submitted["faq"]["etag"],
        idempotency_key="approve-masked",
    )
    activated = svc.activate(
        faq_id=faq["faq_id"], version_id=created["version"]["version_id"], actor=REVIEWER,
        reason="Bearer activate-secret", expected_etag=approved["faq"]["etag"],
    )
    svc.disable(faq_id=faq["faq_id"], actor=REVIEWER, reason="password: disable-secret", expected_etag=activated["faq"]["etag"])
    persisted = str(repository.list_versions(faq["faq_id"])) + str(repository.list_audit(faq["faq_id"]))
    assert all(secret not in persisted for secret in ("review-secret", "activate-secret", "disable-secret"))


def test_poc_exception_requires_trusted_environment_and_capability(repository):
    svc = service(repository)
    created = svc.create(content=content(), actor=WRITER)
    faq = add_required_tests(svc, created["faq"], created["version"], WRITER)
    submitted = svc.submit(faq_id=faq["faq_id"], version_id=created["version"]["version_id"], actor=WRITER, expected_etag=faq["etag"])
    args = dict(faq_id=faq["faq_id"], version_id=created["version"]["version_id"], actor=WRITER, approve=True, reason="reviewed", poc_exception_reason="lab exception", expected_etag=submitted["faq"]["etag"])
    for policy in (
        PocOnlySelfApprovalException(AllowFaqAuthority(), environment="prod"),
        PocOnlySelfApprovalException(AccessPolicyAuthorization(), environment="poc"),
    ):
        restricted = FaqDomainService(repository, authorization=AllowFaqAuthority(), taxonomy=ActiveTaxonomy(), self_approval_exception=policy)
        with pytest.raises(FaqAuthorizationError):
            restricted.review(**args)
    lab = FaqDomainService(repository, authorization=AllowFaqAuthority(), taxonomy=ActiveTaxonomy(), self_approval_exception=PocOnlySelfApprovalException(AllowFaqAuthority(), environment="poc"))
    approved = lab.review(**args)
    assert approved["version"]["self_approval_exception"] is True
    assert approved["version"]["self_approval_exception_reason"] == "lab exception"


def test_runtime_reads_one_snapshot_and_can_restore_disabled_approved_version(repository, monkeypatch):
    svc = service(repository)
    created = svc.create(content=content(), actor=WRITER)
    approved = approve(svc, created["faq"], created["version"], WRITER, REVIEWER)
    active = svc.activate(faq_id=created["faq"]["faq_id"], version_id=created["version"]["version_id"], actor=REVIEWER, expected_etag=approved["faq"]["etag"], reason="activate")
    with monkeypatch.context() as patch:
        def split_read(*args):
            raise AssertionError("runtime must not use split pointer/version reads")
        patch.setattr(repository, "get_active_version_id", split_read)
        patch.setattr(repository, "get_version", split_read)
        assert svc.active_snapshot(faq_key="VPN_LOCKED", audience_group_ids=("employees",)).answer == "原文固定答案"
    disabled = svc.disable(faq_id=created["faq"]["faq_id"], actor=REVIEWER, expected_etag=active["faq"]["etag"], reason="containment")
    assert svc.active_snapshot(faq_key="VPN_LOCKED", audience_group_ids=("employees",)) is None
    restored = svc.rollback(faq_id=created["faq"]["faq_id"], version_id=created["version"]["version_id"], actor=REVIEWER, expected_etag=disabled["faq"]["etag"], reason="restore approved version")
    assert restored["version"]["approved_by"] == REVIEWER.user_id


def test_file_failed_atomic_replace_leaves_state_audit_and_replay_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "faq.json"
    repo = FileFaqRepository(path)
    svc = service(repo)
    created = svc.create(content=content(), actor=WRITER)
    before = path.read_bytes()
    def fail_replace(*args):
        raise OSError("disk failure")
    monkeypatch.setattr("ai_ops_backoffice.faq_domain.repository.os.replace", fail_replace)
    with pytest.raises(OSError):
        svc.edit(faq_id=created["faq"]["faq_id"], content=content(answer="new"), actor=WRITER, expected_etag=1, idempotency_key="failed")
    assert path.read_bytes() == before
    assert len(FileFaqRepository(path).list_audit(created["faq"]["faq_id"])) == 1


def test_file_independent_instances_concurrent_updates_have_one_winner(tmp_path):
    path = tmp_path / "faq.json"
    created = service(FileFaqRepository(path)).create(content=content(), actor=WRITER)
    barrier = Barrier(2)
    def update(answer):
        svc = service(FileFaqRepository(path))
        barrier.wait()
        try:
            svc.edit(faq_id=created["faq"]["faq_id"], content=content(answer=answer), actor=WRITER, expected_etag=1)
            return "saved"
        except FaqVersionConflictError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(update, ("a", "b"))) == ["conflict", "saved"]
    repo = FileFaqRepository(path)
    assert repo.get_faq(created["faq"]["faq_id"]).etag == 2
    assert len(repo.list_audit(created["faq"]["faq_id"])) == 2
