from os import environ

from aiohttp.web import Application, Request, Response, json_response, middleware, run_app
from microsoft_agents.hosting.aiohttp import (
    CloudAdapter,
    jwt_authorization_middleware,
    start_agent_process,
)
from microsoft_agents.hosting.core import AgentApplication, AgentAuthConfiguration


@middleware
async def authentication_middleware(request: Request, handler):
    if request.path in {"/healthz", "/readyz"}:
        return await handler(request)
    return await jwt_authorization_middleware(request, handler)


def create_web_app(
    agent_application: AgentApplication,
    auth_configuration: AgentAuthConfiguration,
    readiness: dict[str, object] | None = None,
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

    app = Application(middlewares=[authentication_middleware])
    app.router.add_post("/api/messages", messages)
    app.router.add_get("/healthz", health)
    app.router.add_get("/readyz", ready)
    app["agent_configuration"] = auth_configuration
    app["agent_app"] = agent_application
    app["adapter"] = agent_application.adapter
    return app


def start_server(
    agent_application: AgentApplication,
    auth_configuration: AgentAuthConfiguration,
    readiness: dict[str, object] | None = None,
) -> None:
    app = create_web_app(agent_application, auth_configuration, readiness)
    run_app(
        app,
        host=environ.get("HOST", "0.0.0.0"),
        port=int(environ.get("PORT", "3978")),
    )
