"""Read authorized Markdown sources from immutable knowledge releases."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from .settings import AgentSettings

MAX_SOURCE_DOCUMENT_BYTES = 2 * 1024 * 1024
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]+$")
_MARKDOWN_SUFFIXES = {".md", ".markdown", ".txt"}


class SourceDocumentUnavailable(RuntimeError):
    """Raised when an authorized release source cannot be loaded."""


def fetch_release_source_document(
    settings: AgentSettings,
    *,
    release_id: str,
    source_path: str,
    tenant_id: str,
) -> str:
    """Fetch one release-pinned Markdown source from private GCS."""
    if not settings.asset_gcs_bucket:
        raise SourceDocumentUnavailable("Knowledge release storage is not configured.")
    if not _SAFE_IDENTIFIER.fullmatch(release_id):
        raise SourceDocumentUnavailable("Invalid knowledge release identifier.")
    if not _SAFE_IDENTIFIER.fullmatch(tenant_id):
        raise SourceDocumentUnavailable("Invalid source tenant identifier.")

    pure_path = PurePosixPath(source_path)
    if (
        pure_path.is_absolute()
        or ".." in pure_path.parts
        or len(pure_path.parts) < 2
        or pure_path.parts[0] != "sources"
        or pure_path.suffix.lower() not in _MARKDOWN_SUFFIXES
    ):
        raise SourceDocumentUnavailable("Invalid release source path.")

    prefix = settings.asset_gcs_prefix.strip("/")
    object_name = (
        f"{prefix}/tenants/{tenant_id}/releases/{release_id}/{pure_path.as_posix()}"
    ).lstrip("/")
    value = _download_source(settings.asset_gcs_bucket, object_name)
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SourceDocumentUnavailable("Release source is not valid UTF-8.") from error


def _download_source(bucket_name: str, object_name: str) -> bytes:
    try:
        from google.api_core.exceptions import Forbidden, GoogleAPIError, NotFound
        from google.cloud import storage
    except ImportError as error:
        raise SourceDocumentUnavailable("GCS source delivery dependency is unavailable.") from error

    blob = storage.Client().bucket(bucket_name).blob(object_name)
    try:
        blob.reload()
        if blob.size is not None and blob.size > MAX_SOURCE_DOCUMENT_BYTES:
            raise SourceDocumentUnavailable("Release source exceeds the size limit.")
        value = blob.download_as_bytes()
    except NotFound as error:
        raise SourceDocumentUnavailable("Release source was not found.") from error
    except Forbidden as error:
        raise SourceDocumentUnavailable("Release source access was denied.") from error
    except GoogleAPIError as error:
        raise SourceDocumentUnavailable("Release source delivery failed.") from error
    if len(value) > MAX_SOURCE_DOCUMENT_BYTES:
        raise SourceDocumentUnavailable("Release source exceeds the size limit.")
    return value
