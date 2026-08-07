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

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from microsoft_teams.apps import FastAPIAdapter

from .media import render_teams_image, resolve_asset
from .settings import AgentSettings


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
