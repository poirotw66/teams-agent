"""Shared types, protocols, and exceptions for viewer membership stores."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

try:
    from google.cloud.exceptions import PreconditionFailed
except ImportError:

    class PreconditionFailed(Exception):  # type: ignore[no-redef]
        pass


class PreconditionConflictError(Exception):
    """Simulated CAS precondition conflict for in-memory or fallback mode."""


class RevocationStorageError(RuntimeError):
    """Raised when revocation storage state cannot be verified or updated."""


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


__all__ = [
    "AuthoritativeRevocationResolver",
    "CallableRevocationResolver",
    "PreconditionConflictError",
    "PreconditionFailed",
    "RevocationStorageError",
    "ViewerMembership",
    "ViewerMembershipResolver",
]
