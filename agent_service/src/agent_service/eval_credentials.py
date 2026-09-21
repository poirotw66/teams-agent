"""Credential selection for offline / live evaluation entrypoints.

Playground and ``start.sh`` keep using ``GEMINI_API_KEY`` / ``GOOGLE_API_KEY``.
Live eval scripts prefer ``GEMINI_EVAL_API_KEY`` (alias ``GOOGLE_EVAL_API_KEY``)
so embedding and answer-model quota stay isolated from interactive traffic.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_EVAL_KEY_NAMES: tuple[str, ...] = ("GEMINI_EVAL_API_KEY", "GOOGLE_EVAL_API_KEY")
_RUNTIME_KEY_NAMES: tuple[str, ...] = ("GEMINI_API_KEY", "GOOGLE_API_KEY")


def _first_nonempty(*names: str) -> tuple[str, str] | None:
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return name, value
    return None


def apply_eval_gemini_credentials(*, dotenv_path: Path | None = None) -> str:
    """Load dotenv then point runtime Gemini env vars at the eval key when set.

    Returns the env var name that supplied the active credential (for logs).
    Does not log secret values.
    """
    if dotenv_path is not None:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path, override=False)

    selected = _first_nonempty(*_EVAL_KEY_NAMES)
    if selected is not None:
        source_name, api_key = selected
        for runtime_name in _RUNTIME_KEY_NAMES:
            os.environ[runtime_name] = api_key
        logger.info(
            "eval_credentials_applied source=%s runtime=GEMINI_API_KEY+GOOGLE_API_KEY",
            source_name,
        )
        return source_name

    fallback = _first_nonempty(*_RUNTIME_KEY_NAMES)
    if fallback is not None:
        source_name, _api_key = fallback
        logger.warning(
            "eval_credentials_fallback source=%s "
            "(set GEMINI_EVAL_API_KEY to isolate eval quota from Playground)",
            source_name,
        )
        return source_name

    raise RuntimeError(
        "No Gemini API key for eval. Set GEMINI_EVAL_API_KEY (preferred) "
        "or GEMINI_API_KEY / GOOGLE_API_KEY in agent_service/.env."
    )


__all__ = ["apply_eval_gemini_credentials"]
