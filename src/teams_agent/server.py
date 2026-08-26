"""HTTP surface for the Teams Adapter.

The Microsoft Teams SDK owns `POST /api/messages`: `App.initialize()`
registers that route on whatever `HttpServerAdapter` it is given and guards
it with Bot Framework JWT validation. Everything else the adapter exposes
(`/healthz`, `/readyz`, and the signed `/rag-assets/` image endpoint) is
registered here on the same FastAPI instance, so a single uvicorn server
serves both.

These extra routes are deliberately unauthenticated:

- `/healthz` and `/readyz` are Cloud Run probes and return no user data.
- `/rag-assets/{path}` is guarded by its own HMAC signature + expiry
  (`teams_agent.media`), because Teams itself fetches those image URLs
  without any bearer token.
"""

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from microsoft_teams.apps import FastAPIAdapter
from microsoft_teams.apps.auth import TokenValidator

from .media import render_teams_image, resolve_asset
from .settings import AgentSettings

logger = logging.getLogger(__name__)


class EntraPlaygroundTokenValidator:
    """Validate the Playground's Entra token without a Bot Framework claim.

    Entra client-credentials tokens do not contain Bot Framework's
    ``serviceurl`` claim. Signature, issuer, audience and expiry are still
    validated by the SDK's Entra validator.
    """

    def __init__(self, validator: TokenValidator) -> None:
        self._validator = validator

    async def validate_token(
        self,
        raw_token: str,
        service_url: str | None = None,
        scope: str | None = None,
    ) -> dict[str, Any]:
        del service_url
        return await self._validator.validate_token(raw_token, None, scope)


class DualInboundTokenValidator:
    """Accept either Bot Framework (Teams) or Entra (Playground) JWTs.

    Real Teams / Azure Bot traffic uses the Bot Framework issuer. The hosted
    Agents Playground uses a tenant-scoped Entra client-credentials token.
    One Cloud Run adapter must accept both when demos and private Apps share
    the same messaging endpoint.
    """

    def __init__(self, primary: Any, secondary: Any) -> None:
        self._primary = primary
        self._secondary = secondary

    async def validate_token(
        self,
        raw_token: str,
        service_url: str | None = None,
        scope: str | None = None,
    ) -> dict[str, Any]:
        try:
            return await self._primary.validate_token(raw_token, service_url, scope)
        except Exception as primary_error:
            try:
                return await self._secondary.validate_token(
                    raw_token, service_url, scope
                )
            except Exception:
                raise primary_error from None


def _entra_playground_validator(settings: AgentSettings) -> EntraPlaygroundTokenValidator:
    if not settings.client_id or not settings.tenant_id:
        raise ValueError("Entra inbound auth requires client_id and tenant_id")
    return EntraPlaygroundTokenValidator(
        TokenValidator.for_entra(
            settings.client_id,
            settings.tenant_id,
        )
    )


def configure_inbound_auth(app: object, settings: AgentSettings) -> None:
    """Select the JWT issuer used for inbound Playground/Teams activities."""
    mode = settings.teams_inbound_auth_mode
    if mode == "botframework":
        return

    # The SDK currently exposes no public hook for replacing only the inbound
    # validator. This preserves Bot Framework credentials for outbound sends
    # while accepting the Playground's tenant-scoped Entra token.
    server = app.server  # type: ignore[attr-defined]
    entra = _entra_playground_validator(settings)
    if mode == "entra":
        server._token_validator = entra
        logger.info("Inbound activity JWT validation configured for Entra Playground")
        return

    # mode == "both": keep the SDK Bot Framework validator and fall back to Entra.
    server._token_validator = DualInboundTokenValidator(
        server._token_validator,
        entra,
    )
    logger.info(
        "Inbound activity JWT validation configured for Bot Framework and Entra Playground"
    )

def build_readiness(settings: AgentSettings) -> dict[str, object]:
    """Readiness payload reported by `GET /readyz`.

    `teamsAuth` reports whether the Teams SDK has app credentials to validate
    inbound Bot Framework JWTs with -- the Teams SDK equivalent of the old
    Azure Bot service-connection check.
    """
    return {
        "status": "ready" if settings.ready and settings.teams_auth_ready else "not_ready",
        "agentMode": settings.mode,
        "teamsAuth": "ready" if settings.teams_auth_ready else "not_configured",
        "ragImages": "ready" if settings.images_ready else "disabled",
    }


def create_web_app(
    settings: AgentSettings,
    readiness: dict[str, object] | None = None,
) -> FastAPI:
    """Build the FastAPI app carrying the adapter's own (non-SDK) routes."""
    app = FastAPI(title="Teams AI Agent Adapter", docs_url=None, redoc_url=None)
    readiness_payload = readiness if readiness is not None else build_readiness(settings)

    @app.get("/healthz")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/readyz")
    async def ready() -> JSONResponse:
        status = 200 if readiness_payload.get("status") == "ready" else 503
        return JSONResponse(readiness_payload, status_code=status)

    @app.get("/rag-assets/{path:path}")
    async def asset(path: str, request: Request) -> Response:
        try:
            resolved = resolve_asset(
                path,
                request.query_params.get("expires"),
                request.query_params.get("signature"),
                settings,
            )
            content, content_type = render_teams_image(resolved, settings)
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="Not Found") from error
        except ValueError as error:
            raise HTTPException(status_code=413, detail=str(error)) from error
        return Response(
            content=content,
            media_type=content_type,
            headers={
                "Cache-Control": f"private, max-age={settings.asset_url_ttl_seconds}",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return app


def build_http_adapter(
    settings: AgentSettings,
    readiness: dict[str, object] | None = None,
) -> FastAPIAdapter:
    """Wrap the adapter's FastAPI app so the Teams SDK can mount onto it."""
    return FastAPIAdapter(app=create_web_app(settings, readiness))
