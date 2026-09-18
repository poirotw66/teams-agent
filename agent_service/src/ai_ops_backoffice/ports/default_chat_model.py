"""Default chat-model id port so Backoffice wiring avoids Agent RagSettings."""

from __future__ import annotations

from collections.abc import Callable

__all__ = [
    "DefaultChatModelIdProvider",
    "configure_default_chat_model_id",
    "get_default_chat_model_id",
]

DefaultChatModelIdProvider = Callable[[], str | None]

_default_chat_model_id: DefaultChatModelIdProvider | None = None


def configure_default_chat_model_id(provider: DefaultChatModelIdProvider | None) -> None:
    """Register the composition-owned default chat-model id provider."""

    global _default_chat_model_id
    _default_chat_model_id = provider


def get_default_chat_model_id() -> str | None:
    if _default_chat_model_id is None:
        raise RuntimeError(
            "Default chat model id is not configured. Call "
            "configure_default_chat_model_id from composition."
        )
    return _default_chat_model_id()
