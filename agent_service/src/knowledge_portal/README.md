# Knowledge Operations Portal

Internal web application for knowledge lifecycle management, separate from Teams chat runtime.

Spec: [`../../docs/knowledge-operations-portal-spec.md`](../../docs/knowledge-operations-portal-spec.md)

## Run locally

```bash
cd agent_service
uv run knowledge-portal
```

Open `http://localhost:8090/`.

### Identity

| Mode | Setup |
|---|---|
| `HEADER` (default) | Send `X-Portal-User-Id`, `X-Portal-User-Name`, `X-Portal-Role`, `X-Portal-Owner-Units` |
| `ENTRA` | Set `KNOWLEDGE_PORTAL_AUTH_MODE=ENTRA` and send `Authorization: Bearer <token>` |

Entra role mapping uses app roles in the token (`roles` claim):

- `Knowledge.PlatformAdmin` → `PLATFORM`
- `Knowledge.Manager` → `MANAGER`
- `Knowledge.Reviewer` → `REVIEWER`
- `Knowledge.Auditor` → `AUDITOR`
- otherwise → `CONTRIBUTOR`

Install Entra auth extras: `uv sync --extra portal`

Optional bearer auth: set `KNOWLEDGE_PORTAL_TOKEN`.

## Bootstrap release-0001

Import existing Markdown under `data/sources/` (or `data/sources.sample/`) and activate `release-0001`:

```bash
./scripts/bootstrap_knowledge_release_0001.sh
```

Uses `KNOWLEDGE_PORTAL_REPOSITORY_MODE=FILE` by default so portal state persists under `data/portal_state/portal_state.json`.

## Phase 1 MVP included

- Dashboard, knowledge list, Markdown draft create/update
- Validation preview with blocking/warning/info checks
- Draft-index test room (`POST /api/documents/{id}/draft-search`) and test-case runs
- Submit for review, approve/reject, publish release artifact, rollback pointer
- Append-only audit events
- Repository modes: `MEMORY`, `FILE`, or `FIRESTORE`

## Agent integration

When the portal publishes or rolls back a release, it writes:

- `data/releases/<release-id>/index/chunks.json`
- `data/releases/active_release.json`

Agent Service resolves the active index via `KNOWLEDGE_RELEASE_MODE`:

| Mode | Behavior |
|---|---|
| `AUTO` | Prefer portal active release; fall back to bundled `RAG_INDEX_PATH` |
| `PORTAL` | Require portal release index (fail `/readyz` if missing) |
| `BUNDLED` | Ignore portal releases; use image-bundled index only |

Check `GET /readyz` fields: `knowledgeReleaseId`, `knowledgeIndexSource`, `knowledgeIndexPath`.

Cloud Run (Terraform) defaults to `KNOWLEDGE_RELEASE_MODE=PORTAL` and `KNOWLEDGE_RELEASE_DIR=/app/data/releases`. Portal bootstrap and Agent must share that directory (same container volume or GCS mount).

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `KNOWLEDGE_PORTAL_PORT` | `8090` | HTTP port |
| `KNOWLEDGE_PORTAL_REPOSITORY_MODE` | `MEMORY` | `MEMORY`, `FILE`, or `FIRESTORE` |
| `KNOWLEDGE_PORTAL_STATE_PATH` | `data/portal_state/portal_state.json` | FILE repo persistence |
| `KNOWLEDGE_PORTAL_RELEASE_DIR` | `data/releases` | Immutable release artifacts |
| `KNOWLEDGE_PORTAL_AUTH_MODE` | `HEADER` | `HEADER` or `ENTRA` |
| `KNOWLEDGE_PORTAL_AGENT_API_URL` | unset | Optional proxy to Agent `/retrieval/search` |
| `KNOWLEDGE_PORTAL_REQUIRE_DUAL_APPROVAL` | `true` | Block self-publish by contributor |

Release artifacts contain parsed sources, `manifest.json`, and `index/chunks.json`. Agent Service loads the active release when `KNOWLEDGE_RELEASE_MODE` is `AUTO` or `PORTAL`.
