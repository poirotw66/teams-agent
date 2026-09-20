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
| **v2.1 Evidence expansion** | Real parent materialization; expand after selection | **Done** |
| **v2.1 Canary** | A Weighted / B RRF / C RRF+Rerank; contextual=release A/B | **Done** |
| Dedicated reranker A/B | Vertex Ranking / Qwen3 | **Blocked until Evidence Recall@4 moves** |

## Current safe defaults (v2.1)

| Flag | Default |
|---|---|
| `RAG_FUSION_MODE` | `RRF` (Weighted still available / honest for baseline A) |
| `RAG_RERANKER_ENABLED` | `false` |
| `RAG_RERANKER_MODEL` | `lexical` |
| `RAG_RERANK_TIMEOUT_MS` | `700` |
| `RAG_CANARY_PERCENT` | `0` |

## Explicit non-goals (unchanged)

No GraphRAG / Vector DB / workflow rewrite / microservice / Answer-Citation rewrite until Evidence Recall@4 + answer quality move together.
