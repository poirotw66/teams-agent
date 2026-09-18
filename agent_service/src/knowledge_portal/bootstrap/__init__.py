"""Knowledge Portal application bootstrap."""

from __future__ import annotations

from .container import PortalContainer, build_portal_container
from .error_handlers import portal_http_exception
from .register_routes import register_portal_routes

__all__ = [
    "PortalContainer",
    "build_portal_container",
    "portal_http_exception",
    "register_portal_routes",
]
