"""Portal HTTP helpers for knowledge inventory and governance queries."""

from __future__ import annotations

from typing import Any

import httpx

from .query_knowledge_status import derive_index_status, normalize_format_type


async def fetch_document_inventory(
    *,
    portal_url: str,
    headers: dict[str, str],
    status: str | None,
    owner_unit_id: str | None,
    query: str | None,
) -> dict[str, Any]:
    params = {
        key: value
        for key, value in {
            "status": status,
            "owner_unit_id": owner_unit_id,
            "query": query,
        }.items()
        if value
    }
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(
                f"{portal_url}/api/documents",
                headers=headers,
                params=params,
            )
        if response.status_code >= 400:
            return {
                "status": "unavailable",
                "items": [],
                "warning": f"Portal returned HTTP {response.status_code}",
            }
        payload = response.json()
        items = payload.get("items") or []
        return {
            "status": "available",
            "items": [item for item in items if isinstance(item, dict)],
        }
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return {"status": "unavailable", "items": [], "warning": str(exc)}


async def fetch_active_release_document_ids(
    *,
    portal_url: str,
    headers: dict[str, str],
) -> set[str] | None:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(
                f"{portal_url}/api/releases",
                headers=headers,
            )
        if response.status_code >= 400:
            return None
        payload = response.json()
        releases = payload.get("items") if isinstance(payload, dict) else payload
        releases = [item for item in (releases or []) if isinstance(item, dict)]
        active = next(
            (item for item in releases if item.get("status") == "ACTIVE"),
            None,
        )
        if active is None:
            return set()
        manifest = active.get("manifest") or []
        return {
            str(entry.get("document_id"))
            for entry in manifest
            if isinstance(entry, dict) and entry.get("document_id")
        }
    except Exception:
        # Release probe is best-effort; inventory must still render.
        return None


async def fetch_document_governance(
    *,
    portal_url: str,
    headers: dict[str, str],
    document_id: str,
    indexed_document_ids: set[str] | None = None,
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(
                f"{portal_url}/api/documents/{document_id}",
                headers=headers,
            )
        if response.status_code == 404:
            return {"status": "not_found", "portalUrl": portal_url}
        if response.status_code >= 400:
            return {
                "status": "unavailable",
                "portalUrl": portal_url,
                "note": f"Portal returned HTTP {response.status_code}",
            }
        payload = response.json()
        document = payload.get("document") or {}
        published = payload.get("published_version") or {}
        draft = payload.get("draft_version") or {}
        raw_format = published.get("source_type") or draft.get("source_type") or "UNKNOWN"
        format_type = normalize_format_type(raw_format)
        # Preserve original source label for display while normalizing family.
        display_format = "PDF" if str(raw_format).upper() == "PDF" else str(raw_format or "UNKNOWN")
        parse_status = (
            "READY"
            if (published.get("parse_preview") or draft.get("parse_preview"))
            else "NOT_PARSED"
        )
        has_published = bool(
            document.get("current_published_version_id") or published.get("version_id")
        )
        index_status = derive_index_status(
            lifecycle_status=document.get("status"),
            has_published_version=has_published,
            parse_status=parse_status,
            indexed_document_ids=indexed_document_ids,
            document_id=document_id,
        )
        return {
            "status": "available",
            "portalUrl": f"{portal_url}/#document/{document_id}",
            "lifecycleStatus": document.get("status"),
            "formatType": display_format if display_format != "UNKNOWN" else format_type,
            "formatFamily": format_type,
            "parseStatus": parse_status,
            "indexStatus": index_status,
            "currentPublishedVersionId": document.get("current_published_version_id"),
            "draftVersionId": document.get("draft_version_id"),
            "statusLabel": payload.get("status_label") or document.get("status"),
        }
    except httpx.HTTPError as exc:
        return {
            "status": "unavailable",
            "portalUrl": portal_url,
            "note": str(exc),
        }
