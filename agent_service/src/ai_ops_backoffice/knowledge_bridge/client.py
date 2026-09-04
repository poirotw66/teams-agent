"""HTTP client for allowlisted Knowledge Portal calls."""

from __future__ import annotations

from typing import Any, Mapping

import httpx

from agent_service.operations.access import ActorContext

from .delegation import DELEGATION_HEADER, issue_delegation_envelope
from .errors import KnowledgeBridgeError, portal_api_path


class KnowledgePortalClient:
    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        delegation_secret: str,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._delegation_secret = delegation_secret
        self._timeout = timeout_seconds
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._delegation_secret)

    def _headers(
        self,
        actor: ActorContext,
        *,
        correlation_id: str,
        content_type: str | None,
        extra: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        headers = {
            "X-Correlation-Id": correlation_id,
            DELEGATION_HEADER: issue_delegation_envelope(
                actor,
                secret=self._delegation_secret,
                correlation_id=correlation_id,
            ),
        }
        if self._service_token:
            headers["Authorization"] = f"Bearer {self._service_token}"
        if content_type:
            headers["Content-Type"] = content_type
        if extra:
            headers.update(extra)
        # Never forward browser portal identity headers.
        return headers

    async def request(
        self,
        *,
        method: str,
        relative_path: str,
        actor: ActorContext,
        correlation_id: str,
        query: Mapping[str, Any] | None = None,
        json_body: Any | None = None,
        content: bytes | None = None,
        content_type: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        if not self.configured:
            raise KnowledgeBridgeError(
                code="KNOWLEDGE_BRIDGE_DISABLED",
                message="知識整合尚未啟用或未設定內部服務位址。",
                status_code=503,
                retryable=False,
                correlation_id=correlation_id,
            )
        path = portal_api_path(relative_path)
        request_headers = self._headers(
            actor,
            correlation_id=correlation_id,
            content_type=content_type,
            extra=headers,
        )
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.request(
                    method.upper(),
                    path,
                    params=query,
                    json=json_body,
                    content=content,
                    headers=request_headers,
                )
        except httpx.TimeoutException as exc:
            raise KnowledgeBridgeError(
                code="KNOWLEDGE_UPSTREAM_TIMEOUT",
                message="知識服務回應逾時，請稍後再試或查詢操作狀態。",
                status_code=504,
                retryable=True,
                correlation_id=correlation_id,
            ) from exc
        except httpx.HTTPError as exc:
            raise KnowledgeBridgeError(
                code="KNOWLEDGE_UPSTREAM_UNAVAILABLE",
                message="知識服務暫時不可用。",
                status_code=503,
                retryable=True,
                correlation_id=correlation_id,
            ) from exc
        return response
