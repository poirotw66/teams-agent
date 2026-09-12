"""Live viewer membership cache for citation re-authorization.

Signed source URLs bind a subject identity. ACL groups are never trusted from
the URL: every open must re-resolve the subject's current membership from this
cache (refreshed on each authenticated bot turn) or an injected resolver.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import time
from typing import Any, ClassVar, Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ViewerMembership:
    subject: str
    groups: tuple[str, ...] = ()
    tenant_id: str | None = None
    revoked: bool = False
    expires_at: float = 0.0


class ViewerMembershipResolver(Protocol):
    def resolve(self, subject: str) -> ViewerMembership | None: ...


class AuthoritativeRevocationResolver(Protocol):
    """Authoritative source for checking whether a viewer/principal has been revoked."""

    def is_revoked(self, subject: str, tenant_id: str | None = None) -> bool: ...


class CallableRevocationResolver:
    """Wrapper adapting a callable or set/dict to AuthoritativeRevocationResolver."""

    def __init__(self, checker: Any) -> None:
        self._checker = checker

    def is_revoked(self, subject: str, tenant_id: str | None = None) -> bool:
        if isinstance(self._checker, (set, frozenset, list, tuple)):
            return str(subject).strip() in self._checker
        try:
            return bool(self._checker(subject, tenant_id=tenant_id))
        except TypeError:
            try:
                return bool(self._checker(subject, tenant_id))
            except TypeError:
                return bool(self._checker(subject))


class InMemoryViewerMembershipStore:
    """Process-local membership cache updated from live Teams/Playground turns."""

    def __init__(
        self,
        *,
        default_ttl_seconds: float = 3600.0,
        revocation_resolver: AuthoritativeRevocationResolver | None = None,
    ) -> None:
        self._default_ttl_seconds = max(30.0, float(default_ttl_seconds))
        self._revocation_resolver = revocation_resolver
        self._entries: dict[str, ViewerMembership] = {}
        self._lock = Lock()

    def remember(
        self,
        subject: str,
        *,
        groups: tuple[str, ...] | list[str] = (),
        tenant_id: str | None = None,
        revoked: bool = False,
        ttl_seconds: float | None = None,
        now: float | None = None,
    ) -> ViewerMembership:
        key = str(subject or "").strip()
        if not key:
            raise ValueError("Viewer subject is required.")
        issued_at = time() if now is None else float(now)
        ttl = self._default_ttl_seconds if ttl_seconds is None else float(ttl_seconds)
        entry = ViewerMembership(
            subject=key,
            groups=tuple(
                sorted({str(item).strip() for item in groups if str(item).strip()})
            ),
            tenant_id=str(tenant_id).strip() if tenant_id else None,
            revoked=bool(revoked),
            expires_at=issued_at + max(1.0, ttl),
        )
        with self._lock:
            self._entries[key] = entry
        return entry

    def resolve(self, subject: str, *, now: float | None = None) -> ViewerMembership | None:
        key = str(subject or "").strip()
        if not key:
            return None
        current = time() if now is None else float(now)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if self._revocation_resolver is not None and self._revocation_resolver.is_revoked(
                key, tenant_id=entry.tenant_id
            ):
                return ViewerMembership(
                    subject=entry.subject,
                    groups=(),
                    tenant_id=entry.tenant_id,
                    revoked=True,
                    expires_at=entry.expires_at,
                )
            if entry.expires_at < current:
                self._entries.pop(key, None)
                return None
            return entry

    def revoke(self, subject: str) -> None:
        key = str(subject or "").strip()
        if not key:
            return
        with self._lock:
            existing = self._entries.get(key)
            if existing is None:
                return
            self._entries[key] = ViewerMembership(
                subject=existing.subject,
                groups=(),
                tenant_id=existing.tenant_id,
                revoked=True,
                expires_at=existing.expires_at,
            )

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class FileBackedViewerMembershipStore:
    """Persistent, multi-instance file-backed membership store with cross-process sync."""

    def __init__(
        self,
        storage_path: str | Path,
        *,
        default_ttl_seconds: float = 3600.0,
        revocation_resolver: AuthoritativeRevocationResolver | None = None,
    ) -> None:
        self._path = Path(storage_path).resolve()
        self._default_ttl_seconds = max(30.0, float(default_ttl_seconds))
        self._revocation_resolver = revocation_resolver
        self._lock = Lock()

    def _ensure_dir(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _read_data(self, fd: int) -> dict[str, Any]:
        import json
        import os

        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, 10_000_000).decode("utf-8")
        if not raw.strip():
            return {"entries": {}}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and isinstance(parsed.get("entries"), dict):
                return parsed
        except (ValueError, UnicodeDecodeError):
            pass
        return {"entries": {}}

    def _write_data(self, fd: int, data: dict[str, Any]) -> None:
        import json
        import os

        serialized = json.dumps(data, indent=2).encode("utf-8")
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, serialized)
        os.ftruncate(fd, len(serialized))

    def remember(
        self,
        subject: str,
        *,
        groups: tuple[str, ...] | list[str] = (),
        tenant_id: str | None = None,
        revoked: bool = False,
        ttl_seconds: float | None = None,
        now: float | None = None,
    ) -> ViewerMembership:
        key = str(subject or "").strip()
        if not key:
            raise ValueError("Viewer subject is required.")
        issued_at = time() if now is None else float(now)
        ttl = self._default_ttl_seconds if ttl_seconds is None else float(ttl_seconds)
        entry = ViewerMembership(
            subject=key,
            groups=tuple(
                sorted({str(item).strip() for item in groups if str(item).strip()})
            ),
            tenant_id=str(tenant_id).strip() if tenant_id else None,
            revoked=bool(revoked),
            expires_at=issued_at + max(1.0, ttl),
        )
        self._ensure_dir()
        import fcntl
        import os

        with self._lock:
            fd = os.open(str(self._path), os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                data = self._read_data(fd)
                entries = data.get("entries", {})
                # Evict expired entries during remember
                cleaned = {
                    k: v
                    for k, v in entries.items()
                    if isinstance(v, dict) and float(v.get("expires_at", 0.0)) >= issued_at
                }
                cleaned[key] = {
                    "subject": entry.subject,
                    "groups": list(entry.groups),
                    "tenant_id": entry.tenant_id,
                    "revoked": entry.revoked,
                    "expires_at": entry.expires_at,
                }
                self._write_data(fd, {"entries": cleaned})
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
        return entry

    def resolve(self, subject: str, *, now: float | None = None) -> ViewerMembership | None:
        key = str(subject or "").strip()
        if not key:
            return None
        if not self._path.is_file():
            return None
        current = time() if now is None else float(now)
        import fcntl
        import os

        with self._lock:
            try:
                fd = os.open(str(self._path), os.O_RDONLY)
            except OSError:
                return None
            try:
                fcntl.flock(fd, fcntl.LOCK_SH)
                data = self._read_data(fd)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

        entry_data = data.get("entries", {}).get(key)
        if not isinstance(entry_data, dict):
            return None
        tenant_id = entry_data.get("tenant_id")
        if self._revocation_resolver is not None and self._revocation_resolver.is_revoked(
            key, tenant_id=tenant_id
        ):
            return ViewerMembership(
                subject=str(entry_data.get("subject", key)),
                groups=(),
                tenant_id=tenant_id,
                revoked=True,
                expires_at=float(entry_data.get("expires_at", 0.0)),
            )
        expires_at = float(entry_data.get("expires_at", 0.0))
        if expires_at < current:
            return None
        return ViewerMembership(
            subject=str(entry_data.get("subject", key)),
            groups=tuple(entry_data.get("groups", [])),
            tenant_id=tenant_id,
            revoked=bool(entry_data.get("revoked", False)),
            expires_at=expires_at,
        )

    def revoke(self, subject: str) -> None:
        key = str(subject or "").strip()
        if not key or not self._path.is_file():
            return
        import fcntl
        import os

        with self._lock:
            try:
                fd = os.open(str(self._path), os.O_RDWR)
            except OSError:
                return
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                data = self._read_data(fd)
                entries = data.get("entries", {})
                if key in entries and isinstance(entries[key], dict):
                    entries[key]["revoked"] = True
                    entries[key]["groups"] = []
                    self._write_data(fd, data)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def clear(self) -> None:
        if not self._path.is_file():
            return
        import fcntl
        import os

        with self._lock:
            try:
                fd = os.open(str(self._path), os.O_RDWR)
            except OSError:
                return
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                self._write_data(fd, {"entries": {}})
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)


class GcsViewerMembershipStore:
    """GCS-backed viewer membership store for multi-instance Cloud Run deployments.

    Persists memberships to GCS blobs so all Cloud Run instances share live
    session memberships and revocation status.
    """

    _SHARED_STORE: ClassVar[dict[str, dict[str, Any]]] = {}

    def __init__(
        self,
        bucket_name: str,
        client: Any = None,
        *,
        prefix: str = "viewer_sessions",
        allow_memory_fallback: bool = False,
        default_ttl_seconds: float = 3600.0,
        revocation_resolver: AuthoritativeRevocationResolver | None = None,
    ) -> None:
        self.bucket_name = str(bucket_name).strip()
        self.client = client
        self.prefix = prefix.strip("/")
        self._allow_memory_fallback = bool(allow_memory_fallback)
        self._default_ttl_seconds = max(30.0, float(default_ttl_seconds))
        self._revocation_resolver = revocation_resolver
        self._lock = Lock()
        if self.bucket_name not in self._SHARED_STORE:
            self._SHARED_STORE[self.bucket_name] = {"entries": {}}
        if self.client is None and not self._allow_memory_fallback:
            try:
                from google.cloud import storage

                self.client = storage.Client()
            except Exception as exc:
                logger.debug("Failed to initialize Google Cloud Storage client: %s", exc)
                if not self._allow_memory_fallback:
                    raise ValueError(
                        "GcsViewerMembershipStore requires a real GCS client or allow_memory_fallback=True."
                    ) from exc

    def _blob_name(self) -> str:
        return f"{self.prefix}/memberships.json" if self.prefix else "memberships.json"

    def _read_data(self) -> dict[str, Any]:
        if self.client is not None:
            try:
                bucket = self.client.bucket(self.bucket_name)
                blob = bucket.blob(self._blob_name())
                if blob.exists():
                    import json

                    raw = blob.download_as_text()
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict) and isinstance(parsed.get("entries"), dict):
                        return parsed
            except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
                logger.debug("Failed to read GCS blob %s: %s", self._blob_name(), exc)
            return {"entries": {}}
        return dict(self._SHARED_STORE.get(self.bucket_name, {"entries": {}}))

    def _write_data(self, data: dict[str, Any]) -> None:
        if self.client is not None:
            import json

            bucket = self.client.bucket(self.bucket_name)
            blob = bucket.blob(self._blob_name())
            serialized = json.dumps(data, indent=2)
            blob.upload_from_string(serialized, content_type="application/json")
        else:
            self._SHARED_STORE[self.bucket_name] = data

    def remember(
        self,
        subject: str,
        *,
        groups: tuple[str, ...] | list[str] = (),
        tenant_id: str | None = None,
        revoked: bool = False,
        ttl_seconds: float | None = None,
        now: float | None = None,
    ) -> ViewerMembership:
        key = str(subject or "").strip()
        if not key:
            raise ValueError("Viewer subject is required.")
        issued_at = time() if now is None else float(now)
        ttl = self._default_ttl_seconds if ttl_seconds is None else float(ttl_seconds)
        entry = ViewerMembership(
            subject=key,
            groups=tuple(
                sorted({str(item).strip() for item in groups if str(item).strip()})
            ),
            tenant_id=str(tenant_id).strip() if tenant_id else None,
            revoked=bool(revoked),
            expires_at=issued_at + max(1.0, ttl),
        )
        with self._lock:
            data = self._read_data()
            entries = data.get("entries", {})
            cleaned = {
                k: v
                for k, v in entries.items()
                if isinstance(v, dict) and float(v.get("expires_at", 0.0)) >= issued_at
            }
            cleaned[key] = {
                "subject": entry.subject,
                "groups": list(entry.groups),
                "tenant_id": entry.tenant_id,
                "revoked": entry.revoked,
                "expires_at": entry.expires_at,
            }
            self._write_data({"entries": cleaned})
        return entry

    def resolve(self, subject: str, *, now: float | None = None) -> ViewerMembership | None:
        key = str(subject or "").strip()
        if not key:
            return None
        current = time() if now is None else float(now)
        with self._lock:
            data = self._read_data()
        entry_data = data.get("entries", {}).get(key)
        if not isinstance(entry_data, dict):
            return None
        tenant_id = entry_data.get("tenant_id")
        if self._revocation_resolver is not None and self._revocation_resolver.is_revoked(
            key, tenant_id=tenant_id
        ):
            return ViewerMembership(
                subject=str(entry_data.get("subject", key)),
                groups=(),
                tenant_id=tenant_id,
                revoked=True,
                expires_at=float(entry_data.get("expires_at", 0.0)),
            )
        expires_at = float(entry_data.get("expires_at", 0.0))
        if expires_at < current:
            return None
        return ViewerMembership(
            subject=str(entry_data.get("subject", key)),
            groups=tuple(entry_data.get("groups", [])),
            tenant_id=tenant_id,
            revoked=bool(entry_data.get("revoked", False)),
            expires_at=expires_at,
        )

    def revoke(self, subject: str) -> None:
        key = str(subject or "").strip()
        if not key:
            return
        with self._lock:
            data = self._read_data()
            entries = data.get("entries", {})
            if key in entries and isinstance(entries[key], dict):
                entries[key]["revoked"] = True
                entries[key]["groups"] = []
                self._write_data({"entries": entries})

    def clear(self) -> None:
        with self._lock:
            self._write_data({"entries": {}})


_DEFAULT_STORE = InMemoryViewerMembershipStore()
_FILE_STORES: dict[Path, FileBackedViewerMembershipStore] = {}
_FILE_STORES_LOCK = Lock()
_GCS_STORES: dict[str, GcsViewerMembershipStore] = {}
_GCS_STORES_LOCK = Lock()


def default_viewer_membership_store() -> InMemoryViewerMembershipStore:
    return _DEFAULT_STORE


def get_viewer_membership_store(
    settings: Any = None,
) -> InMemoryViewerMembershipStore | FileBackedViewerMembershipStore | GcsViewerMembershipStore:
    backend = getattr(settings, "viewer_membership_backend", None)
    bucket = getattr(settings, "viewer_membership_gcs_bucket", None)
    path = getattr(settings, "viewer_membership_store_path", None)

    if backend == "gcs" or bucket:
        bucket_name = str(bucket or "default-memberships")
        with _GCS_STORES_LOCK:
            if bucket_name not in _GCS_STORES:
                _GCS_STORES[bucket_name] = GcsViewerMembershipStore(
                    bucket_name,
                    allow_memory_fallback=True,
                )
            return _GCS_STORES[bucket_name]

    if path is not None or backend == "file":
        resolved = Path(path or "data/viewer_memberships.json").resolve()
        with _FILE_STORES_LOCK:
            if resolved not in _FILE_STORES:
                _FILE_STORES[resolved] = FileBackedViewerMembershipStore(resolved)
            return _FILE_STORES[resolved]

    return _DEFAULT_STORE
