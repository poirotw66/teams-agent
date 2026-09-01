from __future__ import annotations

from agent_service.operations.access import ActorContext
from agent_service.operations.audit import AuditStore, build_audit_event


async def record_query_audit(
    audit_store: AuditStore,
    *,
    actor: ActorContext,
    action: str,
    target_id: str,
    environment: str,
    after: dict[str, object] | None = None,
) -> None:
    await audit_store.append(
        build_audit_event(
            actor_id=actor.user_id,
            actor_role=actor.role,
            action=action,
            target_type="query",
            target_id=target_id,
            after=after,
            environment=environment,
        )
    )
