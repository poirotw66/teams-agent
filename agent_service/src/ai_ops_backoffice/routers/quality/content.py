"""Register quality case content linking and draft routes."""

from __future__ import annotations

from fastapi import FastAPI

from .content_link import register_content_link_routes
from .context import QualityRouteContext
from .drafts import register_document_draft_routes, register_faq_draft_routes


def register_content_routes(app: FastAPI, ctx: QualityRouteContext) -> None:
    register_content_link_routes(app, ctx)
    register_document_draft_routes(app, ctx)
    register_faq_draft_routes(app, ctx)
