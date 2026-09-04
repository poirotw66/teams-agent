"""LangGraph workflow graph builder and domain node group constants.

Production uses only :func:`build_agent_workflow_graph`. The ``*_NODES`` tuples
document how node implementations are split across mixin modules; they are not
separate compiled subgraphs.

Conversation memory vs execution recovery
-----------------------------------------
``ConversationRepository`` / ``save_conversation`` persist **dialogue state**
(messages, unresolved issues, handoff case) so the next user turn can continue
the conversation.

That is **not** LangGraph execution checkpointing.  Without a checkpointer,
an interrupted in-flight turn cannot resume at ``process_issues`` or
``evaluate_handoff``; the turn must be retried from START.

When long-running human approval or cross-process resume is required, pass a
LangGraph checkpointer into :func:`build_agent_workflow_graph` and design
``interrupt`` points with idempotent external side effects (ticket create,
handoff provider calls).
"""

from __future__ import annotations

from typing import Any, Protocol

from langgraph.graph import END, START, StateGraph

CLARIFICATION_NODES = ("load_conversation", "extract_issues", "filter_it_issues")
KNOWLEDGE_NODES = ("process_issues",)
TICKET_NODES = ("process_issues",)
HANDOFF_NODES = ("route_handoff", "evaluate_handoff")
RESPONSE_NODES = ("build_response", "save_conversation")

# Side effects that must stay idempotent before enabling interrupt/resume.
IDEMPOTENT_EXTERNAL_OPS = (
    "ticket.create",
    "ticket.query",
    "handoff.offer",
    "handoff.complete",
    "ops.event.append",
)


class WorkflowGraphNodes(Protocol):
    async def _load_conversation(self, state: dict) -> dict: ...

    async def _route_handoff(self, state: dict) -> dict: ...

    async def _extract_issues(self, state: dict) -> dict: ...

    async def _filter_it_issues(self, state: dict) -> dict: ...

    async def _process_issues(self, state: dict) -> dict: ...

    async def _evaluate_handoff(self, state: dict) -> dict: ...

    async def _build_response(self, state: dict) -> dict: ...

    async def _save_conversation(self, state: dict) -> dict: ...


def build_agent_workflow_graph(
    state_type: type,
    workflow: WorkflowGraphNodes,
    *,
    checkpointer: Any | None = None,
) -> Any:
    """Compose the production Agent workflow graph from domain node groups.

    ``checkpointer=None`` (default) means each ``ainvoke``/``astream`` runs the
    full turn graph without mid-graph resume.  Conversation continuity still
    comes from ``load_conversation`` / ``save_conversation``.
    """
    builder = StateGraph(state_type)
    builder.add_node("load_conversation", workflow._load_conversation)
    builder.add_node("route_handoff", workflow._route_handoff)
    builder.add_node("extract_issues", workflow._extract_issues)
    builder.add_node("filter_it_issues", workflow._filter_it_issues)
    builder.add_node("process_issues", workflow._process_issues)
    builder.add_node("evaluate_handoff", workflow._evaluate_handoff)
    builder.add_node("build_response", workflow._build_response)
    builder.add_node("save_conversation", workflow._save_conversation)

    builder.add_edge(START, "load_conversation")
    builder.add_edge("load_conversation", "route_handoff")
    builder.add_conditional_edges(
        "route_handoff",
        lambda state: (
            "handled"
            if state.get("handoff_handled")
            else "respond"
            if state.get("skip_issue_pipeline")
            else "ai"
        ),
        {
            "handled": "save_conversation",
            "respond": "build_response",
            "ai": "extract_issues",
        },
    )
    builder.add_edge("extract_issues", "filter_it_issues")
    builder.add_edge("filter_it_issues", "process_issues")
    builder.add_edge("process_issues", "evaluate_handoff")
    builder.add_conditional_edges(
        "evaluate_handoff",
        lambda state: "handled" if state.get("handoff_handled") else "build",
        {"handled": "save_conversation", "build": "build_response"},
    )
    builder.add_edge("build_response", "save_conversation")
    builder.add_edge("save_conversation", END)
    if checkpointer is None:
        return builder.compile()
    return builder.compile(checkpointer=checkpointer)
