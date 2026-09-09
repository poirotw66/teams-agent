"""Teams Agentic RAG FastAPI assembly entry."""

from __future__ import annotations

from fastapi import FastAPI

from .deps import make_authorize
from .lifespan import build_lifespan
from .routers import (
    register_chat_routes,
    register_feedback_routes,
    register_health_routes,
    register_knowledge_admin_routes,
    register_ops_health_routes,
    register_retrieval_routes,
)
from .settings import RagSettings


def create_app(settings: RagSettings | None = None) -> FastAPI:
    resolved_settings = settings or RagSettings.from_env()
    authorize = make_authorize(resolved_settings)

    app = FastAPI(
        title="Teams Agentic RAG Service",
        version="0.1.0",
        lifespan=build_lifespan(resolved_settings),
    )

    register_health_routes(app, resolved_settings=resolved_settings)
    register_knowledge_admin_routes(
        app, resolved_settings=resolved_settings, authorize=authorize
    )
    register_chat_routes(
        app, resolved_settings=resolved_settings, authorize=authorize
    )
    register_ops_health_routes(app, authorize=authorize)
    register_feedback_routes(app, authorize=authorize)
    register_retrieval_routes(
        app, resolved_settings=resolved_settings, authorize=authorize
    )

    return app


app = create_app()
