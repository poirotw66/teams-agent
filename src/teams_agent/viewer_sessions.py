"""Live viewer membership cache for citation re-authorization.

Signed source URLs bind a subject identity. ACL groups are never trusted from
the URL: every open must re-resolve the subject's current membership from this
cache (refreshed on each authenticated bot turn) or an injected resolver.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import time
from typing import Protocol


@dataclass(frozen=True)
class ViewerMembership:
    subject: str
    groups: tuple[str, ...] = ()
    tenant_id: str | None = None
    revoked: bool = False
    expires_at: float = 0.0


class ViewerMembershipResolver(Protocol):
    def resolve(self, subject: str) -> ViewerMembership | None: ...


class InMemoryViewerMembershipStore:
    """Process-local membership cache updated from live Teams/Playground turns."""

    def __init__(self, *, default_ttl_seconds: float = 3600.0) -> None:
        self._default_ttl_seconds = max(30.0, float(default_ttl_seconds))
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


_DEFAULT_STORE = InMemoryViewerMembershipStore()


def default_viewer_membership_store() -> InMemoryViewerMembershipStore:
    return _DEFAULT_STORE
