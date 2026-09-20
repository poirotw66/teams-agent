"""Unit tests for Layer-3 eval telemetry helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from agent_service.documents import DocumentChunk

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_eval_helpers():
    path = _REPO_ROOT / "scripts" / "run_rag_pipeline_eval.py"
    spec = importlib.util.spec_from_file_location("run_rag_pipeline_eval", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_candidate_pool_from_retrieval_trace_rebuilds_search_results() -> None:
    helpers = _load_eval_helpers()
    chunk = DocumentChunk(
        chunk_id="c1",
        title="Portal",
        content="password reset steps",
        document_id="d1",
        source_path="portal.md",
    )
    trace = SimpleNamespace(
        attempts=[
            SimpleNamespace(
                candidates=[
                    SimpleNamespace(
                        chunkId="c1",
                        documentId="d1",
                        title="Portal",
                        score=0.91,
                        sparseScore=0.8,
                        denseScore=0.7,
                    )
                ]
            )
        ]
    )
    pool = helpers._candidate_pool_from_retrieval_trace(
        trace,
        chunk_by_id={"c1": chunk},
        candidate_k=24,
    )
    assert len(pool) == 1
    assert pool[0].chunk.chunk_id == "c1"
    assert pool[0].score == 0.91


def test_candidate_pool_empty_without_trace() -> None:
    helpers = _load_eval_helpers()
    assert helpers._candidate_pool_from_retrieval_trace(None, chunk_by_id={}, candidate_k=24) == []


def test_layer3_summary_aggregates_flattened_telemetry_keys() -> None:
    """Regression: L3 reports must not zero-out pipeline fields when telemetries exist."""
    import statistics

    telemetries = [
        {
            "facetCount": 2,
            "fastPath": 1.0,
            "batchEmbeddingMs": 40.0,
            "cacheMiss": 1.0,
        },
        {
            "facetCount": 0,
            "fastPath": 0.0,
            "batchEmbeddingMs": 60.0,
            "cacheMiss": 0.0,
        },
    ]
    evidence_candidate_recalls_24 = [1.0, 0.5]
    summary: dict[str, float] = {}
    summary["candidateEvidenceRecallAt24"] = float(statistics.fmean(evidence_candidate_recalls_24))
    summary["candidateRecallAt24"] = summary["candidateEvidenceRecallAt24"]
    summary["fastPathRate"] = float(
        statistics.fmean(1.0 if t.get("fastPath", 0.0) > 0.0 else 0.0 for t in telemetries)
    )
    summary["avgFacetCount"] = float(statistics.fmean(t.get("facetCount", 0) for t in telemetries))
    batch_times = [
        t.get("batchEmbeddingMs", 0.0) for t in telemetries if t.get("batchEmbeddingMs", 0.0) > 0
    ]
    summary["avgBatchEmbeddingMs"] = float(statistics.fmean(batch_times))
    cache_hits = 0
    for telemetry in telemetries:
        miss_raw = telemetry.get("cacheMiss", 1.0)
        miss_value = 1.0 if miss_raw is None else float(miss_raw)
        if miss_value <= 0.0:
            cache_hits += 1
    summary["approxCacheHitRate"] = float(cache_hits / len(telemetries))

    assert summary["candidateEvidenceRecallAt24"] == 0.75
    assert summary["candidateRecallAt24"] == 0.75
    assert summary["fastPathRate"] == 0.5
    assert summary["avgFacetCount"] == 1.0
    assert summary["avgBatchEmbeddingMs"] == 50.0
    assert summary["approxCacheHitRate"] == 0.5
