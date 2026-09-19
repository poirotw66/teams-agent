# Architecture Follow-up Progress (2026-09-19, arch-1)

Tracks execution of [`docs/0919-arch-1.md`](./0919-arch-1.md) after PR #7 merge.

## Status

| Step | Item | Status |
|---|---|---|
| 1 | PR #7 merge + stop large architecture moves | **Done** — merged `7bbb15a` |
| 2 | Golden User Journeys (~12) | **Done** — `agent_service/tests/test_golden_user_journeys.py` |
| 3 | Turn Planner real A/B → Keep / Delete / Enable | Pending (flag stays off) |
| 4 | Resume feature development + Change Radius | Pending after A/B decision |

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

## Explicit non-goals (per arch-1)

- Do not enable `TURN_PLANNER_ENABLED` yet.
- Do not relocate into `packages/` / `apps/`.
- Do not independently deploy Citation Asset Gateway.
- Do not start an OTel mega-sprint.
