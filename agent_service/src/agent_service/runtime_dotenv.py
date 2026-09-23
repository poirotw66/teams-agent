"""Load local dotenv files at application entrypoints only.

Importing ``agent_service.settings`` must not call ``load_dotenv``. Tests and
library imports therefore see process environment only; CLI / ASGI / worker
entrypoints call ``load_runtime_dotenv`` before reading settings from env.
"""

from __future__ import annotations

from os import environ
from pathlib import Path

from dotenv import load_dotenv

_LOADED = False


def load_runtime_dotenv(*, dotenv_path: Path | str | None = None) -> bool:
    """Load dotenv once per process and strip trailing CR from env values.

    Returns True when this call performed the load (first successful invocation).
    Subsequent calls are no-ops and return False.
    """
    global _LOADED
    if _LOADED:
        return False

    if dotenv_path is None:
        load_dotenv()
    else:
        load_dotenv(dotenv_path, override=False)

    # Normalize dotenv values that may retain trailing CR on Windows-edited files.
    for key, value in list(environ.items()):
        if "\r" in value:
            environ[key] = value.replace("\r", "")

    _LOADED = True
    return True


def reset_runtime_dotenv_for_tests() -> None:
    """Allow tests to re-invoke ``load_runtime_dotenv`` in the same process."""
    global _LOADED
    _LOADED = False
