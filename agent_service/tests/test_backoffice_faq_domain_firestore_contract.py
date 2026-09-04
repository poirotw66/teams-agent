from __future__ import annotations

import pytest
from google.api_core.exceptions import Aborted, PermissionDenied
from google.auth.credentials import AnonymousCredentials
from google.cloud.firestore_v1 import Client
from google.cloud.firestore_v1.types import (
    BatchGetDocumentsResponse,
    BeginTransactionResponse,
    CommitResponse,
)
from google.protobuf.empty_pb2 import Empty
from google.protobuf.timestamp_pb2 import Timestamp
from test_backoffice_faq_domain import content, service

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.faq_domain import FirestoreFaqRepository


class OfflineFirestoreApi:
    """RPC stub behind the real synchronous Firestore SDK transaction object."""

    def __init__(self, *, abort_first_commit: bool = False, deny_commit: bool = False) -> None:
        self.abort_first_commit = abort_first_commit
        self.deny_commit = deny_commit
        self.begin_ids: list[bytes] = []
        self.batch_transactions: list[bytes] = []
        self.commit_transactions: list[bytes] = []
        self.rollback_transactions: list[bytes] = []
        self.committed_paths: list[str] = []

    def begin_transaction(self, *, request, metadata, **kwargs):
        transaction_id = f"transaction-{len(self.begin_ids) + 1}".encode()
        self.begin_ids.append(transaction_id)
        return BeginTransactionResponse(transaction=transaction_id)

    def batch_get_documents(self, *, request, metadata, **kwargs):
        self.batch_transactions.append(request.get("transaction") or b"")
        yield BatchGetDocumentsResponse(
            missing=request["documents"][0], read_time=Timestamp(seconds=1)
        )

    def commit(self, *, request, metadata, **kwargs):
        self.commit_transactions.append(request["transaction"])
        if self.abort_first_commit:
            self.abort_first_commit = False
            raise Aborted("retry the transaction")
        if self.deny_commit:
            raise PermissionDenied("audit collection unavailable")
        self.committed_paths.extend(write.update.name for write in request["writes"])
        return CommitResponse(commit_time=Timestamp(seconds=2))

    def rollback(self, *, request, metadata, **kwargs):
        self.rollback_transactions.append(request["transaction"])
        return Empty()


def test_real_firestore_sdk_begins_and_retries_transaction_before_transactional_reads() -> None:
    client = Client(project="offline-faq-contract", credentials=AnonymousCredentials())
    api = OfflineFirestoreApi(abort_first_commit=True)
    client._firestore_api_internal = api
    contributor = ActorContext("writer", "Writer", "KNOWLEDGE_ADMIN", ("it",))
    result = service(FirestoreFaqRepository(client)).create(
        content=content(audience="ALL"), actor=contributor, idempotency_key="real-sdk-contract"
    )
    assert result["faq"]["etag"] == 1
    assert len(api.begin_ids) == 2
    assert api.commit_transactions == api.begin_ids
    # The one empty transaction id is the preflight idempotency point read.
    assert api.batch_transactions.count(b"") == 1
    assert all(value in {b"", *api.begin_ids} for value in api.batch_transactions)
    assert {path.rsplit("/", 2)[1] for path in api.committed_paths} == {
        "ai_ops_faq_faqs", "ai_ops_faq_keys", "ai_ops_faq_versions",
        "ai_ops_faq_audit", "ai_ops_faq_idempotency",
    }


def test_real_sdk_failed_commit_rolls_back_without_returning_success() -> None:
    client = Client(project="offline-faq-contract", credentials=AnonymousCredentials())
    api = OfflineFirestoreApi(deny_commit=True)
    client._firestore_api_internal = api
    actor = ActorContext("writer", "Writer", "KNOWLEDGE_ADMIN", ("it",))
    with pytest.raises(PermissionDenied):
        service(FirestoreFaqRepository(client)).create(content=content(), actor=actor)
    assert api.committed_paths == []
    assert api.rollback_transactions == api.begin_ids
