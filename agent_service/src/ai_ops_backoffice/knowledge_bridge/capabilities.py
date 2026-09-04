"""Explicit knowledge capability grants (deny-by-default; not role-name aliasing)."""

from __future__ import annotations

from agent_service.operations.access import ActorContext

# Spec §8.2 minimum capability set.
KNOWLEDGE_CAPABILITIES = frozenset(
    {
        "knowledge.read",
        "knowledge.create",
        "knowledge.edit",
        "knowledge.assets.write",
        "knowledge.validate",
        "knowledge.test",
        "knowledge.submit",
        "knowledge.review",
        "knowledge.publish",
        "knowledge.unpublish",
        "knowledge.rollback",
        "knowledge.delete",
        "knowledge.audit.read",
    }
)

_ALL = KNOWLEDGE_CAPABILITIES
_EDITOR = frozenset(
    {
        "knowledge.read",
        "knowledge.create",
        "knowledge.edit",
        "knowledge.assets.write",
        "knowledge.validate",
        "knowledge.test",
        "knowledge.submit",
    }
)
_MANAGER = _EDITOR | frozenset(
    {
        "knowledge.review",
        "knowledge.publish",
        "knowledge.unpublish",
        "knowledge.rollback",
        "knowledge.delete",
        "knowledge.audit.read",
    }
)

# Engineering default pending D03 sign-off. Unmapped roles get nothing.
ROLE_KNOWLEDGE_CAPABILITIES: dict[str, frozenset[str]] = {
    "SYSTEM_ADMIN": _ALL,
    "KNOWLEDGE_ADMIN": _MANAGER,
    "SERVICE_OWNER": frozenset({"knowledge.read"}),
    "AUDITOR": frozenset({"knowledge.read", "knowledge.audit.read"}),
    "AI_ADMIN": frozenset(),
    "ANALYST": frozenset(),
}

# Map granted knowledge capabilities to an existing Portal RBAC role.
# This is an internal compatibility bridge, not a product role rename.
_PORTAL_ROLE_FOR_CAPS: tuple[tuple[frozenset[str], str], ...] = (
    (frozenset({"knowledge.publish", "knowledge.rollback"}), "PLATFORM"),
    (frozenset({"knowledge.review", "knowledge.publish"}), "MANAGER"),
    (frozenset({"knowledge.review"}), "REVIEWER"),
    (frozenset({"knowledge.audit.read"}), "AUDITOR"),
    (frozenset({"knowledge.create", "knowledge.edit", "knowledge.submit"}), "CONTRIBUTOR"),
)


def knowledge_capabilities_for(actor: ActorContext) -> frozenset[str]:
    return ROLE_KNOWLEDGE_CAPABILITIES.get(actor.role, frozenset())


def has_knowledge_capability(actor: ActorContext, capability: str) -> bool:
    return capability in knowledge_capabilities_for(actor)


def portal_role_for(actor: ActorContext) -> str:
    caps = knowledge_capabilities_for(actor)
    if not caps:
        raise PermissionError("no knowledge capabilities for actor")
    for required, role in _PORTAL_ROLE_FOR_CAPS:
        if required <= caps:
            return role
    if "knowledge.read" in caps:
        return "AUDITOR" if "knowledge.audit.read" in caps else "CONTRIBUTOR"
    raise PermissionError("no portal role mapping for actor capabilities")


def capability_for_portal_path(method: str, relative_path: str) -> str:
    """Map an allowlisted Portal relative path to a knowledge.* capability."""
    method = method.upper()
    path = relative_path.strip("/")
    if path == "dashboard" and method == "GET":
        return "knowledge.read"
    if path == "documents" and method == "GET":
        return "knowledge.read"
    if path == "documents" and method == "POST":
        return "knowledge.create"
    if path.startswith("documents/") and path.endswith("/import-pdf") and method == "POST":
        return "knowledge.create"
    if path.startswith("documents/") and path.endswith("/import-markdown") and method == "POST":
        return "knowledge.create"
    if "/draft/assets" in path and method in {"POST", "DELETE"}:
        return "knowledge.assets.write"
    if "/draft/asset-ref" in path and method == "POST":
        return "knowledge.assets.write"
    if path.endswith("/draft") and method == "PUT":
        return "knowledge.edit"
    if path.endswith("/validate") and method == "POST":
        return "knowledge.validate"
    if path.endswith("/submit-review") and method == "POST":
        return "knowledge.submit"
    if path.endswith("/publish") and method == "POST":
        return "knowledge.publish"
    if path.endswith("/unpublish") and method == "POST":
        return "knowledge.unpublish"
    if path.endswith("/discard-draft") and method == "POST":
        return "knowledge.edit"
    if path.endswith("/start-revision") and method == "POST":
        return "knowledge.edit"
    if "/test-cases" in path and method == "POST":
        return "knowledge.test"
    if path.endswith("/draft-search") and method == "POST":
        return "knowledge.test"
    if "/test-runs" in path and method == "GET":
        return "knowledge.test"
    if path.endswith("/run") and method == "POST":
        return "knowledge.test"
    if path.startswith("reviews/") and path.endswith("/decision") and method == "POST":
        return "knowledge.review"
    if path == "reviews/pending" and method == "GET":
        return "knowledge.review"
    if path == "releases/rollback" and method == "POST":
        return "knowledge.rollback"
    if path.startswith("releases") and method == "GET":
        return "knowledge.read"
    if path == "audit-events" and method == "GET":
        return "knowledge.audit.read"
    if method == "DELETE" and path.startswith("documents/"):
        return "knowledge.delete"
    if method == "GET":
        return "knowledge.read"
    return "knowledge.edit"
