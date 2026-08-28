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


def test_public_base_url_allows_local_http_for_playground(tmp_path) -> None:
    settings = AgentSettings(
        asset_dir=tmp_path,
        public_base_url="http://localhost:3978",
        asset_signing_key="test-signing-key-long-enough",
        allow_unauthenticated_requests=True,
    )

    settings.validate()

    assert settings.images_ready is True


def test_public_base_url_rejects_local_http_outside_playground_mode(tmp_path) -> None:
    settings = AgentSettings(
        asset_dir=tmp_path,
        public_base_url="http://localhost:3978",
        asset_signing_key="test-signing-key-long-enough",
    )

    with pytest.raises(SettingsError, match="DANGEROUSLY_ALLOW_UNAUTHENTICATED_REQUESTS"):
        settings.validate()


def test_public_base_url_rejects_insecure_remote_url(tmp_path) -> None:
    settings = AgentSettings(
        asset_dir=tmp_path,
        public_base_url="http://adapter.internal",
        asset_signing_key="test-signing-key-long-enough",
        allow_unauthenticated_requests=True,
    )

    with pytest.raises(SettingsError, match="HTTPS"):
        settings.validate()


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


def test_entra_inbound_auth_requires_app_identity() -> None:
    settings = AgentSettings(teams_inbound_auth_mode="entra")

    with pytest.raises(SettingsError, match="CLIENT_ID and TENANT_ID"):
        settings.validate()


def test_entra_inbound_auth_accepts_app_identity() -> None:
    settings = AgentSettings(
        teams_inbound_auth_mode="entra",
        client_id="client-1",
        tenant_id="tenant-1",
    )

    settings.validate()


def test_playground_test_email_requires_a_playground_auth_mode() -> None:
    settings = AgentSettings(playground_test_user_email="playground.user@example.test")

    with pytest.raises(SettingsError, match="PLAYGROUND_TEST_USER_EMAIL"):
        settings.validate()


def test_playground_test_email_is_allowed_in_unsafe_local_mode() -> None:
    settings = AgentSettings(
        playground_test_user_email="playground.user@example.test",
        allow_unauthenticated_requests=True,
    )

    settings.validate()


def test_playground_test_email_is_allowed_for_entra_playground() -> None:
    settings = AgentSettings(
        playground_test_user_email="playground.user@example.test",
        teams_inbound_auth_mode="entra",
        client_id="client-1",
        tenant_id="tenant-1",
    )

    settings.validate()


def test_playground_test_email_is_allowed_for_both_mode() -> None:
    settings = AgentSettings(
        playground_test_user_email="playground.user@example.test",
        teams_inbound_auth_mode="both",
        client_id="client-1",
        tenant_id="tenant-1",
    )

    settings.validate()


def test_both_inbound_auth_requires_app_identity() -> None:
    settings = AgentSettings(teams_inbound_auth_mode="both")

    with pytest.raises(SettingsError, match="CLIENT_ID and TENANT_ID"):
        settings.validate()


def test_playground_identity_fallback_covers_entra_and_both() -> None:
    entra = AgentSettings(
        teams_inbound_auth_mode="entra",
        client_id="client-1",
        tenant_id="tenant-1",
    )
    both = AgentSettings(
        teams_inbound_auth_mode="both",
        client_id="client-1",
        tenant_id="tenant-1",
    )
    botframework = AgentSettings(teams_inbound_auth_mode="botframework")

    assert entra.uses_playground_identity_fallback is True
    assert both.uses_playground_identity_fallback is True
    assert botframework.uses_playground_identity_fallback is False


def test_resolved_feedback_url_derives_from_api_url() -> None:
    settings = AgentSettings(
        mode="api",
        api_url="https://agent.example.run.app/agent/chat",
    )

    assert settings.resolved_feedback_url == "https://agent.example.run.app/feedback"


def test_resolved_feedback_url_is_none_without_api_url() -> None:
    settings = AgentSettings()

    assert settings.resolved_feedback_url is None
