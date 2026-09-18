"""Release gate port shared by Agent, Portal, and Backoffice consumers."""

from __future__ import annotations

from typing import Any, Protocol


class ReleaseGateBlockedError(Exception):
    """Raised when an ENFORCE gate blocks activation or publish."""


class ReleaseGateChecker(Protocol):
    def check_activation(
        self,
        *,
        target_manifest_hash: str,
        target_type: str,
        policy_id: str = "default-gate-policy",
        tenant_id: str | None = None,
        environment: str = "prod",
        policy_version: int | None = None,
    ) -> dict[str, Any]:
        """Return gate status dict, or raise ReleaseGateBlockedError when blocked."""
        ...
