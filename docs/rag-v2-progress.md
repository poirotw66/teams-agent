# RAG v2 Progress

Tracks execution of [`docs/rag-v2-spec.md`](./rag-v2-spec.md).
Course correction: [`docs/rag-v2.1-plan.md`](./rag-v2.1-plan.md).
**PR #10 merged** to `main` as v2.1 course-correction (eval + safe defaults) — **not** a production cutover.
**PR #16 merged** accuracy / telemetry sprint (`main @ 2319be5`).
**Closeout branch** fixes rewrite Query-RRF + enterprise injection ranking, Evaluation Contract separation, and shared Confidence Contract.

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
| **PR #16** | Pipeline eval Layer 3 deterministic path, within-doc oracle, calibrated No-answer F1, telemetry toggles | **Done** |
| **Closeout P0** | Rewrite Query-RRF fuses previous×1.0 + rewrite×0.6; enterprise inject never `sort(score)` | **Done** |
| **Closeout P1** | Evidence labels for all answerable cases; Document/Evidence/No-answer metrics separated; shared Confidence Contract | **Done** |
| **Closeout P1** | Production-model Layer 3 (`--live-model`) release benchmark | **Done** (CLI + usage/latency metrics; release-only) |
| Dedicated reranker A/B | Vertex Ranking / Qwen3 | **Paused** — labeled headroom **5.78 pp** (< 10 pp gate) |

## Current safe defaults (v2.2)

| Flag | Default |
|---|---|
| `RAG_FUSION_MODE` | `RRF` (Weighted still available / honest for baseline A) |
| `RAG_RERANKER_ENABLED` | `false` |
| `RAG_RERANKER_MODEL` | `lexical` |
| `RAG_RERANK_TIMEOUT_MS` | `700` |
| `RAG_CANARY_PERCENT` | `0` |
| `RAG_EVIDENCE_TOKEN_BUDGET` | `1200` |

## Evaluation Contract (post-closeout)

Dataset: `data/eval/retrieval_eval_v2.json`

| Population | Count |
|---|---:|
| Total cases | 121 |
| Answerable | 88 |
| No-answer / hard-negative | **33** (was 13) |
| Answerable with `expectedEvidence` | **88 / 88** (was 60) |

| Metric | Population |
|---|---|
| Document Recall@4 / Document Hit@1 | answerable |
| Evidence Recall@4 | evidence-labeled answerable only |
| Candidate Evidence Recall@24 | evidence-labeled answerable only |
| Document Candidate Hit@24 | answerable |
| No-answer F1 | no-answer + answerable negatives |
| Answer Accuracy | all (Layer 3) |

**Do not** fall back Document Hit into Evidence Recall. Empty evidence labels are excluded from Evidence aggregates (`evidenceLabeledCaseCount`).

### Metric reinterpretation (why older “56%” looked scary)

PR #16 / pre-closeout Evidence Recall@4 ≈ 56% on 101 cases was dominated by **28 answerable cases without evidence labels** (and Document-Hit fallback into Evidence metrics). On the previously labeled 60 cases, Top24 evidence coverage was essentially complete and Top4 was ~95%. Within-document oracle Top-4 document hit remains ~100% / WithinDocRecall@4 ~99%.

**Architectural freeze:** no hierarchical retrieval / chunking redesign without new labeled headroom evidence.

## Ranking correctness closeout

1. **Rewrite Query-RRF** — `run_retrieve` attempt>0 with a single rewrite set now fuses `previous` (weight 1.0) with rewrite (0.6). Pipeline regression: `test_run_retrieve_rewrite_attempt_fuses_previous_results`.
2. **Enterprise App injection** — preserves current ranking order; appends missing trust candidates with tail `final_rank`; never re-sorts by evidence `score`.

## Confidence Contract

Shared module: `agent_service.knowledge_pipeline.retrieval_confidence`

```text
ConfidenceFeatures → evaluate_confidence → HIGH | UNCERTAIN | LOW
```

- Production `evaluate_retrieval_confidence` delegates here (HIGH skips relevance LLM; UNCERTAIN grades; LOW no-answer).
- Eval `calibrated_predict_no_answer` lives in the same module (`min_score` is enforced).
- Logistic regression calibration deferred until no-answer set is larger / more diverse (now 33; target remains 50+ over time).

## Closeout Layer-2 benchmark (verified)

Command:

```bash
set -a && source .env && set +a
.venv/bin/python scripts/run_rag_pipeline_eval.py \
  --split all --layer 2 --taxonomy --output /tmp/rag-l2-closeout.json
```

Results on the fully labeled closeout set (`121` cases; `88` evidence-labeled answerable; `33` no-answer):

| Metric | Value | Population |
|---|---:|---|
| Evidence Recall@4 | **93.09%** | 88 evidence-labeled |
| Candidate Evidence Recall@24 | **98.86%** | 88 evidence-labeled |
| Reranker headroom | **+5.78 pp** (7 cases) | labeled only |
| Document Hit@4 | **96.59%** | 88 answerable |
| No-answer F1 | **81.82%** | 33 negatives + answerable |
| Latency P50 / P95 | 494 ms / 788 ms | all |

Failure taxonomy (20 failures): `RANKING_OR_RERANKER_OPPORTUNITY=7`, `NO_ANSWER_FALSE_POSITIVE=6`, `NO_ANSWER_FALSE_NEGATIVE=6`, `RETRIEVAL_RECALL_MISS=1`. No `WRONG_SECTION_OR_CHUNKING` after label completion.

### Reranker decision

Gate from the closeout brief:

- `< 5pp` → do not ship a dedicated reranker
- `> 10pp` → worth controlled A/B

Measured headroom is **5.78 pp** (borderline, well under 10 pp). **Decision: keep dedicated Vertex/Qwen reranker paused / off the critical path.** Optional future A/B only if ambiguous short queries (`v2-amb-*`) become a product priority.

## Architecture review closeout (2026-09-20)

Follow-up to [`docs/project-architecture-post-refactor-review-20260918.md`](./project-architecture-post-refactor-review-20260918.md). Artifacts under `data/eval/reports/`.

| Phase | Gate | Result |
|---|---|---|
| 0 Mergeable | Agent suite + architecture 0 findings; mid-band STANDARD; no rewrite on standard reject | **Done** |
| 1 No-answer | Test F1 ≥ 88%, FP ≤ 2, no new LLM | **Done** — Test F1 **94.12%**, FP **1**, recall **100%** (distinctive-title rescue) |
| 1 Telemetry | Layer 2 stage P50/P95 + batch×query-RRF 2×2 ablation | **Done** — embed/sparse/dense/fusion/batch/expand + facet groups; ablation shows no Ev@4 gain from batch+query-RRF on frozen test |
| 2 Ranking | All Ev@4 ≥ 95%; test ≥ 98.28%; NA F1 not down | **Done** — All **97.63%**, test **100%**, all-set NA F1 **82.76%** (was 81.82%) |
| 3 Latency | Test P95 ≤ 700 ms; 3-run variance ≤ 25% | **Done** — test P95 **649 ms**; 3-run P95 gap **12.8%** (Cloud Run concurrency not run) |
| 4 Live L3 | Production-model release report | **Done** — see `data/eval/reports/rag-l3-live-test-20260920.json` |

Live Layer 3 (test split, `--live-model`): Answer Accuracy **77.0%**, No-answer F1 **100%**, Citation P/R **79.3% / 95.9%**, Groundedness **100%**, total P95 **~5.4 s**, retrieval P95 **~1.2 s**, ~**1.43** LLM calls/query, usage source **ESTIMATED**.

Remaining ambiguity ranking cases (`v2-amb-*`, token, Forti multi-sec) stay deferred; dedicated reranker remains paused.

## Production-model Layer 3 benchmark

```bash
../.venv/bin/python ../scripts/run_rag_pipeline_eval.py \
  --split test --layer 3 --live-model --output /tmp/rag-l3-live.json

# Smoke / cost-controlled:
../.venv/bin/python ../scripts/run_rag_pipeline_eval.py \
  --split test --layer 3 --live-model --max-cases 5
```

- Default Layer 3 remains deterministic (`model=None`) for offline CI.
- `--live-model` wires `settings.model` / `settings.agent_model` via `build_chat_model` and an `ExecutionContext` usage collector.
- Report fields: Total / stage P50–P95, `llmCallsPerQuery`, `inputTokensPerQuery`, `outputTokensPerQuery`, `costUsdPerQuery`, `queryTierCounts`, Answer Accuracy, No-answer F1, Groundedness, Citation Accuracy.

## Explicit non-goals (unchanged)

No GraphRAG / Vector DB / workflow rewrite / microservice / Answer-Citation rewrite until Evidence Recall@4 + answer quality move together. No hierarchical retrieval redesign while labeled Top4 evidence remains high.
