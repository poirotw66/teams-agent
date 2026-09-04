"""Shared eval harness doubles for governance lifecycle tests."""

from __future__ import annotations

from ai_ops_backoffice.governance_domain.eval_flow import (
    AgentWorkflowFlowHarness,
    DeterministicAgentFlowHarness,
    PromptFlowHarness,
)


class DeterministicTurnExecutor:
    """AgentTurnExecutor that reuses deterministic routing for lab publish tests."""

    def execute(
        self,
        *,
        template: str,
        model_id: str,
        text: str,
        history: list[dict[str, str]] | None,
    ):
        return DeterministicAgentFlowHarness().observe(
            template=template,
            text=text,
            history=history,
            model_id=model_id,
        )


def release_eligible_lab_harness() -> PromptFlowHarness:
    """Release-eligible harness for tests that must exercise publish gates."""
    return AgentWorkflowFlowHarness(
        DeterministicTurnExecutor(),
        fixture_metadata={
            "version": "deterministic-lab-fixture-v1",
            "layer": "flowRegression",
            "knowledgeQualityAcceptance": False,
            "note": "lab double; not live Agent/RAG acceptance",
        },
    )