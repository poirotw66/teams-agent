"""Tests for entrypoint-only dotenv loading."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_settings_import_does_not_load_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importing settings must not pull ambient agent_service/.env into os.environ."""
    marker = "RUNTIME_DOTENV_SHOULD_NOT_APPEAR"
    monkeypatch.delenv(marker, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(f"{marker}=from-dotenv\n", encoding="utf-8")

    import importlib
    import sys

    # Force a fresh import path independent of prior session state.
    for name in list(sys.modules):
        if name == "agent_service.settings" or name.startswith("agent_service.settings."):
            sys.modules.pop(name, None)

    import agent_service.settings as settings_mod

    importlib.reload(settings_mod)

    assert os.environ.get(marker) is None
    assert not hasattr(settings_mod, "load_dotenv")


def test_load_runtime_dotenv_loads_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_service.runtime_dotenv import (
        load_runtime_dotenv,
        reset_runtime_dotenv_for_tests,
    )

    reset_runtime_dotenv_for_tests()
    env_file = tmp_path / ".env"
    env_file.write_text("RUNTIME_DOTENV_ONCE=first\n", encoding="utf-8")
    monkeypatch.delenv("RUNTIME_DOTENV_ONCE", raising=False)

    assert load_runtime_dotenv(dotenv_path=env_file) is True
    assert os.environ.get("RUNTIME_DOTENV_ONCE") == "first"
    assert load_runtime_dotenv(dotenv_path=env_file) is False

    reset_runtime_dotenv_for_tests()
