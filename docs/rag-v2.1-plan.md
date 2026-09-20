# RAG v2.1 Plan — Evidence-Level Evaluation + Proper Reranker

**Status (2026-09-20):** PR #10 merged to `main` as the v2.1 **course-correction** (eval gates + safe defaults). That was **not** a production cutover.

## Diagnosis (kept)

| Issue | Fix direction |
|---|---|
| Benchmark leakage in listwise prompt | Generic ranking principles only |
| Title-only eval (`expectedSourceTitles`) | Evidence / chunk labels + Recall@4 |
| No-answer vacuous `relevant=[]` | Predict from empty retrieval, not empty labels |
| `WEIGHTED` aliased to RRF | Restore real weighted baseline path |
| `rerank_candidate_k=24` but search limit 12 | `max(top_k×mult, rerank_k, fusion_k)` |
| Gemini Flash + 90s timeout as default | Off by default; dedicated reranker A/B later |
| `SearchResult.score` reused for ranking | Ranking contract: confidence ≠ rank |
| Parent expansion vs production `parent_id` | Materialize parent from siblings; expand after selection |

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

1. **P0 Eval** — evidence schema, no-answer fix, true Weighted baseline, frozen split ✅ (in #10)
2. **P0.5** — strip exam-key rules from listwise prompts ✅
3. **P0 Ranking contract + Evidence expansion** — stop washing RRF/rerank; EvidenceBundle after selection
4. **P1** — canary = A Weighted / B RRF / C RRF+Rerank; contextual = release-level A/B
5. **P1** — Vertex Ranking API vs Qwen3-Reranker-0.6B (only after ranking contract is green)
6. **P2** — retire `inject_enterprise_app_evidence`; Knowledge Lexicon; OTel metrics

## Runtime canary (simplified)

```text
A_WEIGHTED          = Weighted fusion
B_RRF               = RRF
C_RRF_RERANK        = RRF + dedicated reranker (when globally enabled)
```

Contextual embeddings are **release-level** (plain vs contextual index promotion), not a per-request variant. Legacy `C_RRF_CONTEXTUAL` / `D_RRF_CONTEXTUAL_RERANK` labels remain as aliases.

## Dedicated reranker A/B (after ranking contract)

Gemini listwise stays **experiment-only**. Production candidate order:

1. **Vertex AI Ranking API** (`RAG_RERANKER_MODEL=vertex-ranking`)
2. **Qwen3-Reranker-0.6B** (`RAG_RERANKER_MODEL=qwen3-reranker:...`)
3. **Qwen3-Reranker-4B** — only if 0.6B fails gates

Ship gate: Evidence Recall@4 + No-answer F1 + P95 + cost vs Weighted/RRF on the **frozen test** split.

## Eval tooling

```bash
uv run python scripts/enrich_retrieval_eval_v2_evidence.py

cd agent_service
uv run python ../scripts/run_retrieval_eval_v2.py --fusion-mode WEIGHTED --split test
uv run python ../scripts/run_retrieval_eval_v2.py --fusion-mode RRF --split test
```

Keep: RRF impl, contextual schema, reranker interface, observability, shadow/canary, hard-eval scaffolding.

Withdraw from “done/cutover”: Gemini listwise production default, 90s timeout, M7 Weighted deletion, §45 production-complete claim.
