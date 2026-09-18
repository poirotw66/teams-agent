"""Run a scheduled embedding rebuild or File Search client refresh."""

from __future__ import annotations

import os
from typing import Any

import httpx

from operations_core.access import ActorContext


class ModelEffectError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def run_scheduled_effect(
    *,
    governance: Any,
    actor: ActorContext,
    config_id: str,
    version_id: str,
    reason: str,
    effect: str,
    model_id: str,
    agent_api_url: str | None,
    portal_url: str | None,
    service_token: str,
    already_scheduled: bool = False,
) -> dict[str, Any]:
    if not already_scheduled:
        governance.schedule_model(
            config_id=config_id, version_id=version_id, reason=reason, actor=actor
        )
    try:
        governance.mark_schedule_running(config_id=config_id, version_id=version_id, actor=actor)
        if effect == "reindex":
            await _reindex(portal_url, service_token, model_id)
            await _post_agent(
                agent_api_url,
                service_token,
                "/admin/model-control/embedding/adopt",
                {"expectedModelId": model_id},
            )
        elif effect == "service_refresh":
            applied = await _post_agent(
                agent_api_url,
                service_token,
                "/admin/model-control/file-search/apply",
                {"modelId": model_id},
            )
            try:
                return governance.complete_schedule(
                    config_id=config_id, version_id=version_id, actor=actor, reason=reason
                )
            except Exception:
                previous = applied.get("previousModel")
                if previous:
                    await _post_agent(
                        agent_api_url,
                        service_token,
                        "/admin/model-control/file-search/restore",
                        {"modelId": previous},
                    )
                raise
        else:
            raise ModelEffectError("component does not use a scheduled effect")
        return governance.complete_schedule(
            config_id=config_id, version_id=version_id, actor=actor, reason=reason
        )
    except Exception as exc:
        _fail_quietly(
            governance, config_id=config_id, version_id=version_id, actor=actor, error=exc
        )
        if isinstance(exc, ModelEffectError):
            raise
        raise ModelEffectError(_error_text(exc)) from exc


async def _reindex(portal_url: str | None, service_token: str, model_id: str) -> None:
    if not portal_url:
        raise ModelEffectError("knowledge portal URL is not configured")
    headers = _headers(service_token)
    headers["X-Portal-Role"] = "PLATFORM"
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{portal_url.rstrip('/')}/api/sync",
            headers=headers,
            json={"scopeType": "ALL", "scopeIds": [], "embeddingModel": model_id},
        )
    if response.status_code >= 400:
        raise ModelEffectError(f"reindex failed with HTTP {response.status_code}")


async def _post_agent(
    agent_api_url: str | None,
    service_token: str,
    path: str,
    payload: dict[str, str],
) -> dict[str, Any]:
    if not agent_api_url:
        raise ModelEffectError("agent API URL is not configured")
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{agent_api_url.rstrip('/')}{path}",
            headers=_headers(service_token),
            json=payload,
        )
    if response.status_code >= 400:
        detail = _response_detail(response)
        raise ModelEffectError(detail or f"agent apply failed with HTTP {response.status_code}")
    body = response.json()
    return body if isinstance(body, dict) else {}


def _headers(service_token: str) -> dict[str, str]:
    headers = {
        "X-Portal-User-Id": "ai-ops-model-control",
        "X-Portal-User-Name": "AI Ops Model Control",
    }
    token = (
        os.environ.get("AGENT_SERVICE_TOKEN")
        or os.environ.get("AGENT_RELOAD_TOKEN")
        or service_token
    )
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
    return ""


def _error_text(error: Exception) -> str:
    message = getattr(error, "message", None) or str(error)
    return message or type(error).__name__


def _fail_quietly(
    governance: Any,
    *,
    config_id: str,
    version_id: str,
    actor: ActorContext,
    error: Exception,
) -> None:
    try:
        governance.fail_schedule(
            config_id=config_id,
            version_id=version_id,
            reason=_error_text(error)[:240] or "scheduled model effect failed",
            actor=actor,
        )
    except Exception:
        return
