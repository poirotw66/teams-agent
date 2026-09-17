"""Trusted Adapter → Backoffice original-source proxy client."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .settings import AgentSettings
from .source_delegation import DELEGATION_HEADER, SourceDelegationError, issue_source_delegation

logger = logging.getLogger(__name__)

SERVICE_TOKEN_HEADER = "X-Backoffice-Service-Token"
MAX_SOURCE_PREVIEW_BYTES = 64 * 1024


class SourceApiError(RuntimeError):
    """Raised when the configured Source API cannot deliver an original."""

    def __init__(
        self,
        message: str,
        *,
        status: int = 502,
        headers: Mapping[str, str] | None = None,
        body: bytes = b"",
    ) -> None:
        super().__init__(message)
        self.status = status
        self.headers = dict(headers or {})
        self.body = body


@dataclass(frozen=True)
class SourceApiResponse:
    status: int
    headers: dict[str, str]
    body: bytes


def source_api_ready(settings: AgentSettings) -> bool:
    return settings.source_api_ready


def _google_identity_token(audience: str) -> str | None:
    """Mint a Cloud Run invoker ID token when ADC credentials are available."""

    try:
        from google.auth.transport.requests import Request as GoogleAuthRequest
        from google.oauth2.id_token import fetch_id_token
    except ImportError:
        return None
    try:
        return fetch_id_token(GoogleAuthRequest(), audience)
    except Exception:
        logger.debug("Unable to mint Google ID token for Source API", exc_info=True)
        return None


async def fetch_source_preview(
    settings: AgentSettings,
    *,
    source_ref_id: str,
    subject: str,
    tenant_id: str | None = None,
    groups: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Fetch one authorized citation preview from the Backoffice."""
    if not source_api_ready(settings):
        raise SourceApiError("Source API is not configured.")
    source_ref = str(source_ref_id or "").strip()
    if not source_ref or "/" in source_ref or ".." in source_ref:
        raise SourceApiError("Invalid source reference.")
    try:
        delegation = issue_source_delegation(
            subject=subject,
            secret=settings.source_delegation_secret or "",
            tenant_id=tenant_id,
            groups=groups,
            display_name=subject,
        )
    except SourceDelegationError as error:
        raise SourceApiError(str(error)) from error

    base = str(settings.source_api_base_url or "").rstrip("/")
    headers = {
        SERVICE_TOKEN_HEADER: str(settings.source_api_token or ""),
        "Authorization": f"Bearer {settings.source_api_token}",
        DELEGATION_HEADER: delegation,
        "Accept": "application/json",
    }
    identity = _google_identity_token(base)
    if identity:
        headers["Authorization"] = f"Bearer {identity}"

    timeout = ClientTimeout(total=float(settings.source_api_timeout_seconds))
    try:
        async with ClientSession(timeout=timeout) as session, session.get(
            f"{base}/api/sources/{source_ref}",
            headers=headers,
        ) as response:
            body = await response.content.read(MAX_SOURCE_PREVIEW_BYTES + 1)
            if len(body) > MAX_SOURCE_PREVIEW_BYTES:
                raise SourceApiError("Source API preview exceeded the size limit.")
            if response.status >= 400:
                detail = body[:200].decode("utf-8", errors="replace")
                raise SourceApiError(
                    f"Source API returned HTTP {response.status}: {detail}",
                    status=response.status,
                    body=body,
                )
    except ClientError as error:
        raise SourceApiError(f"Source API request failed: {error}") from error

    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SourceApiError("Source API returned an invalid preview.") from error
    if not isinstance(payload, dict):
        raise SourceApiError("Source API returned an invalid preview.")
    return payload


async def fetch_original_source_file(
    settings: AgentSettings,
    *,
    source_ref_id: str,
    subject: str,
    tenant_id: str | None = None,
    groups: tuple[str, ...] = (),
    range_header: str | None = None,
    accept: str | None = None,
    method: str = "GET",
) -> SourceApiResponse:
    if not source_api_ready(settings):
        raise SourceApiError("Source API is not configured.")
    source_ref = str(source_ref_id or "").strip()
    if not source_ref or "/" in source_ref or ".." in source_ref:
        raise SourceApiError("Invalid source reference.")
    try:
        delegation = issue_source_delegation(
            subject=subject,
            secret=settings.source_delegation_secret or "",
            tenant_id=tenant_id,
            groups=groups,
            display_name=subject,
        )
    except SourceDelegationError as error:
        raise SourceApiError(str(error)) from error

    base = str(settings.source_api_base_url or "").rstrip("/")
    url = f"{base}/api/sources/{source_ref}/file"
    headers = {
        SERVICE_TOKEN_HEADER: str(settings.source_api_token or ""),
        "Authorization": f"Bearer {settings.source_api_token}",
        DELEGATION_HEADER: delegation,
        "Accept": accept or "*/*",
    }
    identity = _google_identity_token(base)
    if identity:
        # Cloud Run private services require a Google ID token in Authorization.
        # Keep the shared service token in a dedicated header for app auth.
        headers["Authorization"] = f"Bearer {identity}"
    if range_header:
        headers["Range"] = range_header

    request_method = str(method or "GET").upper()
    if request_method not in {"GET", "HEAD"}:
        raise SourceApiError(f"Unsupported Source API method: {request_method}")

    timeout = ClientTimeout(total=float(settings.source_api_timeout_seconds))
    session = ClientSession(timeout=timeout)
    try:
        async with session.request(request_method, url, headers=headers) as response:
            body = b"" if request_method == "HEAD" else await response.read()
            passthrough = _passthrough_headers(response.headers)
            if response.status >= 400:
                detail = body[:200].decode("utf-8", errors="replace") if body else response.reason
                raise SourceApiError(
                    f"Source API returned HTTP {response.status}: {detail}",
                    status=response.status,
                    headers=passthrough,
                    body=body,
                )
            return SourceApiResponse(
                status=response.status,
                headers=passthrough,
                body=body,
            )
    except ClientError as error:
        raise SourceApiError(f"Source API request failed: {error}") from error
    finally:
        try:
            await session.close()
        except Exception:
            logger.debug("Failed closing source API session", exc_info=True)


def _passthrough_headers(headers: Mapping[str, Any]) -> dict[str, str]:
    allowed = {
        "content-type",
        "content-length",
        "content-range",
        "accept-ranges",
        "content-disposition",
        "cache-control",
        "etag",
        "last-modified",
    }
    result: dict[str, str] = {"X-Content-Type-Options": "nosniff"}
    for key, value in headers.items():
        lower = str(key).lower()
        if lower in allowed and value is not None:
            result[str(key)] = str(value)
    return result


async def stream_original_source_file(
    settings: AgentSettings,
    *,
    source_ref_id: str,
    subject: str,
    tenant_id: str | None = None,
    groups: tuple[str, ...] = (),
    range_header: str | None = None,
    accept: str | None = None,
    chunk_size: int = 64 * 1024,
) -> tuple[int, dict[str, str], AsyncIterator[bytes]]:
    """Return status/headers plus an async byte iterator for large originals with bounded memory."""

    if not source_api_ready(settings):
        raise SourceApiError("Source API is not configured.")
    source_ref = str(source_ref_id or "").strip()
    if not source_ref or "/" in source_ref or ".." in source_ref:
        raise SourceApiError("Invalid source reference.")
    try:
        delegation = issue_source_delegation(
            subject=subject,
            secret=settings.source_delegation_secret or "",
            tenant_id=tenant_id,
            groups=groups,
            display_name=subject,
        )
    except SourceDelegationError as error:
        raise SourceApiError(str(error)) from error

    base = str(settings.source_api_base_url or "").rstrip("/")
    url = f"{base}/api/sources/{source_ref}/file"
    headers = {
        SERVICE_TOKEN_HEADER: str(settings.source_api_token or ""),
        "Authorization": f"Bearer {settings.source_api_token}",
        DELEGATION_HEADER: delegation,
        "Accept": accept or "*/*",
    }
    identity = _google_identity_token(base)
    if identity:
        headers["Authorization"] = f"Bearer {identity}"
    if range_header:
        headers["Range"] = range_header

    timeout = ClientTimeout(total=float(settings.source_api_timeout_seconds))
    session = ClientSession(timeout=timeout)
    response = None
    try:
        response = await session.request("GET", url, headers=headers)
        passthrough = _passthrough_headers(response.headers)
        if response.status >= 400:
            body = await response.read()
            detail = body[:200].decode("utf-8", errors="replace") if body else response.reason
            await response.release()
            await session.close()
            raise SourceApiError(
                f"Source API returned HTTP {response.status}: {detail}",
                status=response.status,
                headers=passthrough,
                body=body,
            )

        async def _chunks() -> AsyncIterator[bytes]:
            try:
                async for chunk in response.content.iter_chunked(chunk_size):
                    yield chunk
            finally:
                try:
                    await response.release()
                except Exception:
                    logger.debug("Failed releasing source API response", exc_info=True)
                try:
                    await session.close()
                except Exception:
                    logger.debug("Failed closing source API session", exc_info=True)

        return response.status, passthrough, _chunks()
    except Exception:
        if response is not None:
            try:
                await response.release()
            except Exception:
                logger.debug("Failed releasing source response on error", exc_info=True)
        try:
            await session.close()
        except Exception:
            logger.debug("Failed closing source session on error", exc_info=True)
        raise

