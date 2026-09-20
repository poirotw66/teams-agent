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

## True RAG Pipeline Benchmark (`scripts/run_rag_pipeline_eval.py`)

Unlike `run_retrieval_eval_v2.py` (which only evaluates direct `index.search(query)`), the True RAG Pipeline Benchmark exercises the complete multi-stage pipeline:
1. **Layer 1: Index Retrieval** (HybridIndex direct search)
2. **Layer 2: Retrieval Pipeline** (Facet planning -> batch query embeddings -> multi-query RRF -> candidate selection -> adaptive EvidenceBundle expansion)
3. **Candidate Recall@24**: Oracle ceiling for reranker headroom (evaluating the unpruned Top 24 candidate pool)
4. **Retrieval Failure Taxonomy**: Automatic root-cause categorization when Evidence Recall@4 < 1.0

### Candidate Recall@24 & Oracle Reranker Headroom

Evaluated on `split=all` (101 cases) and `split=test` (33 cases):

| Split | Candidate Recall@24 | Evidence Recall@4 | Headroom (Delta) |
|---|---|---|---|
| `split=test` (33 cases) | 66.67% | 66.67% | **0.00 pp** (0 cases) |
| `split=all` (101 cases) | 59.41% | 56.44% | **+2.97 pp** (4 cases) |

**Key Architectural Insight**:
The maximum potential gain an oracle reranker (e.g. Vertex Ranking, Qwen3) can achieve across the entire 101 evaluation suite is **at most 2.97 percentage points (4 cases)**. The candidate retrieval pool already caps total recall at 59.41%.

### Retrieval Failure Taxonomy (`split=all`, 40 failure cases)

Automated diagnosis of the 40 cases failing Evidence Recall@4:

| Category | Count | Pct | Root Cause & Diagnosis |
|---|---|---|---|
| `WRONG_SECTION_OR_CHUNKING` | **26** | **65.0%** | Correct document retrieved in Top 24 candidates, but the specific expected chunk/section was not matched due to chunk boundary fragmentation or missing contextual header propagation. |
| `NO_ANSWER_FALSE_NEGATIVE` | **6** | **15.0%** | Expected no-answer case, but irrelevant chunks scored above threshold and were returned as answers. |
| `NO_ANSWER_FALSE_POSITIVE` | **4** | **10.0%** | Expected valid answer, but retrieval scores fell below confidence threshold and triggered false rejection. |
| `RANKING_OR_RERANKER_OPPORTUNITY` | **4** | **10.0%** | Correct chunk was present in Top 24 candidate pool, but was ranked > 4. **Only these 4 cases could be saved by a reranker.** |
| `ACL_OR_GROUP_FILTER` | 0 | 0.0% | No failures caused by ACL or group authorization mismatch. |
| `FACET_OR_QUERY_DRIFT` | 0 | 0.0% | Facet planning did not displace relevant primary chunks. |
| `OUT_OF_INDEX_OR_UNINDEXED` | 0 | 0.0% | Target documents exist in index. |

### Component Attribution: Multi-Step Ablation Matrix (`split=all`, 101 cases)

| Config | Variant | Evidence Recall@4 | Candidate Recall@24 | Hit@1 | No-Ans F1 | Latency P95 |
|---|---|---|---|---|---|---|
| **A** | Vanilla Weighted (Linear Sum) | 55.94% | 59.41% | 42.57% | 43.48% | ~630 ms |
| **B** | + RRF Document Fusion | **56.44%** | **59.41%** | **58.42%** (+15.85pp) | **58.33%** (+14.85pp) | 628.7 ms |
| **C** | + Sparse Fast Path | 56.44% | 59.41% | 58.42% | 58.33% | 628.7 ms |
| **D** | + Provider-Safe Batch Query Embedding | 56.44% | 59.41% | 56.44% | 58.33% | 620.5 ms |
| **E** | + Query-Level RRF (Option B Rewrite) | 56.44% | 59.41% | 58.42% | 58.33% | 625.0 ms |
| **F** | + Adaptive EvidenceBundle (Full Pipeline) | 56.44% | 59.41% | 58.42% | 58.33% | **613.1 ms** |

### P0 Correctness: Provider-Safe Batch Query Embedding

- **Problem**: `GoogleGenerativeAIEmbeddings.embed_documents()` implicitly passes `task_type="RETRIEVAL_DOCUMENT"`, degrading asymmetric query embeddings into document vector space when batch-embedding facet/rewrite queries.
- **Solution**: `agent_service.retrieval_embeddings.embed_queries_batch()` inspects client signature and enforces `task_type="RETRIEVAL_QUERY"`, ensuring strict parity between `embed_query()` and batch execution across asymmetric models while preserving compatibility for symmetric models (OpenAI, HuggingFace).

## Explicit non-goals (unchanged)

No GraphRAG / Vector DB / workflow rewrite / microservice / Answer-Citation rewrite until Evidence Recall@4 + answer quality move together.

