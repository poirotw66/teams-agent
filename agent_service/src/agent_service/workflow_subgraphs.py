"""LangGraph subgraph builders for AgentWorkflow domain boundaries."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from langgraph.graph import END, START, StateGraph

CLARIFICATION_NODES = ("load_conversation", "extract_issues", "filter_it_issues")
KNOWLEDGE_NODES = ("process_issues",)
TICKET_NODES = ("process_issues",)
HANDOFF_NODES = ("route_handoff", "evaluate_handoff")
RESPONSE_NODES = ("build_response", "save_conversation")


class WorkflowGraphNodes(Protocol):
    async def _load_conversation(self, state: dict) -> dict: ...

    async def _route_handoff(self, state: dict) -> dict: ...

    async def _extract_issues(self, state: dict) -> dict: ...

    async def _filter_it_issues(self, state: dict) -> dict: ...

    async def _process_issues(self, state: dict) -> dict: ...

    async def _evaluate_handoff(self, state: dict) -> dict: ...

    async def _build_response(self, state: dict) -> dict: ...

    async def _save_conversation(self, state: dict) -> dict: ...


def build_clarification_subgraph(
    *,
    load_conversation: Callable[..., Any],
    extract_issues: Callable[..., Any],
    filter_it_issues: Callable[..., Any],
) -> Any:
    builder = StateGraph(dict)
    builder.add_node("load_conversation", load_conversation)
    builder.add_node("extract_issues", extract_issues)
    builder.add_node("filter_it_issues", filter_it_issues)
    builder.add_edge(START, "load_conversation")
    builder.add_edge("load_conversation", "extract_issues")
    builder.add_edge("extract_issues", "filter_it_issues")
    builder.add_edge("filter_it_issues", END)
    return builder.compile()


def build_knowledge_subgraph(*, process_issues: Callable[..., Any]) -> Any:
    builder = StateGraph(dict)
    builder.add_node("process_issues", process_issues)
    builder.add_edge(START, "process_issues")
    builder.add_edge("process_issues", END)
    return builder.compile()


def build_ticket_subgraph(*, process_issues: Callable[..., Any]) -> Any:
    return build_knowledge_subgraph(process_issues=process_issues)


def build_handoff_subgraph(
    *,
    route_handoff: Callable[..., Any],
    evaluate_handoff: Callable[..., Any],
) -> Any:
    builder = StateGraph(dict)
    builder.add_node("route_handoff", route_handoff)
    builder.add_node("evaluate_handoff", evaluate_handoff)
    builder.add_edge(START, "route_handoff")
    builder.add_edge("route_handoff", END)
    builder.add_edge(START, "evaluate_handoff")
    builder.add_edge("evaluate_handoff", END)
    return builder.compile()


def build_agent_workflow_graph(state_type: type, workflow: WorkflowGraphNodes) -> Any:
    """Compose the production Agent workflow graph from domain node groups."""
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
    return builder.compile()
