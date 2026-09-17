import pytest

from ai_ops_backoffice.settings import BackofficeSettings


def test_source_delegation_secret_strips_secret_manager_newline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_OPS_SOURCE_DELEGATION_SECRET", "source-secret\n")

    settings = BackofficeSettings.from_env()

    assert settings.source_delegation_secret == "source-secret"
