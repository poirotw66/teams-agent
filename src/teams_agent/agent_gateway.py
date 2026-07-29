import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .contracts import AgentRequest, AgentResponse
from .settings import AgentSettings

Transport = Callable[
    [str, dict[str, Any], dict[str, str], float],
    Awaitable[object],
]


class AgentGatewayError(RuntimeError):
    """Raised when the configured Agent Gateway cannot provide an answer."""


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
    ) -> None:
        self.settings = settings
        self.transport = transport

    async def answer(self, request: AgentRequest) -> AgentResponse:
        if self.settings.mode == "echo":
            return AgentResponse(
                answer=f"收到：{request.message.text}",
                traceId=request.requestId,
            )

        headers = {"Content-Type": "application/json"}
        if self.settings.api_token:
            headers["Authorization"] = f"Bearer {self.settings.api_token}"

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
        except (asyncio.TimeoutError, ClientError, TypeError, ValueError) as error:
            raise AgentGatewayError("Agent API request failed.") from error
