#!/usr/bin/env python3
"""Shadow / experiment matrix runner for RAG v2 (spec §44–§47).

Compares the A/B/C/D matrix on the hard eval set without changing production
defaults:

    A = WEIGHTED (plain index)
    B = RRF (plain index)
    C = RRF + in-memory contextual retrieval_text
    D = RRF + contextual + reranker (``--reranker-model``, default lexical)

    cd agent_service
    uv run python ../scripts/run_rag_v2_shadow_eval.py \\
        --variants A,B,C,D \\
        --output ../outputs/rag-v2-shadow.json

    # §45-cleared stack (needs Gemini credentials):
    uv run python ../scripts/run_rag_v2_shadow_eval.py \\
        --variants A,D --reranker-model listwise:gemini-2.5-flash
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_service" / "src"))

from agent_service.rag_rollout import (  # noqa: E402
    VARIANT_A_WEIGHTED,
    VARIANT_B_RRF,
    VARIANT_C_RRF_CONTEXTUAL,
    VARIANT_D_RRF_CONTEXTUAL_RERANK,
    top1_changed,
    topk_overlap,
)
from agent_service.reranker import build_default_reranker  # noqa: E402
from agent_service.retrieval import HybridIndex  # noqa: E402
from agent_service.retrieval_eval_metrics import (  # noqa: E402
    aggregate_case_scores,
    score_retrieval_case,
)
from agent_service.settings import RagSettings  # noqa: E402
from knowledge_core.contextual_representation import (  # noqa: E402
    apply_contextual_representation,
)

_VARIANT_ALIASES = {
    "A": VARIANT_A_WEIGHTED,
    "B": VARIANT_B_RRF,
    "C": VARIANT_C_RRF_CONTEXTUAL,
    "D": VARIANT_D_RRF_CONTEXTUAL_RERANK,
    VARIANT_A_WEIGHTED: VARIANT_A_WEIGHTED,
    VARIANT_B_RRF: VARIANT_B_RRF,
    VARIANT_C_RRF_CONTEXTUAL: VARIANT_C_RRF_CONTEXTUAL,
    VARIANT_D_RRF_CONTEXTUAL_RERANK: VARIANT_D_RRF_CONTEXTUAL_RERANK,
}


def _contextualize_index(index: HybridIndex, *, fusion_mode: str, settings: Any) -> HybridIndex:
    already_contextual = all((chunk.retrieval_text or "").strip() for chunk in index.chunks)
    if already_contextual:
        return HybridIndex(
            list(index.chunks),
            embedding_model=index.embedding_model_name,
            fusion_mode=fusion_mode,
            rrf_k=settings.rag_rrf_k,
            sparse_candidate_k=settings.rag_sparse_candidate_k,
            dense_candidate_k=settings.rag_dense_candidate_k,
            fusion_candidate_k=max(settings.rag_fusion_candidate_k, 20),
        )
    chunks = []
    for chunk in index.chunks:
        clone = copy.deepcopy(chunk)
        apply_contextual_representation(clone)
        # Preserve dense vectors when present; only drop them if absent so BM25
        # tokenization matches the rebuilt retrieval_text without stale mismatch.
        if not clone.vector:
            clone.vector = None
        chunks.append(clone)
    return HybridIndex(
        chunks,
        embedding_model=index.embedding_model_name if any(c.vector for c in chunks) else None,
        fusion_mode=fusion_mode,
        rrf_k=settings.rag_rrf_k,
        sparse_candidate_k=settings.rag_sparse_candidate_k,
        dense_candidate_k=settings.rag_dense_candidate_k,
        fusion_candidate_k=max(settings.rag_fusion_candidate_k, 20),
    )


def _build_index_for_variant(
    *,
    base: HybridIndex,
    variant: str,
    settings: Any,
) -> HybridIndex:
    if variant == VARIANT_A_WEIGHTED:
        return HybridIndex(
            list(base.chunks),
            embedding_model=base.embedding_model_name,
            fusion_mode="RRF",
            rrf_k=settings.rag_rrf_k,
            sparse_candidate_k=settings.rag_sparse_candidate_k,
            dense_candidate_k=settings.rag_dense_candidate_k,
            fusion_candidate_k=max(settings.rag_fusion_candidate_k, 20),
        )
    if variant == VARIANT_B_RRF:
        return HybridIndex(
            list(base.chunks),
            embedding_model=base.embedding_model_name,
            fusion_mode="RRF",
            rrf_k=settings.rag_rrf_k,
            sparse_candidate_k=settings.rag_sparse_candidate_k,
            dense_candidate_k=settings.rag_dense_candidate_k,
            fusion_candidate_k=max(settings.rag_fusion_candidate_k, 20),
        )
    if variant in {VARIANT_C_RRF_CONTEXTUAL, VARIANT_D_RRF_CONTEXTUAL_RERANK}:
        return _contextualize_index(base, fusion_mode="RRF", settings=settings)
    raise ValueError(f"Unknown variant: {variant}")


def _rank_titles(
    index: HybridIndex,
    query: str,
    *,
    limit: int,
    fusion_mode: str | None = None,
) -> list[str]:
    results = index.search(query, limit=limit, groups=set(), fusion_mode=fusion_mode)
    titles: list[str] = []
    seen: set[str] = set()
    for item in results:
        title = item.chunk.title
        if title in seen:
            continue
        seen.add(title)
        titles.append(title)
    return titles


async def _rank_titles_with_rerank(
    index: HybridIndex,
    query: str,
    *,
    limit: int,
    timeout_ms: int,
    model_name: str,
) -> list[str]:
    results = index.search(query, limit=max(limit, 24), groups=set())
    reranker = build_default_reranker(
        enabled=True,
        timeout_ms=timeout_ms,
        model_name=model_name,
    )
    ranked = await reranker.rerank(query=query, candidates=results, limit=limit)
    titles: list[str] = []
    seen: set[str] = set()
    for item in ranked:
        title = item.chunk.title
        if title in seen:
            continue
        seen.add(title)
        titles.append(title)
    return titles


def _score_ranked(
    *,
    cases: list[dict[str, Any]],
    rankings: dict[str, list[str]],
) -> dict[str, float]:
    scored = []
    for case in cases:
        ranked = rankings[case["id"]]
        relevant = list(case.get("expectedSourceTitles") or [])
        hard_negatives = [item["title"] for item in case.get("hardNegatives") or []]
        grades = {
            str(key): float(value) for key, value in (case.get("relevanceGrades") or {}).items()
        }
        scored.append(
            score_retrieval_case(
                case_id=case["id"],
                ranked_ids=ranked,
                relevant_ids=relevant,
                relevance_grades=grades,
                hard_negative_ids=hard_negatives,
                forbidden_ids=list(case.get("forbiddenSourceTitles") or []),
            )
        )
    return aggregate_case_scores(scored)


async def _evaluate_variant(
    *,
    index: HybridIndex,
    variant: str,
    cases: list[dict[str, Any]],
    limit: int,
    timeout_ms: int,
    reranker_model: str,
) -> tuple[dict[str, float], dict[str, list[str]], float]:
    rankings: dict[str, list[str]] = {}
    started = time.perf_counter()
    for case in cases:
        query = case["query"]
        if variant == VARIANT_D_RRF_CONTEXTUAL_RERANK:
            rankings[case["id"]] = await _rank_titles_with_rerank(
                index,
                query,
                limit=limit,
                timeout_ms=timeout_ms,
                model_name=reranker_model,
            )
        elif variant == VARIANT_A_WEIGHTED:
            rankings[case["id"]] = _rank_titles(
                index, query, limit=limit, fusion_mode="LEGACY_WEIGHTED"
            )
        else:
            rankings[case["id"]] = _rank_titles(index, query, limit=limit)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    summary = _score_ranked(cases=cases, rankings=rankings)
    summary["variant"] = variant
    summary["elapsedMs"] = elapsed_ms
    summary["caseCount"] = len(cases)
    return summary, rankings, elapsed_ms


def _pairwise_shadow(
    *,
    baseline_id: str,
    candidate_id: str,
    baseline_ranks: dict[str, list[str]],
    candidate_ranks: dict[str, list[str]],
    k: int,
) -> dict[str, Any]:
    changed = 0
    overlaps: list[float] = []
    for case_id, baseline in baseline_ranks.items():
        candidate = candidate_ranks.get(case_id, [])
        if top1_changed(baseline, candidate):
            changed += 1
        overlaps.append(topk_overlap(baseline, candidate, k=k))
    total = max(len(baseline_ranks), 1)
    return {
        "baseline": baseline_id,
        "candidate": candidate_id,
        "top1ChangeRate": round(changed / total, 4),
        "topkOverlapMean": round(sum(overlaps) / len(overlaps), 4) if overlaps else 0.0,
        "casesCompared": len(baseline_ranks),
    }


def main() -> int:
    from agent_service.eval_credentials import apply_eval_gemini_credentials

    apply_eval_gemini_credentials(dotenv_path=ROOT / "agent_service" / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--eval-set",
        type=Path,
        default=ROOT / "data" / "eval" / "retrieval_eval_v2.json",
    )
    parser.add_argument(
        "--variants",
        default=None,
        help="Comma-separated A/B/C/D (or full variant ids). Default A,B,C,D.",
    )
    parser.add_argument(
        "--modes",
        default=None,
        help="Deprecated alias: WEIGHTED,RRF maps to A,B.",
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--reranker-model",
        default="lexical",
        help="PairScorer for variant D (lexical | listwise | listwise:gemini-2.5-flash).",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    settings = RagSettings.from_env()
    cases = json.loads(args.eval_set.read_text(encoding="utf-8"))["cases"]

    if args.modes and not args.variants:
        mapped = []
        for mode in [item.strip().upper() for item in args.modes.split(",") if item.strip()]:
            if mode == "WEIGHTED":
                mapped.append("A")
            elif mode == "RRF":
                mapped.append("B")
        variant_keys = mapped
    else:
        raw = args.variants or "A,B,C,D"
        variant_keys = [item.strip() for item in raw.split(",") if item.strip()]

    variants = [_VARIANT_ALIASES[key.upper() if len(key) == 1 else key] for key in variant_keys]

    base = HybridIndex.load(
        settings.index_path,
        settings.embedding_model,
        fusion_mode="WEIGHTED",
        rrf_k=settings.rag_rrf_k,
        sparse_candidate_k=settings.rag_sparse_candidate_k,
        dense_candidate_k=settings.rag_dense_candidate_k,
        fusion_candidate_k=max(settings.rag_fusion_candidate_k, args.limit),
    )

    from agent_service.eval_credentials import eval_gemini_report_fields

    report: dict[str, Any] = {
        "evalSet": str(args.eval_set),
        "indexPath": str(settings.index_path),
        **eval_gemini_report_fields(),
        "indexHasVectors": any(bool(chunk.vector) for chunk in base.chunks),
        "indexHasRetrievalText": any(bool(chunk.retrieval_text) for chunk in base.chunks),
        "rerankerModel": args.reranker_model,
        "variants": {},
        "shadowComparisons": [],
        "notes": [
            "Local index may be BM25-only; C/D apply contextual text in-memory.",
            f"D uses PairScorer model_name={args.reranker_model!r}.",
            "Offline §45 label-free gate: scripts/run_rag_v2_section45_eval.py",
        ],
    }

    rankings_by_variant: dict[str, dict[str, list[str]]] = {}

    async def _run() -> None:
        for variant in variants:
            index = _build_index_for_variant(base=base, variant=variant, settings=settings)
            summary, rankings, _elapsed = await _evaluate_variant(
                index=index,
                variant=variant,
                cases=cases,
                limit=args.limit,
                timeout_ms=int(getattr(settings, "rag_rerank_timeout_ms", 700)),
                reranker_model=args.reranker_model,
            )
            report["variants"][variant] = summary
            rankings_by_variant[variant] = rankings
            print(variant, json.dumps(summary, ensure_ascii=False))

        if VARIANT_A_WEIGHTED in rankings_by_variant:
            baseline = VARIANT_A_WEIGHTED
            for candidate in variants:
                if candidate == baseline:
                    continue
                comparison = _pairwise_shadow(
                    baseline_id=baseline,
                    candidate_id=candidate,
                    baseline_ranks=rankings_by_variant[baseline],
                    candidate_ranks=rankings_by_variant[candidate],
                    k=min(args.limit, 5),
                )
                report["shadowComparisons"].append(comparison)
                print("SHADOW", json.dumps(comparison, ensure_ascii=False))

    asyncio.run(_run())

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
