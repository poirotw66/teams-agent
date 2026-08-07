import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout
from google.auth import exceptions as google_auth_exceptions
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.id_token import fetch_id_token

from .contracts import AgentRequest, AgentResponse, FeedbackRequest
from .settings import AgentSettings

Transport = Callable[
    [str, dict[str, Any], dict[str, str], float],
    Awaitable[object],
]
IdentityTokenProvider = Callable[[str], Awaitable[str]]


class AgentGatewayError(RuntimeError):
    """Raised when the configured Agent Gateway cannot provide an answer."""


async def google_identity_token_provider(audience: str) -> str:
    return await asyncio.to_thread(
        fetch_id_token,
        GoogleAuthRequest(),
        audience,
    )


async def aiohttp_transport(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: float,
) -> object:
    timeout = ClientTimeout(total=timeout_seconds)
    async with (
        ClientSession(timeout=timeout) as session,
        session.post(url, json=payload, headers=headers) as response,
    ):
        if response.status >= 400:
            body = await response.text()
            raise AgentGatewayError(
                f"Agent API returned HTTP {response.status}: {body[:200]}"
            )
        return await response.json()


class AgentGateway:
    def __init__(
        self,
        settings: AgentSettings,
        transport: Transport = aiohttp_transport,
        identity_token_provider: IdentityTokenProvider = google_identity_token_provider,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.identity_token_provider = identity_token_provider

    async def _auth_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.api_auth_mode == "google_id_token":
            audience = self.settings.resolved_api_audience
            if not audience:
                raise AgentGatewayError("Agent API audience is not configured.")
            try:
                identity_token = await self.identity_token_provider(audience)
            except google_auth_exceptions.GoogleAuthError as error:
                raise AgentGatewayError(
                    "Unable to obtain a Google identity token."
                ) from error
            headers["Authorization"] = f"Bearer {identity_token}"
        elif self.settings.api_auth_mode == "service_token":
            headers["Authorization"] = f"Bearer {self.settings.api_token}"
        return headers

    async def answer(self, request: AgentRequest) -> AgentResponse:
        if self.settings.mode == "echo":
            return AgentResponse(
                answer=f"收到：{request.message.text}",
                traceId=request.requestId,
                correlationId=request.correlationId,
            )

        headers = await self._auth_headers()

        try:
            payload = await self.transport(
                self.settings.api_url or "",
                request.to_payload(),
                headers,
                self.settings.api_timeout_seconds,
            )
            return AgentResponse.from_payload(payload, request.requestId)
        except AgentGatewayError:
            raise
        except (TimeoutError, ClientError, TypeError, ValueError) as error:
            raise AgentGatewayError("Agent API request failed.") from error

    async def send_feedback(self, feedback: FeedbackRequest) -> None:
        """POST /feedback on the Agent Service (spec §14).

        Guarded by the same bearer/ID-token auth as `/agent/chat`. Raises
        `AgentGatewayError` on failure; the caller (teams_agent.agent) is
        responsible for logging and degrading silently for the user per
        spec §17 -- this method does not swallow errors itself so callers
        can still distinguish "not configured" from "sent".
        """
        if self.settings.mode == "echo":
            return

        feedback_url = self.settings.resolved_feedback_url
        if not feedback_url:
            raise AgentGatewayError("Agent API URL is not configured for feedback.")

        headers = await self._auth_headers()

        try:
            await self.transport(
                feedback_url,
                feedback.to_payload(),
                headers,
                self.settings.api_timeout_seconds,
            )
        except AgentGatewayError:
            raise
        except (TimeoutError, ClientError, TypeError, ValueError) as error:
            raise AgentGatewayError("Feedback submission failed.") from error
