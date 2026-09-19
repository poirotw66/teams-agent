#!/usr/bin/env python3
"""Run RAG v2 hard retrieval eval (docs/rag-v2-spec.md §6–§7).

Scores ranked HybridIndex titles against ``data/eval/retrieval_eval_v2.json``
using pure metrics in ``agent_service.retrieval_eval_metrics``.

Usage:

    cd agent_service
    uv run python ../scripts/run_retrieval_eval_v2.py \\
        --eval-set ../data/eval/retrieval_eval_v2.json \\
        --fusion-mode WEIGHTED \\
        --output ../outputs/retrieval-eval-v2-weighted.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_service" / "src"))

from agent_service.retrieval import HybridIndex  # noqa: E402
from agent_service.retrieval_eval_metrics import (  # noqa: E402
    NoAnswerOutcome,
    aggregate_case_scores,
    no_answer_confusion,
    score_retrieval_case,
)
from agent_service.settings import RagSettings  # noqa: E402


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload["cases"])


def _rank_titles(index: HybridIndex, query: str, *, limit: int) -> list[str]:
    results = index.search(query, limit=limit, groups=set())
    titles: list[str] = []
    seen: set[str] = set()
    for item in results:
        title = item.chunk.title
        if title in seen:
            continue
        seen.add(title)
        titles.append(title)
    return titles


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--eval-set",
        type=Path,
        default=ROOT / "data" / "eval" / "retrieval_eval_v2.json",
    )
    parser.add_argument("--fusion-mode", choices=("WEIGHTED", "RRF"), default="WEIGHTED")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    settings = RagSettings.from_env()
    index = HybridIndex.load(
        settings.index_path,
        settings.embedding_model,
        fusion_mode=args.fusion_mode,
        rrf_k=settings.rag_rrf_k,
        sparse_candidate_k=settings.rag_sparse_candidate_k,
        dense_candidate_k=settings.rag_dense_candidate_k,
        fusion_candidate_k=max(settings.rag_fusion_candidate_k, args.limit),
    )

    cases = _load_cases(args.eval_set)
    scored_rows = []
    no_answer_rows: list[NoAnswerOutcome] = []
    for case in cases:
        ranked = _rank_titles(index, case["query"], limit=args.limit)
        relevant = list(case.get("expectedSourceTitles") or [])
        hard_negatives = [item["title"] for item in case.get("hardNegatives") or []]
        grades = {
            str(key): float(value) for key, value in (case.get("relevanceGrades") or {}).items()
        }
        forbidden = list(case.get("forbiddenSourceTitles") or [])
        case_score = score_retrieval_case(
            case_id=case["id"],
            ranked_ids=ranked,
            relevant_ids=relevant,
            relevance_grades=grades,
            hard_negative_ids=hard_negatives,
            forbidden_ids=forbidden,
        )
        predicted_no_answer = len(ranked) == 0 or not case.get("expectedFound", True)
        if not case.get("expectedFound", True):
            # For no-answer cases, treat empty/top-irrelevant as predicted no-answer
            # only when no expected title appears in top-3.
            predicted_no_answer = not any(title in ranked[:3] for title in relevant)
        no_answer_rows.append(
            NoAnswerOutcome(
                expected_no_answer=not bool(case.get("expectedFound", True)),
                predicted_no_answer=predicted_no_answer
                if not case.get("expectedFound", True)
                else False,
            )
        )
        scored_rows.append(case_score)

    summary = aggregate_case_scores(scored_rows)
    summary["noAnswer"] = no_answer_confusion(no_answer_rows)
    summary["fusionMode"] = args.fusion_mode
    summary["evalSet"] = str(args.eval_set)
    summary["caseCount"] = float(len(cases))

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "summary": summary,
            "cases": [
                {
                    "caseId": row.case_id,
                    "recallAt5": row.recall_at_5,
                    "recallAt10": row.recall_at_10,
                    "recallAt20": row.recall_at_20,
                    "mrrAt10": row.mrr_at_10,
                    "ndcgAt10": row.ndcg_at_10,
                    "hitAt1": row.hit_at_1,
                    "hitAt3": row.hit_at_3,
                    "hardNegativeAccuracy": row.hard_negative_accuracy,
                    "aclLeakageCount": row.acl_leakage_count,
                }
                for row in scored_rows
            ],
        }
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
