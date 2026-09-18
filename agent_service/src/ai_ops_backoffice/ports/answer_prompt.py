"""Default knowledge answer-prompt port (Agent ANSWER_PROMPT injected at composition)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = [
    "AnswerPromptProvider",
    "configure_default_answer_prompt",
    "get_default_answer_prompt",
]


@runtime_checkable
class AnswerPromptProvider(Protocol):
    def __call__(self) -> str:
        ...


_default_answer_prompt: AnswerPromptProvider | None = None


def configure_default_answer_prompt(provider: AnswerPromptProvider | None) -> None:
    """Register the composition-owned default answer prompt provider."""

    global _default_answer_prompt
    _default_answer_prompt = provider


def get_default_answer_prompt() -> str:
    if _default_answer_prompt is None:
        raise RuntimeError(
            "Default answer prompt is not configured. Call "
            "configure_default_answer_prompt from composition."
        )
    return _default_answer_prompt()
