from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .conversations_routes_handlers import (
    register_conversation_detail_route,
    register_conversation_list_route,
)


def register_conversations_routes(
    app: Any,
    *,
    query_service: Any,
    current_actor: Callable[..., Any],
    require_capability: Callable[[Any, str], None],
    audit_read: Callable[..., Any],
) -> None:
    """Register HTTP read routes for conversation list and detail."""
    kwargs = dict(
        query_service=query_service,
        current_actor=current_actor,
        require_capability=require_capability,
        audit_read=audit_read,
    )
    register_conversation_list_route(app, **kwargs)
    register_conversation_detail_route(app, **kwargs)
