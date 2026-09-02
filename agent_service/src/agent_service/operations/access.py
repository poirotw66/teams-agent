from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BackofficeRole = Literal[
    "SYSTEM_ADMIN",
    "AI_ADMIN",
    "KNOWLEDGE_ADMIN",
    "SERVICE_OWNER",
    "ANALYST",
    "AUDITOR",
]

CAPABILITIES: dict[str, frozenset[str]] = {
    "SYSTEM_ADMIN": frozenset(
        {
            "ops.health.read",
            "ops.config.read",
            "ops.audit.read",
            "ops.roles.read",
        }
    ),
    "AI_ADMIN": frozenset(
        {
            "ops.summary.read",
            "ops.cost.read",
            "ops.issues.read",
            "ops.health.read",
            "ops.conversations.read",
            "ops.exports.create",
            "ops.exports.read",
        }
    ),
    "KNOWLEDGE_ADMIN": frozenset(
        {
            "ops.summary.read",
            "ops.issues.read",
            "ops.feedback.read",
            "ops.knowledge.read",
            "ops.conversations.read",
            "ops.quality.read",
            "ops.faq.write",
            "ops.exports.create",
            "ops.exports.read",
        }
    ),
    "SERVICE_OWNER": frozenset(
        {
            "ops.summary.read",
            "ops.issues.read",
            "ops.feedback.read",
            "ops.cost.read",
            "ops.conversations.read",
            "ops.exports.create",
            "ops.exports.read",
        }
    ),
    "ANALYST": frozenset(
        {
            "ops.summary.read",
            "ops.issues.read",
            "ops.feedback.read",
            "ops.cost.read",
            "ops.conversations.read",
            "ops.exports.read",
        }
    ),
    "AUDITOR": frozenset({"ops.audit.read", "ops.exports.read"}),
}


@dataclass(frozen=True)
class ActorContext:
    user_id: str
    display_name: str
    role: BackofficeRole
    owner_unit_ids: tuple[str, ...]

    def has_capability(self, capability: str) -> bool:
        return capability in CAPABILITIES.get(self.role, frozenset())

    def allows_owner_unit(self, owner_unit_id: str | None) -> bool:
        if self.role in {"SYSTEM_ADMIN", "AI_ADMIN", "AUDITOR"}:
            return True
        if not owner_unit_id:
            return False
        if not self.owner_unit_ids:
            return False
        return owner_unit_id in self.owner_unit_ids
