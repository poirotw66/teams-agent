"""Export a Golden baseline JSON report as a question-by-question comparison CSV."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

CSV_COLUMNS = (
    "case_id",
    "topic",
    "difficulty",
    "coverage",
    "question",
    "reference_answer",
    "rubric",
    "expected_sources",
    "agent_answer",
    "actual_sources",
    "verdict",
    "correctness",
    "completeness",
    "groundedness",
    "source_match",
    "source_matches",
    "matched_sources",
    "missing_sources",
    "claim_assessments",
    "unsupported_claims",
    "missing_required_facts",
    "judge_confidence",
    "review_status",
    "secondary_verdict",
    "primary_assessment",
    "secondary_assessment",
    "adjudication_assessment",
    "needs_human_review",
    "judge_reason",
    "judge_queue_ms",
    "judge_latency_ms",
    "target_latency_ms",
    "target_error",
    "correlation_id",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("question_bank", type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args()


def load_question_bank(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    return {str(row.get("題號") or "").strip(): row for row in rows}


def load_report_cases(path: Path) -> list[dict[str, Any]]:
    report = json.loads(path.read_text(encoding="utf-8"))
    cases = report.get("cases")
    if not isinstance(cases, list):
        raise TypeError("Baseline report must contain a cases array")
    return cases


def build_comparison_rows(
    report_cases: list[dict[str, Any]],
    question_bank: dict[str, dict[str, str]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for case in report_cases:
        case_id = str(case.get("caseId") or "")
        golden = question_bank.get(case_id)
        if golden is None:
            raise ValueError(f"Question bank does not contain case {case_id}")
        rows.append(_build_row(case, golden))
    return rows


def _build_row(
    case: dict[str, Any],
    golden: dict[str, str],
) -> dict[str, object]:
    target = _mapping(case.get("target"))
    judge = _mapping(case.get("judge"))
    retrieval = _mapping(judge.get("retrieval"))
    citations = target.get("citations")
    citation_rows = citations if isinstance(citations, list) else []
    actual_sources = _unique_text(
        str(_mapping(citation).get("title") or "") for citation in citation_rows
    )
    return {
        "case_id": case.get("caseId", ""),
        "topic": case.get("topic", ""),
        "difficulty": case.get("difficulty", ""),
        "coverage": case.get("coverage", ""),
        "question": case.get("question", ""),
        "reference_answer": golden.get("詳細答案", ""),
        "rubric": golden.get("解析", ""),
        "expected_sources": _join_values(case.get("expectedSources")),
        "agent_answer": target.get("answer", ""),
        "actual_sources": " | ".join(actual_sources),
        "verdict": judge.get("verdict", ""),
        "correctness": judge.get("correctness", ""),
        "completeness": judge.get("completeness", ""),
        "groundedness": judge.get("groundedness", ""),
        "source_match": judge.get("source_match", ""),
        "source_matches": _json_value(retrieval.get("matches")),
        "matched_sources": _join_values(retrieval.get("matched_sources")),
        "missing_sources": _join_values(retrieval.get("missing_sources")),
        "claim_assessments": _json_value(judge.get("claim_assessments")),
        "unsupported_claims": _join_values(judge.get("unsupported_claims")),
        "missing_required_facts": _join_values(judge.get("missing_required_facts")),
        "judge_confidence": judge.get("confidence", ""),
        "review_status": judge.get("review_status", ""),
        "secondary_verdict": judge.get("secondary_verdict", ""),
        "primary_assessment": _json_value(judge.get("primary_assessment")),
        "secondary_assessment": _json_value(judge.get("secondary_assessment")),
        "adjudication_assessment": _json_value(judge.get("adjudication_assessment")),
        "needs_human_review": judge.get("needs_human_review", ""),
        "judge_reason": judge.get("reason", ""),
        "judge_queue_ms": judge.get("queueMs", ""),
        "judge_latency_ms": judge.get("latencyMs", ""),
        "target_latency_ms": target.get("latencyMs", ""),
        "target_error": target.get("error", ""),
        "correlation_id": target.get("correlationId", ""),
    }


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _join_values(value: object) -> str:
    if not isinstance(value, list):
        return ""
    return " | ".join(str(item) for item in value)


def _json_value(value: object) -> str:
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _unique_text(values: Iterable[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        if value and value not in unique:
            unique.append(value)
    return unique


def write_comparison_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=CSV_COLUMNS,
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        writer.writerows(
            {column: _spreadsheet_safe(row.get(column, "")) for column in CSV_COLUMNS}
            for row in rows
        )


def _spreadsheet_safe(value: object) -> object:
    if not isinstance(value, str):
        return value
    if value.lstrip().startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


def main() -> int:
    args = parse_args()
    question_bank = load_question_bank(args.question_bank)
    report_cases = load_report_cases(args.report)
    rows = build_comparison_rows(report_cases, question_bank)
    write_comparison_csv(args.output, rows)
    print(f"Exported {len(rows)} comparison rows to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
