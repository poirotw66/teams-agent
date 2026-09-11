"""Signed citation links for knowledge source markdown files.

Knowledge citations often arrive without a formal document URL. When the Agent
Service includes ``sourcePath``, the adapter mints a short-lived signed URL under
``/rag-sources/`` so Playground and Teams can render clickable markdown links.
Historical conversation storage still keeps ``sourceRefId``; these URLs are for
display only (same pattern as ``/rag-assets/`` images).

Portal releases store derived markdown under ``data/releases/{releaseId}/sources/``
(hashed ``doc--*.md`` names). Bundled corpus files may still live at
``data/sources/*.md``. Delivery paths prefer the release-scoped location when a
``releaseId`` is present or the active release pointer resolves the file.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import re
from dataclasses import replace
from pathlib import Path, PurePosixPath
from time import time
from urllib.parse import quote

from .contracts import AgentResponse, Citation
from .settings import AgentSettings

_SOURCE_SIGN_PREFIX = "rag-source\n"
_ALLOWED_SUFFIXES = {".md", ".markdown", ".txt", ".pdf"}
_SAFE_RELEASE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def sign_source_path(path: str, expires: int, key: str) -> str:
    payload = f"{_SOURCE_SIGN_PREFIX}{path}\n{expires}".encode()
    return hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()


def active_release_id(settings: AgentSettings) -> str | None:
    source_dir = (settings.source_dir or Path()).resolve()
    pointer = source_dir / "releases" / "active_release.json"
    if not pointer.is_file():
        return None
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = payload.get("releaseId") or payload.get("release_id")
    if not isinstance(value, str) or not _SAFE_RELEASE_ID.fullmatch(value):
        return None
    return value


def citation_delivery_path(
    source_path: str,
    settings: AgentSettings,
    *,
    release_id: str | None = None,
) -> str | None:
    """Map a citation sourcePath to a filesystem-relative delivery path."""

    pure_path = _normalize_source_path(source_path)
    if pure_path is None:
        return None
    path = pure_path.as_posix()
    if path.startswith("releases/"):
        return path

    source_root = (settings.source_dir or Path()).resolve()
    direct = source_root / path
    preferred_release = (release_id or "").strip() or active_release_id(settings)
    if preferred_release and _SAFE_RELEASE_ID.fullmatch(preferred_release):
        release_relative = f"releases/{preferred_release}/{path}"
        release_file = source_root / release_relative
        if release_file.is_file():
            return release_relative
        # Portal release artifacts use hashed doc--* filenames that only exist
        # under the release tree, not under the bundled corpus directory.
        if pure_path.name.startswith("doc--"):
            return release_relative

    if direct.is_file():
        return path
    return path


def build_source_url(
    path: str,
    settings: AgentSettings,
    now: int | None = None,
    *,
    release_id: str | None = None,
) -> str | None:
    if not settings.sources_ready:
        return None
    delivery = citation_delivery_path(path, settings, release_id=release_id)
    if delivery is None:
        return None
    issued_at = int(time()) if now is None else now
    expires = issued_at + settings.asset_url_ttl_seconds
    signature = sign_source_path(
        delivery, expires, settings.asset_signing_key or ""
    )
    encoded_path = quote(delivery, safe="/")
    return (
        f"{settings.public_base_url}/rag-sources/{encoded_path}"
        f"?expires={expires}&signature={signature}"
    )


def resolve_source_file(
    path: str,
    expires: str | None,
    signature: str | None,
    settings: AgentSettings,
    now: int | None = None,
) -> Path:
    if not settings.sources_ready:
        raise PermissionError("RAG source delivery is not configured.")
    try:
        expiry = int(expires or "")
    except ValueError as error:
        raise PermissionError("Invalid source expiry.") from error
    current_time = int(time()) if now is None else now
    if expiry < current_time or expiry > current_time + settings.asset_url_ttl_seconds:
        raise PermissionError("Source URL has expired or has an invalid lifetime.")

    pure_path = _normalize_source_path(path)
    if pure_path is None:
        raise PermissionError("Invalid source path.")
    delivery = pure_path.as_posix()
    expected = sign_source_path(
        delivery, expiry, settings.asset_signing_key or ""
    )
    if not signature or not hmac.compare_digest(signature, expected):
        raise PermissionError("Invalid source signature.")

    source_dir = (settings.source_dir or Path()).resolve()
    resolved = (source_dir / pure_path).resolve()
    try:
        resolved.relative_to(source_dir)
    except ValueError as error:
        raise PermissionError("Invalid source path.") from error
    if not resolved.is_file():
        # Legacy unsigned-style links may still point at sources/doc--*.md.
        # Fall back to the active release artifact when present.
        if not delivery.startswith("releases/"):
            fallback = citation_delivery_path(delivery, settings)
            if fallback and fallback != delivery:
                candidate = (source_dir / fallback).resolve()
                try:
                    candidate.relative_to(source_dir)
                except ValueError as error:
                    raise PermissionError("Invalid source path.") from error
                if candidate.is_file():
                    resolved = candidate
                else:
                    raise FileNotFoundError(path)
            else:
                raise FileNotFoundError(path)
        else:
            raise FileNotFoundError(path)
    if resolved.suffix.lower() not in _ALLOWED_SUFFIXES:
        raise PermissionError("Unsupported source file type.")
    return resolved


def source_media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    if path.suffix.lower() in {".md", ".markdown"}:
        return "text/markdown; charset=utf-8"
    return "text/plain; charset=utf-8"


def enrich_citation_urls(
    response: AgentResponse,
    settings: AgentSettings,
    *,
    now: int | None = None,
) -> AgentResponse:
    """Fill missing citation URLs from ``sourcePath`` when delivery is ready."""

    if not response.citations or not settings.sources_ready:
        return response
    enriched: list[Citation] = []
    changed = False
    for citation in response.citations:
        if citation.url or not citation.sourcePath:
            enriched.append(citation)
            continue
        url = build_source_url(
            citation.sourcePath,
            settings,
            now=now,
            release_id=citation.releaseId,
        )
        if not url:
            enriched.append(citation)
            continue
        enriched.append(replace(citation, url=url))
        changed = True
    if not changed:
        return response
    return replace(response, citations=enriched)


def _normalize_source_path(path: str) -> PurePosixPath | None:
    candidate = str(path or "").replace("\\", "/").strip()
    if not candidate or "://" in candidate:
        return None
    pure_path = PurePosixPath(candidate)
    if pure_path.is_absolute() or ".." in pure_path.parts:
        return None
    if not pure_path.parts:
        return None
    return pure_path
