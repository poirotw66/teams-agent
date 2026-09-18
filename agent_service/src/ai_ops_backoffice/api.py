"""AI Ops Backoffice FastAPI application entrypoint."""

from __future__ import annotations

from collections.abc import Callable

import httpx
from fastapi import FastAPI

from ai_ops_backoffice.bootstrap.container import build_backoffice_container
from ai_ops_backoffice.bootstrap.error_handlers import register_exception_handlers
from ai_ops_backoffice.bootstrap.eval_prompt import build_eval_prompt_resolver
from ai_ops_backoffice.bootstrap.register_routes import bind_app_state, register_domain_routes
from ai_ops_backoffice.bootstrap.ui import UI_ASSET_VERSION
from ai_ops_backoffice.settings import BackofficeSettings

__all__ = [
    "UI_ASSET_VERSION",
    "app",
    "build_eval_prompt_resolver",
    "create_app",
]


def create_app(
    settings: BackofficeSettings | None = None,
    *,
    eval_flow_harness: object | None = None,
    knowledge_transport: httpx.AsyncBaseTransport | None = None,
    notification_transport: httpx.AsyncBaseTransport | None = None,
    sync_transport: httpx.AsyncBaseTransport | None = None,
    email_sender: Callable[[str, str, str], None] | None = None,
    eval_chat_model: object | None = None,
    eval_model_invoker: Callable[..., object] | None = None,
    eval_answering_fn: Callable[..., object] | None = None,
    portal_app_factory: Callable[..., FastAPI] | None = None,
) -> FastAPI:
    resolved_settings = settings or BackofficeSettings.from_env()
    prod_issues = resolved_settings.validate_for_production()
    if prod_issues:
        raise ValueError(f"Invalid production configuration: {'; '.join(prod_issues)}")

    container = build_backoffice_container(
        resolved_settings,
        eval_flow_harness=eval_flow_harness,
        knowledge_transport=knowledge_transport,
        notification_transport=notification_transport,
        sync_transport=sync_transport,
        email_sender=email_sender,
        eval_chat_model=eval_chat_model,
        eval_model_invoker=eval_model_invoker,
        eval_answering_fn=eval_answering_fn,
        portal_app_factory=portal_app_factory,
    )
    app = FastAPI(title="AI Operations Backoffice", lifespan=container.lifespan)
    register_exception_handlers(app)
    bind_app_state(app, container)
    register_domain_routes(app, container)
    return app


app = create_app()
