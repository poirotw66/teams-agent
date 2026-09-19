"""Live viewer membership cache for citation re-authorization.

Signed source URLs bind a subject identity. ACL groups are never trusted from
the URL: every open must re-resolve the subject's current membership from this
cache (refreshed on each authenticated bot turn) or an injected resolver.
"""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any

from .viewer_sessions_file import FileBackedViewerMembershipStore
from .viewer_sessions_gcs import GcsViewerMembershipStore
from .viewer_sessions_memory import InMemoryViewerMembershipStore
from .viewer_sessions_types import (
    AuthoritativeRevocationResolver,
    CallableRevocationResolver,
    PreconditionConflictError,
    PreconditionFailed,
    RevocationStorageError,
    ViewerMembership,
    ViewerMembershipResolver,
)

__all__ = [
    "AuthoritativeRevocationResolver",
    "CallableRevocationResolver",
    "FileBackedViewerMembershipStore",
    "GcsViewerMembershipStore",
    "InMemoryViewerMembershipStore",
    "PreconditionConflictError",
    "PreconditionFailed",
    "RevocationStorageError",
    "ViewerMembership",
    "ViewerMembershipResolver",
    "default_viewer_membership_store",
    "get_viewer_membership_store",
]

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
        allow_fallback = bool(getattr(settings, "viewer_membership_allow_memory_fallback", False))
        with _GCS_STORES_LOCK:
            if bucket_name not in _GCS_STORES:
                _GCS_STORES[bucket_name] = GcsViewerMembershipStore(
                    bucket_name,
                    allow_memory_fallback=allow_fallback,
                )
            return _GCS_STORES[bucket_name]

    if path is not None or backend == "file":
        resolved = Path(path or "data/viewer_memberships.json").resolve()
        with _FILE_STORES_LOCK:
            if resolved not in _FILE_STORES:
                _FILE_STORES[resolved] = FileBackedViewerMembershipStore(resolved)
            return _FILE_STORES[resolved]

    return _DEFAULT_STORE
