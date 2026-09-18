"""Example management HTTP routes (orchestrator)."""

from __future__ import annotations

from fastapi import FastAPI

from .example_doc_conversation_create_routes import (
    register_example_doc_conversation_create_routes,
)
from .example_faq_manual_create_routes import register_example_faq_manual_create_routes
from .example_mutation_routes import register_example_mutation_routes
from .example_read_routes import register_example_read_routes


def register_example_routes(
    app: FastAPI,
    *,
    resolved_settings,
    query_service,
    example_service,
    faq_service,
    current_actor,
    require_capability,
) -> None:
    kwargs = dict(
        resolved_settings=resolved_settings,
        query_service=query_service,
        example_service=example_service,
        faq_service=faq_service,
        current_actor=current_actor,
        require_capability=require_capability,
    )
    register_example_read_routes(app, **kwargs)
    register_example_faq_manual_create_routes(app, **kwargs)
    register_example_doc_conversation_create_routes(app, **kwargs)
    register_example_mutation_routes(app, **kwargs)
