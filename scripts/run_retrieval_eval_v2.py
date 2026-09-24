#!/usr/bin/env python3
"""Run RAG v2 / v2.1 hard retrieval eval (docs/rag-v2-spec.md §6–§7).

Scores ranked HybridIndex results against ``data/eval/retrieval_eval_v2.json``.
When ``expectedChunkIds`` / ``expectedEvidence`` are present, reports chunk and
evidence metrics (Evidence Recall@4). Title-only labels remain as fallback.

Usage:

    cd agent_service
    uv run python ../scripts/run_retrieval_eval_v2.py \\
        --eval-set ../data/eval/retrieval_eval_v2.json \\
        --fusion-mode WEIGHTED \\
        --split test \\
        --output ../outputs/retrieval-eval-v2-weighted.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_service" / "src"))

from agent_service.knowledge_pipeline.retrieval_confidence import (  # noqa: E402
    calibrated_predict_no_answer,
)
from agent_service.retrieval import HybridIndex  # noqa: E402
from agent_service.retrieval_eval_metrics import (  # noqa: E402
    NoAnswerOutcome,
    aggregate_case_scores,
    no_answer_confusion,
    score_retrieval_case,
)
from agent_service.retrieval_eval_schema import EvidenceLevelCase  # noqa: E402
from agent_service.settings import RagSettings  # noqa: E402


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload["cases"])


def _rank_results(
    index: HybridIndex,
    query: str,
    *,
    limit: int,
) -> tuple[list[str], list[str], list[str], list[float], float]:
    """Return (ranked_ids, titles, texts, scores, latency_ms)."""
    started = time.perf_counter()
    results = index.search(query, limit=limit, groups=set())
    latency_ms = (time.perf_counter() - started) * 1000.0
    ranked_ids: list[str] = []
    titles: list[str] = []
    texts: list[str] = []
    scores: list[float] = []
    seen_titles: set[str] = set()
    for item in results:
        ranked_ids.append(item.chunk.chunk_id)
        scores.append(float(item.score))
        texts.append(
            "\n".join(
                part
                for part in (
                    item.chunk.title,
                    item.chunk.section or "",
                    item.chunk.content,
                )
                if part
            )
        )
        title = item.chunk.title
        if title not in seen_titles:
            seen_titles.add(title)
            titles.append(title)
    return ranked_ids, titles, texts, scores, latency_ms


def main() -> int:
    from agent_service.eval_credentials import apply_eval_gemini_credentials

    apply_eval_gemini_credentials(dotenv_path=ROOT / "agent_service" / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--eval-set",
        type=Path,
        default=ROOT / "data" / "eval" / "retrieval_eval_v2.json",
    )
    parser.add_argument("--fusion-mode", choices=("WEIGHTED", "RRF"), default="WEIGHTED")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--split", choices=("all", "dev", "test"), default="all")
    parser.add_argument("--min-score", type=float, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    settings = RagSettings.from_env()
    min_score = (
        float(args.min_score)
        if args.min_score is not None
        else float(settings.min_score)
    )
    index = HybridIndex.load(
        settings.index_path,
        settings.embedding_model,
        fusion_mode=args.fusion_mode,
        rrf_k=settings.rag_rrf_k,
        sparse_candidate_k=settings.rag_sparse_candidate_k,
        dense_candidate_k=settings.rag_dense_candidate_k,
        fusion_candidate_k=max(settings.rag_fusion_candidate_k, args.limit),
        sparse_weight=settings.rag_sparse_weight,
        dense_weight=settings.rag_dense_weight,
    )

    cases = _load_cases(args.eval_set)
    if args.split != "all":
        cases = [case for case in cases if case.get("split", "dev") == args.split]

    scored_rows = []
    no_answer_rows: list[NoAnswerOutcome] = []
    latencies_ms: list[float] = []
    for raw in cases:
        case = EvidenceLevelCase.from_dict(raw)
        ranked_ids, titles, texts, scores, latency_ms = _rank_results(
            index, case.query, limit=args.limit
        )
        latencies_ms.append(latency_ms)
        relevant = list(case.primary_relevant_ids())
        # When scoring chunk ids, grades keyed by title still apply to titles only;
        # fall back to uniform grades over relevant ids.
        grades = {
            str(key): float(value) for key, value in (raw.get("relevanceGrades") or {}).items()
        }
        if case.expected_chunk_ids and not any(chunk_id in grades for chunk_id in relevant):
            grades = {chunk_id: 1.0 for chunk_id in relevant}
        hard_negatives = [item["title"] for item in raw.get("hardNegatives") or []]
        if case.expected_chunk_ids:
            # Hard negatives remain title-level; convert via ranked title parallel is
            # imperfect — keep title hard-neg accuracy only when scoring titles.
            hard_negatives = []
        forbidden = list(case.forbidden_evidence or raw.get("forbiddenSourceTitles") or [])
        evidence_must = [list(fact.must_contain) for fact in case.expected_evidence]
        case_score = score_retrieval_case(
            case_id=case.case_id,
            ranked_ids=ranked_ids if case.expected_chunk_ids else titles,
            relevant_ids=relevant,
            relevance_grades=grades,
            hard_negative_ids=hard_negatives,
            forbidden_ids=forbidden,
            retrieved_texts=texts,
            evidence_must_contain=evidence_must,
        )
        predicted_no_answer = calibrated_predict_no_answer(
            ranked_ids=ranked_ids,
            scores=scores,
            texts=texts,
            query=case.query,
            min_score=min_score,
            titles=titles,
        )
        no_answer_rows.append(
            NoAnswerOutcome(
                expected_no_answer=not case.expected_found,
                predicted_no_answer=predicted_no_answer,
            )
        )
        scored_rows.append(case_score)

    summary = aggregate_case_scores(scored_rows)
    summary["noAnswer"] = no_answer_confusion(no_answer_rows)
    summary["fusionMode"] = args.fusion_mode
    summary["evalSet"] = str(args.eval_set)
    summary["split"] = args.split
    summary["minScore"] = min_score
    summary["caseCount"] = float(len(cases))
    if latencies_ms:
        summary["latencyMsP50"] = float(statistics.median(latencies_ms))
        summary["latencyMsP95"] = float(
            statistics.quantiles(latencies_ms, n=20)[18]
            if len(latencies_ms) >= 20
            else max(latencies_ms)
        )
        summary["latencyMsMean"] = float(statistics.fmean(latencies_ms))
    summary["answerMetricsNote"] = (
        "Answer Correctness / Groundedness / Cost: use scripts/retrieval_ab_test.py"
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        from agent_service.eval_credentials import eval_gemini_report_fields

        payload = {
            "summary": summary,
            **eval_gemini_report_fields(),
            "cases": [
                {
                    "caseId": row.case_id,
                    "recallAt4": row.recall_at_4,
                    "precisionAt4": row.precision_at_4,
                    "evidenceRecallAt4": row.evidence_recall_at_4,
                    "evidencePrecisionAt4": row.evidence_precision_at_4,
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
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
