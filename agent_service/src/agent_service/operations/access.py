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
            "ops.summary.read",
            "ops.cost.read",
            "ops.issues.read",
            "ops.conversations.read",
            "ops.conversations.unmasked",
            "ops.feedback.read",
            "ops.knowledge.read",
            "ops.quality.read",
            "ops.quality.write",
            "ops.quality.resolve",
            "ops.faq.read",
            "ops.faq.write",
            "ops.faq.review",
            "ops.faq.activate",
            "ops.faq.disable",
            "ops.examples.read",
            "ops.examples.write",
            "ops.examples.verify",
            "ops.examples.retire",
            "ops.sync.read",
            "ops.sync.write",
            "ops.budget.read",
            "ops.budget.write",
            "ops.budget.evaluate",
            "ops.alerts.read",
            "ops.alerts.manage",
            "ops.prompts.read",
            "ops.prompts.content.read",
            "ops.prompts.candidates.create",
            "ops.exports.create",
            "ops.exports.read",
        }
    ),
    "AI_ADMIN": frozenset(
        {
            "ops.summary.read",
            "ops.cost.read",
            "ops.issues.read",
            "ops.health.read",
            "ops.conversations.read",
            "ops.conversations.unmasked",
            "ops.quality.read",
            "ops.examples.read",
            "ops.sync.read",
            "ops.budget.read",
            "ops.alerts.read",
            "ops.prompts.read",
            "ops.prompts.content.read",
            "ops.prompts.candidates.create",
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
            "ops.conversations.unmasked",
            "ops.quality.read",
            "ops.quality.write",
            "ops.faq.read",
            "ops.faq.write",
            "ops.examples.read",
            "ops.examples.write",
            "ops.sync.read",
            "ops.sync.write",
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
            "ops.quality.read",
            "ops.quality.write",
            "ops.quality.resolve",
            "ops.sync.read",
            "ops.budget.read",
            "ops.budget.write",
            "ops.budget.evaluate",
            "ops.alerts.read",
            "ops.alerts.manage",
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
    "AUDITOR": frozenset(
        {
            "ops.audit.read",
            "ops.exports.read",
            "ops.faq.read",
            "ops.examples.read",
            "ops.budget.read",
            "ops.alerts.read",
        }
    ),
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
