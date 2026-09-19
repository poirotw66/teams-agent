#!/usr/bin/env python3
"""Reproduce label-free §45 gate using Soft-best RRF + Gemini cache + title-protect.

Does not call Gemini live — uses ``outputs/rag-v2-gemini-listwise-cache.json``
and ``outputs/rag-v2-query-embeddings.json`` produced by prior offline runs.

    cd agent_service
    uv run python ../scripts/run_rag_v2_section45_eval.py \
        --output ../outputs/rag-v2-label-free-policy.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_service" / "src"))

from agent_service.retrieval import (  # noqa: E402
    HybridIndex,
    SearchResult,
    cosine_similarity,
    tokenize,
)
from agent_service.retrieval_blend import blend_soft_and_listwise_top1  # noqa: E402
from agent_service.retrieval_eval_metrics import (  # noqa: E402
    aggregate_case_scores,
    score_retrieval_case,
)
from agent_service.retrieval_fusion import reciprocal_rank_fusion  # noqa: E402
from agent_service.settings import RagSettings  # noqa: E402


def _bm25_scores(query: str, tokenized: list[list[str]]) -> list[float]:
    query_tokens = tokenize(query)
    doc_count = len(tokenized)
    avg_len = mean(len(tokens) for tokens in tokenized) if tokenized else 1.0
    document_frequency: Counter[str] = Counter()
    for tokens in tokenized:
        document_frequency.update(set(tokens))
    k1, b = 1.5, 0.75
    scores = [0.0] * doc_count
    for index, doc_tokens in enumerate(tokenized):
        term_counts = Counter(doc_tokens)
        length = len(doc_tokens)
        score = 0.0
        for term in query_tokens:
            frequency = term_counts[term]
            if not frequency:
                continue
            idf = math.log(
                1
                + (doc_count - document_frequency[term] + 0.5)
                / (document_frequency[term] + 0.5)
            )
            score += idf * frequency * (k1 + 1) / (
                frequency + k1 * (1 - b + b * length / avg_len)
            )
        scores[index] = score
    return scores


def _soft_rrf(
    *,
    case: dict,
    chunks: list,
    tokenized: list[list[str]],
    query_embeddings: dict[str, list[float]],
) -> list[SearchResult]:
    query = case["query"]
    query_vector = query_embeddings[query]
    sparse = _bm25_scores(query, tokenized)
    max_sparse = max(sparse) or 0.0
    normalized = [score / max_sparse if max_sparse else 0.0 for score in sparse]
    results = [
        SearchResult(
            chunk=chunk,
            score=normalized[index],
            sparse_score=normalized[index],
            dense_score=(
                max(0.0, cosine_similarity(query_vector, chunk.vector))
                if chunk.vector
                else None
            ),
        )
        for index, chunk in enumerate(chunks)
    ]
    sparse_ranked = sorted(
        (
            SearchResult(
                chunk=item.chunk,
                score=item.sparse_score,
                sparse_score=item.sparse_score,
                dense_score=item.dense_score,
            )
            for item in results
            if item.sparse_score > 0
        ),
        key=lambda item: item.sparse_score,
        reverse=True,
    )[:40]
    dense_ranked = sorted(
        (
            SearchResult(
                chunk=item.chunk,
                score=item.dense_score or 0.0,
                sparse_score=item.sparse_score,
                dense_score=item.dense_score,
            )
            for item in results
            if item.dense_score and item.dense_score > 0
        ),
        key=lambda item: item.dense_score or 0.0,
        reverse=True,
    )[:10]
    return reciprocal_rank_fusion(
        sparse_results=sparse_ranked,
        dense_results=dense_ranked,
        k=5,
        sparse_weight=0.5,
        dense_weight=1.5,
    )


def _uniq_docs(ranked: list[SearchResult], limit: int = 12) -> list[SearchResult]:
    unique: list[SearchResult] = []
    seen: set[str] = set()
    for item in ranked:
        if item.chunk.title in seen:
            continue
        seen.add(item.chunk.title)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def _listwise_top(
    case_id: str,
    soft: list[SearchResult],
    orders: dict[str, list[int]],
) -> SearchResult | None:
    order = orders.get(case_id)
    unique = _uniq_docs(soft, 12)
    if not order or len(unique) < 2:
        return None
    clipped = [index for index in order if 1 <= index <= len(unique)]
    if not clipped:
        return None
    return unique[clipped[0] - 1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--eval",
        type=Path,
        default=ROOT / "data" / "eval" / "retrieval_eval_v2.json",
    )
    parser.add_argument(
        "--embeddings",
        type=Path,
        default=ROOT / "outputs" / "rag-v2-query-embeddings.json",
    )
    parser.add_argument(
        "--orders",
        type=Path,
        default=ROOT / "outputs" / "rag-v2-gemini-listwise-cache.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "outputs" / "rag-v2-label-free-policy.json",
    )
    args = parser.parse_args()

    cases = json.loads(args.eval.read_text(encoding="utf-8"))["cases"]
    query_embeddings = json.loads(args.embeddings.read_text(encoding="utf-8"))
    orders = json.loads(args.orders.read_text(encoding="utf-8"))
    index = HybridIndex.load(RagSettings.from_env().index_path, None)
    chunks = index.chunks
    tokenized = [
        tokenize(
            (chunk.retrieval_text or "").strip()
            or f"{chunk.title}\n{chunk.content}"
        )
        for chunk in chunks
    ]

    baseline = {
        "hitAt1": 0.7524752475247525,
        "mrrAt10": 0.7984598459845986,
        "hardNegativeAccuracy": 0.9090909090909091,
        "recallAt20": 0.8594059405940594,
    }
    scores = []
    for case in cases:
        soft = _soft_rrf(
            case=case,
            chunks=chunks,
            tokenized=tokenized,
            query_embeddings=query_embeddings,
        )
        ranked = blend_soft_and_listwise_top1(
            query=case["query"],
            soft_ranked=soft,
            listwise_top=_listwise_top(case["id"], soft, orders),
        )
        titles: list[str] = []
        seen: set[str] = set()
        for item in ranked[:20]:
            if item.chunk.title in seen:
                continue
            seen.add(item.chunk.title)
            titles.append(item.chunk.title)
        scores.append(
            score_retrieval_case(
                case_id=case["id"],
                ranked_ids=titles,
                relevant_ids=list(case.get("expectedSourceTitles") or []),
                hard_negative_ids=[
                    item["title"] for item in case.get("hardNegatives") or []
                ],
            )
        )

    metrics = aggregate_case_scores(scores)
    delta_hit = metrics["hitAt1"] - baseline["hitAt1"]
    delta_mrr = (metrics["mrrAt10"] - baseline["mrrAt10"]) / baseline["mrrAt10"]
    delta_hard = metrics["hardNegativeAccuracy"] - baseline["hardNegativeAccuracy"]
    gate = (delta_mrr >= 0.08 and delta_hit >= 0.08) or delta_hard >= 0.10
    payload = {
        "baselineWeighted": baseline,
        "labelFreeSoftGeminiTitleProtect": {
            "hitAt1": metrics["hitAt1"],
            "mrrAt10": metrics["mrrAt10"],
            "hardNegativeAccuracy": metrics["hardNegativeAccuracy"],
            "recallAt20": metrics["recallAt20"],
            "deltaHitAt1": delta_hit,
            "deltaMrrRelative": delta_mrr,
            "deltaHardNeg": delta_hard,
            "gate45": gate,
            "policy": (
                "soft-best RRF + Gemini listwise top1 + title-protect "
                "(no ground-truth labels)"
            ),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["labelFreeSoftGeminiTitleProtect"], indent=2))
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
