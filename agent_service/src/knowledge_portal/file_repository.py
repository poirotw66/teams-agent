from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from .models import (
    AuditEventRecord,
    KnowledgeDocumentRecord,
    KnowledgeVersionRecord,
    ReleaseRecord,
    ReviewRecord,
    TestCaseRecord,
    TestRunRecord,
)
from .repository import InMemoryPortalRepository


class FilePortalRepository(InMemoryPortalRepository):
    """JSON-backed portal state for local bootstrap and handoff drills."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        self._loaded = False
        self._lock = asyncio.Lock()

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        async with self._lock:
            if self._loaded:
                return
            if self._path.exists():
                payload = json.loads(self._path.read_text(encoding="utf-8"))
                self.documents = {
                    item["document_id"]: KnowledgeDocumentRecord.model_validate(item)
                    for item in payload.get("documents", [])
                }
                self.versions = {
                    item["version_id"]: KnowledgeVersionRecord.model_validate(item)
                    for item in payload.get("versions", [])
                }
                self.reviews = {
                    item["review_id"]: ReviewRecord.model_validate(item)
                    for item in payload.get("reviews", [])
                }
                self.releases = {
                    item["release_id"]: ReleaseRecord.model_validate(item)
                    for item in payload.get("releases", [])
                }
                self.audit_events = [
                    AuditEventRecord.model_validate(item)
                    for item in payload.get("audit_events", [])
                ]
                self.test_cases = {
                    item["test_case_id"]: TestCaseRecord.model_validate(item)
                    for item in payload.get("test_cases", [])
                }
                self.test_runs = {
                    item["test_run_id"]: TestRunRecord.model_validate(item)
                    for item in payload.get("test_runs", [])
                }
                self.active_release_id = payload.get("active_release_id")
            self._loaded = True

    async def _persist(self) -> None:
        async with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "documents": [
                    item.model_dump(mode="json") for item in self.documents.values()
                ],
                "versions": [
                    item.model_dump(mode="json") for item in self.versions.values()
                ],
                "reviews": [item.model_dump(mode="json") for item in self.reviews.values()],
                "releases": [
                    item.model_dump(mode="json") for item in self.releases.values()
                ],
                "audit_events": [
                    item.model_dump(mode="json") for item in self.audit_events
                ],
                "test_cases": [
                    item.model_dump(mode="json") for item in self.test_cases.values()
                ],
                "test_runs": [
                    item.model_dump(mode="json") for item in self.test_runs.values()
                ],
                "active_release_id": self.active_release_id,
            }
            temporary = self._path.with_suffix(f"{self._path.suffix}.tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary, self._path)

    async def save_document(self, document: KnowledgeDocumentRecord) -> KnowledgeDocumentRecord:
        await self._ensure_loaded()
        result = await super().save_document(document)
        await self._persist()
        return result

    async def save_version(self, version: KnowledgeVersionRecord) -> KnowledgeVersionRecord:
        await self._ensure_loaded()
        result = await super().save_version(version)
        await self._persist()
        return result

    async def save_review(self, review: ReviewRecord) -> ReviewRecord:
        await self._ensure_loaded()
        result = await super().save_review(review)
        await self._persist()
        return result

    async def save_release(self, release: ReleaseRecord) -> ReleaseRecord:
        await self._ensure_loaded()
        result = await super().save_release(release)
        await self._persist()
        return result

    async def set_active_release_id(self, release_id: str | None) -> None:
        await self._ensure_loaded()
        await super().set_active_release_id(release_id)
        await self._persist()

    async def append_audit(self, event: AuditEventRecord) -> AuditEventRecord:
        await self._ensure_loaded()
        result = await super().append_audit(event)
        await self._persist()
        return result

    async def save_test_case(self, test_case: TestCaseRecord) -> TestCaseRecord:
        await self._ensure_loaded()
        result = await super().save_test_case(test_case)
        await self._persist()
        return result

    async def save_test_run(self, test_run: TestRunRecord) -> TestRunRecord:
        await self._ensure_loaded()
        result = await super().save_test_run(test_run)
        await self._persist()
        return result

    async def list_documents(self, *, actor, status=None, owner_unit_id=None, query=None):
        await self._ensure_loaded()
        return await super().list_documents(
            actor=actor,
            status=status,
            owner_unit_id=owner_unit_id,
            query=query,
        )

    async def get_document(self, document_id: str):
        await self._ensure_loaded()
        return await super().get_document(document_id)

    async def get_version(self, version_id: str):
        await self._ensure_loaded()
        return await super().get_version(version_id)

    async def list_versions_for_document(self, document_id: str):
        await self._ensure_loaded()
        return await super().list_versions_for_document(document_id)

    async def get_review(self, review_id: str):
        await self._ensure_loaded()
        return await super().get_review(review_id)

    async def get_open_review_for_version(self, version_id: str):
        await self._ensure_loaded()
        return await super().get_open_review_for_version(version_id)

    async def list_pending_reviews(self, actor):
        await self._ensure_loaded()
        return await super().list_pending_reviews(actor)

    async def get_release(self, release_id: str):
        await self._ensure_loaded()
        return await super().get_release(release_id)

    async def list_releases(self):
        await self._ensure_loaded()
        return await super().list_releases()

    async def get_active_release_id(self):
        await self._ensure_loaded()
        return await super().get_active_release_id()

    async def list_audit_events(self, *, limit: int = 100):
        await self._ensure_loaded()
        return await super().list_audit_events(limit=limit)

    async def list_test_cases(self, version_id: str):
        await self._ensure_loaded()
        return await super().list_test_cases(version_id)

    async def list_test_runs(self, version_id: str):
        await self._ensure_loaded()
        return await super().list_test_runs(version_id)

    async def dashboard_summary(self, actor):
        await self._ensure_loaded()
        return await super().dashboard_summary(actor)
