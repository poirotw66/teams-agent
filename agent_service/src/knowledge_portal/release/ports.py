"""Protocol stubs for release workflow side effects.

``ReleaseGateChecker`` already lives in ``platform_kernel.ports``; this module
re-exports it for portal-local wiring and adds Agent reload, activation store,
and source-catalog ports that ``ReleaseService`` will adopt in later slices.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from platform_kernel.ports.release_gate import (
    ReleaseGateBlockedError,
    ReleaseGateChecker,
)
from platform_kernel.ports.source_catalog import (
    SourceCatalogEntry,
    SourceCatalogWriter,
)

# Portal release workflow prefers the shared platform port names.
SourceCatalogPort = SourceCatalogWriter


def fetch_google_id_token(audience: str) -> str:
    """Fetch a Google ID token for Portal-to-Agent authenticated reload calls."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.id_token import fetch_id_token
    except ImportError as error:  # pragma: no cover - deployment dependency
        raise RuntimeError(
            "google-auth is required for Portal-to-Agent identity tokens."
        ) from error
    return fetch_id_token(Request(), audience)


class AgentReloadPort(Protocol):
    """Notify the Agent runtime to reload an activated knowledge release."""

    async def reload_release(
        self,
        release_id: str,
        *,
        correlation_id: str,
    ) -> tuple[bool, str | None]:
        """Return ``(success, error_message)`` after attempting agent reload."""
        ...


class ActivationStorePort(Protocol):
    """Persist release records and the active-release pointer."""

    async def get_active_release_id(self) -> str | None:
        ...

    async def set_active_release_id(self, release_id: str | None) -> None:
        ...

    async def get_release(self, release_id: str) -> object | None:
        ...

    async def save_release(self, release: object) -> None:
        ...

    async def list_releases(self) -> Sequence[object]:
        ...


__all__ = [
    "ActivationStorePort",
    "AgentReloadPort",
    "ReleaseGateBlockedError",
    "ReleaseGateChecker",
    "SourceCatalogEntry",
    "SourceCatalogPort",
    "SourceCatalogWriter",
    "fetch_google_id_token",
]
