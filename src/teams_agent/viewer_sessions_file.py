"""File-backed viewer membership store with cross-process sync."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from time import time
from typing import Any

from .viewer_sessions_types import (
    AuthoritativeRevocationResolver,
    ViewerMembership,
)


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
            groups=tuple(sorted({str(item).strip() for item in groups if str(item).strip()})),
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


__all__ = ["FileBackedViewerMembershipStore"]
