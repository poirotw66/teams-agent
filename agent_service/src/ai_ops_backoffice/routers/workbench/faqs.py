"""Workbench FAQ routes."""

from __future__ import annotations

from fastapi import FastAPI

from .context import WorkbenchRouteContext
from .faq_list_routes import register_faq_list_routes
from .faq_mutation_routes import register_faq_mutation_routes


def register_faq_routes(app: FastAPI, ctx: WorkbenchRouteContext) -> None:
    register_faq_list_routes(app, ctx)
    register_faq_mutation_routes(app, ctx)
