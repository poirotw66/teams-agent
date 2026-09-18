"""Agent chat and SSE streaming routes."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI

from ..settings import RagSettings
from .chat_execute_routes import register_chat_execute_routes
from .chat_stream_routes import register_chat_stream_routes


def register_chat_routes(
    app: FastAPI,
    *,
    resolved_settings: RagSettings,
    authorize: Callable[..., None],
    authorize_evaluation: Callable[..., None],
) -> None:
    register_chat_execute_routes(
        app,
        resolved_settings=resolved_settings,
        authorize=authorize,
        authorize_evaluation=authorize_evaluation,
    )
    register_chat_stream_routes(
        app,
        resolved_settings=resolved_settings,
        authorize=authorize,
    )


__all__ = ["register_chat_routes"]
