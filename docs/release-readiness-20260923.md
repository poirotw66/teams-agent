# Release readiness — 2026-09-23

> Date: 2026-09-23 (Asia/Taipei)  
> Git tip checked: `bdd3894` on `release/rag-prod-opt-and-eval-gates`  
> Replaces outdated “CI 全綠 / publish-now” framing in `docs/project-architecture-post-refactor-review-20260918.md` (historical review kept as-is)  
> Scope: modular-monolith stance, this-branch P0/P1 landings, CI-equivalent gates, ops cutover backlog, 156-case blind live status

---

## 1. Verdict

**Code on this branch is release-candidate for merge from an architecture and automation perspective.** Formal cloud cutover remains an **ops** checklist (Teams endpoint, IAM, monitoring, app-reg isolation, citation URLs, soak) — not a reason to redo frameworks or split the repo.

| Question | Answer |
|---|---|
| Split into multiple repos now? | **No** |
| Replace LangGraph / vector stack / add GraphRAG now? | **No** |
| Modular monolith OK? | **Yes** — composition root + ownership ratchets are sufficient |
| Block merge on ops cutover items? | **No** — track post-merge |
| Block merge on fresh 156-case blind live? | **Completed on HEAD** — Acc 96.8% / CiteP 98.8% (`rag-l3-v3-blind-full-live-20260923-bdd3894.json`); residual 5 omission + 3 bad citation are quality follow-ups |

---

## 2. Architecture stance

Unchanged from the 2026-09-18/21 reviews, and still correct:

- Keep the **modular monolith** with `composition/` as the wiring root.
- Keep ownership edges (`ai_ops_backoffice→agent_service`, `knowledge_portal→agent_service`) at **0** importers unless an explicit, reviewed exception lands.
- Do **not** start a second large directory reorganization, framework swap, or dedicated reranker rollout while candidate recall remains high and residual errors are selection / omission shaped.

Primary remaining product risk is **answer/citation quality under live RAG**, not package boundaries.

---

## 3. P0 / P1 landed on this branch (summary)

### P0 — correctness & release plumbing

- **RAG relevance / citation strategy** — source roles, query-aligned prune, packing/selection path fixes (prior live packing baseline: Answer Accuracy ~89.7%, Citation Precision ~95%; see historical `rag-l3-v3-blind-full-live-packing.json`).
- **OpenAPI + console canonical paths** — snapshots green; `sync_console_v2 --check` matches committed `static/console-v2`.
- **Auth status tests** — 401 vs 502 split; console static asset coverage via `index.html`.
- **Test DX — dotenv off import-time** (this turn):
  - Removed `load_dotenv()` from `agent_service.settings` import path.
  - Added `agent_service.runtime_dotenv.load_runtime_dotenv()` for Agent CLI / ASGI entrypoints.
  - Portal/Backoffice ASGI load dotenv via composition; Backoffice worker loads dotenv only when constructing settings from env.
  - Importing `agent_service.settings` no longer pulls `agent_service/.env` (verified: `RAG_EMBEDDING_MODEL` stays unset; `RagSettings.from_env().embedding_model is None` without ambient env).

### P1 — policy & shared validation

- Policy overlay + handoff **LEGAL** actions.
- `validate_service_catalog_payload` moved to `knowledge_core` (shared ownership).

---

## 4. CI-equivalent gate evidence (2026-09-23)

Re-checked on this tip for the report. Full historical “agent 2153 / 2 skip” suite was already green earlier on the branch; this turn re-ran focused slices plus architecture / OpenAPI / console / dotenv isolation **without** needing `RAG_EMBEDDING_MODEL=` empty override.

| Gate | Result | Notes |
|---|---|---|
| Adapter `pytest` (root) | **223 passed** | Re-run 2026-09-23 |
| Agent focused slice (settings/dotenv/rag/api/security/…) | **104 + 226 + 59** passed in slices | No `RAG_EMBEDDING_MODEL=` override |
| `test_runtime_dotenv` + composition isolation | **10 passed** | Import of settings does not load dotenv |
| `ruff check` (agent_service src/tests) | **pass** | |
| `scripts/check_architecture.py` | **pass** | After avoiding portal/backoffice→agent_service dotenv imports |
| `scripts/snapshot_openapi.py --check` | **pass** | |
| `scripts/sync_console_v2.py --check` | **pass** | Bundle matches rebuild |
| Playground CI job | Prior branch green | Not re-run this turn (Node job; unchanged surface) |
| Full agent suite (~2153) | Prior branch green | Prefer re-run in CI on PR if desired |

### Dotenv verification commands

```bash
# Import settings must NOT load agent_service/.env
cd agent_service && uv run python -c \
  'import os; from agent_service import settings; print(os.environ.get("RAG_EMBEDDING_MODEL", "<unset>"))'
# Expected: <unset> (when shell does not already export it)

# Entrypoint helper still loads when asked
uv run python -c \
  'from pathlib import Path; from agent_service.runtime_dotenv import load_runtime_dotenv, reset_runtime_dotenv_for_tests; \
   reset_runtime_dotenv_for_tests(); load_runtime_dotenv(dotenv_path=Path("agent_service/.env")); \
   import os; print(os.environ.get("RAG_EMBEDDING_MODEL"))'
```

---

## 5. 156-case blind live evaluation

### Command (intended)

```bash
uv run python scripts/run_rag_pipeline_eval.py \
  --eval-set data/eval/retrieval_eval_v3_blind.json \
  --split test --layer 3 --live-model \
  --output data/eval/reports/rag-l3-v3-blind-full-live-20260923-bdd3894.json
```

### Attempt log (honest)

| Attempt | Outcome |
|---|---|
| 1 — exact command from repo root | **Failed immediately** — `FileNotFoundError: No verified local knowledge snapshot is available for GCS mirror mode…` because `agent_service/.env` sets `KNOWLEDGE_RELEASE_STORE_MODE=GCS` and `KNOWLEDGE_RELEASE_CACHE_DIR=../data/knowledge_cache`, which resolves to `…/Github/data/knowledge_cache` when cwd is the repo root (outside the synced mirror under `teams-agent/data/knowledge_cache`). Credentials themselves were available (`GEMINI_EVAL_API_KEY`). |
| 2 — same command + absolute cache | **Completed** (~8.2 min). `KNOWLEDGE_RELEASE_CACHE_DIR="$(pwd)/data/knowledge_cache"`; credentials via `GEMINI_EVAL_API_KEY`. Transient embedding `429 RESOURCE_EXHAUSTED` retries observed; run finished exit 0. |

### HEAD blind live result (authoritative for this tip)

- Output: `data/eval/reports/rag-l3-v3-blind-full-live-20260923-bdd3894.json`
- Log: `data/eval/reports/rag-l3-v3-blind-full-live-20260923-bdd3894.log`
- Provenance: commit `bdd3894`, freezeVersion **5**, release `release-4f49088db9ca`, liveModel true, embedding `google_genai:gemini-embedding-2`

| Metric | Value |
|---|---:|
| Case count | **156** |
| Answer Accuracy | **96.79%** |
| Single-turn / multi-turn Acc | 97.79% / 90.0% |
| Citation Precision | **98.82%** |
| Citation Recall | **99.36%** |
| hardNegativeAccuracy | **100%** |
| Document Hit@4 | 99.14% |
| Candidate Evidence Recall@24 | 99.14% |
| noAnswer F1 | **1.0** (0 FP / 0 FN) |
| Failure taxonomy | ANSWER_OMISSION **5**, BAD_CITATION **3** |
| Total P95 | ~4.75s |

### Prior packing-era baseline (historical)

`rag-l3-v3-blind-full-live-packing.json`: Answer Accuracy 89.74%, Citation Precision 94.98%, BAD_CITATION 9 / ANSWER_OMISSION 13 / EVIDENCE_NOT_PASSED 3. Superseded by the HEAD report above for quality sign-off.

---

## 6. Remaining ops readiness (post-merge — not code blockers)

From README near-term / Milestone 6 (~lines 1015–1047), still open for **formal cloud cutover**:

1. **Teams Developer Portal** — switch Bot endpoint to Cloud Run Adapter (`…/api/messages`) and re-test channel / 1:1; stop local Bot / Dev Tunnel after cutover.
2. **Firestore IAM** — on next `./deploy/deploy-gcp.sh`, apply Agent SA `roles/datastore.user` (and keep conversation/handoff on FIRESTORE in cloud).
3. **OpenTelemetry / centralized logs / alerts** — error-rate and P95 latency monitoring before calling production “governed”.
4. **App Registration isolation** — separate Entra app regs for dev / test / prod.
5. **Citation URLs** — map citations to formal document URLs (`RAG_SOURCE_BASE_URL` / corporate doc hosts), not PoC placeholders.
6. **Cloud Run soak** — concurrency / warm-cold / TTFT / P95–P99 / timeout load test after endpoint cutover.
7. Related README notes: `manifest.json` developer URLs still PoC; production ticket HTTP mode optional for POC.

These are **deployment and governance** items. They do not require a modular-monolith rewrite.

---

## 7. Remaining goal gaps (engineering)

- Optional: set `KNOWLEDGE_RELEASE_CACHE_DIR` in local `.env` to an **absolute** path (or always export it when running evals from repo root) so relative `../data/knowledge_cache` cannot resolve outside the synced mirror.
- Full agent pytest suite (~2153) + playground Node job — rely on CI on the PR if not re-run this turn.
- Live Entra formal knowledge write E2E (knowledge control-plane spec gap) — ops/security acceptance, separate from this branch’s RAG/dotenv work.
- Residual live quality: 5 ANSWER_OMISSION + 3 BAD_CITATION on HEAD blind — follow-up, not architecture blockers.

---

## 8. Sign-off summary

| Track | Status |
|---|---|
| Architecture / modular monolith | **OK — no split** |
| CI-equivalent automation (this tip) | **Green** on re-run slices + architecture + OpenAPI + console sync |
| Test DX dotenv | **Done** — settings import no longer loads `.env` |
| 156-case blind live on HEAD | **Done** — 96.8% Acc / 98.8% CiteP; report above |
| Ops cutover (Teams / IAM / OTel / app-reg / citations / soak) | **Open — post-merge** |
