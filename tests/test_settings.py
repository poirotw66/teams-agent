import pytest

from teams_agent.settings import AgentSettings, SettingsError


def test_echo_settings_are_ready_without_api_url() -> None:
    settings = AgentSettings()

    settings.validate()

    assert settings.ready is True


def test_api_mode_requires_url() -> None:
    settings = AgentSettings(mode="api")

    with pytest.raises(SettingsError, match="AGENT_API_URL"):
        settings.validate()


def test_api_mode_rejects_insecure_remote_url() -> None:
    settings = AgentSettings(mode="api", api_url="http://agent.internal/chat")

    with pytest.raises(SettingsError, match="HTTPS"):
        settings.validate()


def test_api_mode_allows_local_http_for_development() -> None:
    settings = AgentSettings(mode="api", api_url="http://localhost:8000/agent/chat")

    settings.validate()

    assert settings.ready is True

