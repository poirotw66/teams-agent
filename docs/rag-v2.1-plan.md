# RAG v2.1 Plan — Evidence-Level Evaluation + Proper Reranker

**Do not merge PR #10 as-is.** Direction (RRF / contextual / reranker interface / shadow-canary) stays; production cutover claims and Gemini-listwise defaults do not.

## Diagnosis (kept)

| Issue | Fix direction |
|---|---|
| Benchmark leakage in listwise prompt | Generic ranking principles only |
| Title-only eval (`expectedSourceTitles`) | Evidence / chunk labels + Recall@4 |
| No-answer vacuous `relevant=[]` | Predict from empty retrieval, not empty labels |
| `WEIGHTED` aliased to RRF | Restore real weighted baseline path |
| `rerank_candidate_k=24` but search limit 12 | `max(top_k×mult, rerank_k, fusion_k)` |
| Gemini Flash + 90s timeout as default | Off by default; dedicated reranker A/B later |

Ranking↑ with Recall≈ explains weak answer UX: Top-4 context often unchanged.

## Success KPIs (v2.1)

```text
Evidence Recall@4
Evidence Precision@4
MRR@10 / nDCG@10
No-answer F1
Answer Correctness / Groundedness
P95 latency / Cost
```

Hit@1 alone is not a ship gate.

## Work order

1. **P0 Eval** — evidence schema, no-answer fix, true Weighted baseline, frozen split
2. **P0.5** — strip exam-key rules from listwise prompts
3. **P1** — candidate pool, Adaptive Fusion (generic signals only), Vertex Ranking API vs Qwen3-Reranker-0.6B
4. **P2** — parent/neighbor expansion; inject enterprise evidence before rerank

## Dedicated reranker A/B (P1)

Gemini listwise stays **experiment-only**. Production candidate order:

1. **Vertex AI Ranking API** (`RAG_RERANKER_MODEL=vertex-ranking`) — low-latency semantic ranking on GCP
2. **Qwen3-Reranker-0.6B** (`RAG_RERANKER_MODEL=qwen3-reranker:Qwen/Qwen3-Reranker-0.6B`) — if Ranking API is blocked
3. **Qwen3-Reranker-4B** — only if 0.6B fails Evidence Recall@4 / answer gates

Adapters live in `agent_service/reranker_dedicated.py` and are wired through `build_default_reranker`.

Ship gate for any reranker: Evidence Recall@4 + No-answer F1 + P95 + cost vs Weighted/RRF baseline on the **frozen test** split. Do not tune on test.

## Eval tooling

```bash
# Enrich labels from index (chunk ids / evidence / split)
uv run python scripts/enrich_retrieval_eval_v2_evidence.py

# Score (chunk + evidence aware)
cd agent_service
uv run python ../scripts/run_retrieval_eval_v2.py --fusion-mode WEIGHTED --split test
uv run python ../scripts/run_retrieval_eval_v2.py --fusion-mode RRF --split test
```

Keep: RRF impl, contextual schema, reranker interface, observability, shadow/canary, hard-eval scaffolding.

Withdraw from “done/cutover”: Gemini listwise production default, 90s timeout, M7 Weighted deletion, §45 production-complete claim.
