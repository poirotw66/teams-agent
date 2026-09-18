"""Shared operations access contracts used by Agent, Backoffice, and Portal.

This package holds stable actor/capability types so Backoffice and Portal do not
need to import Agent runtime implementation modules for authorization context.
"""

from __future__ import annotations

from operations_core.access import (
    CAPABILITIES,
    ActorContext,
    BackofficeRole,
)

__all__ = [
    "CAPABILITIES",
    "ActorContext",
    "BackofficeRole",
]
