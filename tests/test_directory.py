import pytest

from teams_agent.directory import (
    DisabledUserDirectoryService,
    EntraAppTokenProvider,
    GraphUserDirectoryService,
    build_user_directory_service,
)


def make_token_provider(transport, scope: str | None = None) -> EntraAppTokenProvider:
    kwargs = {"transport": transport}
    if scope is not None:
        kwargs["scope"] = scope
    return EntraAppTokenProvider("client-1", "secret-1", "tenant-1", **kwargs)


@pytest.mark.asyncio
async def test_entra_token_provider_requests_client_credentials_grant() -> None:
    seen: dict = {}

    async def fake_transport(url: str, form: dict) -> dict:
        seen["url"] = url
        seen["form"] = form
        return {"access_token": "app-token", "expires_in": 3600}

    token = await make_token_provider(fake_transport)()

    assert token == "app-token"
    assert seen["url"].endswith("/tenant-1/oauth2/v2.0/token")
    assert seen["form"] == {
        "grant_type": "client_credentials",
        "client_id": "client-1",
        "client_secret": "secret-1",
        "scope": "https://graph.microsoft.com/.default",
    }


@pytest.mark.asyncio
async def test_entra_token_provider_caches_until_expiry() -> None:
    calls = {"count": 0}

    async def fake_transport(url: str, form: dict) -> dict:
        calls["count"] += 1
        return {"access_token": "app-token", "expires_in": 3600}

    provider = make_token_provider(fake_transport)

    assert await provider() == "app-token"
    assert await provider() == "app-token"
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_entra_token_provider_refetches_when_the_token_expires() -> None:
    calls = {"count": 0}

    async def fake_transport(url: str, form: dict) -> dict:
        calls["count"] += 1
        # expires_in below the refresh skew means the cached token is already
        # considered stale on the next call.
        return {"access_token": f"app-token-{calls['count']}", "expires_in": 1}

    provider = make_token_provider(fake_transport)

    assert await provider() == "app-token-1"
    assert await provider() == "app-token-2"


@pytest.mark.asyncio
async def test_entra_token_provider_raises_without_an_access_token() -> None:
    async def fake_transport(url: str, form: dict) -> dict:
        return {"error": "invalid_client"}

    with pytest.raises(RuntimeError, match="access token"):
        await make_token_provider(fake_transport)()


@pytest.mark.asyncio
async def test_disabled_service_always_returns_none() -> None:
    service = DisabledUserDirectoryService()

    assert await service.get_email("entra-1") is None
    assert await service.get_email(None) is None


def test_build_user_directory_service_defaults_to_disabled() -> None:
    service = build_user_directory_service("disabled", token_provider=None)

    assert isinstance(service, DisabledUserDirectoryService)


def test_build_user_directory_service_falls_back_when_graph_has_no_token_provider() -> (
    None
):
    service = build_user_directory_service("graph", token_provider=None)

    assert isinstance(service, DisabledUserDirectoryService)


def test_build_user_directory_service_builds_graph_client_when_token_provider_present() -> (
    None
):
    async def fake_token_provider() -> str:
        return "fake-token"

    service = build_user_directory_service("graph", token_provider=fake_token_provider)

    assert isinstance(service, GraphUserDirectoryService)


@pytest.mark.asyncio
async def test_graph_service_returns_none_without_entra_object_id() -> None:
    async def unexpected_token_provider() -> str:
        raise AssertionError("Token provider should not be called without an id.")

    service = GraphUserDirectoryService(token_provider=unexpected_token_provider)

    assert await service.get_email(None) is None


@pytest.mark.asyncio
async def test_graph_service_calls_token_provider_and_transport() -> None:
    calls = {"token": 0, "transport": 0}

    async def fake_token_provider() -> str:
        calls["token"] += 1
        return "fake-token"

    async def fake_transport(url: str, token: str) -> dict:
        calls["transport"] += 1
        assert token == "fake-token"
        assert url.endswith("/users/entra-1")
        return {"mail": "justin@example.com"}

    service = GraphUserDirectoryService(
        token_provider=fake_token_provider, transport=fake_transport
    )

    email = await service.get_email("entra-1")

    assert email == "justin@example.com"
    assert calls == {"token": 1, "transport": 1}


@pytest.mark.asyncio
async def test_graph_service_falls_back_to_user_principal_name() -> None:
    async def fake_token_provider() -> str:
        return "fake-token"

    async def fake_transport(url: str, token: str) -> dict:
        return {"mail": None, "userPrincipalName": "justin@example.onmicrosoft.com"}

    service = GraphUserDirectoryService(
        token_provider=fake_token_provider, transport=fake_transport
    )

    email = await service.get_email("entra-1")

    assert email == "justin@example.onmicrosoft.com"


@pytest.mark.asyncio
async def test_graph_service_caches_results_within_ttl() -> None:
    calls = {"transport": 0}

    async def fake_token_provider() -> str:
        return "fake-token"

    async def fake_transport(url: str, token: str) -> dict:
        calls["transport"] += 1
        return {"mail": "justin@example.com"}

    service = GraphUserDirectoryService(
        token_provider=fake_token_provider,
        transport=fake_transport,
        cache_ttl_seconds=300,
    )

    first = await service.get_email("entra-1")
    second = await service.get_email("entra-1")

    assert first == second == "justin@example.com"
    assert calls["transport"] == 1


@pytest.mark.asyncio
async def test_graph_service_degrades_to_none_on_transport_failure() -> None:
    async def fake_token_provider() -> str:
        return "fake-token"

    async def failing_transport(url: str, token: str) -> dict:
        raise RuntimeError("Graph is down")

    service = GraphUserDirectoryService(
        token_provider=fake_token_provider, transport=failing_transport
    )

    email = await service.get_email("entra-1")

    assert email is None


@pytest.mark.asyncio
async def test_graph_service_degrades_to_none_on_token_failure() -> None:
    async def failing_token_provider() -> str:
        raise RuntimeError("No permissions")

    async def unexpected_transport(url: str, token: str) -> dict:
        raise AssertionError("Transport should not run without a token.")

    service = GraphUserDirectoryService(
        token_provider=failing_token_provider, transport=unexpected_transport
    )

    email = await service.get_email("entra-1")

    assert email is None
