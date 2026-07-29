from os import environ

from aiohttp.web import (
    Application,
    HTTPForbidden,
    HTTPNotFound,
    HTTPRequestEntityTooLarge,
    Request,
    Response,
    json_response,
    middleware,
    run_app,
)
from microsoft_agents.hosting.aiohttp import (
    CloudAdapter,
    jwt_authorization_middleware,
    start_agent_process,
)
from microsoft_agents.hosting.core import AgentApplication, AgentAuthConfiguration

from .media import render_teams_image, resolve_asset
from .settings import AgentSettings


@middleware
async def authentication_middleware(request: Request, handler):
    if request.path in {"/healthz", "/readyz"} or request.path.startswith(
        "/rag-assets/"
    ):
        return await handler(request)
    return await jwt_authorization_middleware(request, handler)


def create_web_app(
    agent_application: AgentApplication,
    auth_configuration: AgentAuthConfiguration,
    readiness: dict[str, object] | None = None,
    settings: AgentSettings | None = None,
) -> Application:
    async def messages(request: Request) -> Response:
        agent: AgentApplication = request.app["agent_app"]
        adapter: CloudAdapter = request.app["adapter"]
        return await start_agent_process(request, agent, adapter)

    async def health(_request: Request) -> Response:
        return json_response({"status": "ok"})

    async def ready(_request: Request) -> Response:
        payload = readiness or {"status": "ready"}
        status = 200 if payload.get("status") == "ready" else 503
        return json_response(payload, status=status)

    async def asset(request: Request) -> Response:
        if settings is None:
            raise HTTPNotFound()
        try:
            path = resolve_asset(
                request.match_info["path"],
                request.query.get("expires"),
                request.query.get("signature"),
                settings,
            )
            content, content_type = render_teams_image(path, settings)
        except PermissionError as error:
            raise HTTPForbidden(text=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPNotFound() from error
        except ValueError as error:
            raise HTTPRequestEntityTooLarge(
                max_size=settings.asset_max_bytes,
                actual_size=0,
                text=str(error),
            ) from error
        return Response(
            body=content,
            content_type=content_type,
            headers={
                "Cache-Control": (
                    f"private, max-age={settings.asset_url_ttl_seconds}"
                ),
                "X-Content-Type-Options": "nosniff",
            },
        )

    app = Application(middlewares=[authentication_middleware])
    app.router.add_post("/api/messages", messages)
    app.router.add_get("/healthz", health)
    app.router.add_get("/readyz", ready)
    app.router.add_get("/rag-assets/{path:.*}", asset)
    app["agent_configuration"] = auth_configuration
    app["agent_app"] = agent_application
    app["adapter"] = agent_application.adapter
    return app


def start_server(
    agent_application: AgentApplication,
    auth_configuration: AgentAuthConfiguration,
    readiness: dict[str, object] | None = None,
    settings: AgentSettings | None = None,
) -> None:
    app = create_web_app(
        agent_application,
        auth_configuration,
        readiness,
        settings,
    )
    run_app(
        app,
        host=environ.get("HOST", "0.0.0.0"),
        port=int(environ.get("PORT", "3978")),
    )
