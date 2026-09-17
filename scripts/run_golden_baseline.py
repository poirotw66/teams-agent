"""Run a production-contract knowledge baseline with an independent Gemini judge."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from ai_ops_backoffice.evaluation_domain.baseline import (
    AgentTargetResult,
    GeminiAnswerJudge,
    JudgeAssessment,
    KnowledgeBaselineCase,
    ProductionAgentHttpTarget,
    load_question_bank_csv,
)
from ai_ops_backoffice.evaluation_domain.baseline_pipeline import run_baseline_pipeline

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / "agent_service" / ".env", override=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("question_bank", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default="golden-baseline")
    parser.add_argument("--token-env", default="GOLDEN_EVALUATION_TOKEN")
    parser.add_argument(
        "--judge-model",
        default="google_genai:gemini-3.1-pro-preview",
    )
    parser.add_argument("--agent-concurrency", type=int)
    parser.add_argument("--judge-concurrency", type=int)
    parser.add_argument(
        "--max-concurrency",
        type=int,
        help="Deprecated: set both pipeline stages to this concurrency.",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _case_record(
    case: KnowledgeBaselineCase,
    target: AgentTargetResult,
    assessment: JudgeAssessment,
    *,
    judge_queue_ms: float,
    judge_latency_ms: float,
) -> dict[str, Any]:
    return {
        "caseId": case.case_id,
        "topic": case.topic,
        "difficulty": case.difficulty,
        "coverage": case.coverage,
        "question": case.question,
        "expectedSources": list(case.expected_sources),
        "target": {
            "answer": target.answer,
            "citations": list(target.citations),
            "issueResults": list(target.issue_results),
            "correlationId": target.correlation_id,
            "latencyMs": target.latency_ms,
            "error": target.error,
        },
        "judge": {
            **assessment.model_dump(mode="json"),
            "queueMs": judge_queue_ms,
            "latencyMs": judge_latency_ms,
        },
    }


def _group_rates(
    records: list[dict[str, Any]],
    key: str,
) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for record in records:
        grouped[str(record[key])].append(str(record["judge"]["verdict"]))
    return {
        group: {
            "cases": len(verdicts),
            "passRate": round(verdicts.count("PASS") / len(verdicts), 4),
            "acceptableRate": round(
                sum(value in {"PASS", "PARTIAL"} for value in verdicts) / len(verdicts),
                4,
            ),
        }
        for group, verdicts in sorted(grouped.items())
    }


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    verdicts = Counter(str(record["judge"]["verdict"]) for record in records)
    review_statuses = Counter(
        str(record["judge"].get("review_status") or "LEGACY") for record in records
    )
    total = len(records)
    completed = total - verdicts["INCONCLUSIVE"]
    latencies = [float(record["target"]["latencyMs"]) for record in records]
    judge_latencies = [
        float(record["judge"]["latencyMs"])
        for record in records
        if record["judge"].get("latencyMs") is not None
    ]
    judge_queue_times = [
        float(record["judge"]["queueMs"])
        for record in records
        if record["judge"].get("queueMs") is not None
    ]
    scores = [
        float(record["judge"]["correctness"])
        for record in records
        if record["judge"]["verdict"] != "INCONCLUSIVE"
    ]
    return {
        "caseCount": total,
        "conclusiveCount": completed,
        "verdicts": dict(verdicts),
        "strictPassRate": round(verdicts["PASS"] / total, 4),
        "conclusivePassRate": round(verdicts["PASS"] / completed, 4) if completed else None,
        "acceptableRate": round(
            (verdicts["PASS"] + verdicts["PARTIAL"]) / total,
            4,
        ),
        "meanCorrectness": round(statistics.fmean(scores), 4) if scores else None,
        "meanSourceRecall": round(
            statistics.fmean(float(record["judge"]["source_match"]) for record in records),
            4,
        )
        if records
        else None,
        "reviewStatuses": dict(review_statuses),
        "needsHumanReviewCount": sum(
            bool(record["judge"].get("needs_human_review")) for record in records
        ),
        "meanLatencyMs": round(statistics.fmean(latencies), 2) if latencies else None,
        "p95LatencyMs": _percentile(latencies, 0.95),
        "meanJudgeLatencyMs": (
            round(statistics.fmean(judge_latencies), 2) if judge_latencies else None
        ),
        "p95JudgeLatencyMs": _percentile(judge_latencies, 0.95),
        "meanJudgeQueueMs": (
            round(statistics.fmean(judge_queue_times), 2) if judge_queue_times else None
        ),
        "byDifficulty": _group_rates(records, "difficulty"),
        "byTopic": _group_rates(records, "topic"),
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * percentile + 0.999999) - 1))
    return round(ordered[index], 2)


def _build_report(
    *,
    args: argparse.Namespace,
    cases: list[KnowledgeBaselineCase],
    records_by_index: dict[int, dict[str, Any]],
    started_at: datetime,
    is_complete: bool,
) -> dict[str, Any]:
    records = [records_by_index[index] for index in range(len(cases)) if index in records_by_index]
    updated_at = datetime.now(UTC)
    agent_concurrency, judge_concurrency = _resolve_concurrency(args)
    return {
        "schemaVersion": "golden-baseline-v2",
        "startedFromQuestionBank": str(args.question_bank.resolve()),
        "startedAt": started_at.isoformat(),
        "updatedAt": updated_at.isoformat(),
        "completedAt": updated_at.isoformat() if is_complete else None,
        "progress": {
            "status": "COMPLETED" if is_complete else "RUNNING",
            "completed": len(records),
            "total": len(cases),
            "remaining": len(cases) - len(records),
        },
        "target": {
            "kind": "production-agent-http",
            "baseUrl": args.base_url,
            "endpoint": "/agent/evaluation/chat",
        },
        "judge": {
            "modelId": args.judge_model,
            "rubricVersion": "knowledge-answer-judge-v2",
        },
        "pipeline": {
            "agentConcurrency": agent_concurrency,
            "judgeConcurrency": judge_concurrency,
        },
        "summary": summarize_records(records),
        "cases": records,
    }


def _write_report(output: Path, report: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(f"{output.suffix}.tmp")
    temporary_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_output.replace(output)


def _resolve_concurrency(args: argparse.Namespace) -> tuple[int, int]:
    legacy = getattr(args, "max_concurrency", None)
    agent = getattr(args, "agent_concurrency", None) or legacy or 8
    judge = getattr(args, "judge_concurrency", None) or legacy or 16
    return max(1, agent), max(1, judge)


async def run(args: argparse.Namespace) -> dict[str, Any]:
    cases = load_question_bank_csv(args.question_bank.resolve())
    if args.limit is not None:
        cases = cases[: max(0, args.limit)]
    if not cases:
        raise ValueError("No cases selected for evaluation")

    target = ProductionAgentHttpTarget(
        base_url=args.base_url,
        tenant_id=args.tenant_id,
        token=os.environ.get(args.token_env),
    )
    judge = GeminiAnswerJudge(model_id=args.judge_model)
    agent_concurrency, judge_concurrency = _resolve_concurrency(args)
    records_by_index: dict[int, dict[str, Any]] = {}
    started_at = datetime.now(UTC)

    try:
        results = run_baseline_pipeline(
            cases=cases,
            target=target,
            judge=judge,
            agent_concurrency=agent_concurrency,
            judge_concurrency=judge_concurrency,
        )
        completed = 0
        async for result in results:
            completed += 1
            record = _case_record(
                result.case,
                result.target,
                result.assessment,
                judge_queue_ms=result.judge_queue_ms,
                judge_latency_ms=result.judge_latency_ms,
            )
            records_by_index[result.index] = record
            print(
                f"[{completed}/{len(cases)}] {record['caseId']} {record['judge']['verdict']}",
                flush=True,
            )
            checkpoint = _build_report(
                args=args,
                cases=cases,
                records_by_index=records_by_index,
                started_at=started_at,
                is_complete=False,
            )
            _write_report(args.output, checkpoint)
    finally:
        await target.aclose()

    return _build_report(
        args=args,
        cases=cases,
        records_by_index=records_by_index,
        started_at=started_at,
        is_complete=True,
    )


def main() -> int:
    args = parse_args()
    if args.output is None:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        args.output = REPO_ROOT / "outputs" / f"golden-baseline-{timestamp}.json"
    report = asyncio.run(run(args))
    _write_report(args.output, report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Report: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
