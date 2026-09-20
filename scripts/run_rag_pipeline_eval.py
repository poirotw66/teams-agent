#!/usr/bin/env python3
"""Run True RAG Pipeline Benchmark across Index, Pipeline, and E2E layers.

Evaluates:
  - Layer 1: Index Retrieval (direct HybridIndex search)
  - Layer 2: Retrieval Pipeline (facets -> batch embed -> query RRF -> select -> EvidenceBundle)
  - Layer 3: End-to-End RAG (grounded answer, citations, total latency, token cost)
  - Candidate Recall@24: Oracle ceiling for reranker headroom
  - Failure Taxonomy: Automatic failure classification for failed Top-4 cases
  - Ablation Matrix: Multi-step component attribution with real toggles
  - Within-Doc Oracle: Ground-truth bounded recall diagnostic

Usage:
    cd agent_service
    ../.venv/bin/python ../scripts/run_rag_pipeline_eval.py --split test
    ../.venv/bin/python ../scripts/run_rag_pipeline_eval.py --split all --taxonomy
    ../.venv/bin/python ../scripts/run_rag_pipeline_eval.py --split test --ablation
    ../.venv/bin/python ../scripts/run_rag_pipeline_eval.py --split all --within-doc-oracle
    ../.venv/bin/python ../scripts/run_rag_pipeline_eval.py --split test --layer 3
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

from agent_service.contracts import KnowledgeResult, UserContext
from agent_service.knowledge_hybrid import HybridKnowledgeService
from agent_service.knowledge_hybrid_serving import build_retrieval_host
from agent_service.knowledge_pipeline.planner import bounded_facet_queries
from agent_service.knowledge_pipeline.query_tier import classify_query_tier
from agent_service.knowledge_pipeline.relevance import _GENERIC_LEXICAL_TOKENS
from agent_service.knowledge_pipeline.retrieval_stage import run_retrieve
from agent_service.knowledge_pipeline.retrieval_state import RetrievalState
from agent_service.retrieval import HybridIndex, SearchResult, tokenize
from agent_service.retrieval_eval_metrics import (
    NoAnswerOutcome,
    aggregate_case_scores,
    evidence_fact_hit,
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


def calibrated_predict_no_answer(
    *,
    ranked_ids: list[str],
    scores: list[float],
    texts: list[str],
    query: str,
    min_score: float = 0.45,
) -> bool:
    """Calibrated retrieval-level no-answer predictor.

    Combines CJK tokenization, stopword filtering, and top-3 evidence overlap ratio.
    """
    if not ranked_ids or not scores:
        return True

    query_tokens = [
        t for t in tokenize(query)
        if t not in _GENERIC_LEXICAL_TOKENS and len(t) >= 2
    ]
    if not query_tokens:
        query_tokens = [t for t in tokenize(query) if t not in _GENERIC_LEXICAL_TOKENS]
    if not query_tokens:
        return True

    top_text = " ".join(texts[:3]).casefold()
    overlap = [t for t in query_tokens if t.casefold() in top_text]
    overlap_ratio = len(overlap) / len(query_tokens)

    if len(overlap) == 0:
        return True
    return len(query_tokens) >= 3 and overlap_ratio < 0.20


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
    enable_evidence_expand: bool = True,
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

    provisional = classify_query_tier(
        state,
        min_score=host.min_score,
        max_retrieval_rewrites=0,
    )
    query_tier = provisional.tier.value
    if enable_evidence_expand:
        bundles = build_evidence_bundles(
            state.results,
            chunk_by_id=host.chunk_by_id,
            chunks_by_parent_id=getattr(host, "chunks_by_parent_id", None),
            query_tier=query_tier,
            token_budget=token_budget,
        )
    else:
        bundles = [EvidenceBundle(seed=r, supporting_chunks=[]) for r in state.results]

    telemetry = {
        "facetCount": len(facet_queries),
        "traceAttempts": len(getattr(state, "trace_attempts", [])),
        "fastPath": state.stage_timings_ms.get("fastPath", 0.0),
        "batchEmbeddingMs": state.stage_timings_ms.get("batchEmbeddingMs", 0.0),
        "batchEmbeddingQueryCount": state.stage_timings_ms.get("batchEmbeddingQueryCount", 0.0),
        "candidateCount": len(state.raw_results),
        "selectedCount": len(state.results),
        "bundlesCount": len(bundles),
        "queryTier": query_tier,
    }
    return bundles, state.raw_results, latency_ms, state.stage_timings_ms, telemetry


# --- Layer 3: End-to-End RAG ---


async def run_layer3_case(
    service: HybridKnowledgeService,
    query: str,
    *,
    token_budget: int = 1200,
) -> tuple[KnowledgeResult, float, dict[str, Any]]:
    started = time.perf_counter()
    user_context = UserContext()
    result = await service.search(query=query, user_context=user_context)
    latency_ms = (time.perf_counter() - started) * 1000.0

    trace = getattr(result, "retrievalTrace", None)
    timings = getattr(trace, "stageTimingsMs", {}) if trace else {}
    telemetry = {
        "found": result.found,
        "answerLength": len(result.answer),
        "sourcesCount": len(result.sources),
        "claimsCount": len(getattr(result, "claims", [])),
        "terminalReason": getattr(result, "terminalReason", None),
        "queryTier": getattr(trace, "queryTier", None),
        "timings": timings,
    }
    return result, latency_ms, telemetry


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

    expected_doc_ids = set(case.expected_documents or ())
    expected_titles = set(case.expected_source_titles or ())

    # If the case has no evidence tokens, document hit in top 4 counts as SUCCESS
    if not case.expected_evidence and (
        (expected_doc_ids and (expected_doc_ids & set(top4_chunk_ids)))
        or (expected_titles and (expected_titles & set(top4_titles)))
    ):
        return "SUCCESS"

    # Case failed Top 4. Did the candidates pool have it?
    if candidate_recall_24 >= 1.0:
        expected_version = getattr(case, "expected_version_id", None) or getattr(case, "expected_release_id", None)
        if expected_version:
            top_versions = [r.chunk.version_id for r in candidates_24[:4] if r.chunk.version_id]
            if top_versions and all(v != expected_version for v in top_versions):
                return "VERSION_CONFUSION"
        return "RANKING_OR_RERANKER_OPPORTUNITY"

    # Expected evidence was NOT in Top 24 at all
    cand_doc_ids = {r.chunk.document_id for r in candidates_24 if r.chunk.document_id}
    cand_titles = {r.chunk.title for r in candidates_24 if r.chunk.title}

    if (expected_doc_ids and (expected_doc_ids & cand_doc_ids)) or (expected_titles and (expected_titles & cand_titles)):
        return "WRONG_SECTION_OR_CHUNKING"

    if re.search(r"(?<![\w-])-?\d{3,5}(?![\w-])", case.query):
        return "LEXICON_OR_CODE_MISS"

    return "RETRIEVAL_RECALL_MISS"


# --- Within-Document Recall Oracle ---


def run_within_doc_oracle(
    cases_raw: list[dict[str, Any]],
    index: HybridIndex,
) -> dict[str, Any]:
    """Execute Within-Document Recall Oracle diagnostic for cases."""
    print("\n" + "=" * 80)
    print("RUNNING WITHIN-DOCUMENT RECALL ORACLE DIAGNOSTIC")
    print("=" * 80)

    rows: list[dict[str, Any]] = []
    recalls: list[float] = []
    top1_hits: list[float] = []
    doc_hits: list[float] = []

    for raw in cases_raw:
        case = EvidenceLevelCase.from_dict(raw)
        if not case.expected_found:
            continue
        exp_docs = set(case.expected_documents or ()) | set(case.expected_source_titles or ())
        doc_chunks = [
            c for c in index.chunks
            if (c.document_id and c.document_id in exp_docs)
            or (c.title and c.title in exp_docs)
        ]
        if not doc_chunks:
            continue

        doc_index = HybridIndex(
            doc_chunks,
            embedding_model=None,
            enable_sparse_fast_path=False,
        )
        results, _ = doc_index.search_with_timings(case.query, limit=4)
        top4_texts = [
            f"{r.chunk.title}\n{r.chunk.section or ''}\n{r.chunk.content}"
            for r in results[:4]
        ]
        top4_titles = [r.chunk.title for r in results[:4]]
        evidence_must = [list(fact.must_contain) for fact in case.expected_evidence]

        if evidence_must:
            recall = evidence_recall_at_k(
                retrieved_texts=top4_texts,
                evidence_must_contain=evidence_must,
                k=4,
            )
        else:
            recall = 1.0 if any(t in exp_docs for t in top4_titles) else 0.0

        recalls.append(recall)
        hit_top1 = top4_titles[0] in exp_docs if top4_titles else False
        top1_hits.append(1.0 if hit_top1 else 0.0)
        hit_doc = any(t in exp_docs for t in top4_titles)
        doc_hits.append(1.0 if hit_doc else 0.0)

        rows.append({
            "caseId": case.case_id,
            "query": case.query,
            "chunksInDoc": len(doc_chunks),
            "withinDocRecall4": recall,
            "top1Hit": hit_top1,
            "docHit4": hit_doc,
        })

    avg_recall = float(statistics.fmean(recalls)) if recalls else 0.0
    avg_top1 = float(statistics.fmean(top1_hits)) if top1_hits else 0.0
    avg_hit = float(statistics.fmean(doc_hits)) if doc_hits else 0.0

    print(f"{'Case ID':<28} | {'Chunks':<6} | {'Recall@4':<9} | {'Top-1 Hit':<10} | {'Hit@4':<6}")
    print("-" * 72)
    for r in rows[:15]:
        print(
            f"{r['caseId']:<28} | "
            f"{r['chunksInDoc']:<6} | "
            f"{r['withinDocRecall4']*100:>7.1f}% | "
            f"{'YES' if r['top1Hit'] else 'NO':<10} | "
            f"{'YES' if r['docHit4'] else 'NO':<6}"
        )
    if len(rows) > 15:
        print(f"... ({len(rows) - 15} more cases)")
    print("-" * 72)
    print(f"Overall WithinDocRecall@4: {avg_recall*100:.2f}% (across {len(rows)} evaluated cases)")
    print(f"Overall Top-1 Document Hit: {avg_top1*100:.2f}%")
    print(f"Overall Top-4 Document Hit: {avg_hit*100:.2f}%")
    print("=" * 80 + "\n")

    return {
        "caseCount": len(rows),
        "withinDocRecallAt4": avg_recall,
        "withinDocTop1Hit": avg_top1,
        "withinDocHitAt4": avg_hit,
        "cases": rows,
    }


# --- Evaluation Runner ---


async def evaluate_pipeline(
    *,
    cases_raw: list[dict[str, Any]],
    index: HybridIndex,
    settings: RagSettings,
    layer: int = 2,
    candidate_k: int = 24,
    token_budget: int = 1200,
    enable_fast_path: bool = True,
    enable_batch_embedding: bool = True,
    enable_query_rrf: bool = True,
    enable_evidence_expand: bool = True,
) -> dict[str, Any]:
    index.enable_sparse_fast_path = enable_fast_path
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
        enable_batch_embedding=enable_batch_embedding,
        enable_query_rrf=enable_query_rrf,
    )
    min_score = float(settings.min_score)

    scored_rows = []
    no_answer_rows: list[NoAnswerOutcome] = []
    latencies_ms: list[float] = []
    telemetries: list[dict[str, Any]] = []
    failure_reports: list[FailureAnalysis] = []
    candidate_recalls_24: list[float] = []

    answer_accuracies: list[float] = []
    citation_precisions: list[float] = []
    citation_recalls: list[float] = []
    groundedness_scores: list[float] = []

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
            ) if evidence_must else (1.0 if any(t in (case.expected_documents or case.expected_source_titles) for t in titles[:candidate_k]) else 0.0)
            candidate_recalls_24.append(cand_recall_24)

        elif layer == 2:
            bundles, raw_results, lat_ms, _timings, telemetry = await run_layer2_case(
                host,
                case.query,
                token_budget=token_budget,
                limit=candidate_k,
                enable_evidence_expand=enable_evidence_expand,
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
            ) if evidence_must else (1.0 if any(t in (case.expected_documents or case.expected_source_titles) for t in [r.chunk.title for r in raw_results[:candidate_k]]) else 0.0)
            candidate_recalls_24.append(cand_recall_24)

        else:
            # Layer 3: True End-to-End RAG
            result, lat_ms, telemetry = await run_layer3_case(
                service,
                case.query,
                token_budget=token_budget,
            )
            latencies_ms.append(lat_ms)
            telemetries.append(telemetry)

            ranked_ids = [s.chunkId or s.title for s in result.sources if s.chunkId or s.title]
            titles = [s.title for s in result.sources]
            texts = [result.answer]
            scores = [1.0 for _ in result.sources]
            cand_24_results = []
            cand_recall_24 = 1.0 if result.found else 0.0
            candidate_recalls_24.append(cand_recall_24)

            # E2E Answer Accuracy
            if case.expected_found:
                if evidence_must:
                    ans_hit = sum(
                        1 for tokens in evidence_must
                        if evidence_fact_hit(retrieved_texts=[result.answer], must_contain=tokens)
                    ) / len(evidence_must)
                else:
                    ans_hit = 1.0 if result.found else 0.0
            else:
                ans_hit = 1.0 if not result.found else 0.0
            answer_accuracies.append(ans_hit)

            # E2E Citation Accuracy
            exp_docs = set(case.expected_documents or ()) | set(case.expected_source_titles or ())
            cited_docs = set(titles)
            if cited_docs and exp_docs:
                c_prec = len(cited_docs & exp_docs) / len(cited_docs)
                c_rec = len(cited_docs & exp_docs) / len(exp_docs)
            elif not exp_docs:
                c_prec = 1.0 if not cited_docs else 0.0
                c_rec = 1.0
            else:
                c_prec = 0.0
                c_rec = 0.0
            citation_precisions.append(c_prec)
            citation_recalls.append(c_rec)

            # E2E Groundedness
            claims = getattr(result, "claims", [])
            if claims:
                grounded_ratio = sum(1 for cl in claims if getattr(cl, "chunkIds", None)) / len(claims)
            else:
                grounded_ratio = 1.0 if result.found and result.sources else (1.0 if not result.found else 0.0)
            groundedness_scores.append(grounded_ratio)

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

        predicted_no_answer = calibrated_predict_no_answer(
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
                    expected_chunk_ids=list(case.expected_chunk_ids),
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
        batch_times = [t.get("batchEmbeddingMs", 0.0) for t in telemetries if t.get("batchEmbeddingMs", 0.0) > 0]
        summary["avgBatchEmbeddingMs"] = float(statistics.fmean(batch_times)) if batch_times else 0.0

    if layer == 3:
        summary["answerAccuracy"] = float(statistics.fmean(answer_accuracies)) if answer_accuracies else 0.0
        summary["citationPrecision"] = float(statistics.fmean(citation_precisions)) if citation_precisions else 0.0
        summary["citationRecall"] = float(statistics.fmean(citation_recalls)) if citation_recalls else 0.0
        summary["groundedness"] = float(statistics.fmean(groundedness_scores)) if groundedness_scores else 0.0

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
    print("\n" + "=" * 98)
    print("RUNNING RAG PIPELINE ABLATION MATRIX (REAL COMPONENT TOGGLES)")
    print("=" * 98)

    configs = [
        ("Config A (Vanilla Weighted)", {
            "fusion_mode": "WEIGHTED",
            "layer": 1,
            "enable_fast_path": False,
            "enable_batch_embedding": False,
            "enable_query_rrf": False,
            "enable_evidence_expand": False,
        }),
        ("Config B (RRF Fusion)", {
            "fusion_mode": "RRF",
            "layer": 1,
            "enable_fast_path": False,
            "enable_batch_embedding": False,
            "enable_query_rrf": False,
            "enable_evidence_expand": False,
        }),
        ("Config C (RRF + Fast Path)", {
            "fusion_mode": "RRF",
            "layer": 1,
            "enable_fast_path": True,
            "enable_batch_embedding": False,
            "enable_query_rrf": False,
            "enable_evidence_expand": False,
        }),
        ("Config D (Pipeline L2: Single-pass)", {
            "fusion_mode": "RRF",
            "layer": 2,
            "enable_fast_path": True,
            "enable_batch_embedding": False,
            "enable_query_rrf": False,
            "enable_evidence_expand": False,
        }),
        ("Config E (+ Batch Embed & Query RRF)", {
            "fusion_mode": "RRF",
            "layer": 2,
            "enable_fast_path": True,
            "enable_batch_embedding": True,
            "enable_query_rrf": True,
            "enable_evidence_expand": False,
        }),
        ("Config F (+ Adaptive EvidenceBundle)", {
            "fusion_mode": "RRF",
            "layer": 2,
            "enable_fast_path": True,
            "enable_batch_embedding": True,
            "enable_query_rrf": True,
            "enable_evidence_expand": True,
        }),
    ]

    print(f"{'Configuration':<37} | {'EvRecall@4':<11} | {'CandRecall@24':<13} | {'Hit@1':<8} | {'NoAns F1':<9} | {'P95 (ms)':<8}")
    print("-" * 98)

    for label, cfg in configs:
        index.fusion_mode = cfg["fusion_mode"]
        index.enable_sparse_fast_path = cfg["enable_fast_path"]
        res = await evaluate_pipeline(
            cases_raw=cases,
            index=index,
            settings=settings,
            layer=cfg["layer"],
            enable_fast_path=cfg["enable_fast_path"],
            enable_batch_embedding=cfg["enable_batch_embedding"],
            enable_query_rrf=cfg["enable_query_rrf"],
            enable_evidence_expand=cfg["enable_evidence_expand"],
        )
        s = res["summary"]
        print(
            f"{label:<37} | "
            f"{s['evidenceRecallAt4']*100:>9.2f}% | "
            f"{s['candidateRecallAt24']*100:>11.2f}% | "
            f"{s['hitAt1']*100:>6.2f}% | "
            f"{s['noAnswer']['f1']*100:>7.2f}% | "
            f"{s.get('latencyMsP95', 0.0):>7.1f}ms"
        )
    print("-" * 98 + "\n")


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
    parser.add_argument("--within-doc-oracle", action="store_true", help="Run within-document recall oracle diagnostic")
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

    if args.within_doc_oracle:
        oracle_res = run_within_doc_oracle(raw_cases, index)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(oracle_res, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

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
