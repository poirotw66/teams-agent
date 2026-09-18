"""Chat-model factory port so Backoffice domains avoid Agent graph imports."""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

__all__ = [
    "ChatModelFactory",
    "configure_chat_model_factory",
    "get_chat_model_factory",
]


@runtime_checkable
class ChatModelFactory(Protocol):
    """Build a LangChain chat model, or return None when no model is configured."""

    def __call__(
        self,
        model_name: str | None,
        *,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None,
    ) -> object | None:
        ...


_chat_model_factory: ChatModelFactory | None = None


def configure_chat_model_factory(factory: ChatModelFactory | None) -> None:
    """Register the composition-owned chat-model factory for Backoffice callers."""

    global _chat_model_factory
    _chat_model_factory = factory


def get_chat_model_factory() -> ChatModelFactory:
    if _chat_model_factory is None:
        raise RuntimeError(
            "Chat model factory is not configured. Call "
            "configure_chat_model_factory from Backoffice wiring."
        )
    return _chat_model_factory
