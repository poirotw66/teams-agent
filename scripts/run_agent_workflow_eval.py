#!/usr/bin/env python3
"""Run production-path AgentWorkflow evaluation.

Each case enters through ``AgentRequest`` and exits as ``AgentResponse`` via
``AgentWorkflowTurnExecutor`` (or a compatible workflow ``respond`` / ``run``).

Usage:
    uv run python scripts/run_agent_workflow_eval.py \\
      --eval-set data/eval/agent_workflow_eval_v1.json \\
      --output data/eval/reports/agent-workflow-eval.json
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_service" / "src"))

from agent_service.agent_workflow_eval import (
    AgentWorkflowEvalCase,
    aggregate_agent_workflow_scores,
    issue_routes_from_state,
    observe_answer_found,
    observe_handoff_triggered,
    observe_ticket_triggered,
    score_agent_workflow_case,
)
from agent_service.contracts import (
    AgentRequest,
    ConversationIdentity,
    MessageContent,
    UserIdentity,
)
from agent_service.eval_agent_harness import run_production_turn
from agent_service.eval_conversation import (
    create_eval_conversation,
    seed_prior_turn,
)
from agent_service.settings import RagSettings


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit_sha() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    sha = completed.stdout.strip()
    return sha or None


def _build_provenance(
    *,
    eval_set: Path,
    settings: RagSettings,
    freeze_version: int | None,
    started_at: str,
    completed_at: str,
) -> dict[str, Any]:
    from agent_service.rag_models import resolve_rag_model_ids

    ids = resolve_rag_model_ids(settings)
    return {
        "commitSha": _git_commit_sha(),
        "datasetPath": str(eval_set),
        "datasetHash": _file_sha256(eval_set),
        "freezeVersion": freeze_version,
        "releaseId": settings.knowledge_active_release_id,
        "agentModel": settings.agent_model or settings.model,
        "answerModel": ids.answer,
        "relevanceModel": ids.relevance,
        "rewriteModel": ids.rewrite,
        "hardAnswerModel": ids.hard_answer,
        "embeddingModel": settings.embedding_model,
        "escalationPolicy": ids.escalation_policy,
        "region": (
            os.environ.get("VERTEX_LOCATION")
            or os.environ.get("GOOGLE_CLOUD_REGION")
            or os.environ.get("GCP_REGION")
        ),
        "startedAt": started_at,
        "completedAt": completed_at,
    }


def _build_request(
    *,
    case: AgentWorkflowEvalCase,
    conversation_id: str,
    teams_user_id: str,
) -> AgentRequest:
    return AgentRequest(
        requestId=f"workflow-eval-{case.case_id}",
        channel="rag-eval",
        conversation=ConversationIdentity(
            tenantId="rag-eval",
            conversationId=conversation_id,
        ),
        user=UserIdentity(
            displayName="workflow-eval",
            teamsUserId=teams_user_id,
            groups=list(case.groups),
        ),
        message=MessageContent(text=case.message),
    )


def _cited_titles(issue_results: list[Any], response: Any) -> tuple[str, ...]:
    titles: list[str] = []
    sources = getattr(response, "sources", None) or []
    for source in sources:
        title = getattr(source, "title", None)
        if title:
            titles.append(str(title))
    for item in issue_results:
        item_sources = getattr(item, "sources", None)
        if item_sources is None and isinstance(item, dict):
            item_sources = item.get("sources") or []
        for source in item_sources or []:
            title = getattr(source, "title", None)
            if title is None and isinstance(source, dict):
                title = source.get("title")
            if title:
                titles.append(str(title))
    return tuple(dict.fromkeys(titles))


async def _run_case(
    *,
    workflow: Any,
    case: AgentWorkflowEvalCase,
    settings: RagSettings,
) -> dict[str, Any]:
    handles = await create_eval_conversation(case_id=case.case_id, settings=settings)
    # Seed and execute against the same ConversationService so prior turns are visible.
    previous_conversation_service = getattr(workflow, "conversation_service", None)
    workflow.conversation_service = handles.service
    try:
        for index, prior in enumerate(case.prior_turns):
            await seed_prior_turn(
                handles,
                prior_turn=prior,
                request_id=f"workflow-eval-{case.case_id}-prior-{index}",
                correlation_id=f"workflow-eval-{case.case_id}",
            )
        request = _build_request(
            case=case,
            conversation_id=handles.teams_conversation_id,
            teams_user_id=handles.teams_user_id,
        )
        # Reuse AgentWorkflowTurnExecutor production entry (request → workflow.run/respond).
        answer, issue_results, state, latency_ms = await run_production_turn(
            workflow, request
        )
    finally:
        if previous_conversation_service is not None:
            workflow.conversation_service = previous_conversation_service
    observed_route = None
    state_dict = state if isinstance(state, dict) else None
    if state_dict is not None:
        decision = state_dict.get("supervisor_decision")
        observed_route = getattr(decision, "intent", None) if decision is not None else None
        execution_context = state_dict.get("execution_context")
        llm_calls = int(getattr(getattr(execution_context, "llm_calls", None), "count", 0) or 0)
    else:
        llm_calls = 0
    observed_issue_routes = issue_routes_from_state(
        state=state_dict, issue_results=issue_results
    )
    if observed_route is None and observed_issue_routes:
        observed_route = observed_issue_routes[0]

    class _ResponseView:
        def __init__(self) -> None:
            self.answer = answer
            self.issueResults = issue_results
            self.sources = []

    response = _ResponseView()
    score = score_agent_workflow_case(
        case=case,
        observed_route=str(observed_route) if observed_route else None,
        observed_issue_count=len(issue_results),
        observed_issue_routes=observed_issue_routes,
        observed_found=observe_answer_found(issue_results),
        cited_titles=_cited_titles(issue_results, response),
        ticket_triggered=observe_ticket_triggered(issue_results, state=state_dict),
        handoff_triggered=observe_handoff_triggered(state=state_dict, answer=answer),
        llm_calls=llm_calls,
        latency_ms=latency_ms,
    )
    return {
        "caseId": case.case_id,
        "score": score,
        "observedRoute": observed_route,
        "issueCount": len(issue_results),
        "answer": answer,
    }


async def evaluate_agent_workflow(
    *,
    cases: list[AgentWorkflowEvalCase],
    workflow: Any,
    settings: RagSettings,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        rows.append(await _run_case(workflow=workflow, case=case, settings=settings))
    scores = [row["score"] for row in rows]
    summary = aggregate_agent_workflow_scores(scores)
    return {"summary": summary, "cases": rows}


def main() -> int:
    from agent_service.eval_credentials import apply_eval_gemini_credentials

    apply_eval_gemini_credentials(dotenv_path=ROOT / "agent_service" / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--eval-set",
        type=Path,
        default=ROOT / "data" / "eval" / "agent_workflow_eval_v1.json",
    )
    parser.add_argument("--live-model", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--workflow-factory",
        default=None,
        help="Optional import path 'module:attr' returning an AgentWorkflow-like object.",
    )
    args = parser.parse_args()
    settings = RagSettings.from_env()
    payload = json.loads(args.eval_set.read_text(encoding="utf-8"))
    cases = [AgentWorkflowEvalCase.from_dict(item) for item in payload["cases"]]
    started_at = datetime.now(UTC).isoformat()

    if args.workflow_factory:
        module_name, attr_name = args.workflow_factory.split(":", 1)
        module = __import__(module_name, fromlist=[attr_name])
        factory = getattr(module, attr_name)
        workflow = factory(settings=settings, live_model=args.live_model)
    else:
        print(
            "ERROR: pass --workflow-factory module:attr that builds AgentWorkflow. "
            "This script does not construct a second workflow harness.",
            file=sys.stderr,
        )
        return 2

    result = asyncio.run(
        evaluate_agent_workflow(cases=cases, workflow=workflow, settings=settings)
    )
    completed_at = datetime.now(UTC).isoformat()
    provenance = _build_provenance(
        eval_set=args.eval_set,
        settings=settings,
        freeze_version=payload.get("freezeVersion"),
        started_at=started_at,
        completed_at=completed_at,
    )
    summary = result["summary"]
    summary["provenance"] = provenance
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {"summary": summary, "provenance": provenance},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
