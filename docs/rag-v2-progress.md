# RAG v2 Progress

Tracks execution of [`docs/rag-v2-spec.md`](./rag-v2-spec.md).
**Course correction:** [`docs/rag-v2.1-plan.md`](./rag-v2.1-plan.md) — do **not** merge PR #10 as-is.

## Status

| Milestone | Item | Status |
|---|---|---|
| M0–M5 | Hard eval / RRF / contextual / reranker iface / shadow / canary | **Keep infrastructure** |
| §45 offline Hit@1 | Label-free title ranking | **Not a production cutover gate** |
| M6 Gemini listwise default | Production default | **Withdrawn** (default off / lexical) |
| M7 Delete Weighted | Alias WEIGHTED→RRF | **Reverted** — Weighted path restored for A/B |
| **v2.1 P0** | Evidence-level eval + no-answer fix + frozen split | **Done** |
| **v2.1 P0.5** | Remove benchmark leakage from listwise prompt | **Done** |
| **v2.1 P1** | Candidate pool + Adaptive Fusion + reranker A/B plan | **Done** |
| **v2.1 P2** | Inject before rerank + parent/neighbor expand | **Done** (basic) |

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
