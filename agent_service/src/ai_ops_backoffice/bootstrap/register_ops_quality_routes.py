"""Ops / quality / sync / budget route registration group."""

from __future__ import annotations

from fastapi import FastAPI

from ai_ops_backoffice.bootstrap.container import BackofficeContainer
from ai_ops_backoffice.bootstrap.register_ops_core_routes import register_ops_core_routes
from ai_ops_backoffice.bootstrap.register_ops_support_routes import (
    register_ops_support_routes,
)


def register_ops_quality_routes(app: FastAPI, container: BackofficeContainer) -> None:
    register_ops_core_routes(app, container)
    register_ops_support_routes(app, container)
