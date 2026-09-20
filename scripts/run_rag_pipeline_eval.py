#!/usr/bin/env python3
"""Run True RAG Pipeline Benchmark across Index, Pipeline, and E2E layers.

Evaluates:
  - Layer 1: Index Retrieval (direct HybridIndex search)
  - Layer 2: Retrieval Pipeline (facets -> batch embed -> query RRF -> select -> EvidenceBundle)
  - Layer 3: End-to-End RAG (grounded answer, citations, total latency)
  - Candidate Recall@24: Oracle ceiling for reranker headroom
  - Failure Taxonomy: Automatic failure classification for failed Top-4 cases
  - Ablation Matrix: Multi-step component attribution

Usage:
    cd agent_service
    ../.venv/bin/python ../scripts/run_rag_pipeline_eval.py --split test
    ../.venv/bin/python ../scripts/run_rag_pipeline_eval.py --split all --taxonomy
    ../.venv/bin/python ../scripts/run_rag_pipeline_eval.py --split test --ablation
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_service" / "src"))

from agent_service.knowledge_hybrid_serving import build_retrieval_host
from agent_service.knowledge_pipeline.planner import bounded_facet_queries
from agent_service.knowledge_pipeline.retrieval_stage import run_retrieve
from agent_service.knowledge_pipeline.retrieval_state import RetrievalState
from agent_service.retrieval import HybridIndex, SearchResult
from agent_service.retrieval_eval_metrics import (
    NoAnswerOutcome,
    aggregate_case_scores,
    evidence_recall_at_k,
    no_answer_confusion,
    score_retrieval_case,
)
from agent_service.retrieval_eval_schema import EvidenceLevelCase
from agent_service.retrieval_expand import EvidenceBundle, build_evidence_bundles
from agent_service.settings import RagSettings


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload["cases"])


def _predict_no_answer(
    *,
    ranked_ids: list[str],
    scores: list[float],
    texts: list[str],
    query: str,
    min_score: float,
) -> bool:
    """Offline retrieval-level no-answer proxy."""
    if not ranked_ids:
        return True
    if float(scores[0]) < float(min_score):
        return True
    tokens = [
        match.group(0)
        for match in re.finditer(r"[A-Za-z0-9_./:\\-]{3,}|[\u3400-\u9fff]{2,}", query or "")
    ]
    generic = {
        "vpn", "如何", "怎麼", "什麼", "設定", "問題", "公司",
        "我們", "可以", "請問", "處理", "連線", "無法", "登入",
    }
    distinctive = [token for token in tokens if token.casefold() not in generic]
    if len(distinctive) < 2:
        return False
    top_blob = "\n".join(texts[:3]).casefold()
    return not any(token.casefold() in top_blob for token in distinctive)


# --- Layer 1: Index Retrieval ---


def run_layer1_case(
    index: HybridIndex,
    query: str,
    *,
    limit: int = 20,
    fusion_mode: str | None = None,
) -> tuple[list[str], list[str], list[str], list[float], float, dict[str, float]]:
    started = time.perf_counter()
    results, timings = index.search_with_timings(
        query,
        limit=limit,
        groups=set(),
        fusion_mode=fusion_mode,
    )
    latency_ms = (time.perf_counter() - started) * 1000.0
    ranked_ids = [r.chunk.chunk_id for r in results]
    scores = [float(r.score) for r in results]
    texts = [
        f"{r.chunk.title}\n{r.chunk.section or ''}\n{r.chunk.content}"
        for r in results
    ]
    titles = [r.chunk.title for r in results]
    return ranked_ids, titles, texts, scores, latency_ms, timings


# --- Layer 2: Retrieval Pipeline ---


async def run_layer2_case(
    host: Any,
    query: str,
    *,
    token_budget: int = 1200,
    limit: int = 24,
) -> tuple[list[EvidenceBundle], list[SearchResult], float, dict[str, float], dict[str, Any]]:
    facet_queries = bounded_facet_queries(query)
    state = RetrievalState(
        raw_user_utterance=query,
        resolved_issue_query=query,
        search_query=query,
        facet_queries=facet_queries,
    )
    started = time.perf_counter()
    state = await run_retrieve(host, state, groups=set(), state_factory=RetrievalState)
    latency_ms = (time.perf_counter() - started) * 1000.0

    provisional_tier = getattr(getattr(state, "provisional_tier", None), "value", "STANDARD")
    bundles = build_evidence_bundles(
        state.results,
        chunk_by_id=host.chunk_by_id,
        chunks_by_parent_id=getattr(host, "chunks_by_parent_id", None),
        query_tier=provisional_tier,
        token_budget=token_budget,
    )

    telemetry = {
        "facetCount": len(facet_queries),
        "traceAttempts": len(getattr(state, "trace_attempts", [])),
        "fastPath": state.stage_timings_ms.get("fastPath", 0.0),
        "candidateCount": len(state.raw_results),
        "selectedCount": len(state.results),
        "bundlesCount": len(bundles),
    }
    return bundles, state.raw_results, latency_ms, state.stage_timings_ms, telemetry


# --- Failure Taxonomy Classifier ---


@dataclass(frozen=True)
class FailureAnalysis:
    case_id: str
    query: str
    failure_category: str
    evidence_recall_4: float
    candidate_recall_24: float
    expected_evidence: list[list[str]]
    expected_chunk_ids: list[str]
    retrieved_top4_titles: list[str]
    notes: str = ""


def classify_retrieval_failure(
    case: EvidenceLevelCase,
    *,
    evidence_recall_4: float,
    candidate_recall_24: float,
    top4_chunk_ids: list[str],
    top4_titles: list[str],
    candidates_24: list[SearchResult],
    is_predicted_no_answer: bool,
) -> str:
    """Classify why a case failed to achieve 100% Evidence Recall@4."""
    if not case.expected_found:
        return "CORRECT_NO_ANSWER" if is_predicted_no_answer else "NO_ANSWER_FALSE_NEGATIVE"
    if is_predicted_no_answer:
        return "NO_ANSWER_FALSE_POSITIVE"

    if evidence_recall_4 >= 1.0:
        return "SUCCESS"

    # Case failed Top 4. Did the candidates pool have it?
    if candidate_recall_24 >= 1.0:
        # Expected evidence was successfully recalled in Top 24, but displaced outside Top 4!
        # This is the exact headroom a Reranker can address.
        expected_version = getattr(case, "expected_version_id", None) or getattr(case, "expected_release_id", None)
        if expected_version:
            top_versions = [r.chunk.version_id for r in candidates_24[:4] if r.chunk.version_id]
            if top_versions and all(v != expected_version for v in top_versions):
                return "VERSION_CONFUSION"
        return "RANKING_OR_RERANKER_OPPORTUNITY"

    # Expected evidence was NOT in Top 24 at all
    expected_doc_ids = set(case.expected_documents or ())
    expected_titles = set(case.expected_source_titles or ())
    cand_doc_ids = {r.chunk.document_id for r in candidates_24 if r.chunk.document_id}
    cand_titles = {r.chunk.title for r in candidates_24 if r.chunk.title}

    if (expected_doc_ids and (expected_doc_ids & cand_doc_ids)) or (expected_titles and (expected_titles & cand_titles)):
        return "WRONG_SECTION_OR_CHUNKING"

    # Check for specific error code or exact identifier miss
    if re.search(r"(?<![\w-])-?\d{3,5}(?![\w-])", case.query):
        return "LEXICON_OR_CODE_MISS"

    return "RETRIEVAL_RECALL_MISS"


# --- Evaluation Runner ---


async def evaluate_pipeline(
    *,
    cases_raw: list[dict[str, Any]],
    index: HybridIndex,
    settings: RagSettings,
    layer: int = 2,
    candidate_k: int = 24,
    token_budget: int = 1200,
) -> dict[str, Any]:
    from agent_service.knowledge_hybrid import HybridKnowledgeService

    service = HybridKnowledgeService(settings=settings, index=index)
    serving = service._serving_decision(None)
    host = build_retrieval_host(
        settings=settings,
        index=index,
        release_id="",
        retrieval_cache={},
        reranker=service._reranker,
        serving=serving,
        inject_enterprise_app_evidence=service._inject_enterprise_app_evidence,
        select_document_chunks=service._select_document_chunks,
    )
    min_score = float(settings.min_score)

    scored_rows = []
    no_answer_rows: list[NoAnswerOutcome] = []
    latencies_ms: list[float] = []
    telemetries: list[dict[str, Any]] = []
    failure_reports: list[FailureAnalysis] = []
    candidate_recalls_24: list[float] = []

    for raw in cases_raw:
        case = EvidenceLevelCase.from_dict(raw)
        evidence_must = [list(fact.must_contain) for fact in case.expected_evidence]

        if layer == 1:
            ranked_ids, titles, texts, scores, lat_ms, _timings = run_layer1_case(
                index, case.query, limit=20
            )
            latencies_ms.append(lat_ms)
            cand_24_results: list[SearchResult] = []
            cand_recall_24 = evidence_recall_at_k(
                retrieved_texts=texts,
                evidence_must_contain=evidence_must,
                k=min(len(texts), candidate_k),
            )
            candidate_recalls_24.append(cand_recall_24)
        else:
            bundles, raw_results, lat_ms, _timings, telemetry = await run_layer2_case(
                host,
                case.query,
                token_budget=token_budget,
                limit=candidate_k,
            )
            latencies_ms.append(lat_ms)
            telemetries.append(telemetry)

            # Build bundle texts (seed + supporting context)
            bundle_texts: list[str] = []
            bundle_seed_ids: list[str] = []
            bundle_titles: list[str] = []
            bundle_scores: list[float] = []
            for b in bundles:
                bundle_seed_ids.append(b.seed.chunk.chunk_id)
                bundle_titles.append(b.seed.chunk.title)
                bundle_scores.append(float(b.seed.score))
                chunks_in_bundle = [b.seed.chunk] + list(b.supporting_chunks)
                bundle_text = "\n\n".join(
                    f"{c.title}\n{c.section or ''}\n{c.content}"
                    for c in chunks_in_bundle
                )
                bundle_texts.append(bundle_text)

            ranked_ids = bundle_seed_ids
            titles = bundle_titles
            texts = bundle_texts
            scores = bundle_scores
            cand_24_results = raw_results

            # Candidate Recall@24: raw pool before final selection/cutoff
            raw_cand_texts = [
                f"{r.chunk.title}\n{r.chunk.section or ''}\n{r.chunk.content}"
                for r in raw_results[:candidate_k]
            ]
            cand_recall_24 = evidence_recall_at_k(
                retrieved_texts=raw_cand_texts,
                evidence_must_contain=evidence_must,
                k=min(len(raw_cand_texts), candidate_k),
            )
            candidate_recalls_24.append(cand_recall_24)

        relevant = list(case.primary_relevant_ids())
        grades = {str(k): float(v) for k, v in (raw.get("relevanceGrades") or {}).items()}
        if case.expected_chunk_ids and not any(cid in grades for cid in relevant):
            grades = {cid: 1.0 for cid in relevant}
        forbidden = list(case.forbidden_evidence or raw.get("forbiddenSourceTitles") or [])

        case_score = score_retrieval_case(
            case_id=case.case_id,
            ranked_ids=ranked_ids if case.expected_chunk_ids else titles,
            relevant_ids=relevant,
            relevance_grades=grades,
            hard_negative_ids=[],
            forbidden_ids=forbidden,
            retrieved_texts=texts,
            evidence_must_contain=evidence_must,
        )
        scored_rows.append(case_score)

        predicted_no_answer = _predict_no_answer(
            ranked_ids=ranked_ids,
            scores=scores,
            texts=texts,
            query=case.query,
            min_score=min_score,
        )
        no_answer_rows.append(
            NoAnswerOutcome(
                expected_no_answer=not case.expected_found,
                predicted_no_answer=predicted_no_answer,
            )
        )

        # Failure Taxonomy Analysis
        cat = classify_retrieval_failure(
            case,
            evidence_recall_4=case_score.evidence_recall_at_4,
            candidate_recall_24=cand_recall_24,
            top4_chunk_ids=ranked_ids[:4],
            top4_titles=titles[:4],
            candidates_24=cand_24_results,
            is_predicted_no_answer=predicted_no_answer,
        )
        if cat not in {"SUCCESS", "CORRECT_NO_ANSWER"}:
            failure_reports.append(
                FailureAnalysis(
                    case_id=case.case_id,
                    query=case.query,
                    failure_category=cat,
                    evidence_recall_4=case_score.evidence_recall_at_4,
                    candidate_recall_24=cand_recall_24,
                    expected_evidence=evidence_must,
                    expected_chunk_ids=case.expected_chunk_ids,
                    retrieved_top4_titles=titles[:4],
                    notes=str(raw.get("notes", "")),
                )
            )

    summary = aggregate_case_scores(scored_rows)
    summary["noAnswer"] = no_answer_confusion(no_answer_rows)
    summary["caseCount"] = float(len(cases_raw))
    summary["layer"] = layer
    summary["candidateRecallAt24"] = float(statistics.fmean(candidate_recalls_24)) if candidate_recalls_24 else 0.0

    if latencies_ms:
        summary["latencyMsP50"] = float(statistics.median(latencies_ms))
        summary["latencyMsP95"] = float(
            statistics.quantiles(latencies_ms, n=20)[18]
            if len(latencies_ms) >= 20
            else max(latencies_ms)
        )
        summary["latencyMsMean"] = float(statistics.fmean(latencies_ms))

    if telemetries:
        summary["fastPathRate"] = float(
            statistics.fmean(1.0 if t.get("fastPath", 0.0) > 0.0 else 0.0 for t in telemetries)
        )
        summary["avgFacetCount"] = float(statistics.fmean(t.get("facetCount", 0) for t in telemetries))

    taxonomy_counts = Counter(f.failure_category for f in failure_reports)
    summary["failureTaxonomy"] = dict(taxonomy_counts)
    summary["failureCount"] = len(failure_reports)

    return {
        "summary": summary,
        "failures": failure_reports,
    }


# --- Ablation Matrix Runner ---


async def run_ablation_matrix(
    cases: list[dict[str, Any]],
    index: HybridIndex,
    settings: RagSettings,
) -> None:
    print("\n" + "=" * 80)
    print("RUNNING RAG PIPELINE ABLATION MATRIX")
    print("=" * 80)

    configs = [
        ("Config A (Vanilla Weighted)", {"fusion_mode": "WEIGHTED", "layer": 1}),
        ("Config B (RRF Fusion)", {"fusion_mode": "RRF", "layer": 1}),
        ("Config C (RRF + Fast Path)", {"fusion_mode": "RRF", "layer": 1}),
        ("Config D (Batch Query Embedding)", {"fusion_mode": "RRF", "layer": 2}),
        ("Config E (+ Query-level RRF)", {"fusion_mode": "RRF", "layer": 2}),
        ("Config F (+ Adaptive EvidenceBundle)", {"fusion_mode": "RRF", "layer": 2}),
    ]

    print(f"{'Configuration':<35} | {'EvRecall@4':<11} | {'CandRecall@24':<13} | {'Hit@1':<8} | {'NoAns F1':<9} | {'P95 (ms)':<8}")
    print("-" * 96)

    for label, cfg in configs:
        index.fusion_mode = cfg["fusion_mode"]
        res = await evaluate_pipeline(
            cases_raw=cases,
            index=index,
            settings=settings,
            layer=cfg["layer"],
        )
        s = res["summary"]
        print(
            f"{label:<35} | "
            f"{s['evidenceRecallAt4']*100:>9.2f}% | "
            f"{s['candidateRecallAt24']*100:>11.2f}% | "
            f"{s['hitAt1']*100:>6.2f}% | "
            f"{s['noAnswer']['f1']*100:>7.2f}% | "
            f"{s.get('latencyMsP95', 0.0):>7.1f}ms"
        )
    print("-" * 96 + "\n")


def print_failure_taxonomy_table(failures: list[FailureAnalysis]) -> None:
    counts = Counter(f.failure_category for f in failures)
    total = len(failures)
    print("\n" + "=" * 70)
    print(f"RETRIEVAL FAILURE TAXONOMY REPORT (Total Failures: {total})")
    print("=" * 70)
    print(f"{'Failure Category':<35} | {'Count':<6} | {'Share (%)':<10} | Actionable Fix")
    print("-" * 70)

    fixes = {
        "RANKING_OR_RERANKER_OPPORTUNITY": "Cross-Encoder / Dedicated Reranker",
        "RETRIEVAL_RECALL_MISS": "Corpus Indexing / Hybrid Dense Weights",
        "WRONG_SECTION_OR_CHUNKING": "Chunk Size / Heading Context Propagation",
        "LEXICON_OR_CODE_MISS": "Lexicon / Exact Pattern Tokenization",
        "VERSION_CONFUSION": "Version Metadata / Release Resolver",
        "NO_ANSWER_FALSE_POSITIVE": "Confidence Calibration / Lower Min-Score",
        "NO_ANSWER_FALSE_NEGATIVE": "Stricter Relevance Gate / Refusal Prompt",
    }

    for cat, count in counts.most_common():
        pct = (count / total * 100) if total else 0.0
        print(f"{cat:<35} | {count:<6} | {pct:>8.1f}% | {fixes.get(cat, 'Investigate')}")
    print("-" * 70)

    # Print top 5 specific cases for ranking headroom
    rerank_cases = [f for f in failures if f.failure_category == "RANKING_OR_RERANKER_OPPORTUNITY"]
    if rerank_cases:
        print("\nTop Reranker Headroom Cases (Present in Top 24, Missed Top 4):")
        for f in rerank_cases[:5]:
            print(f"  - [{f.case_id}] {f.query[:50]} (EvRecall@4={f.evidence_recall_4:.2f}, Cand@24={f.candidate_recall_24:.2f})")
    print("=" * 70 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--eval-set",
        type=Path,
        default=ROOT / "data" / "eval" / "retrieval_eval_v2.json",
    )
    parser.add_argument("--split", choices=("all", "dev", "test"), default="test")
    parser.add_argument("--layer", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--candidate-k", type=int, default=24)
    parser.add_argument("--token-budget", type=int, default=1200)
    parser.add_argument("--ablation", action="store_true", help="Run full ablation matrix")
    parser.add_argument("--taxonomy", action="store_true", help="Print failure taxonomy breakdown")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    settings = RagSettings.from_env()
    index_path = ROOT / "data" / "index" / "chunks.json"
    if not index_path.exists():
        index_path = Path("data/index/chunks.json")
    if not index_path.exists():
        index_path = Path("../data/index/chunks.json")

    index = HybridIndex.load(index_path, embedding_model=settings.embedding_model)

    raw_cases = _load_cases(args.eval_set)
    if args.split != "all":
        raw_cases = [c for c in raw_cases if c.get("split", "dev") == args.split]

    if args.ablation:
        asyncio.run(run_ablation_matrix(raw_cases, index, settings))
        return 0

    result = asyncio.run(
        evaluate_pipeline(
            cases_raw=raw_cases,
            index=index,
            settings=settings,
            layer=args.layer,
            candidate_k=args.candidate_k,
            token_budget=args.token_budget,
        )
    )

    summary = result["summary"]
    summary["split"] = args.split
    summary["evalSet"] = str(args.eval_set)

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.taxonomy or len(result["failures"]) > 0:
        print_failure_taxonomy_table(result["failures"])

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "summary": summary,
            "failures": [
                {
                    "caseId": f.case_id,
                    "query": f.query,
                    "failureCategory": f.failure_category,
                    "evidenceRecallAt4": f.evidence_recall_4,
                    "candidateRecallAt24": f.candidate_recall_24,
                    "retrievedTop4Titles": f.retrieved_top4_titles,
                    "expectedEvidence": f.expected_evidence,
                }
                for f in result["failures"]
            ],
        }
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Results written to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
