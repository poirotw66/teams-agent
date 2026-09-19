# Architecture Follow-up Progress (2026-09-19, arch-1)

Tracks execution of [`docs/0919-arch-1.md`](./0919-arch-1.md) after PR #7 merge.

## Status

| Step | Item | Status |
|---|---|---|
| 1 | PR #7 merge + stop large architecture moves | **Done** — merged `7bbb15a` |
| 2 | Golden User Journeys (~12) | **Done** — `agent_service/tests/test_golden_user_journeys.py` (PR #8) |
| 3 | Turn Planner real A/B → Keep / Delete / Enable | **In progress** — stub A/B leans Delete; live Golden still required before cut |
| 4 | Resume feature development + Change Radius | Pending after A/B decision |
| 5 | RAG accuracy + workflow efficiency (product track) | **Started** — see below |

## Golden User Journeys

Suite: `uv run pytest -q tests/test_golden_user_journeys.py` (from `agent_service/`).

| # | Journey | Test |
|---|---|---|
| 1 | RAG → Citation → Answer | `test_journey_01_rag_citation_answer` |
| 2 | FAQ deterministic | `test_journey_02_faq_deterministic_answer` |
| 3 | Clarification | `test_journey_03_insufficient_info_asks_clarification` |
| 4 | Follow-up continues issue | `test_journey_04_follow_up_continues_same_issue` |
| 5 | Multi-issue prioritize | `test_journey_05_multi_issue_prioritizes` |
| 6 | IT + non-IT mixed | `test_journey_06_mixed_it_and_non_it` |
| 7 | Knowledge miss, no hallucination | `test_journey_07_knowledge_miss_no_hallucination` |
| 8 | Miss → handoff/ticket offer | `test_journey_08_knowledge_miss_offers_handoff_paths` |
| 9 | Handoff active → agent silent | `test_journey_09_handoff_active_agent_stops_answering` |
| 10 | Feedback 👍/👎 | `test_journey_10_feedback_after_answer` |
| 11 | Restricted document ACL | `test_journey_11_restricted_document_acl` |
| 12 | Conversation timeout → fresh | `test_journey_12_conversation_timeout_starts_fresh` |

CI already runs the full `agent_service` pytest suite; no workflow change required.

## RAG accuracy + workflow efficiency

Baseline: Golden `#06` Helpdesk-96 — acceptable **91.7%**, strict pass **53.1%**, mean LLM calls **2.12**, P95 **9.5s**.

### Accuracy (current focus)

Helpdesk-96 FAIL triage (8 cases) dominant bucket: **policy / security boilerplate mis-attributed to knowledge `[S#]`** (QB-049 / 020 / 070 / 084 pattern).

Landed this session:

- `prune_uncited_material_sentences` now drops policy-leak clauses even when falsely tagged `[S#]`, while preserving real `[POLICY-SEC-*]` advisory lines.
- Answer prompt: when the source does not state data-protection limits, do not rewrite Rule 10 as that source’s rule.
- Regression tests in `tests/test_rag_pipeline_improvements.py`.

Already fixed after `#06` (no further code change needed here):

- FAQ answers attach `faq:<id>:<version>` provenance citations (QB-081 empty-citations class).

### Efficiency

| Signal | Finding |
|---|---|
| Stub Turn Planner A/B (`scripts/agent_turn_benchmark.py --mode compare`) | Planner often **+1 LLM call** on IT paths vs supervisor-first (supervisor already skips its model on standalone IT) |
| Live mean LLM calls (`#06`) | Already **~2.1** — close to the original 2-call target without enabling Planner |
| Outliers (3–4 calls) | Mostly rewrite / visual / claim-repair paths (QB-045, QB-097, …) |

**Decision stance (unchanged until live Golden):** keep `TURN_PLANNER_ENABLED=false`. Prefer **Delete PoC** unless live Accuracy / P95 / Cost clearly wins. Do not chase Planner for efficiency while mean calls are already ~2.1.

### Next (in order)

1. Run live Golden Baseline twice (flag off / on) on the same question-bank hash → Keep / Delete / Enable.
2. If Planner loses: delete PoC surface; keep tuning current path (relevance skip, rewrite budget, repair).
3. Accuracy pass 2: retrieval misses (QB-019 VPN role scope, QB-007 enterprise App) + PARTIAL completeness (required-fact coverage).
4. Re-run Helpdesk-96 → candidate Baseline `#07`.

## Explicit non-goals (per arch-1)

- Do not enable `TURN_PLANNER_ENABLED` yet.
- Do not relocate into `packages/` / `apps/`.
- Do not independently deploy Citation Asset Gateway.
- Do not start an OTel mega-sprint.
