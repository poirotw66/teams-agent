"""Agent reload HTTP client used after release activation.

Extracted from ``ReleaseService._notify_agent_reload`` without changing
request shape, auth modes, or success/failure classification.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable

import httpx

from .ports import fetch_google_id_token

logger = logging.getLogger(__name__)

FetchIdToken = Callable[[str], str]


async def notify_agent_reload(
    *,
    agent_api_url: str | None,
    agent_api_auth_mode: str | None,
    agent_api_token: str | None,
    release_id: str,
    correlation_id: str,
    fetch_id_token: FetchIdToken = fetch_google_id_token,
) -> tuple[bool, str | None]:
    """POST reload-knowledge to the Agent API.

    Returns ``(success, error_message)``. When ``agent_api_url`` is unset,
    treats reload as a no-op success (local / offline deployments).
    """
    if not agent_api_url:
        return True, None

    target_url = f"{agent_api_url.rstrip('/')}/admin/reload-knowledge"
    headers = {
        "Content-Type": "application/json",
        "X-Correlation-ID": correlation_id,
    }
    if agent_api_auth_mode == "GOOGLE_ID_TOKEN":
        identity_token = await asyncio.to_thread(fetch_id_token, agent_api_url)
        headers["Authorization"] = f"Bearer {identity_token}"
    elif agent_api_token:
        headers["Authorization"] = f"Bearer {agent_api_token}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                target_url,
                json={"releaseId": release_id},
                headers=headers,
            )
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    returned_release = data.get("releaseId")
                    if returned_release and returned_release != release_id:
                        err_msg = (
                            f"Agent reload returned release '{returned_release}' "
                            f"which does not match expected '{release_id}'"
                        )
                        logger.warning(err_msg)
                        return False, err_msg
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
                logger.info(
                    "Agent reload acknowledged for release %s (correlation_id=%s)",
                    release_id,
                    correlation_id,
                )
                return True, None
            err_msg = f"Agent reload returned HTTP {resp.status_code}: {resp.text[:200]}"
            logger.warning(
                "Agent reload failed for release %s: %s",
                release_id,
                err_msg,
            )
            return False, err_msg
    except Exception as exc:  # noqa: BLE001 - boundary: network/client errors
        err_msg = f"Agent reload error: {exc}"
        logger.warning(
            "Agent reload request failed for release %s: %s",
            release_id,
            err_msg,
        )
        return False, err_msg


__all__ = ["notify_agent_reload"]
