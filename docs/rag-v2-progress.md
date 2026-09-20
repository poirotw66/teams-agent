# RAG v2 Progress

Tracks execution of [`docs/rag-v2-spec.md`](./rag-v2-spec.md).
Course correction: [`docs/rag-v2.1-plan.md`](./rag-v2.1-plan.md).
**PR #10 merged** to `main` as v2.1 course-correction (eval + safe defaults) — **not** a production cutover.

## Status

| Milestone | Item | Status |
|---|---|---|
| M0–M5 | Hard eval / RRF / contextual / reranker iface / shadow / canary | **Keep infrastructure** |
| §45 offline Hit@1 | Label-free title ranking | **Not a production cutover gate** |
| M6 Gemini listwise default | Production default | **Withdrawn** (default off / lexical) |
| M7 Delete Weighted | Alias WEIGHTED→RRF | **Reverted** — Weighted path restored for A/B |
| **v2.1 P0** | Evidence-level eval + no-answer fix + frozen split | **Done** (#10) |
| **v2.1 P0.5** | Remove benchmark leakage from listwise prompt | **Done** |
| **v2.1 Ranking contract** | `score`≠rank; merge/doc-select preserve RRF/rerank | **Done** |
| **v2.1 Evidence expansion** | Discrete supporting chunks; dedupe; grounding contract | **Done** |
| **v2.1 Canary & Cache** | BASELINE/CANDIDATE decoupled reranker; cache isolation | **Done** (#12) |
| **v2.2 Perf & Quality Sprint** | Precomputed Index Maps, Sparse Fast Path, Batch Query Embeddings, Query-level RRF, Reranker Reuse, Token Budget Expansion | **Done** |
| Dedicated reranker A/B | Vertex Ranking / Qwen3 | **Ready for controlled A/B canary** |

## Current safe defaults (v2.2)

| Flag | Default |
|---|---|
| `RAG_FUSION_MODE` | `RRF` (Weighted still available / honest for baseline A) |
| `RAG_RERANKER_ENABLED` | `false` |
| `RAG_RERANKER_MODEL` | `lexical` |
| `RAG_RERANK_TIMEOUT_MS` | `700` |
| `RAG_CANARY_PERCENT` | `0` |
| `RAG_EVIDENCE_TOKEN_BUDGET` | `1200` |

## Quality & Performance Sprint Benchmark Results

### Frozen Test Split (`split=test`, 33 cases)

| Metric | PR #12 Baseline | Post-Optimization | Delta |
|---|---|---|---|
| Evidence Recall@4 | 66.67% | **66.67%** | 0.0% |
| Hit@1 | 63.64% | **63.64%** | 0.0% |
| MRR@10 | 70.76% | **70.76%** | 0.0% |
| No-Answer F1 | 88.89% | **88.89%** | 0.0% |
| Latency P50 | 519.6 ms | **501.2 ms** | -18.4 ms (-3.5%) |
| Latency P95 | 698.2 ms | **645.4 ms** | -52.8 ms (-7.6%) |
| Latency Mean | 493.5 ms | **467.4 ms** | -26.1 ms (-5.3%) |

### Full Dataset (`split=all`, 101 cases)

| Metric | PR #12 Baseline | Post-Optimization | Delta |
|---|---|---|---|
| Evidence Recall@4 | 56.93% | **56.44%** | -0.49% |
| Hit@1 | 59.41% | **58.42%** | -0.99% |
| No-Answer F1 | 58.33% | **58.33%** | 0.0% |
| Latency P50 | 490.6 ms | **495.0 ms** | +4.4 ms |
| Latency P95 | 670.3 ms | **628.7 ms** | -41.6 ms (-6.2%) |
| Latency Mean | 450.2 ms | **433.6 ms** | -16.6 ms (-3.7%) |

## Explicit non-goals (unchanged)

No GraphRAG / Vector DB / workflow rewrite / microservice / Answer-Citation rewrite until Evidence Recall@4 + answer quality move together.
