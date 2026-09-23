"""Enterprise service-scope evidence for routing policy.

Scope evidence vetoes premature NOT_IT / NON_IT short-circuits so in-scope
service requests reach ACL-limited retrieval. It does not generate answers
and must not unconditionally force ``route=KNOWLEDGE`` when deterministic
ticket, escalation, greeting, or assistant-meta paths already win.

Alias ownership (current bridge → future Portal UI):

* **Governed source of truth**: Knowledge Portal document / version
  ``source_aliases``, published into each release ``manifest.json``.
* **Runtime**: Prefer aliases loaded from the active release manifest when
  configured; otherwise fall back to the static P0 catalog below.
* **Document body** must not command routing — aliases are metadata only.
* Full Portal UI for editing a service directory is deferred; this module is
  the stable call-site surface while ownership moves to Portal metadata.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "EXPECTED_RELEASE_TITLES_FOR_SCOPE",
    "ServiceScopeHit",
    "catalog_entries_from_manifest_documents",
    "configure_service_scope_from_documents",
    "configure_service_scope_from_manifest",
    "configure_service_scope_from_release",
    "find_service_scope_hits",
    "get_service_catalog_audit_meta",
    "has_service_scope_evidence",
    "is_complete_service_scope_query",
    "missing_expected_release_titles",
    "reset_service_scope_catalog",
]

logger = logging.getLogger(__name__)

_MANIFEST_FILENAME = "manifest.json"

# Populated when a release catalog/manifest overlay is installed. Used for
# answer/audit metadata (spec §4); not a substitute for Portal catalog governance.
_catalog_audit_meta: dict[str, str | int | None] | None = None


def get_service_catalog_audit_meta() -> dict[str, str | int | None]:
    """Return loaded catalog schema/release identity for answer audit fields."""
    return dict(_catalog_audit_meta or {})


def _set_catalog_audit_meta(
    *,
    schema_version: int | None,
    release_id: str | None,
    source: str,
    entry_count: int,
) -> None:
    global _catalog_audit_meta
    _catalog_audit_meta = {
        "schemaVersion": schema_version,
        "releaseId": release_id,
        "source": source,
        "entryCount": entry_count,
    }


@dataclass(frozen=True)
class ServiceScopeHit:
    """One matched in-scope catalog alias."""

    service_id: str
    matched_alias: str
    canonical_title: str


@dataclass(frozen=True)
class _CatalogEntry:
    service_id: str
    aliases: tuple[str, ...]
    canonical_title: str


# FILE / local-sandbox fallback only: used when no release catalog overlay is
# loaded. Must NOT compete with ``catalog/service_catalog.json`` — when that
# release artifact is present it is the sole routing authority (no static merge).
_SEAT_RELOCATION_ALIASES: tuple[str, ...] = (
    "座位搬遷",
    "座位遷移",
    "換座位",
    "座位異動",
    "電腦聯繫單",
    "電腦聯絡單",
)

_SEAT_RELOCATION_SERVICE = ServiceScopeHit(
    service_id="seat_relocation",
    matched_alias="",
    canonical_title="座位搬遷需求",
)

# Titles expected in a complete knowledge release that covers scope catalog docs.
EXPECTED_RELEASE_TITLES_FOR_SCOPE: frozenset[str] = frozenset(
    {_SEAT_RELOCATION_SERVICE.canonical_title}
)

# Markers that a utterance is already a complete doc / process / how-to query.
_COMPLETE_DOC_PROCESS_MARKERS: tuple[str, ...] = (
    "準則",
    "需求",
    "怎麼申請",
    "如何申請",
    "怎麼填",
    "如何填",
    "申請方式",
    "聯繫單",
    "聯絡單",
    "流程",
    "規定",
    "辦法",
    "說明",
    "格式",
    "附件",
    "什麼時候",
    "何時",
    "一週前",
)

# Optional overlay from the active release manifest (None = use static only).
_governed_entries: tuple[_CatalogEntry, ...] | None = None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.strip()).casefold()


def _dedupe_aliases(*alias_groups: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for group in alias_groups:
        for alias in group:
            cleaned = str(alias).strip()
            key = _normalize(cleaned)
            if not key or key in seen:
                continue
            seen.add(key)
            ordered.append(cleaned)
    return tuple(ordered)


def _static_catalog_entries() -> tuple[_CatalogEntry, ...]:
    return (
        _CatalogEntry(
            service_id=_SEAT_RELOCATION_SERVICE.service_id,
            aliases=_SEAT_RELOCATION_ALIASES,
            canonical_title=_SEAT_RELOCATION_SERVICE.canonical_title,
        ),
    )


def catalog_entries_from_manifest_documents(
    documents: Sequence[Mapping[str, object]],
) -> tuple[_CatalogEntry, ...]:
    """Build catalog rows from release manifest (or Portal) document metadata.

    Only documents with a non-empty ``source_aliases`` list contribute. The
    document title is always included as an alias. Empty-alias documents are
    ignored so the FILE/sandbox static fallback remains available until a
    release catalog or populated Portal metadata is loaded.
    """
    entries: list[_CatalogEntry] = []
    for document in documents:
        title = str(document.get("title") or "").strip()
        if not title:
            continue
        raw_aliases = document.get("source_aliases")
        if raw_aliases is None:
            raw_aliases = document.get("sourceAliases")
        if not isinstance(raw_aliases, list) or not raw_aliases:
            continue
        aliases = _dedupe_aliases(raw_aliases, (title,))
        if not aliases:
            continue
        document_id = str(document.get("document_id") or document.get("documentId") or "").strip()
        service_id = document_id or f"title:{_normalize(title)}"
        entries.append(
            _CatalogEntry(
                service_id=service_id,
                aliases=aliases,
                canonical_title=title,
            )
        )
    return tuple(entries)


def configure_service_scope_from_documents(
    documents: Sequence[Mapping[str, object]],
    *,
    schema_version: int | None = None,
    release_id: str | None = None,
    source: str = "manifest_documents",
) -> int:
    """Install a governed overlay from document metadata. Returns entry count."""
    global _governed_entries
    _governed_entries = catalog_entries_from_manifest_documents(documents)
    _set_catalog_audit_meta(
        schema_version=schema_version,
        release_id=release_id,
        source=source,
        entry_count=len(_governed_entries),
    )
    logger.info(
        "Configured service-scope catalog from governed metadata: entries=%d",
        len(_governed_entries),
    )
    return len(_governed_entries)


def configure_service_scope_from_manifest(manifest_path: Path | str) -> int:
    """Load governed aliases from a release ``manifest.json`` path."""
    path = Path(manifest_path)
    if not path.is_file():
        reset_service_scope_catalog()
        logger.debug("Service-scope manifest missing; using static catalog: %s", path)
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        reset_service_scope_catalog()
        logger.warning(
            "Failed to load service-scope manifest %s; using static catalog: %s",
            path,
            error,
        )
        return 0
    documents = payload.get("documents") if isinstance(payload, dict) else None
    if not isinstance(documents, list):
        reset_service_scope_catalog()
        return 0
    release_id = None
    schema_version = None
    if isinstance(payload, dict):
        raw_release = payload.get("releaseId")
        if isinstance(raw_release, str) and raw_release.strip():
            release_id = raw_release.strip()
        raw_schema = payload.get("schemaVersion")
        if isinstance(raw_schema, int):
            schema_version = raw_schema
    return configure_service_scope_from_documents(
        documents,
        schema_version=schema_version,
        release_id=release_id,
        source="manifest.json",
    )


def configure_service_scope_from_release(
    release_dir: Path | str,
    release_id: str,
) -> int:
    """Load governed aliases for ``release_id`` under the releases root.

    Prefers ``catalog/service_catalog.json`` when present (packaged release
    artifact); falls back to ``manifest.json`` documents.
    """
    root = Path(release_dir) / release_id
    catalog_path = root / "catalog" / "service_catalog.json"
    if catalog_path.is_file():
        try:
            raw_payload = json.loads(catalog_path.read_text(encoding="utf-8"))
            from knowledge_core.service_catalog import (
                validate_service_catalog_payload,
            )

            payload = validate_service_catalog_payload(raw_payload)
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as error:
            logger.warning(
                "Failed to load service catalog %s; falling back to manifest: %s",
                catalog_path,
                error,
            )
        else:
            rows = payload.get("services") or []
            if isinstance(rows, list) and rows:
                documents = [
                    {
                        "document_id": (
                            item.get("documentId")
                            or item.get("linkedDocumentId")
                            or item.get("serviceId")
                        ),
                        "title": item.get("officialName") or item.get("serviceId"),
                        "source_aliases": item.get("aliases") or [],
                        "acl_groups": item.get("aclGroups") or item.get("audienceGroupIds") or [],
                    }
                    for item in rows
                    if isinstance(item, dict)
                ]
                schema_version = payload.get("schemaVersion")
                catalog_release = payload.get("releaseId")
                return configure_service_scope_from_documents(
                    documents,
                    schema_version=schema_version if isinstance(schema_version, int) else None,
                    release_id=(
                        str(catalog_release).strip()
                        if isinstance(catalog_release, str) and catalog_release.strip()
                        else release_id
                    ),
                    source="catalog/service_catalog.json",
                )
    manifest_path = root / _MANIFEST_FILENAME
    return configure_service_scope_from_manifest(manifest_path)


def reset_service_scope_catalog() -> None:
    """Clear the governed overlay so lookups use the static P0 catalog only."""
    global _governed_entries, _catalog_audit_meta
    _governed_entries = None
    _catalog_audit_meta = None


def _catalog_entries() -> tuple[tuple[str, tuple[str, ...], str], ...]:
    """Return (service_id, aliases, canonical_title) rows.

    Authority order:
    * ``catalog/service_catalog.json`` overlay → release catalog only (no
      hard-coded static merge).
    * ``manifest.json`` overlay → governed aliases win per title; static
      FILE/sandbox aliases may fill gaps for unlisted titles only.
    * No overlay → static FILE/sandbox fallback only.
    """
    static = _static_catalog_entries()
    governed = _governed_entries
    if not governed:
        return tuple(
            (entry.service_id, entry.aliases, entry.canonical_title) for entry in static
        )

    source = str((_catalog_audit_meta or {}).get("source") or "")
    if source == "catalog/service_catalog.json":
        return tuple(
            (entry.service_id, entry.aliases, entry.canonical_title)
            for entry in governed
        )

    # Manifest / document overlay (FILE sandbox transitional path): governed
    # aliases first; keep static services that the overlay did not cover.
    static_by_title = {_normalize(entry.canonical_title): entry for entry in static}
    merged: list[_CatalogEntry] = []
    seen_titles: set[str] = set()

    for entry in governed:
        title_key = _normalize(entry.canonical_title)
        seen_titles.add(title_key)
        static_match = static_by_title.get(title_key)
        if static_match is None:
            merged.append(entry)
            continue
        # Prefer governed aliases; do not re-inject static aliases that the
        # release may have deliberately dropped — only keep static service_id.
        merged.append(
            _CatalogEntry(
                service_id=static_match.service_id,
                aliases=entry.aliases,
                canonical_title=static_match.canonical_title,
            )
        )

    for entry in static:
        if _normalize(entry.canonical_title) not in seen_titles:
            merged.append(entry)

    return tuple((entry.service_id, entry.aliases, entry.canonical_title) for entry in merged)


def find_service_scope_hits(text: str) -> list[ServiceScopeHit]:
    """Return catalog hits found in ``text`` (deduped by service_id)."""
    normalized = _normalize(text)
    if not normalized:
        return []
    hits: list[ServiceScopeHit] = []
    seen: set[str] = set()
    for service_id, aliases, canonical_title in _catalog_entries():
        for alias in aliases:
            if _normalize(alias) in normalized:
                if service_id not in seen:
                    seen.add(service_id)
                    hits.append(
                        ServiceScopeHit(
                            service_id=service_id,
                            matched_alias=alias,
                            canonical_title=canonical_title,
                        )
                    )
                break
    return hits


def has_service_scope_evidence(text: str) -> bool:
    """Return True when utterance matches governed in-scope service aliases."""
    return bool(find_service_scope_hits(text))


def is_complete_service_scope_query(text: str) -> bool:
    """Return True when scope evidence is a complete doc/process query.

    Bare catalog aliases (for example ``座位遷移``) are treated as complete
    enough for a knowledge lookup against the published service document.
    Additional markers such as 準則 / 需求 / 怎麼申請 reinforce completeness.
    """
    if not has_service_scope_evidence(text):
        return False
    normalized = _normalize(text)
    if any(marker in text for marker in _COMPLETE_DOC_PROCESS_MARKERS):
        return True
    # Alias-only or alias-dominant utterances are searchable catalog requests.
    for _service_id, aliases, _title in _catalog_entries():
        for alias in aliases:
            if _normalize(alias) and _normalize(alias) in normalized:
                return True
    return False


def missing_expected_release_titles(
    release_titles: Iterable[str],
    *,
    expected: Iterable[str] | None = None,
) -> list[str]:
    """List expected scope-related titles missing from a release title set.

    Lightweight coverage helper for promote/preflight checks. Does not
    republish Portal content.
    """
    present = {title.strip() for title in release_titles if str(title).strip()}
    required = (
        frozenset(title.strip() for title in expected if str(title).strip())
        if expected is not None
        else EXPECTED_RELEASE_TITLES_FOR_SCOPE
    )
    return sorted(title for title in required if title not in present)
