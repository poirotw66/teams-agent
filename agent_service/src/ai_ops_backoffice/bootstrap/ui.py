"""Static UI routes and asset helpers for AI Ops Backoffice."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ai_ops_backoffice.settings import BackofficeSettings

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
UI_ASSET_VERSION = "ops-ui-20260918a"
LEGACY_JS_MOUNT = "/static/legacy-js"

_CONSOLE_V2_STATIC_EXTENSIONS = frozenset(
    {
        ".js",
        ".css",
        ".map",
        ".json",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".ico",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
    }
)


def _js_import_map_script(version: str) -> str:
    """Remap legacy-js module URLs so nested ES imports share one cache-busted URL."""
    js_root = STATIC_DIR / "legacy-js"
    mount = LEGACY_JS_MOUNT
    imports = {
        f"{mount}/{path.relative_to(js_root).as_posix()}": (
            f"{mount}/{path.relative_to(js_root).as_posix()}?v={version}"
        )
        for path in sorted(js_root.rglob("*.js"))
    }
    payload = json.dumps({"imports": imports}, ensure_ascii=True, indent=2)
    return f'<script type="importmap">\n{payload}\n</script>'


def _render_index_html(version: str = UI_ASSET_VERSION) -> str:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace("__UI_ASSET_VERSION__", version)
    marker = "<!-- AI_OPS_IMPORT_MAP -->"
    import_map = _js_import_map_script(version)
    if marker in html:
        return html.replace(marker, import_map, 1)
    return html.replace("</head>", f"    {import_map}\n  </head>", 1)


class _NoStoreStaticCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        path = request.url.path
        if path in {"/", "/legacy", "/legacy/"} or path.startswith(
            ("/static/", "/knowledge-ui", "/console-v2")
        ):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


def _register_console_v2_routes(app: FastAPI, *, enabled: bool) -> None:
    console_v2_dir = STATIC_DIR / "console-v2"
    if enabled:

        @app.get("/console-v2")
        @app.get("/console-v2/")
        @app.get("/console-v2/{full_path:path}")
        async def console_v2_spa(full_path: str = "") -> Response:
            if full_path:
                target = console_v2_dir / full_path
                if target.is_file():
                    return FileResponse(target)
                target_path = Path(full_path)
                if (
                    full_path.startswith("assets/")
                    or target_path.suffix.lower() in _CONSOLE_V2_STATIC_EXTENSIONS
                ):
                    raise HTTPException(status_code=404, detail="Asset not found")
            index_file = console_v2_dir / "index.html"
            if index_file.is_file():
                return FileResponse(
                    index_file,
                    headers={"Cache-Control": "no-cache, must-revalidate"},
                )
            return HTMLResponse(
                "<!doctype html><html><body><h1>AI Ops Console V2</h1>"
                "<p>Initializing...</p></body></html>",
                headers={"Cache-Control": "no-cache, must-revalidate"},
            )
        return

    @app.get("/console-v2")
    @app.get("/console-v2/")
    @app.get("/console-v2/{full_path:path}")
    async def console_v2_disabled() -> Response:
        from starlette.responses import RedirectResponse

        return RedirectResponse(url="/", status_code=307)


def register_static_ui_routes(
    app: FastAPI,
    settings: BackofficeSettings,
    *,
    current_actor: Any,
    require_capability: Any,
    governance_service: Any,
) -> None:
    # Phase 3 feature-flag list remains available under the governed API.
    @app.get("/api/feature-flags")
    async def list_feature_flags(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.flags.read")
        return {"items": governance_service.list_flags(actor=actor)}

    @app.get("/legacy")
    @app.get("/legacy/")
    async def legacy_shell() -> Response:
        """Emergency legacy shell; disabled unless BACKOFFICE_LEGACY_SHELL_ENABLED."""
        if settings.console_v2_enabled and not settings.legacy_shell_enabled:
            from starlette.responses import RedirectResponse

            return RedirectResponse(url="/console-v2/dashboard", status_code=307)
        return HTMLResponse(
            _render_index_html(),
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )

    @app.get("/")
    async def index() -> Response:
        if settings.console_v2_enabled:
            from starlette.responses import RedirectResponse

            return RedirectResponse(url="/console-v2/dashboard", status_code=307)
        return HTMLResponse(
            _render_index_html(),
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )

    portal_static = Path(__file__).resolve().parents[2] / "knowledge_portal" / "static"
    if portal_static.is_dir():
        app.mount(
            "/static/kp",
            StaticFiles(directory=portal_static),
            name="knowledge_portal_static",
        )

    @app.get("/knowledge-ui")
    @app.get("/knowledge-ui/")
    async def knowledge_ui() -> FileResponse:
        """Same-origin Knowledge Portal UI hosted inside the ops console."""
        return FileResponse(
            STATIC_DIR / "knowledge-ui.html",
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )

    _register_console_v2_routes(app, enabled=settings.console_v2_enabled)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.add_middleware(_NoStoreStaticCacheMiddleware)
