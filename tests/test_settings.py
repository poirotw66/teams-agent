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


def test_google_identity_token_uses_cloud_run_origin_as_audience() -> None:
    settings = AgentSettings(
        mode="api",
        api_url="https://rag-agent.example.run.app/agent/chat",
        api_auth_mode="google_id_token",
    )

    settings.validate()

    assert settings.resolved_api_audience == "https://rag-agent.example.run.app"


def test_user_directory_mode_defaults_to_disabled() -> None:
    settings = AgentSettings()

    settings.validate()

    assert settings.user_directory_mode == "disabled"


def test_user_directory_mode_rejects_unknown_value() -> None:
    settings = AgentSettings(user_directory_mode="not-a-mode")

    with pytest.raises(SettingsError, match="USER_DIRECTORY_MODE"):
        settings.validate()


def test_resolved_feedback_url_derives_from_api_url() -> None:
    settings = AgentSettings(
        mode="api",
        api_url="https://agent.example.run.app/agent/chat",
    )

    assert settings.resolved_feedback_url == "https://agent.example.run.app/feedback"


def test_resolved_feedback_url_is_none_without_api_url() -> None:
    settings = AgentSettings()

    assert settings.resolved_feedback_url is None
