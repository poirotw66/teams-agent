"""HTTP health probes for AI Ops backoffice components."""

from __future__ import annotations

from typing import Any

import httpx


class HealthProbeMixin:
    """Mixin providing live HTTP probes for BackofficeQueryService."""

    async def _probe_url(self, url: str | None, path: str = "/healthz") -> dict[str, str]:
        if not url:
            return {"status": "UNKNOWN", "note": "URL not configured."}
        target = f"{url.rstrip('/')}{path}"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(target)
            if response.status_code < 400:
                return {"status": "READY", "note": f"HTTP {response.status_code}"}
            return {"status": "DEGRADED", "note": f"HTTP {response.status_code}"}
        except httpx.HTTPError as exc:
            return {"status": "DOWN", "note": str(exc)}

    async def _probe_agent_functional(self, url: str | None) -> dict[str, str]:
        if not url:
            return {"status": "UNKNOWN", "note": "Agent API URL not configured."}
        target = f"{url.rstrip('/')}/healthz"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(target)
            if response.status_code >= 400:
                return {"status": "DEGRADED", "note": f"HTTP {response.status_code}"}
            payload = response.json()
            retrieval = str(payload.get("retrieval") or "")
            chunks = int(payload.get("chunks") or 0)
            if retrieval and chunks > 0:
                return {
                    "status": "READY",
                    "note": f"retrieval={retrieval}, chunks={chunks}",
                }
            return {"status": "DEGRADED", "note": "Agent health ok but retrieval index is empty."}
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return {"status": "DOWN", "note": str(exc)}

    async def _probe_retrieval_search(self, url: str | None) -> dict[str, str]:
        if not url:
            return {"status": "UNKNOWN", "note": "Agent API URL not configured."}
        target = f"{url.rstrip('/')}/retrieval/search"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.post(
                    target,
                    json={"query": "vpn", "limit": 1, "groups": []},
                )
            if response.status_code == 401:
                return {"status": "READY", "note": "Retrieval endpoint reachable (auth required)."}
            if response.status_code >= 400:
                return {"status": "DEGRADED", "note": f"HTTP {response.status_code}"}
            hits = response.json().get("hits") or []
            return {"status": "READY", "note": f"hits={len(hits)}"}
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return {"status": "DOWN", "note": str(exc)}

    async def _probe_knowledge_release(self, url: str | None) -> dict[str, Any]:
        if not url:
            return {
                "status": "UNKNOWN",
                "note": "Knowledge Portal URL not configured.",
                "releaseId": None,
                "publishedAt": None,
                "indexStatus": "UNKNOWN",
                "documentCount": 0,
            }
        headers = {
            "X-Portal-User-Id": "ai-ops-backoffice",
            "X-Portal-User-Name": "AI%20Ops%20Backoffice",
            "X-Portal-Role": "PLATFORM",
            "X-Portal-Owner-Units": self._settings.default_owner_unit_id,
        }
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(
                    f"{url.rstrip('/')}/api/releases",
                    headers=headers,
                )
            if response.status_code >= 400:
                return {
                    "status": "DOWN",
                    "note": f"Portal returned HTTP {response.status_code}",
                    "releaseId": None,
                    "publishedAt": None,
                    "indexStatus": "UNKNOWN",
                    "documentCount": 0,
                }
            return _parse_knowledge_release_payload(response.json())
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return {
                "status": "DOWN",
                "note": str(exc),
                "releaseId": None,
                "publishedAt": None,
                "indexStatus": "UNKNOWN",
                "documentCount": 0,
            }


def _parse_knowledge_release_payload(payload: Any) -> dict[str, Any]:
    releases = payload.get("items") if isinstance(payload, dict) else payload
    releases = [item for item in (releases or []) if isinstance(item, dict)]
    active = next(
        (item for item in releases if item.get("status") == "ACTIVE"),
        None,
    )
    if active is None:
        return {
            "status": "DEGRADED",
            "note": "No active Knowledge release.",
            "releaseId": None,
            "publishedAt": None,
            "indexStatus": "NOT_ACTIVE",
            "documentCount": 0,
        }
    return {
        "status": "READY",
        "note": "Active Knowledge release is available.",
        "releaseId": active.get("release_id"),
        "publishedAt": active.get("activated_at") or active.get("created_at"),
        "indexStatus": "READY",
        "documentCount": len(active.get("manifest") or []),
        "indexSettingVersion": active.get("index_setting_version"),
    }
