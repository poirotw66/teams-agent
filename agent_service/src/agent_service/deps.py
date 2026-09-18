"""Shared FastAPI dependencies and knowledge-index sync helpers."""

from __future__ import annotations

import hmac
import logging
from collections.abc import Callable

from fastapi import FastAPI, Header, HTTPException

from .deps_sync import apply_synced_knowledge_index, load_validated_release_index
from .knowledge_release import read_active_release_id, release_index_path
from .settings import RagSettings

logger = logging.getLogger(__name__)


def make_authorize(resolved_settings: RagSettings) -> Callable[..., None]:
    """Build the Bearer service-token dependency closed over ``resolved_settings``."""

    def authorize(authorization: str | None = Header(default=None)) -> None:
        expected = resolved_settings.service_token
        if not expected:
            return
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(token, expected):
            raise HTTPException(status_code=401, detail="Invalid service token.")

    return authorize


def make_evaluation_authorize(
    resolved_settings: RagSettings,
) -> Callable[..., None]:
    """Build a fail-closed capability check for full evaluation evidence."""

    expected = resolved_settings.golden_evaluation_token
    service_token = resolved_settings.service_token
    if expected and service_token and hmac.compare_digest(expected, service_token):
        raise ValueError("GOLDEN_EVALUATION_TOKEN must differ from AGENT_SERVICE_TOKEN")

    def authorize(authorization: str | None = Header(default=None)) -> None:
        if not expected:
            raise HTTPException(status_code=404, detail="Not found.")
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(token, expected):
            raise HTTPException(status_code=401, detail="Invalid evaluation token.")

    return authorize


def sync_knowledge_to_active_pointer(target_app: FastAPI, resolved_settings: RagSettings) -> bool:
    """Reload the in-memory index when the portal active-release pointer moves."""
    if (
        resolved_settings.knowledge_release_store_mode == "GCS"
        or resolved_settings.knowledge_active_release_id
    ):
        return False
    release_dir = resolved_settings.knowledge_release_dir or (
        resolved_settings.data_dir / "releases"
    )
    active_release_id = read_active_release_id(release_dir)
    if not active_release_id:
        return False
    current_release_id = getattr(target_app.state, "knowledge_release_id", None)
    if current_release_id == active_release_id:
        return False

    target_index_path = release_index_path(release_dir, active_release_id)
    if not target_index_path.exists():
        logger.warning(
            "Active release index not found for auto-sync: release_id=%s path=%s",
            active_release_id,
            target_index_path,
        )
        return False

    try:
        new_index, artifact = load_validated_release_index(
            target_app=target_app,
            resolved_settings=resolved_settings,
            release_dir=release_dir,
            active_release_id=active_release_id,
            target_index_path=target_index_path,
        )
        apply_synced_knowledge_index(
            target_app=target_app,
            resolved_settings=resolved_settings,
            new_index=new_index,
            target_index_path=target_index_path,
            active_release_id=active_release_id,
            artifact=artifact,
        )
        return True
    except Exception as err:
        logger.error(
            "Failed to auto-sync knowledge index to active pointer %s: %s",
            active_release_id,
            err,
        )
        return False
