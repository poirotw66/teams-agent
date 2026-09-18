"""In-memory, file, and Firestore repositories for tool fixtures."""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any

from .json_record_io import iter_json_models
from .tool_fixture_models import ToolFixture, ToolFixtureVersion

__all__ = [
    "FileToolFixtureRepository",
    "FirestoreToolFixtureRepository",
    "ToolFixtureRepository",
]


class ToolFixtureRepository:
    """Thread-safe in-memory repository for tool fixtures and their versions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fixtures: dict[str, ToolFixture] = {}
        self._versions: dict[tuple[str, int], ToolFixtureVersion] = {}

    def save_fixture(self, fixture: ToolFixture) -> None:
        with self._lock:
            self._fixtures[fixture.fixture_id] = fixture

    def get_fixture(self, fixture_id: str) -> ToolFixture | None:
        with self._lock:
            return self._fixtures.get(fixture_id)

    def list_fixtures(self, tenant_id: str | None = None) -> list[ToolFixture]:
        with self._lock:
            if tenant_id:
                return [f for f in self._fixtures.values() if f.tenant_id == tenant_id]
            return list(self._fixtures.values())

    def save_version(self, version: ToolFixtureVersion) -> None:
        with self._lock:
            self._versions[(version.fixture_id, version.version)] = version

    def get_version(self, fixture_id: str, version: int) -> ToolFixtureVersion | None:
        with self._lock:
            return self._versions.get((fixture_id, version))

    def list_versions(self, fixture_id: str) -> list[ToolFixtureVersion]:
        with self._lock:
            versions = [v for (f_id, _), v in self._versions.items() if f_id == fixture_id]
            return sorted(versions, key=lambda v: v.version)


class FileToolFixtureRepository(ToolFixtureRepository):
    """Multi-process safe, file-based tool fixture repository."""

    def __init__(self, directory: Path) -> None:
        super().__init__()
        self._dir = directory
        self._fixtures_dir = self._dir / "fixtures"
        self._versions_dir = self._dir / "versions"
        self._lock_file = self._dir / ".fixtures.lock"
        self._fixtures_dir.mkdir(parents=True, exist_ok=True)
        self._versions_dir.mkdir(parents=True, exist_ok=True)
        self._sync_from_disk()

    def _sync_from_disk(self) -> None:
        with self._lock:
            self._fixtures = {
                fixture.fixture_id: fixture
                for _, fixture in iter_json_models(self._fixtures_dir, ToolFixture)
            }
            self._versions = {
                (version.fixture_id, version.version): version
                for _, version in iter_json_models(self._versions_dir, ToolFixtureVersion)
            }

    def _write_record_atomic(self, target: Path, content: str) -> None:
        import os
        import uuid

        temp = target.with_suffix(f".{uuid.uuid4().hex}.tmp")
        with temp.open("w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, target)
        if sys.platform != "win32":
            pfd = os.open(str(target.parent), os.O_RDONLY)
            try:
                os.fsync(pfd)
            finally:
                os.close(pfd)

    def _with_lock(self, fn: Any) -> Any:
        import fcntl

        self._lock_file.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_file.open("a+") as lh:
            fcntl.flock(lh.fileno(), fcntl.LOCK_EX)
            try:
                self._sync_from_disk()
                return fn()
            finally:
                fcntl.flock(lh.fileno(), fcntl.LOCK_UN)

    def save_fixture(self, fixture: ToolFixture) -> None:
        def _op() -> None:
            super(FileToolFixtureRepository, self).save_fixture(fixture)
            target = self._fixtures_dir / f"{fixture.fixture_id}.json"
            self._write_record_atomic(target, fixture.model_dump_json(indent=2))

        self._with_lock(_op)

    def get_fixture(self, fixture_id: str) -> ToolFixture | None:
        self._sync_from_disk()
        return super().get_fixture(fixture_id)

    def list_fixtures(self, tenant_id: str | None = None) -> list[ToolFixture]:
        self._sync_from_disk()
        return super().list_fixtures(tenant_id)

    def save_version(self, version: ToolFixtureVersion) -> None:
        def _op() -> None:
            super(FileToolFixtureRepository, self).save_version(version)
            target = self._versions_dir / f"{version.fixture_id}_{version.version}.json"
            self._write_record_atomic(target, version.model_dump_json(indent=2))

        self._with_lock(_op)

    def get_version(self, fixture_id: str, version: int) -> ToolFixtureVersion | None:
        self._sync_from_disk()
        return super().get_version(fixture_id, version)

    def list_versions(self, fixture_id: str) -> list[ToolFixtureVersion]:
        self._sync_from_disk()
        return super().list_versions(fixture_id)


class FirestoreToolFixtureRepository:
    """Production GCP Firestore repository for tool fixtures and fixture versions."""

    def __init__(self, client: Any, prefix: str = "ai_ops_fixture") -> None:
        self._client = client
        self._fixtures_col = self._client.collection(f"{prefix}_items")
        self._versions_col = self._client.collection(f"{prefix}_versions")

    def save_fixture(self, fixture: ToolFixture) -> None:
        import json

        self._fixtures_col.document(fixture.fixture_id).set(json.loads(fixture.model_dump_json()))

    def get_fixture(self, fixture_id: str) -> ToolFixture | None:
        doc = self._fixtures_col.document(fixture_id).get()
        if not doc.exists:
            return None
        return ToolFixture.model_validate(doc.to_dict())

    def list_fixtures(self, tenant_id: str | None = None) -> list[ToolFixture]:
        q = self._fixtures_col
        if tenant_id:
            q = q.where("tenant_id", "==", tenant_id)
        return [ToolFixture.model_validate(d.to_dict()) for d in q.stream()]

    def save_version(self, version: ToolFixtureVersion) -> None:
        import json

        doc_id = f"{version.fixture_id}_{version.version}"
        self._versions_col.document(doc_id).set(json.loads(version.model_dump_json()))

    def get_version(self, fixture_id: str, version: int) -> ToolFixtureVersion | None:
        doc_id = f"{fixture_id}_{version}"
        doc = self._versions_col.document(doc_id).get()
        if not doc.exists:
            return None
        return ToolFixtureVersion.model_validate(doc.to_dict())

    def list_versions(self, fixture_id: str) -> list[ToolFixtureVersion]:
        q = self._versions_col.where("fixture_id", "==", fixture_id)
        versions = [ToolFixtureVersion.model_validate(d.to_dict()) for d in q.stream()]
        return sorted(versions, key=lambda v: v.version)
