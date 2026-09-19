# RAG v2 Canary / Cutover

Operational checklist for [`docs/rag-v2-spec.md`](./rag-v2-spec.md) §46–§49.

## Production defaults (M6 — applied)

| Flag | Default | Notes |
|---|---|---|
| `RAG_FUSION_MODE` | `RRF` | Soft-best knobs below; `WEIGHTED` aliases to RRF (M7) |
| `RAG_RRF_K` | `5` | Soft-best local tune |
| `RAG_SPARSE_WEIGHT` / `RAG_DENSE_WEIGHT` | `0.5` / `1.5` | Dense-heavy RRF |
| `RAG_CONTEXTUAL_INDEX` | `true` | Dual-read v1/v2 |
| `RAG_RERANKER_ENABLED` | `true` | Fail-open if Gemini unavailable |
| `RAG_RERANKER_MODEL` | `listwise:gemini-2.5-flash` | Title-protect blend |
| `RAG_RERANK_TIMEOUT_MS` | `90000` | Listwise budget |
| `RAG_SHADOW_ENABLED` | `false` | Optional background compare |
| `RAG_CANARY_PERCENT` | `0` | Sticky canary off |

## Experiment matrix (offline)

```bash
cd agent_service
uv run python ../scripts/run_rag_v2_shadow_eval.py \
  --variants A,B,C,D \
  --output ../outputs/rag-v2-shadow.json

# A uses LEGACY_WEIGHTED scoring (eval-only). D default PairScorer is lexical;
# for §45 stack:
uv run python ../scripts/run_rag_v2_shadow_eval.py \
  --variants A,D --reranker-model listwise:gemini-2.5-flash
```

Reproduce §45:

```bash
uv run python ../scripts/run_rag_v2_section45_eval.py
```

## Rollback

```text
RAG_RERANKER_ENABLED=false   # Soft-RRF only (still better than pre-M6 weighted)
# or redeploy prior release
```

Weighted linear fusion is **not** available as a production fusion mode after M7.

## M7 notes

- Production `HybridIndex.search` always runs Soft-best RRF (+ error-code guard).
- `RAG_FUSION_MODE=WEIGHTED` is accepted but mapped to RRF.
- `legacy_weighted_hybrid_rank` / `fusion_mode=LEGACY_WEIGHTED` remain for offline baseline A only.
