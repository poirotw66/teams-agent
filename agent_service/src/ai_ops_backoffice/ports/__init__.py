"""Backoffice ports for Agent-backed collaborators injected at composition time."""

from __future__ import annotations

from .chat_model import (
    ChatModelFactory,
    configure_chat_model_factory,
    get_chat_model_factory,
)

__all__ = [
    "ChatModelFactory",
    "configure_chat_model_factory",
    "get_chat_model_factory",
]
