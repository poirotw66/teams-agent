"""Tenant-scoped knowledge release cache path helpers.

Canonical mirror path (managed only by the GCS syncer):

    <KNOWLEDGE_RELEASE_CACHE_DIR>/tenants/<tenantId>/releases/<releaseId>/

Legacy transitional layout ``<cache>/<releaseId>/`` remains readable until
mirrors are re-verified under the tenant-scoped tree. Sandbox / draft releases
must live under ``KNOWLEDGE_RELEASE_DIR``, never inside the mirror tree.
"""

from __future__ import annotations

import re
from pathlib import Path

_SAFE_IDENTIFIER = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")

VERIFIED_MARKER_FILENAME = ".qa_snapshot_verified"
SYNC_STATUS_FILENAME = "sync_status.json"
SYNC_LOCK_FILENAME = "sync.lock"

__all__ = [
    "SYNC_LOCK_FILENAME",
    "SYNC_STATUS_FILENAME",
    "VERIFIED_MARKER_FILENAME",
    "is_verified_release_dir",
    "legacy_release_cache_dir",
    "require_safe_identifier",
    "resolve_local_release_dir",
    "resolve_mirrored_release_dir",
    "sync_lock_path",
    "sync_status_path",
    "tenant_release_cache_dir",
    "tenant_release_dir",
    "tenant_releases_root",
    "tenant_sync_root",
    "verified_marker_path",
]


def require_safe_identifier(label: str, value: str) -> str:
    if not _SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid knowledge {label} identifier.")
    return value


def tenant_sync_root(cache_root: Path, tenant_id: str) -> Path:
    safe_tenant = require_safe_identifier("tenant", tenant_id)
    return cache_root / "tenants" / safe_tenant


def tenant_releases_root(cache_root: Path, tenant_id: str) -> Path:
    return tenant_sync_root(cache_root, tenant_id) / "releases"


def tenant_release_cache_dir(cache_root: Path, tenant_id: str, release_id: str) -> Path:
    safe_release = require_safe_identifier("release", release_id)
    return tenant_releases_root(cache_root, tenant_id) / safe_release


# Alias used by the syncer.
tenant_release_dir = tenant_release_cache_dir


def legacy_release_cache_dir(cache_root: Path, release_id: str) -> Path:
    safe_release = require_safe_identifier("release", release_id)
    return cache_root / safe_release


def sync_status_path(cache_root: Path, tenant_id: str) -> Path:
    return tenant_sync_root(cache_root, tenant_id) / SYNC_STATUS_FILENAME


def sync_lock_path(cache_root: Path, tenant_id: str) -> Path:
    return tenant_sync_root(cache_root, tenant_id) / SYNC_LOCK_FILENAME


def verified_marker_path(release_dir: Path) -> Path:
    return release_dir / VERIFIED_MARKER_FILENAME


def is_verified_release_dir(release_dir: Path) -> bool:
    return verified_marker_path(release_dir).is_file() and (
        release_dir / "manifest.json"
    ).is_file()


def resolve_mirrored_release_dir(
    cache_root: Path,
    *,
    tenant_id: str,
    release_id: str,
) -> Path | None:
    """Prefer tenant-scoped mirror; fall back to legacy ``<cache>/<releaseId>``."""
    tenant_scoped = tenant_release_cache_dir(cache_root, tenant_id, release_id)
    if (tenant_scoped / "manifest.json").is_file():
        return tenant_scoped
    legacy = legacy_release_cache_dir(cache_root, release_id)
    if (legacy / "manifest.json").is_file():
        return legacy
    return None


def resolve_local_release_dir(
    cache_root: Path,
    *,
    tenant_id: str,
    release_id: str,
    require_verified: bool = True,
) -> Path | None:
    """Locate a local mirror, optionally requiring a verification marker."""
    candidate = resolve_mirrored_release_dir(
        cache_root,
        tenant_id=tenant_id,
        release_id=release_id,
    )
    if candidate is None:
        return None
    if require_verified and not is_verified_release_dir(candidate):
        return None
    return candidate
