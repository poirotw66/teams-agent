#!/usr/bin/env python3
"""Check Adapter ↔ Agent Service wire-contract field compatibility.

The packages keep separate model implementations (dataclass vs Pydantic).
This ratchet ensures shared request/response shapes stay field-compatible:
adapter-required fields must exist on the agent model (agent may be a
superset). Optional adapter-only extras are reported as warnings but do not
fail the gate unless listed in REQUIRED_SHARED_FIELDS.

Usage:
  PYTHONPATH=src:agent_service/src uv run python scripts/check_wire_contracts.py
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_CONTRACTS = REPO_ROOT / "src" / "teams_agent" / "contracts.py"
AGENT_CONTRACTS = (
    REPO_ROOT / "agent_service" / "src" / "agent_service" / "contracts.py"
)

# Shared type names that travel on the Adapter ↔ Agent wire.
SHARED_MODELS = (
    "ConversationIdentity",
    "UserIdentity",
    "MessageContent",
    "AgentRequest",
    "Citation",
    "AgentImage",
    "IssueResult",
    "AgentResponse",
    "FeedbackRequest",
)

# Fields the adapter always expects to round-trip. Agent models must declare
# each of these (extra agent-only fields are allowed).
REQUIRED_SHARED_FIELDS: dict[str, frozenset[str]] = {
    "ConversationIdentity": frozenset(
        {"tenantId", "teamId", "channelId", "conversationId"}
    ),
    "UserIdentity": frozenset(
        {"teamsUserId", "entraObjectId", "displayName", "email", "groups"}
    ),
    "MessageContent": frozenset({"text", "locale"}),
    "AgentRequest": frozenset(
        {
            "requestId",
            "channel",
            "conversation",
            "user",
            "message",
            "correlationId",
            "evaluationKnowledgeBackend",
        }
    ),
    "Citation": frozenset({"title", "url", "chunkId", "sourcePath", "sourceRefId", "releaseId"}),
    "AgentImage": frozenset(
        {"path", "title", "altText", "sourceChunkId", "releaseId"}
    ),
    "IssueResult": frozenset({"issueId", "resultType", "answer"}),
    "AgentResponse": frozenset(
        {
            "answer",
            "traceId",
            "citations",
            "images",
            "correlationId",
            "issueResults",
            "feedbackEnabled",
        }
    ),
    "FeedbackRequest": frozenset(
        {"correlationId", "conversationId", "issueId", "rating", "userId"}
    ),
}


@dataclass(frozen=True)
class ModelFields:
    name: str
    fields: frozenset[str]


def _class_fields(path: Path) -> dict[str, ModelFields]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: dict[str, ModelFields] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        names: set[str] = set()
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                names.add(item.target.id)
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
        found[node.name] = ModelFields(name=node.name, fields=frozenset(names))
    return found


def main() -> int:
    adapter = _class_fields(ADAPTER_CONTRACTS)
    agent = _class_fields(AGENT_CONTRACTS)
    errors: list[str] = []
    warnings: list[str] = []

    for name in SHARED_MODELS:
        if name not in adapter:
            errors.append(f"adapter missing shared model {name}")
            continue
        if name not in agent:
            errors.append(f"agent missing shared model {name}")
            continue
        required = REQUIRED_SHARED_FIELDS.get(name, frozenset())
        missing_required = sorted(required - agent[name].fields)
        if missing_required:
            errors.append(
                f"{name}: agent missing required wire fields {missing_required}"
            )
        adapter_only = sorted(adapter[name].fields - agent[name].fields)
        if adapter_only:
            warnings.append(
                f"{name}: adapter-only fields not on agent {adapter_only}"
            )

    for warning in warnings:
        print(f"WARN: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(
            f"check_wire_contracts: {len(errors)} error(s), {len(warnings)} warning(s)",
            file=sys.stderr,
        )
        return 1
    print(
        f"check_wire_contracts: ok ({len(SHARED_MODELS)} shared models, "
        f"{len(warnings)} warning(s))"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
