"""Repair one inconclusive Golden baseline judgment from its cached target result."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from run_golden_baseline import summarize_records

from ai_ops_backoffice.evaluation_domain.baseline import (
    AgentTargetResult,
    GeminiAnswerJudge,
    load_question_bank_csv,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("question_bank", type=Path)
    parser.add_argument("case_id")
    parser.add_argument(
        "--judge-model",
        default="google_genai:gemini-3.1-pro-preview",
    )
    return parser.parse_args()


def _load_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report.get("cases"), list):
        raise TypeError("Baseline report must contain a cases array")
    return report


def _find_report_case(report: dict[str, Any], case_id: str) -> dict[str, Any]:
    for case in report["cases"]:
        if isinstance(case, dict) and case.get("caseId") == case_id:
            return case
    raise ValueError(f"Baseline report does not contain case {case_id}")


def _cached_target(case: dict[str, Any]) -> AgentTargetResult:
    target = case.get("target")
    if not isinstance(target, dict):
        raise TypeError("Baseline case must contain a target object")
    return AgentTargetResult(
        answer=str(target.get("answer") or ""),
        citations=tuple(target.get("citations") or ()),
        issue_results=tuple(target.get("issueResults") or ()),
        correlation_id=target.get("correlationId"),
        latency_ms=float(target.get("latencyMs") or 0.0),
        error=target.get("error"),
    )


def _write_report(path: Path, report: dict[str, Any]) -> None:
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


async def rejudge(args: argparse.Namespace) -> dict[str, Any]:
    report = _load_report(args.report)
    report_case = _find_report_case(report, args.case_id)
    previous_judge = report_case.get("judge")
    if not isinstance(previous_judge, dict):
        raise TypeError("Baseline case must contain a judge object")
    if previous_judge.get("verdict") != "INCONCLUSIVE":
        raise ValueError(f"Case {args.case_id} is not inconclusive")

    cases = load_question_bank_csv(args.question_bank)
    golden_case = next((case for case in cases if case.case_id == args.case_id), None)
    if golden_case is None:
        raise ValueError(f"Question bank does not contain case {args.case_id}")

    judge = GeminiAnswerJudge(model_id=args.judge_model)
    assessment = await judge.judge(golden_case, _cached_target(report_case))
    repaired_at = datetime.now(UTC).isoformat()
    replacement_judge = assessment.model_dump(mode="json")
    report_case["judge"] = replacement_judge
    report["summary"] = summarize_records(report["cases"])
    report["updatedAt"] = repaired_at
    report.setdefault("amendments", []).append(
        {
            "amendmentId": f"{args.case_id}-judge-retry",
            "recordedAt": repaired_at,
            "caseId": args.case_id,
            "reason": "Rejudged cached target output after adding schema retry support.",
            "judgeModelId": args.judge_model,
            "previousJudge": previous_judge,
            "replacementJudge": replacement_judge,
        }
    )
    _write_report(args.report, report)
    return replacement_judge


def main() -> int:
    args = parse_args()
    result = asyncio.run(rejudge(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Updated report: {args.report.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
