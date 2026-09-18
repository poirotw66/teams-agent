#!/usr/bin/env python3
"""Compare golden baseline JSON summaries and critical case verdicts."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


CRITICAL = ("QB-016", "QB-017", "QB-048", "QB-078", "QB-079", "QB-084", "QB-097", "QB-098")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def summarize(path: Path) -> None:
    data = load(path)
    summary = data.get("summary") or {}
    verdicts = summary.get("verdicts") or Counter(
        str((case.get("judge") or {}).get("verdict")) for case in data.get("cases", [])
    )
    print(f"== {path.name} ==")
    print(
        f"PASS/PARTIAL/FAIL: "
        f"{verdicts.get('PASS', 0)}/{verdicts.get('PARTIAL', 0)}/{verdicts.get('FAIL', 0)} "
        f"strict={summary.get('strictPassRate')} acceptable={summary.get('acceptableRate')} "
        f"meanLat={summary.get('meanLatencyMs')} p95={summary.get('p95LatencyMs')} "
        f"meanLLM={summary.get('meanLlmCallCount')}"
    )
    by_id = {case["caseId"]: case for case in data.get("cases", [])}
    for case_id in CRITICAL:
        case = by_id.get(case_id)
        if not case:
            continue
        judge = case.get("judge") or {}
        print(
            f"  {case_id}: {judge.get('verdict')} "
            f"corr={judge.get('correctness')} comp={judge.get('completeness')}"
        )


def compare_pair(baseline: Path, candidate: Path) -> None:
    left = {case["caseId"]: case for case in load(baseline)["cases"]}
    right = {case["caseId"]: case for case in load(candidate)["cases"]}
    improved = []
    regressed = []
    for case_id in sorted(set(left) & set(right)):
        left_v = str((left[case_id].get("judge") or {}).get("verdict"))
        right_v = str((right[case_id].get("judge") or {}).get("verdict"))
        rank = {"FAIL": 0, "PARTIAL": 1, "PASS": 2, "INCONCLUSIVE": -1}
        if rank.get(right_v, -1) > rank.get(left_v, -1):
            improved.append(f"{case_id}: {left_v}->{right_v}")
        elif rank.get(right_v, -1) < rank.get(left_v, -1):
            regressed.append(f"{case_id}: {left_v}->{right_v}")
    print(f"-- {baseline.name} -> {candidate.name} --")
    print(f"improved={len(improved)} regressed={len(regressed)}")
    if improved:
        print("improved:", ", ".join(improved[:20]))
    if regressed:
        print("regressed:", ", ".join(regressed[:20]))


def main() -> int:
    paths = [Path(arg) for arg in sys.argv[1:]]
    if not paths:
        print("usage: compare_golden_baselines.py <baseline.json> [more.json...]")
        return 2
    for path in paths:
        summarize(path)
    if len(paths) >= 2:
        for path in paths[1:]:
            compare_pair(paths[0], path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
