from pathlib import Path

import pytest

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.example_domain import (
    ExampleService,
    FileExampleRepository,
    FirestoreExampleRepository,
)
from ai_ops_backoffice.faq_domain.errors import (
    FaqAuthorizationError,
    FaqValidationError,
    FaqVersionConflictError,
)


class ActiveTaxonomy:
    def require_active(self, issue_type_id: str) -> None:
        if issue_type_id != "vpn.connection_failed":
            raise FaqValidationError(f"inactive issue type: {issue_type_id}")


class FakeSnapshot:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class FakeDocument:
    def __init__(self, collection, key):
        self.collection = collection
        self.key = key

    def get(self, transaction=None):
        if transaction is not None:
            assert transaction.begun
            assert not transaction.pending
        return FakeSnapshot(self.collection.data.get(self.key))


class FakeQuery:
    def __init__(self, collection, field, value):
        self.collection = collection
        self.field = field
        self.value = value

    def stream(self):
        return [
            FakeSnapshot(data)
            for data in self.collection.data.values()
            if data.get(self.field) == self.value
        ]


class FakeCollection:
    def __init__(self, name):
        self.name = name
        self.data = {}

    def document(self, key):
        return FakeDocument(self, key)

    def stream(self):
        return [FakeSnapshot(data) for data in self.data.values()]

    def where(self, field, _operator, value):
        return FakeQuery(self, field, value)


class FakeTransaction:
    def __init__(self, client):
        self.client = client
        self.pending = {}
        self.begun = False

    def set(self, reference, data):
        self.pending[(reference.collection.name, reference.key)] = dict(data)

    def commit(self):
        for (collection, key), data in self.pending.items():
            self.client.collections[collection].data[key] = data


class FakeFirestoreClient:
    def __init__(self):
        self.collections = {}

    def collection(self, name):
        return self.collections.setdefault(name, FakeCollection(name))

    def transaction(self):
        return FakeTransaction(self)


def run_fake_transaction(operation, transaction):
    transaction.begun = True
    result = operation(transaction)
    transaction.commit()
    return result


@pytest.fixture
def writer() -> ActorContext:
    return ActorContext("writer", "Writer", "KNOWLEDGE_ADMIN", ("IT",))


@pytest.fixture
def admin() -> ActorContext:
    return ActorContext("justin", "Justin", "SYSTEM_ADMIN", ())


def create_example(service: ExampleService, writer: ActorContext, **overrides):
    values = {
        "source_type": "FAQ",
        "source_id": "faq-1",
        "source_version_id": "version-1",
        "source_correlation_id": None,
        "owner_unit_id": "IT",
        "text": "VPN user@example.com 無法連線",
        "expected_issue_type_id": "vpn.connection_failed",
        "expected_route": "FAQ",
        "label": "POSITIVE",
        "reason": None,
        "actor": writer,
    }
    values.update(overrides)
    return service.create(**values)


def test_example_lifecycle_masks_persists_and_retires(
    tmp_path: Path, writer: ActorContext, admin: ActorContext
) -> None:
    path = tmp_path / "examples.json"
    service = ExampleService(FileExampleRepository(path), taxonomy=ActiveTaxonomy())
    created = create_example(
        service,
        writer,
        idempotency_key="create-1",
        correlation_id="corr-1",
    )
    replay = create_example(service, writer, idempotency_key="create-1", correlation_id="corr-1")
    assert replay["example"]["example_id"] == created["example"]["example_id"]
    assert "user@example.com" not in created["example"]["text"]
    assert created["example"]["masking_policy_version"]

    example_id = created["example"]["example_id"]
    with pytest.raises(FaqAuthorizationError):
        service.review(
            example_id,
            approve=True,
            reason="checked",
            expected_etag=1,
            actor=writer,
        )
    verified = service.review(
        example_id,
        approve=True,
        reason="已核對 issue 與 route",
        expected_etag=1,
        actor=admin,
    )
    assert verified["example"]["status"] == "VERIFIED"
    assert verified["example"]["dataset_version"].startswith("dataset-")
    with pytest.raises(FaqVersionConflictError):
        service.retire(
            example_id,
            reason="stale",
            expected_etag=1,
            actor=admin,
        )
    retired = service.retire(
        example_id,
        reason="由新案例取代",
        expected_etag=2,
        actor=admin,
    )
    assert retired["example"]["status"] == "RETIRED"

    restarted = ExampleService(FileExampleRepository(path), taxonomy=ActiveTaxonomy())
    detail = restarted.detail(example_id, actor=admin)
    assert detail["example"]["status"] == "RETIRED"
    assert [event["action"] for event in detail["audit"]] == [
        "EXAMPLE_CREATED",
        "EXAMPLE_VERIFIED",
        "EXAMPLE_RETIRED",
    ]


def test_example_validation_update_and_owner_scope(
    tmp_path: Path, writer: ActorContext, admin: ActorContext
) -> None:
    service = ExampleService(
        FileExampleRepository(tmp_path / "examples.json"),
        taxonomy=ActiveTaxonomy(),
    )
    with pytest.raises(FaqValidationError, match="negative"):
        create_example(service, writer, label="NEGATIVE", reason=None)
    with pytest.raises(FaqValidationError, match="credentials"):
        create_example(service, writer, text="password=secret-value")
    with pytest.raises(FaqValidationError, match="reasons"):
        create_example(
            service,
            writer,
            label="NEGATIVE",
            reason="password=secret-value",
        )
    with pytest.raises(FaqValidationError, match="inactive"):
        create_example(service, writer, expected_issue_type_id="unknown.issue")

    created = create_example(
        service,
        writer,
        label="NEGATIVE",
        reason="容易與密碼問題混淆",
    )
    example_id = created["example"]["example_id"]
    updated = service.update(
        example_id,
        text="VPN 安裝失敗",
        expected_issue_type_id="vpn.connection_failed",
        expected_route="FAQ",
        label="POSITIVE",
        reason=None,
        expected_etag=1,
        actor=writer,
    )
    assert updated["example"]["etag"] == 2
    assert updated["example"]["status"] == "DRAFT"
    finance = ActorContext("finance", "Finance", "KNOWLEDGE_ADMIN", ("Finance",))
    assert service.list_examples(actor=finance) == []
    with pytest.raises(FaqAuthorizationError):
        service.detail(example_id, actor=finance)
    assert len(service.list_examples(actor=admin, source_id="faq-1")) == 1


def test_firestore_example_commits_record_audit_and_idempotency_together(
    writer: ActorContext,
) -> None:
    client = FakeFirestoreClient()
    repository = FirestoreExampleRepository(
        client,
        transaction_runner=run_fake_transaction,
    )
    service = ExampleService(repository, taxonomy=ActiveTaxonomy())

    created = create_example(service, writer, idempotency_key="firestore-create")
    example_id = created["example"]["example_id"]
    assert repository.get(example_id) is not None
    assert len(repository.list_audit(example_id)) == 1
    assert len(client.collections["ai_ops_faq_examples"].data) == 1
    assert len(client.collections["ai_ops_faq_example_audit"].data) == 1
    assert len(client.collections["ai_ops_faq_example_idempotency"].data) == 1

    replay = create_example(service, writer, idempotency_key="firestore-create")
    assert replay == created
    assert len(client.collections["ai_ops_faq_examples"].data) == 1