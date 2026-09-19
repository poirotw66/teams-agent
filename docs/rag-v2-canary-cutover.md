# RAG v2 Canary / Cutover

Operational checklist for [`docs/rag-v2-spec.md`](./rag-v2-spec.md) §46–§49.
**Course correction:** see [`docs/rag-v2.1-plan.md`](./rag-v2.1-plan.md) — do **not** treat Gemini listwise Hit@1 as a production cutover gate.

## Production defaults (v2.1 — safe)

| Flag | Default | Notes |
|---|---|---|
| `RAG_FUSION_MODE` | `RRF` | Soft-best knobs below; **`WEIGHTED` remains a real baseline path** for A/B |
| `RAG_RRF_K` | `5` | Soft-best local tune |
| `RAG_SPARSE_WEIGHT` / `RAG_DENSE_WEIGHT` | `0.5` / `1.5` | Overridden per-query by Adaptive Fusion |
| `RAG_CONTEXTUAL_INDEX` | `true` | Dual-read v1/v2 |
| `RAG_RERANKER_ENABLED` | `false` | Dedicated reranker A/B before enabling |
| `RAG_RERANKER_MODEL` | `lexical` | Prefer `vertex-ranking` or `qwen3-reranker:0.6B` in experiments |
| `RAG_RERANK_TIMEOUT_MS` | `700` | Interactive path budget |
| `RAG_SHADOW_ENABLED` | `false` | Optional background compare |
| `RAG_CANARY_PERCENT` | `0` | Sticky canary off |

## Dedicated reranker A/B (v2.1)

```bash
# Vertex Ranking API (preferred on GCP)
RAG_RERANKER_ENABLED=true RAG_RERANKER_MODEL=vertex-ranking \
  VERTEX_RANKING_PROJECT=... \
  uv run python ../scripts/run_rag_v2_shadow_eval.py --variants A,D

# Qwen3-Reranker-0.6B fallback
RAG_RERANKER_ENABLED=true \
  RAG_RERANKER_MODEL=qwen3-reranker:Qwen/Qwen3-Reranker-0.6B \
  uv run python ../scripts/run_rag_v2_shadow_eval.py --variants A,D
```

Ship on **Evidence Recall@4 / No-answer F1 / P95 / cost** using the frozen `split=test` set — not Hit@1 alone.

## Evidence-level eval

```bash
uv run python scripts/enrich_retrieval_eval_v2_evidence.py
cd agent_service
uv run python ../scripts/run_retrieval_eval_v2.py --fusion-mode WEIGHTED --split test
uv run python ../scripts/run_retrieval_eval_v2.py --fusion-mode RRF --split test
```

## Rollback

```text
RAG_RERANKER_ENABLED=false
RAG_FUSION_MODE=WEIGHTED   # honest weighted baseline still available
# or redeploy prior release
```

Gemini listwise (`listwise:gemini-…`) remains **experiment-only**.
