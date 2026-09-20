"""Configurable knowledge document relationships for companion injection.

Temporary hardcoded inject markers in ``document_selection`` should converge
on this catalog so Portal / release manifests can own domain rules without
shipping Chinese keyword lists in runtime source.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CATALOG_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "ops" / "knowledge_relationships.json"
)


@dataclass(frozen=True)
class KnowledgeRelationship:
    relationship_id: str
    aliases: tuple[str, ...]
    intent: str
    require_any_query_markers: tuple[str, ...]
    related_document_markers: tuple[str, ...]
    relationship: str
    owner: str
    temporary_compatibility: bool = True

    def matches_query(self, query: str) -> bool:
        if not any(alias in query for alias in self.aliases):
            return False
        if not self.require_any_query_markers:
            return True
        return any(marker in query for marker in self.require_any_query_markers)

    def matches_chunk_blob(self, blob: str) -> bool:
        return any(marker in blob for marker in self.related_document_markers)


def _parse_relationship(raw: dict[str, Any]) -> KnowledgeRelationship | None:
    relationship_id = str(raw.get("id") or "").strip()
    aliases = tuple(str(item) for item in (raw.get("aliases") or []) if str(item).strip())
    markers = tuple(
        str(item) for item in (raw.get("relatedDocumentMarkers") or []) if str(item).strip()
    )
    if not relationship_id or not aliases or not markers:
        return None
    require_any = tuple(
        str(item) for item in (raw.get("requireAnyQueryMarkers") or []) if str(item).strip()
    )
    return KnowledgeRelationship(
        relationship_id=relationship_id,
        aliases=aliases,
        intent=str(raw.get("intent") or "").strip(),
        require_any_query_markers=require_any,
        related_document_markers=markers,
        relationship=str(raw.get("relationship") or "COMPANION").strip() or "COMPANION",
        owner=str(raw.get("owner") or "knowledge-ops").strip() or "knowledge-ops",
        temporary_compatibility=bool(raw.get("temporaryCompatibility", True)),
    )


def load_knowledge_relationships(path: Path | None = None) -> tuple[KnowledgeRelationship, ...]:
    catalog_path = path or _DEFAULT_CATALOG_PATH
    if not catalog_path.is_file():
        logger.warning("knowledge relationships catalog missing: %s", catalog_path)
        return ()
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return ()
    rows = payload.get("relationships") or []
    if not isinstance(rows, list):
        return ()
    parsed: list[KnowledgeRelationship] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = _parse_relationship(row)
        if item is not None:
            parsed.append(item)
    return tuple(parsed)


@lru_cache(maxsize=4)
def default_knowledge_relationships() -> tuple[KnowledgeRelationship, ...]:
    return load_knowledge_relationships(_DEFAULT_CATALOG_PATH)


def matching_relationships(
    query: str,
    *,
    relationships: tuple[KnowledgeRelationship, ...] | None = None,
) -> list[KnowledgeRelationship]:
    catalog = relationships if relationships is not None else default_knowledge_relationships()
    return [item for item in catalog if item.matches_query(query)]


__all__ = [
    "KnowledgeRelationship",
    "default_knowledge_relationships",
    "load_knowledge_relationships",
    "matching_relationships",
]
