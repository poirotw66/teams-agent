"""Portal FastAPI composition with Backoffice adapters injected."""

from __future__ import annotations

from fastapi import FastAPI

from ai_ops_backoffice.adapters.platform_ports import (
    build_portal_release_gate_checker,
    build_source_catalog_writer_from_settings,
)
from composition.portal_artifact_storage import build_portal_gcs_artifact_storage
from knowledge_portal.api import create_app as create_portal_core_app
from knowledge_portal.original_assets import configure_gcs_artifact_storage_provider
from knowledge_portal.settings import PortalSettings


def create_portal_app(
    settings: PortalSettings | None = None,
    *,
    release_gate_checker: object | None = None,
    source_catalog_writer: object | None = None,
) -> FastAPI:
    resolved = settings or PortalSettings.from_env()
    configure_gcs_artifact_storage_provider(build_portal_gcs_artifact_storage)
    checker = release_gate_checker
    if checker is None:
        checker = build_portal_release_gate_checker(resolved)
    writer = source_catalog_writer
    if writer is None:
        writer = build_source_catalog_writer_from_settings(resolved)
    return create_portal_core_app(
        resolved,
        release_gate_checker=checker,
        source_catalog_writer=writer,
    )
