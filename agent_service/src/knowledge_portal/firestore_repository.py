from __future__ import annotations

from typing import Any

from .models import (
    AuditEventRecord,
    DashboardSummary,
    IdempotencyRecord,
    KnowledgeDocumentRecord,
    KnowledgeVersionRecord,
    PortalActor,
    ReleaseRecord,
    ReviewRecord,
    TestCaseRecord,
    TestRunRecord,
)
from .repository import PortalNotFoundError, PortalRepository
from .settings import PortalSettings


class FirestorePortalRepository:
    def __init__(self, settings: PortalSettings, client: Any | None = None) -> None:
        from google.cloud import firestore

        self._settings = settings
        if client is not None:
            self._client = client
        else:
            self._client = firestore.AsyncClient(
                project=settings.firestore_project_id,
                database=settings.firestore_database_id,
            )

    def _documents(self):
        return self._client.collection(self._settings.documents_collection)

    def _versions(self):
        return self._client.collection(self._settings.versions_collection)

    def _reviews(self):
        return self._client.collection(self._settings.reviews_collection)

    def _releases(self):
        return self._client.collection(self._settings.releases_collection)

    def _audit(self):
        return self._client.collection(self._settings.audit_collection)

    def _config(self):
        return self._client.collection(self._settings.config_collection)

    def _idempotency(self):
        return self._client.collection(f"{self._settings.config_collection}_idempotency")

    @staticmethod
    def _serialize(model) -> dict[str, Any]:
        return model.model_dump(mode="python")

    @staticmethod
    def _deserialize(model_cls, payload: dict[str, Any] | None):
        if payload is None:
            return None
        return model_cls.model_validate(payload)

    async def list_documents(
        self,
        *,
        actor: PortalActor,
        status: str | None = None,
        owner_unit_id: str | None = None,
        query: str | None = None,
    ) -> list[KnowledgeDocumentRecord]:
        snapshots = self._documents().stream()
        items: list[KnowledgeDocumentRecord] = []
        async for snapshot in snapshots:
            document = self._deserialize(KnowledgeDocumentRecord, snapshot.to_dict())
            if document is not None:
                items.append(document)
        memory = _MemoryFilter(items)
        return await memory.list_documents(
            actor=actor,
            status=status,
            owner_unit_id=owner_unit_id,
            query=query,
        )

    async def get_document(self, document_id: str) -> KnowledgeDocumentRecord | None:
        snapshot = await self._documents().document(document_id).get()
        return self._deserialize(KnowledgeDocumentRecord, snapshot.to_dict())

    async def save_document(self, document: KnowledgeDocumentRecord) -> KnowledgeDocumentRecord:
        await self._documents().document(document.document_id).set(self._serialize(document))
        return document

    async def get_version(self, version_id: str) -> KnowledgeVersionRecord | None:
        snapshot = await self._versions().document(version_id).get()
        return self._deserialize(KnowledgeVersionRecord, snapshot.to_dict())

    async def save_version(self, version: KnowledgeVersionRecord) -> KnowledgeVersionRecord:
        await self._versions().document(version.version_id).set(self._serialize(version))
        return version

    async def list_versions_for_document(self, document_id: str) -> list[KnowledgeVersionRecord]:
        query = self._versions().where("document_id", "==", document_id)
        items: list[KnowledgeVersionRecord] = []
        async for snapshot in query.stream():
            version = self._deserialize(KnowledgeVersionRecord, snapshot.to_dict())
            if version is not None:
                items.append(version)
        return items

    async def save_review(self, review: ReviewRecord) -> ReviewRecord:
        await self._reviews().document(review.review_id).set(self._serialize(review))
        return review

    async def get_review(self, review_id: str) -> ReviewRecord | None:
        snapshot = await self._reviews().document(review_id).get()
        return self._deserialize(ReviewRecord, snapshot.to_dict())

    async def get_open_review_for_version(self, version_id: str) -> ReviewRecord | None:
        query = self._reviews().where("version_id", "==", version_id)
        async for snapshot in query.stream():
            review = self._deserialize(ReviewRecord, snapshot.to_dict())
            if review is not None and review.decision is None:
                return review
        return None

    async def list_pending_reviews(self, actor: PortalActor) -> list[ReviewRecord]:
        if actor.role not in {"REVIEWER", "MANAGER", "PLATFORM"}:
            return []
        items: list[ReviewRecord] = []
        async for snapshot in self._reviews().stream():
            review = self._deserialize(ReviewRecord, snapshot.to_dict())
            if review is not None and review.decision is None:
                items.append(review)
        return sorted(items, key=lambda item: item.submitted_at, reverse=True)

    async def save_release(self, release: ReleaseRecord) -> ReleaseRecord:
        await self._releases().document(release.release_id).set(self._serialize(release))
        return release

    async def get_release(self, release_id: str) -> ReleaseRecord | None:
        snapshot = await self._releases().document(release_id).get()
        return self._deserialize(ReleaseRecord, snapshot.to_dict())

    async def list_releases(self) -> list[ReleaseRecord]:
        items: list[ReleaseRecord] = []
        async for snapshot in self._releases().stream():
            release = self._deserialize(ReleaseRecord, snapshot.to_dict())
            if release is not None:
                items.append(release)
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    async def get_active_release_id(self) -> str | None:
        snapshot = await self._config().document("active_release").get()
        payload = snapshot.to_dict() or {}
        value = payload.get("release_id")
        return str(value) if value else None

    async def set_active_release_id(self, release_id: str | None) -> None:
        await self._config().document("active_release").set({"release_id": release_id})

    async def append_audit(self, event: AuditEventRecord) -> AuditEventRecord:
        await self._audit().document(event.event_id).set(self._serialize(event))
        return event

    async def list_audit_events(self, *, limit: int = 100) -> list[AuditEventRecord]:
        query = self._audit().order_by("occurred_at", direction="DESCENDING").limit(limit)
        items: list[AuditEventRecord] = []
        async for snapshot in query.stream():
            event = self._deserialize(AuditEventRecord, snapshot.to_dict())
            if event is not None:
                items.append(event)
        return items

    async def save_test_case(self, test_case: TestCaseRecord) -> TestCaseRecord:
        await self._client.collection("knowledge_test_cases").document(
            test_case.test_case_id
        ).set(self._serialize(test_case))
        return test_case

    async def list_test_cases(self, version_id: str) -> list[TestCaseRecord]:
        query = self._client.collection("knowledge_test_cases").where(
            "version_id", "==", version_id
        )
        items: list[TestCaseRecord] = []
        async for snapshot in query.stream():
            test_case = self._deserialize(TestCaseRecord, snapshot.to_dict())
            if test_case is not None:
                items.append(test_case)
        return items

    async def save_test_run(self, test_run: TestRunRecord) -> TestRunRecord:
        await self._client.collection("knowledge_test_runs").document(
            test_run.test_run_id
        ).set(self._serialize(test_run))
        return test_run

    async def list_test_runs(self, version_id: str) -> list[TestRunRecord]:
        query = self._client.collection("knowledge_test_runs").where(
            "version_id", "==", version_id
        )
        items: list[TestRunRecord] = []
        async for snapshot in query.stream():
            test_run = self._deserialize(TestRunRecord, snapshot.to_dict())
            if test_run is not None:
                items.append(test_run)
        return items

    async def get_idempotency(self, key: str) -> IdempotencyRecord | None:
        doc_id = key.replace("/", "_")
        snapshot = await self._idempotency().document(doc_id).get()
        return self._deserialize(IdempotencyRecord, snapshot.to_dict())

    async def save_idempotency(self, record: IdempotencyRecord) -> None:
        doc_id = record.key.replace("/", "_")
        await self._idempotency().document(doc_id).set(self._serialize(record))

    async def dashboard_summary(self, actor: PortalActor) -> DashboardSummary:
        documents = await self.list_documents(actor=actor)
        pending_reviews = await self.list_pending_reviews(actor)
        active_release_id = await self.get_active_release_id()
        active_release = (
            await self.get_release(active_release_id) if active_release_id else None
        )
        from datetime import UTC, date, datetime, timedelta

        today = datetime.now(UTC).date()
        horizon = today + timedelta(days=30)
        due_soon_count = 0
        for document in documents:
            if document.status != "PUBLISHED" or not document.current_published_version_id:
                continue
            version = await self.get_version(document.current_published_version_id)
            if version is None:
                continue
            try:
                due = date.fromisoformat(version.review_due_at)
            except ValueError:
                continue
            if today <= due <= horizon:
                due_soon_count += 1
        return DashboardSummary(
            my_drafts=sum(1 for item in documents if item.status == "DRAFT"),
            my_changes_requested=sum(
                1 for item in documents if item.status == "CHANGES_REQUESTED"
            ),
            pending_review=len(pending_reviews),
            publish_failed=sum(
                1 for item in documents if item.status == "PUBLISH_FAILED"
            ),
            review_due_soon=due_soon_count,
            active_release_id=active_release_id,
            active_release_activated_at=active_release.activated_at
            if active_release
            else None,
        )


class _MemoryFilter(PortalRepository):
    def __init__(self, documents: list[KnowledgeDocumentRecord]) -> None:
        from .repository import InMemoryPortalRepository

        self._inner = InMemoryPortalRepository()
        for document in documents:
            self._inner.documents[document.document_id] = document

    async def list_documents(self, *, actor, status=None, owner_unit_id=None, query=None):
        return await self._inner.list_documents(
            actor=actor,
            status=status,
            owner_unit_id=owner_unit_id,
            query=query,
        )

    async def list_pending_reviews(self, actor):
        return await self._inner.list_pending_reviews(actor)

    async def get_document(self, document_id: str):
        raise PortalNotFoundError("document", document_id)

    async def save_document(self, document):
        raise PortalNotFoundError("document", document.document_id)

    async def get_version(self, version_id: str):
        raise PortalNotFoundError("version", version_id)

    async def save_version(self, version):
        raise PortalNotFoundError("version", version.version_id)

    async def list_versions_for_document(self, document_id: str):
        return []

    async def save_review(self, review):
        raise PortalNotFoundError("review", review.review_id)

    async def get_open_review_for_version(self, version_id: str):
        return None

    async def save_release(self, release):
        raise PortalNotFoundError("release", release.release_id)

    async def get_release(self, release_id: str):
        return None

    async def list_releases(self):
        return []

    async def get_active_release_id(self):
        return None

    async def set_active_release_id(self, release_id: str | None):
        return None

    async def append_audit(self, event):
        return event

    async def list_audit_events(self, *, limit: int = 100):
        return []

    async def save_test_case(self, test_case):
        return test_case

    async def list_test_cases(self, version_id: str):
        return []

    async def save_test_run(self, test_run):
        return test_run

    async def list_test_runs(self, version_id: str):
        return []

    async def dashboard_summary(self, actor):
        return await self._inner.dashboard_summary(actor)
