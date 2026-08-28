from agent_service.workflow_clarification import ClarificationWorkflowMixin
from agent_service.workflow_handoff_nodes import HandoffWorkflowMixin
from agent_service.workflow_issue_processing import IssueProcessingWorkflowMixin
from agent_service.workflow_response import ResponseWorkflowMixin
from agent_service.workflow_subgraphs import (
    CLARIFICATION_NODES,
    HANDOFF_NODES,
    KNOWLEDGE_NODES,
    TICKET_NODES,
    build_clarification_subgraph,
    build_handoff_subgraph,
)


def test_domain_node_groups_are_documented() -> None:
    assert "load_conversation" in CLARIFICATION_NODES
    assert "route_handoff" in HANDOFF_NODES
    assert "process_issues" in KNOWLEDGE_NODES
    assert "process_issues" in TICKET_NODES


def test_subgraph_builders_compile() -> None:
    async def noop(_state):
        return {}

    assert build_clarification_subgraph(
        load_conversation=noop,
        extract_issues=noop,
        filter_it_issues=noop,
    )
    assert build_handoff_subgraph(route_handoff=noop, evaluate_handoff=noop)


def test_workflow_node_implementations_are_split_by_domain() -> None:
    assert ClarificationWorkflowMixin._load_conversation
    assert HandoffWorkflowMixin._route_handoff
    assert IssueProcessingWorkflowMixin._process_issues
    assert ResponseWorkflowMixin._build_response