"""User Directory Service (spec §3.2, §12).

Resolves a Teams/Entra user's email address via Microsoft Graph when the
Teams activity itself doesn't already carry it. Gated behind
`AgentSettings.user_directory_mode` and disabled by default so the POC can
run without any Graph API permissions granted to the bot's Entra app
registration.

Security (spec §12/§17): implementations here must never request or store a
password, verification code, or user-supplied token. The Graph call is
authenticated with the bot's own app credentials (app-only / client
credentials token), never anything obtained from the end user.
"""

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
# App-only ("client credentials") scope for Microsoft Graph. Requires the
# app's Entra app registration to be granted the User.Read.All (or
# equivalent) application permission with admin consent -- out of scope for
# this adapter to provision.
GRAPH_DEFAULT_SCOPE = "https://graph.microsoft.com/.default"
ENTRA_LOGIN_BASE_URL = "https://login.microsoftonline.com"
# Refresh a little before the token actually expires so a lookup never races
# an expiry that happens mid-request.
_TOKEN_EXPIRY_SKEW_SECONDS = 60.0

TokenProvider = Callable[[], Awaitable[str]]
GraphTransport = Callable[[str, str], Awaitable[dict[str, Any]]]
TokenTransport = Callable[[str, dict[str, str]], Awaitable[dict[str, Any]]]


class UserDirectoryService(Protocol):
    """Resolves a user's email from a stable Entra identifier."""

    async def get_email(self, entra_object_id: str | None) -> str | None: ...


class DisabledUserDirectoryService:
    """Default no-op implementation.

    Always returns None. Losing the email this way is not a hard failure:
    the Agent Service is expected to degrade by refusing ticket creation
    (spec §11.4) when no trustworthy email is available, which is the
    correct behavior for the POC rather than the adapter guessing at one.
    """

    async def get_email(self, entra_object_id: str | None) -> str | None:
        return None


@dataclass
class _CacheEntry:
    email: str | None
    expires_at: float


class GraphUserDirectoryService:
    """Looks up a user's email via `GET /users/{id}` on Microsoft Graph.

    Token acquisition is injected via `token_provider` rather than
    implemented in this class, so the Graph lookup and the auth flow stay
    independently testable. `teams_agent.agent` wires in
    `EntraAppTokenProvider`, an app-only client-credentials flow against the
    app's own Entra app registration. If no provider is supplied (e.g. Graph
    permissions were never granted), lookups fail closed and degrade to no
    email -- they never silently fabricate one.

    Lookups are cached in-process for `cache_ttl_seconds` per Entra object
    id, so a chatty conversation does not trigger a Graph call per message.
    A Graph failure (network error, permission denial, throttling, ...)
    logs a warning and degrades to `None` -- it never raises out of
    `get_email` and never breaks the Teams turn.
    """

    def __init__(
        self,
        token_provider: TokenProvider,
        transport: GraphTransport | None = None,
        cache_ttl_seconds: float = 300.0,
    ) -> None:
        self._token_provider = token_provider
        self._transport = transport or _aiohttp_graph_get
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, _CacheEntry] = {}

    async def get_email(self, entra_object_id: str | None) -> str | None:
        if not entra_object_id:
            return None

        now = time.monotonic()
        cached = self._cache.get(entra_object_id)
        if cached is not None and cached.expires_at > now:
            return cached.email

        try:
            token = await self._token_provider()
            data = await self._transport(
                f"{GRAPH_BASE_URL}/users/{entra_object_id}", token
            )
        except Exception:
            logger.warning(
                "User Directory Service Graph lookup failed for %s; "
                "degrading to no email.",
                entra_object_id,
                exc_info=True,
            )
            return None

        email = data.get("mail") or data.get("userPrincipalName")
        email = email.strip() if isinstance(email, str) and email.strip() else None
        self._cache[entra_object_id] = _CacheEntry(
            email=email, expires_at=now + self._cache_ttl_seconds
        )
        return email


async def _aiohttp_graph_get(url: str, token: str) -> dict[str, Any]:
    import aiohttp

    async with aiohttp.ClientSession() as session, session.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        params={"$select": "mail,userPrincipalName"},
    ) as response:
        response.raise_for_status()
        return await response.json()


async def _aiohttp_token_post(url: str, form: dict[str, str]) -> dict[str, Any]:
    import aiohttp

    async with aiohttp.ClientSession() as session, session.post(
        url, data=form
    ) as response:
        response.raise_for_status()
        return await response.json()


class EntraAppTokenProvider:
    """App-only (client credentials) token provider for Microsoft Graph.

    The Microsoft Teams SDK acquires its own Bot Framework tokens from the
    same Entra app registration, but 2.x exposes no public accessor for an
    arbitrary-scope app token. Rather than reach into SDK internals, this
    runs the standard OAuth 2.0 client-credentials grant directly against
    `https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token`.

    Security (spec §12/§17): only the app's own client id/secret are ever
    sent. No user password, verification code, or user-supplied token is
    requested, stored, or forwarded. The resulting token is cached in
    process until shortly before it expires and is never logged.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        tenant_id: str,
        scope: str = GRAPH_DEFAULT_SCOPE,
        transport: TokenTransport | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._tenant_id = tenant_id
        self._scope = scope
        self._transport = transport or _aiohttp_token_post
        self._token: str | None = None
        self._expires_at = 0.0

    async def __call__(self) -> str:
        now = time.monotonic()
        if self._token is not None and self._expires_at > now:
            return self._token

        payload = await self._transport(
            f"{ENTRA_LOGIN_BASE_URL}/{self._tenant_id}/oauth2/v2.0/token",
            {
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": self._scope,
            },
        )

        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("Entra token response did not contain an access token.")

        try:
            expires_in = float(payload.get("expires_in", 0))
        except (TypeError, ValueError):
            expires_in = 0.0

        self._token = token
        self._expires_at = now + max(expires_in - _TOKEN_EXPIRY_SKEW_SECONDS, 0.0)
        return token


def build_user_directory_service(
    mode: str,
    token_provider: TokenProvider | None,
    cache_ttl_seconds: float = 300.0,
) -> UserDirectoryService:
    """Factory gated by `AgentSettings.user_directory_mode`."""
    if mode == "graph":
        if token_provider is None:
            logger.warning(
                "USER_DIRECTORY_MODE=graph but no token provider is available; "
                "falling back to the disabled User Directory Service."
            )
            return DisabledUserDirectoryService()
        return GraphUserDirectoryService(
            token_provider, cache_ttl_seconds=cache_ttl_seconds
        )
    return DisabledUserDirectoryService()
