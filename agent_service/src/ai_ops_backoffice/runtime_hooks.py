"""Optional composition hooks so Backoffice domain code never imports composition."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI

PortalAppFactory = Callable[..., FastAPI]

_portal_app_factory: PortalAppFactory | None = None


def register_portal_app_factory(factory: PortalAppFactory | None) -> None:
    global _portal_app_factory
    _portal_app_factory = factory


def get_portal_app_factory() -> PortalAppFactory | None:
    return _portal_app_factory
