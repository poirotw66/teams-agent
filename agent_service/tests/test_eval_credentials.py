"""Tests for eval vs Playground Gemini credential isolation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_service.eval_credentials import apply_eval_gemini_credentials


@pytest.fixture(autouse=True)
def _clear_gemini_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "GEMINI_EVAL_API_KEY",
        "GOOGLE_EVAL_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_apply_eval_key_overrides_runtime_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "playground-key")
    monkeypatch.setenv("GEMINI_EVAL_API_KEY", "eval-key")

    source = apply_eval_gemini_credentials()

    assert source == "GEMINI_EVAL_API_KEY"
    assert os.environ["GEMINI_API_KEY"] == "eval-key"
    assert os.environ["GOOGLE_API_KEY"] == "eval-key"


def test_apply_falls_back_to_playground_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "playground-key")

    source = apply_eval_gemini_credentials()

    assert source == "GEMINI_API_KEY"
    assert os.environ["GEMINI_API_KEY"] == "playground-key"


def test_apply_raises_when_no_key_configured() -> None:
    with pytest.raises(RuntimeError, match="GEMINI_EVAL_API_KEY"):
        apply_eval_gemini_credentials()


def test_apply_loads_eval_key_from_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GEMINI_API_KEY=playground-from-file\nGEMINI_EVAL_API_KEY=eval-from-file\n",
        encoding="utf-8",
    )

    source = apply_eval_gemini_credentials(dotenv_path=env_file)

    assert source == "GEMINI_EVAL_API_KEY"
    assert os.environ["GEMINI_API_KEY"] == "eval-from-file"
    assert os.environ["GOOGLE_API_KEY"] == "eval-from-file"
