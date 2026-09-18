# Oversized Source Waivers (Wave 5)

Formal exceptions for production sources that remain above the 500-line
file ratchet or the 80-line function ratchet after the architecture refactor.

## Policy

1. **New production files** must stay at or below 500 lines (`scripts/check_architecture.py`).
2. **Existing oversized files/functions** must not grow past the counts in
   `docs/architecture/baselines/oversized_*.json`. Shrinks are always allowed.
3. This document is the **explicit exception rationale** required by
   `docs/project-architecture-refactor-plan-20260918.md` §10 item 6.
4. Review date: **2026-12-18**. Owners must either shrink the file below the
   threshold or renew the waiver with an updated reason.

## Current inventory

Baselines are the machine-checked source of truth:

| Baseline | Purpose |
|---|---|
| `baselines/oversized_files.json` | Files still above 500 lines |
| `baselines/oversized_functions.json` | Functions still above 80 lines |
| `baselines/reverse_imports.json` | Forbidden reverse-import allowlist (must stay empty) |

Regenerate after intentional shrinks:

```bash
uv run python scripts/check_architecture.py --write-baselines
```

## Waiver classes

| Class | Examples | Why deferred | Exit criteria |
|---|---|---|---|
| Document / extraction pipelines | `documents.py`, `extractor.py`, `layout_chunking`-adjacent | Behavior-coupled OCR/chunk pipelines; split risks citation regressions | Stage extraction behind golden RAG suites |
| Workflow node modules | `workflow_*.py`, `handoff_flow.py` | LangGraph node graphs still share mutable state | Split by node family with characterization tests |
| Evaluation / governance domains | `evaluation_domain/*`, `governance_domain/*` | Large domain services already under package split; further cuts are incremental | Continue use-case extraction per router family |
| Portal asset / PDF jobs | `draft_assets.py`, `pdf_convert_jobs.py`, `version_service.py` | I/O-heavy job orchestration; size tracks job matrix | Extract job runners behind ports |
| Ops emitters / freshness | `operations/emitter.py`, `freshness_store.py` | Event serialization + store shapes | Split write vs query surfaces |
| Console React deep panels | `ChunkInspectorModal.tsx` | UI density; not a new god module | Feature-slice when panel gains second consumer |
| Legacy quarantine (non-product) | `static/legacy-js/**` | Emergency kill-switch only; not on default product path | Delete after one release cycle with `BACKOFFICE_LEGACY_SHELL_ENABLED` unused |

## Env alias policy (Wave 5 residual)

Backoffice/Agent settings still accept a few **secondary** env names for deploy
compatibility (for example `SERVICE_TOKEN` beside `AI_OPS_BACKOFFICE_TOKEN`,
`AUTH_MODE` beside `AI_OPS_BACKOFFICE_AUTH_MODE`). Primary names are the
`AI_OPS_*` / `AGENT_*` / `KNOWLEDGE_PORTAL_*` keys documented in README.
Removing aliases is deferred until Cloud Run and local `start.sh` are confirmed
to use only primary keys; do not silently drop aliases in a structure PR.
