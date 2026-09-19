# RAG v2 Progress

Tracks execution of [`docs/rag-v2-spec.md`](./rag-v2-spec.md).
Rollout ops: [`docs/rag-v2-canary-cutover.md`](./rag-v2-canary-cutover.md).

## Status

| Milestone | Item | Status |
|---|---|---|
| M0 | Hard eval v2 | **Done** |
| M1 | RRF | **Done** (production default) |
| M2 | Contextual index dual-read | **Done** |
| M3 | Reranker (listwise + title-protect) | **Done** (default on, fail-open) |
| M4 | Shadow matrix | **Done** |
| M5 | Canary wiring | **Done** (`RAG_CANARY_PERCENT=0`) |
| §45 | Acceptance vs Weighted | **Cleared offline (label-free)** |
| M6 | Production default | **Done** (`RRF` + `listwise`) |
| M7 | Delete weighted hot path | **Done** (alias → RRF; `LEGACY_WEIGHTED` eval-only) |

## Production defaults (M6)

| Flag | Default |
|---|---|
| `RAG_FUSION_MODE` | `RRF` |
| `RAG_RERANKER_ENABLED` | `true` |
| `RAG_RERANKER_MODEL` | `listwise:gemini-2.5-flash` |
| `RAG_CANARY_PERCENT` | `0` |

`WEIGHTED` env values alias to RRF at `HybridIndex` construction (M7). Shadow/§45 baseline A still uses `fusion_mode=LEGACY_WEIGHTED` on search calls only.

## §45 evidence

`uv run python ../scripts/run_rag_v2_section45_eval.py` → gate45 **true** (Hit +11.9pp / MRR +9.1% / Recall@20 flat).

## Explicit non-goals (unchanged)

No GraphRAG / Vector DB / workflow rewrite / microservice / Answer-Citation rewrite.
