import asyncio
import codecs
import json
from collections.abc import AsyncIterator, Awaitable, Callable
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
# Yields raw SSE blocks (the text between blank lines) from a POST.
StreamTransport = Callable[
    [str, dict[str, Any], dict[str, str], float],
    AsyncIterator[str],
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


async def aiohttp_stream_transport(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: float,
) -> AsyncIterator[str]:
    """POST and yield Server-Sent Event blocks as they arrive.

    `sock_read` rather than `total` is the timeout that matters here: a
    streamed response is open for as long as the workflow runs, so a total
    deadline would cut off long-but-healthy answers. What must not happen is
    the connection going quiet, which `sock_read` bounds per chunk.

    Decoding runs through an incremental decoder because TCP chunk
    boundaries fall wherever they like -- including the middle of a
    multi-byte character. Decoding each chunk on its own would turn a split
    character into replacement characters. The Agent Service currently
    escapes non-ASCII in its JSON, which would hide the bug; this must not
    depend on that.
    """
    timeout = ClientTimeout(total=None, sock_connect=timeout_seconds, sock_read=timeout_seconds)
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    async with (
        ClientSession(timeout=timeout) as session,
        session.post(url, json=payload, headers=headers) as response,
    ):
        if response.status >= 400:
            body = await response.text()
            raise AgentGatewayError(
                f"Agent API returned HTTP {response.status}: {body[:200]}"
            )
        buffer = ""
        async for chunk in response.content.iter_any():
            buffer += decoder.decode(chunk)
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                if block.strip():
                    yield block
        buffer += decoder.decode(b"", final=True)
        if buffer.strip():
            yield buffer


def parse_sse_block(block: str) -> tuple[str, dict[str, Any]] | None:
    """Parse one SSE block into (event, data), or None if unusable.

    Unknown or malformed blocks degrade to None instead of raising: an SSE
    stream may legitimately carry comments (`: keep-alive`) or fields this
    client does not model, and none of that should end a live answer.
    """
    event = ""
    data_lines: list[str] = []
    for line in block.splitlines():
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
    if not event or not data_lines:
        return None
    try:
        data = json.loads("\n".join(data_lines))
    except ValueError:
        return None
    return (event, data) if isinstance(data, dict) else None


class AgentGateway:
    def __init__(
        self,
        settings: AgentSettings,
        transport: Transport = aiohttp_transport,
        identity_token_provider: IdentityTokenProvider = google_identity_token_provider,
        stream_transport: StreamTransport = aiohttp_stream_transport,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.identity_token_provider = identity_token_provider
        self.stream_transport = stream_transport

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

    async def answer_stream(
        self, request: AgentRequest
    ) -> AsyncIterator[tuple[str, Any]]:
        """Stream progress from the Agent Service, ending with the answer.

        Yields ``("stage", label)`` zero or more times, then exactly one
        ``("response", AgentResponse)``. Raises `AgentGatewayError` if the
        service reports an error event, or if the stream ends without ever
        delivering a response -- callers must be able to tell "no answer"
        apart from "answer arrived", since a silent stream would otherwise
        leave the user with progress text and nothing else.
        """
        if not self.settings.streaming_ready:
            raise AgentGatewayError("Agent API streaming is not configured.")

        headers = await self._auth_headers()
        url = self.settings.resolved_stream_url or ""
        seen_response = False

        try:
            async for block in self.stream_transport(
                url,
                request.to_payload(),
                headers,
                self.settings.api_timeout_seconds,
            ):
                parsed = parse_sse_block(block)
                if parsed is None:
                    continue
                event, data = parsed
                if event == "stage":
                    label = data.get("label")
                    if isinstance(label, str) and label.strip():
                        yield "stage", label.strip()
                elif event == "error":
                    raise AgentGatewayError(
                        "Agent API reported a streaming error: "
                        f"{data.get('correlationId') or 'unknown'}"
                    )
                elif event == "response":
                    seen_response = True
                    yield "response", AgentResponse.from_payload(
                        data, request.requestId
                    )
        except AgentGatewayError:
            raise
        except (TimeoutError, ClientError, TypeError, ValueError) as error:
            raise AgentGatewayError("Agent API streaming request failed.") from error

        if not seen_response:
            raise AgentGatewayError("Agent API stream ended without a response.")

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
