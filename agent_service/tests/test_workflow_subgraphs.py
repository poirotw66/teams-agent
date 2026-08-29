from agent_service.workflow_clarification import ClarificationWorkflowMixin
from agent_service.workflow_handoff_nodes import HandoffWorkflowMixin
from agent_service.workflow_issue_processing import IssueProcessingWorkflowMixin
from agent_service.workflow_response import ResponseWorkflowMixin
from agent_service.workflow_subgraphs import (
    CLARIFICATION_NODES,
    HANDOFF_NODES,
    KNOWLEDGE_NODES,
    RESPONSE_NODES,
    TICKET_NODES,
    build_agent_workflow_graph,
)


def test_domain_node_groups_are_documented() -> None:
    assert "load_conversation" in CLARIFICATION_NODES
    assert "route_handoff" in HANDOFF_NODES
    assert "process_issues" in KNOWLEDGE_NODES
    assert "process_issues" in TICKET_NODES
    assert "build_response" in RESPONSE_NODES


def test_production_graph_builder_compiles() -> None:
    class StubWorkflow:
        async def _load_conversation(self, state):
            return {}

        async def _route_handoff(self, state):
            return {}

        async def _extract_issues(self, state):
            return {}

        async def _filter_it_issues(self, state):
            return {}

        async def _process_issues(self, state):
            return {}

        async def _evaluate_handoff(self, state):
            return {}

        async def _build_response(self, state):
            return {}

        async def _save_conversation(self, state):
            return {}

    assert build_agent_workflow_graph(dict, StubWorkflow())


def test_workflow_node_implementations_are_split_by_domain() -> None:
    assert ClarificationWorkflowMixin._load_conversation
    assert HandoffWorkflowMixin._route_handoff
    assert IssueProcessingWorkflowMixin._process_issues
    assert ResponseWorkflowMixin._build_response
