"""Load local dotenv files at application entrypoints only.

Importing ``agent_service.settings`` must not call ``load_dotenv``. Tests and
library imports therefore see process environment only; CLI / ASGI / worker
entrypoints call ``load_runtime_dotenv`` before reading settings from env.

Vertex mode loads dotenv selectively and never copies Gemini/Google API keys
from ``.env`` into the process. Resolution is process-fixed after this load.
"""

from __future__ import annotations

from os import environ
from pathlib import Path

_LOADED = False


def load_runtime_dotenv(*, dotenv_path: Path | str | None = None) -> bool:
    """Load dotenv once per process and strip trailing CR from env values.

    Returns True when this call performed the load (first successful invocation).
    Subsequent calls are no-ops and return False.
    """
    global _LOADED
    if _LOADED:
        return False

    from .gemini_backend import load_dotenv_for_gemini_backend, resolve_gemini_backend

    load_dotenv_for_gemini_backend(dotenv_path=dotenv_path, override=False)

    for key, value in list(environ.items()):
        if "\r" in value:
            environ[key] = value.replace("\r", "")

    resolve_gemini_backend()
    _LOADED = True
    return True


def reset_runtime_dotenv_for_tests() -> None:
    """Allow tests to re-invoke ``load_runtime_dotenv`` in the same process."""
    global _LOADED
    from .gemini_backend import reset_gemini_backend_for_tests

    _LOADED = False
    reset_gemini_backend_for_tests()
