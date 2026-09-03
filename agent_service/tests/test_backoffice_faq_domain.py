from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.faq_domain import (
    FaqAuthorizationError,
    FaqContent,
    FaqDomainService,
    FaqIdempotencyConflictError,
    FaqValidationError,
    FaqVersionConflictError,
    FileFaqRepository,
    FirestoreFaqRepository,
    InMemoryFaqRepository,
)


class AllowFaqAuthority:
    def require(self, *, actor: ActorContext, capability: str, owner_unit_id: str) -> None:
        if owner_unit_id not in actor.owner_unit_ids:
            raise FaqAuthorizationError("owner-unit scope denied")


class ActiveTaxonomy:
    def __init__(self, active: set[str] | None = None) -> None:
        self.active = active or {"vpn.account_locked"}

    def require_active(self, issue_type_id: str) -> None:
        if issue_type_id not in self.active:
            raise FaqValidationError(f"inactive issue type: {issue_type_id}")


@pytest.fixture
def contributor() -> ActorContext:
    return ActorContext("writer", "Writer", "KNOWLEDGE_ADMIN", ("it",))


@pytest.fixture
def reviewer() -> ActorContext:
    return ActorContext("reviewer", "Reviewer", "KNOWLEDGE_ADMIN", ("it",))


def service(repository) -> FaqDomainService:
    return FaqDomainService(
        repository, authorization=AllowFaqAuthority(), taxonomy=ActiveTaxonomy()
    )


def content(*, audience: str = "GROUPS", answer: str = "原文固定答案") -> FaqContent:
    return FaqContent(
        faq_key="VPN_LOCKED",
        question="VPN 被鎖住怎麼辦？",
        answer=answer,
        category="VPN",
        keywords=("vpn", "locked"),
        owner_unit_id="it",
        business_contact="it@example.test",
        issue_type_ids=("vpn.account_locked",),
        audience_type=audience,
        audience_group_ids=("employees",) if audience == "GROUPS" else (),
    )


def add_required_tests(
    svc: FaqDomainService, faq: dict, version: dict, actor: ActorContext
) -> dict:
    positive = svc.add_test(
        faq_id=faq["faq_id"],
        version_id=version["version_id"],
        kind="POSITIVE",
        utterance="我的 VPN 被鎖了",
        expected_audience_group_ids=("employees",),
        actor=actor,
        expected_etag=faq["etag"],
    )
    negative = svc.add_test(
        faq_id=faq["faq_id"],
        version_id=version["version_id"],
        kind="NEGATIVE",
        utterance="我要申請新的筆電",
        expected_audience_group_ids=("employees",),
        actor=actor,
        expected_etag=positive["faq"]["etag"],
    )
    return negative["faq"]


def approve(
    svc: FaqDomainService, faq: dict, version: dict, writer: ActorContext, reviewer: ActorContext
) -> dict:
    current = add_required_tests(svc, faq, version, writer)
    submitted = svc.submit(
        faq_id=faq["faq_id"],
        version_id=version["version_id"],
        actor=writer,
        expected_etag=current["etag"],
    )
    return svc.review(
        faq_id=faq["faq_id"],
        version_id=version["version_id"],
        approve=True,
        reason="內容、正反例與 audience 已驗證",
        actor=reviewer,
        expected_etag=submitted["faq"]["etag"],
    )


def test_full_lifecycle_activation_disable_and_audited_rollback(contributor, reviewer) -> None:
    repo = InMemoryFaqRepository()
    svc = service(repo)
    created = svc.create(content=content(), actor=contributor)
    first = approve(svc, created["faq"], created["version"], contributor, reviewer)
    active_one = svc.activate(
        faq_id=created["faq"]["faq_id"],
        version_id=created["version"]["version_id"],
        actor=reviewer,
        expected_etag=first["faq"]["etag"],
        reason="release v1",
    )
    assert (
        svc.active_snapshot(faq_key="VPN_LOCKED", audience_group_ids=("employees",)).answer
        == "原文固定答案"
    )
    assert svc.active_snapshot(faq_key="VPN_LOCKED", audience_group_ids=("contractors",)) is None

    draft_two = svc.edit(
        faq_id=created["faq"]["faq_id"],
        content=content(answer="原文固定答案 v2"),
        actor=contributor,
        expected_etag=active_one["faq"]["etag"],
    )
    approved_two = approve(svc, draft_two["faq"], draft_two["version"], contributor, reviewer)
    active_two = svc.activate(
        faq_id=created["faq"]["faq_id"],
        version_id=draft_two["version"]["version_id"],
        actor=reviewer,
        expected_etag=approved_two["faq"]["etag"],
        reason="release v2",
    )
    restored = svc.rollback(
        faq_id=created["faq"]["faq_id"],
        version_id=created["version"]["version_id"],
        actor=reviewer,
        expected_etag=active_two["faq"]["etag"],
        reason="v2 regression rollback",
    )
    snapshot = svc.active_snapshot(faq_key="VPN_LOCKED", audience_group_ids=("employees",))
    assert snapshot and snapshot.version_id == created["version"]["version_id"]
    assert snapshot.answer == "原文固定答案"  # no LLM transformation occurs in this contract
    assert restored["faq"]["status"] == "ACTIVE"
    actions = [item.action for item in repo.list_audit(created["faq"]["faq_id"])]
    assert {"FAQ_CREATED", "FAQ_ACTIVATED", "FAQ_ROLLED_BACK"}.issubset(actions)

    disabled = svc.disable(
        faq_id=created["faq"]["faq_id"],
        actor=reviewer,
        expected_etag=restored["faq"]["etag"],
        reason="emergency containment",
    )
    assert disabled["faq"]["status"] == "DISABLED"
    assert svc.active_snapshot(faq_key="VPN_LOCKED", audience_group_ids=("employees",)) is None


def test_review_separation_changes_requested_and_required_tests(contributor, reviewer) -> None:
    svc = service(InMemoryFaqRepository())
    created = svc.create(content=content(), actor=contributor)
    with pytest.raises(FaqValidationError, match="POSITIVE"):
        svc.submit(
            faq_id=created["faq"]["faq_id"],
            version_id=created["version"]["version_id"],
            actor=contributor,
            expected_etag=1,
        )
    faq = add_required_tests(svc, created["faq"], created["version"], contributor)
    submitted = svc.submit(
        faq_id=faq["faq_id"],
        version_id=created["version"]["version_id"],
        actor=contributor,
        expected_etag=faq["etag"],
    )
    with pytest.raises(FaqAuthorizationError, match="submitter"):
        svc.review(
            faq_id=faq["faq_id"],
            version_id=created["version"]["version_id"],
            approve=True,
            reason="self",
            actor=contributor,
            expected_etag=submitted["faq"]["etag"],
        )
    changed = svc.review(
        faq_id=faq["faq_id"],
        version_id=created["version"]["version_id"],
        approve=False,
        reason="請補充步驟",
        actor=reviewer,
        expected_etag=submitted["faq"]["etag"],
    )
    assert changed["version"]["status"] == "CHANGES_REQUESTED"


def test_validation_taxonomy_audience_and_negative_test_rules(contributor) -> None:
    with pytest.raises(ValidationError, match="GROUPS audience"):
        FaqContent(**{**content().model_dump(), "audience_group_ids": ()})
    with pytest.raises(ValidationError, match="ALL audience"):
        FaqContent(**{**content().model_dump(), "audience_type": "ALL"})
    svc = service(InMemoryFaqRepository())
    bad = content().model_copy(update={"issue_type_ids": ("retired.type",)})
    with pytest.raises(FaqValidationError, match="inactive"):
        svc.create(content=bad, actor=contributor)
    created = svc.create(content=content(), actor=contributor)
    with pytest.raises(ValidationError, match="kind"):
        svc.add_test(
            faq_id=created["faq"]["faq_id"],
            version_id=created["version"]["version_id"],
            kind="OTHER",
            utterance="x",
            expected_audience_group_ids=(),
            actor=contributor,
            expected_etag=1,
        )


def test_cas_and_idempotency_prevent_lost_or_duplicate_updates(contributor) -> None:
    repo = InMemoryFaqRepository()
    svc = service(repo)
    first = svc.create(content=content(), actor=contributor, idempotency_key="create-1")
    replay = svc.create(content=content(), actor=contributor, idempotency_key="create-1")
    assert replay == first
    with pytest.raises(FaqIdempotencyConflictError):
        svc.create(
            content=content(answer="different"), actor=contributor, idempotency_key="create-1"
        )
    one = svc.add_test(
        faq_id=first["faq"]["faq_id"],
        version_id=first["version"]["version_id"],
        kind="POSITIVE",
        utterance="vpn",
        expected_audience_group_ids=("employees",),
        actor=contributor,
        expected_etag=1,
    )
    with pytest.raises(FaqVersionConflictError):
        svc.add_test(
            faq_id=first["faq"]["faq_id"],
            version_id=first["version"]["version_id"],
            kind="NEGATIVE",
            utterance="laptop",
            expected_audience_group_ids=("employees",),
            actor=contributor,
            expected_etag=1,
        )
    assert one["faq"]["etag"] == 2


def test_retries_precede_lifecycle_validation_and_edit_fingerprint_is_stable(
    contributor, reviewer
) -> None:
    repo = InMemoryFaqRepository()
    svc = service(repo)
    created = svc.create(content=content(), actor=contributor)
    faq = add_required_tests(svc, created["faq"], created["version"], contributor)
    submitted = svc.submit(
        faq_id=faq["faq_id"],
        version_id=created["version"]["version_id"],
        actor=contributor,
        expected_etag=faq["etag"],
        idempotency_key="submit-1",
    )
    assert (
        svc.submit(
            faq_id=faq["faq_id"],
            version_id=created["version"]["version_id"],
            actor=contributor,
            expected_etag=faq["etag"],
            idempotency_key="submit-1",
        )
        == submitted
    )
    approved = svc.review(
        faq_id=faq["faq_id"],
        version_id=created["version"]["version_id"],
        approve=True,
        reason="ready",
        actor=reviewer,
        expected_etag=submitted["faq"]["etag"],
        idempotency_key="review-1",
    )
    assert (
        svc.review(
            faq_id=faq["faq_id"],
            version_id=created["version"]["version_id"],
            approve=True,
            reason="ready",
            actor=reviewer,
            expected_etag=submitted["faq"]["etag"],
            idempotency_key="review-1",
        )
        == approved
    )
    active = svc.activate(
        faq_id=faq["faq_id"],
        version_id=created["version"]["version_id"],
        actor=reviewer,
        expected_etag=approved["faq"]["etag"],
        reason="go",
    )
    edited = svc.edit(
        faq_id=faq["faq_id"],
        content=content(answer="v2"),
        actor=contributor,
        expected_etag=active["faq"]["etag"],
        idempotency_key="edit-1",
    )
    assert (
        svc.edit(
            faq_id=faq["faq_id"],
            content=content(answer="v2"),
            actor=contributor,
            expected_etag=active["faq"]["etag"],
            idempotency_key="edit-1",
        )
        == edited
    )
    assert len(repo.list_versions(faq["faq_id"])) == 2


def test_owner_transfer_requires_old_and_new_scope_and_self_approval_uses_submitter(
    contributor, reviewer
) -> None:
    svc = service(InMemoryFaqRepository())
    created = svc.create(content=content(), actor=contributor)
    attacker = ActorContext("attacker", "Attacker", "KNOWLEDGE_ADMIN", ("finance",))
    changed_owner = content().model_copy(update={"owner_unit_id": "finance"})
    with pytest.raises(FaqAuthorizationError, match="owner-unit"):
        svc.edit(
            faq_id=created["faq"]["faq_id"], content=changed_owner, actor=attacker, expected_etag=1
        )
    submitter = ActorContext("submitter", "Submitter", "KNOWLEDGE_ADMIN", ("it",))
    faq = add_required_tests(svc, created["faq"], created["version"], submitter)
    submitted = svc.submit(
        faq_id=faq["faq_id"],
        version_id=created["version"]["version_id"],
        actor=submitter,
        expected_etag=faq["etag"],
    )
    approved = svc.review(
        faq_id=faq["faq_id"],
        version_id=created["version"]["version_id"],
        approve=True,
        reason="independent submit",
        actor=contributor,
        expected_etag=submitted["faq"]["etag"],
    )
    assert approved["version"]["submitted_by"] == "submitter"
    second = svc.create(
        content=content(answer="second").model_copy(update={"faq_key": "VPN_LOCKED_2"}),
        actor=contributor,
    )
    second_faq = add_required_tests(svc, second["faq"], second["version"], contributor)
    second_submitted = svc.submit(
        faq_id=second_faq["faq_id"],
        version_id=second["version"]["version_id"],
        actor=contributor,
        expected_etag=second_faq["etag"],
    )
    with pytest.raises(FaqAuthorizationError, match="self approval"):
        svc.review(
            faq_id=second_faq["faq_id"],
            version_id=second["version"]["version_id"],
            approve=True,
            reason="POC",
            poc_exception_reason="just text is insufficient",
            actor=contributor,
            expected_etag=second_submitted["faq"]["etag"],
        )


def test_future_effective_release_and_sensitive_test_source_are_safe(contributor, reviewer) -> None:
    svc = service(InMemoryFaqRepository())
    future = content(audience="ALL").model_copy(
        update={"effective_at": datetime.now(UTC) + timedelta(hours=1)}
    )
    created = svc.create(content=future, actor=contributor)
    stored = svc.add_test(
        faq_id=created["faq"]["faq_id"],
        version_id=created["version"]["version_id"],
        kind="POSITIVE",
        utterance="請寄給 jane@example.test",
        expected_audience_group_ids=(),
        source_type="CONVERSATION",
        source_correlation_id="corr-allowed-reference-only",
        actor=contributor,
        expected_etag=1,
    )
    assert "jane@example.test" not in stored["test"]["utterance"]
    assert stored["test"]["source_correlation_id"] == "corr-allowed-reference-only"
    faq = stored["faq"]
    negative = svc.add_test(
        faq_id=faq["faq_id"],
        version_id=created["version"]["version_id"],
        kind="NEGATIVE",
        utterance="無關問題",
        expected_audience_group_ids=(),
        actor=contributor,
        expected_etag=faq["etag"],
    )
    submitted = svc.submit(
        faq_id=faq["faq_id"],
        version_id=created["version"]["version_id"],
        actor=contributor,
        expected_etag=negative["faq"]["etag"],
    )
    approved = svc.review(
        faq_id=faq["faq_id"],
        version_id=created["version"]["version_id"],
        approve=True,
        reason="checked",
        actor=reviewer,
        expected_etag=submitted["faq"]["etag"],
    )
    svc.activate(
        faq_id=faq["faq_id"],
        version_id=created["version"]["version_id"],
        actor=reviewer,
        expected_etag=approved["faq"]["etag"],
        reason="scheduled",
    )
    assert svc.active_snapshot(faq_key="VPN_LOCKED", audience_group_ids=()) is None
    with pytest.raises(FaqValidationError, match="credential"):
        svc.create(content=content(answer="api key: leaked"), actor=contributor)


def test_file_repository_recovers_lifecycle_and_audit_after_restart(
    tmp_path: Path, contributor, reviewer
) -> None:
    path = tmp_path / "faq-domain.json"
    initial = service(FileFaqRepository(path))
    created = initial.create(content=content(audience="ALL"), actor=contributor)
    approved = approve(initial, created["faq"], created["version"], contributor, reviewer)
    initial.activate(
        faq_id=created["faq"]["faq_id"],
        version_id=created["version"]["version_id"],
        actor=reviewer,
        expected_etag=approved["faq"]["etag"],
        reason="file release",
    )
    restarted_repo = FileFaqRepository(path)
    restarted = service(restarted_repo)
    snapshot = restarted.active_snapshot(faq_key="VPN_LOCKED", audience_group_ids=())
    assert snapshot and snapshot.answer == "原文固定答案"
    assert any(
        event.action == "FAQ_ACTIVATED"
        for event in restarted_repo.list_audit(created["faq"]["faq_id"])
    )


class FakeSnapshot:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class FakeDocument:
    def __init__(self, collection, key):
        self.collection, self.key = collection, key

    def get(self, transaction=None):
        if transaction is not None:
            assert transaction.begun, "read before transaction begin"
            assert not transaction.pending, "read after write in transaction"
        source = (
            transaction.pending.get(
                (self.collection.name, self.key), self.collection.data.get(self.key)
            )
            if transaction
            else self.collection.data.get(self.key)
        )
        return FakeSnapshot(source)


class FakeQuery:
    def __init__(self, collection, field, value):
        self.collection, self.field, self.value = collection, field, value

    def stream(self):
        return [
            FakeSnapshot(data)
            for data in self.collection.data.values()
            if data.get(self.field) == self.value
        ]


class FakeCollection:
    def __init__(self, name):
        self.name, self.data = name, {}

    def document(self, key):
        return FakeDocument(self, key)

    def where(self, field, _operator, value):
        return FakeQuery(self, field, value)


class FakeTransaction:
    def __init__(self, client):
        self.client, self.pending = client, {}
        self.begun = False

    def set(self, ref, data):
        self.pending[(ref.collection.name, ref.key)] = dict(data)

    def commit(self):
        assert self.begun
        for (collection, key), data in self.pending.items():
            self.client.collections[collection].data[key] = data


def run_fake_transaction(operation, transaction):
    transaction.begun = True
    result = operation(transaction)
    transaction.commit()
    return result


class FakeFirestoreClient:
    def __init__(self):
        self.collections = {}

    def collection(self, name):
        return self.collections.setdefault(name, FakeCollection(name))

    def transaction(self):
        return FakeTransaction(self)


def test_firestore_repository_uses_injectable_local_transaction(contributor) -> None:
    # This is a local fake only: no ADC, credentials, network, or cloud write occurs.
    client = FakeFirestoreClient()
    repo = FirestoreFaqRepository(client, transaction_runner=run_fake_transaction)
    result = service(repo).create(
        content=content(audience="ALL"), actor=contributor, idempotency_key="firestore-create"
    )
    assert repo.get_faq(result["faq"]["faq_id"]) is not None
    assert len(repo.list_audit(result["faq"]["faq_id"])) == 1
    assert len(client.collections["ai_ops_faq_idempotency"].data) == 1
