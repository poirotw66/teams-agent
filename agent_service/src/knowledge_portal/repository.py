from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

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


class VersionConflictError(Exception):
    def __init__(self, target_id: str) -> None:
        super().__init__("這份文件剛被其他人更新過，請重新載入後再試。")
        self.target_id = target_id


class PortalNotFoundError(Exception):
    def __init__(self, target_type: str, target_id: str) -> None:
        super().__init__(f"{target_type} not found: {target_id}")
        self.target_type = target_type
        self.target_id = target_id


class PortalRepository(Protocol):
    async def list_documents(
        self,
        *,
        actor: PortalActor,
        status: str | None = None,
        owner_unit_id: str | None = None,
        query: str | None = None,
    ) -> list[KnowledgeDocumentRecord]: ...

    async def get_document(self, document_id: str) -> KnowledgeDocumentRecord | None: ...

    async def save_document(self, document: KnowledgeDocumentRecord) -> KnowledgeDocumentRecord: ...

    async def get_version(self, version_id: str) -> KnowledgeVersionRecord | None: ...

    async def save_version(self, version: KnowledgeVersionRecord) -> KnowledgeVersionRecord: ...

    async def list_versions_for_document(self, document_id: str) -> list[KnowledgeVersionRecord]: ...

    async def save_review(self, review: ReviewRecord) -> ReviewRecord: ...

    async def get_review(self, review_id: str) -> ReviewRecord | None: ...

    async def get_open_review_for_version(self, version_id: str) -> ReviewRecord | None: ...

    async def list_pending_reviews(self, actor: PortalActor) -> list[ReviewRecord]: ...

    async def save_release(self, release: ReleaseRecord) -> ReleaseRecord: ...

    async def get_release(self, release_id: str) -> ReleaseRecord | None: ...

    async def list_releases(self) -> list[ReleaseRecord]: ...

    async def get_active_release_id(self) -> str | None: ...

    async def set_active_release_id(self, release_id: str | None) -> None: ...

    async def append_audit(self, event: AuditEventRecord) -> AuditEventRecord: ...

    async def list_audit_events(self, *, limit: int = 100) -> list[AuditEventRecord]: ...

    async def save_test_case(self, test_case: TestCaseRecord) -> TestCaseRecord: ...

    async def list_test_cases(self, version_id: str) -> list[TestCaseRecord]: ...

    async def save_test_run(self, test_run: TestRunRecord) -> TestRunRecord: ...

    async def list_test_runs(self, version_id: str) -> list[TestRunRecord]: ...

    async def get_idempotency(self, key: str) -> IdempotencyRecord | None: ...

    async def save_idempotency(self, record: IdempotencyRecord) -> None: ...

    async def acquire_publish_lease(self, owner: str, ttl_seconds: float = 30.0) -> bool: ...

    async def release_publish_lease(self, owner: str) -> None: ...

    async def dashboard_summary(self, actor: PortalActor) -> DashboardSummary: ...


def count_review_due_soon(
    documents: list[KnowledgeDocumentRecord],
    *,
    version_lookup,
) -> int:
    today = datetime.now(UTC).date()
    horizon = today + timedelta(days=30)
    count = 0
    for document in documents:
        if document.status != "PUBLISHED" or not document.current_published_version_id:
            continue
        version = version_lookup(document.current_published_version_id)
        if version is None:
            continue
        try:
            due = date.fromisoformat(version.review_due_at)
        except ValueError:
            continue
        if today <= due <= horizon:
            count += 1
    return count


class InMemoryPortalRepository:
    def __init__(self) -> None:
        self.documents: dict[str, KnowledgeDocumentRecord] = {}
        self.versions: dict[str, KnowledgeVersionRecord] = {}
        self.reviews: dict[str, ReviewRecord] = {}
        self.releases: dict[str, ReleaseRecord] = {}
        self.audit_events: list[AuditEventRecord] = []
        self.test_cases: dict[str, TestCaseRecord] = {}
        self.test_runs: dict[str, TestRunRecord] = {}
        self.idempotency_records: dict[str, IdempotencyRecord] = {}
        self.active_release_id: str | None = None
        self._lease_lock = asyncio.Lock()
        self._publish_lease_owner: str | None = None
        self._publish_lease_expires_at: datetime | None = None

    async def list_documents(
        self,
        *,
        actor: PortalActor,
        status: str | None = None,
        owner_unit_id: str | None = None,
        query: str | None = None,
    ) -> list[KnowledgeDocumentRecord]:
        items = list(self.documents.values())
        items = [item for item in items if item.status != "DISCARDED"]
        if actor.role != "PLATFORM":
            if actor.tenant_id:
                items = [
                    item
                    for item in items
                    if item.tenant_id is None or item.tenant_id == actor.tenant_id
                ]
            if actor.owner_unit_ids:
                items = [
                    item
                    for item in items
                    if item.owner_unit_id in actor.owner_unit_ids
                    or item.created_by == actor.user_id
                ]
        if status:
            items = [item for item in items if item.status == status]
        if owner_unit_id:
            items = [item for item in items if item.owner_unit_id == owner_unit_id]
        if query:
            needle = query.casefold()
            items = [
                item
                for item in items
                if needle in item.title.casefold() or needle in item.summary.casefold()
            ]
        return sorted(items, key=lambda item: item.updated_at, reverse=True)

    async def get_document(self, document_id: str) -> KnowledgeDocumentRecord | None:
        return self.documents.get(document_id)

    async def save_document(self, document: KnowledgeDocumentRecord) -> KnowledgeDocumentRecord:
        self.documents[document.document_id] = document
        return document

    async def get_version(self, version_id: str) -> KnowledgeVersionRecord | None:
        return self.versions.get(version_id)

    async def save_version(self, version: KnowledgeVersionRecord) -> KnowledgeVersionRecord:
        self.versions[version.version_id] = version
        return version

    async def list_versions_for_document(self, document_id: str) -> list[KnowledgeVersionRecord]:
        return [
            version
            for version in self.versions.values()
            if version.document_id == document_id
        ]

    async def save_review(self, review: ReviewRecord) -> ReviewRecord:
        self.reviews[review.review_id] = review
        return review

    async def get_review(self, review_id: str) -> ReviewRecord | None:
        return self.reviews.get(review_id)

    async def get_open_review_for_version(self, version_id: str) -> ReviewRecord | None:
        for review in self.reviews.values():
            if review.version_id == version_id and review.decision is None:
                return review
        return None

    async def list_pending_reviews(self, actor: PortalActor) -> list[ReviewRecord]:
        if actor.role not in {"REVIEWER", "MANAGER", "PLATFORM"}:
            return []
        return [
            review
            for review in self.reviews.values()
            if review.decision is None
        ]

    async def save_release(self, release: ReleaseRecord) -> ReleaseRecord:
        self.releases[release.release_id] = release
        return release

    async def get_release(self, release_id: str) -> ReleaseRecord | None:
        return self.releases.get(release_id)

    async def list_releases(self) -> list[ReleaseRecord]:
        return sorted(self.releases.values(), key=lambda item: item.created_at, reverse=True)

    async def get_active_release_id(self) -> str | None:
        return self.active_release_id

    async def set_active_release_id(self, release_id: str | None) -> None:
        self.active_release_id = release_id

    async def append_audit(self, event: AuditEventRecord) -> AuditEventRecord:
        self.audit_events.insert(0, event)
        return event

    async def list_audit_events(self, *, limit: int = 100) -> list[AuditEventRecord]:
        return self.audit_events[:limit]

    async def save_test_case(self, test_case: TestCaseRecord) -> TestCaseRecord:
        self.test_cases[test_case.test_case_id] = test_case
        return test_case

    async def list_test_cases(self, version_id: str) -> list[TestCaseRecord]:
        return [
            item for item in self.test_cases.values() if item.version_id == version_id
        ]

    async def save_test_run(self, test_run: TestRunRecord) -> TestRunRecord:
        self.test_runs[test_run.test_run_id] = test_run
        return test_run

    async def list_test_runs(self, version_id: str) -> list[TestRunRecord]:
        return [
            item for item in self.test_runs.values() if item.version_id == version_id
        ]

    async def get_idempotency(self, key: str) -> IdempotencyRecord | None:
        return self.idempotency_records.get(key)

    async def save_idempotency(self, record: IdempotencyRecord) -> None:
        self.idempotency_records[record.key] = record

    async def acquire_publish_lease(self, owner: str, ttl_seconds: float = 30.0) -> bool:
        async with self._lease_lock:
            now = datetime.now(UTC)
            if self._publish_lease_owner is not None and self._publish_lease_expires_at is not None:
                if self._publish_lease_owner == owner:
                    self._publish_lease_expires_at = now + timedelta(seconds=ttl_seconds)
                    return True
                if now < self._publish_lease_expires_at:
                    return False
            self._publish_lease_owner = owner
            self._publish_lease_expires_at = now + timedelta(seconds=ttl_seconds)
            return True

    async def release_publish_lease(self, owner: str) -> None:
        async with self._lease_lock:
            if self._publish_lease_owner == owner:
                self._publish_lease_owner = None
                self._publish_lease_expires_at = None

    async def dashboard_summary(self, actor: PortalActor) -> DashboardSummary:
        documents = await self.list_documents(actor=actor)
        pending_reviews = await self.list_pending_reviews(actor)
        active_release_id = await self.get_active_release_id()
        active_release = (
            self.releases.get(active_release_id) if active_release_id else None
        )
        return DashboardSummary(
            my_drafts=sum(1 for item in documents if item.status == "DRAFT"),
            my_changes_requested=sum(
                1 for item in documents if item.status == "CHANGES_REQUESTED"
            ),
            pending_review=len(pending_reviews),
            publish_failed=sum(
                1 for item in documents if item.status == "PUBLISH_FAILED"
            ),
            review_due_soon=count_review_due_soon(
                documents,
                version_lookup=self.versions.get,
            ),
            active_release_id=active_release_id,
            active_release_activated_at=active_release.activated_at
            if active_release
            else None,
        )


def build_repository(settings) -> PortalRepository:
    if settings.repository_mode == "MEMORY":
        return InMemoryPortalRepository()
    if settings.repository_mode == "FILE":
        from .file_repository import FilePortalRepository

        return FilePortalRepository(settings.state_path)
    if settings.repository_mode == "FIRESTORE":
        from .firestore_repository import FirestorePortalRepository

        return FirestorePortalRepository(settings)
    raise ValueError(f"Unsupported repository mode: {settings.repository_mode}")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
