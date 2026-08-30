# Knowledge Operations Portal

Internal web application for knowledge lifecycle management, separate from Teams chat runtime.

Spec: [`../../docs/knowledge-operations-portal-spec.md`](../../docs/knowledge-operations-portal-spec.md)

## Run locally

```bash
cd agent_service
uv run knowledge-portal
```

Open `http://localhost:8090/`.

PoC identity uses request headers until Entra SSO is wired:

- `X-Portal-User-Id`
- `X-Portal-User-Name`
- `X-Portal-Role` (`CONTRIBUTOR`, `REVIEWER`, `MANAGER`, `PLATFORM`, `AUDITOR`)
- `X-Portal-Owner-Units`

Optional bearer auth: set `KNOWLEDGE_PORTAL_TOKEN`.

## Phase 1 MVP included

- Dashboard, knowledge list, Markdown draft create/update
- Validation preview with blocking/warning/info checks
- Test case registry and basic test runs
- Submit for review, approve/reject, publish release artifact, rollback pointer
- Append-only audit events
- In-memory repository (`KNOWLEDGE_PORTAL_REPOSITORY_MODE=MEMORY`) or Firestore

## Not included yet

- Entra ID SSO
- Full feedback workbench
- Email/Teams notifications
- PDF/DOCX ingestion

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

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `KNOWLEDGE_PORTAL_PORT` | `8090` | HTTP port |
| `KNOWLEDGE_PORTAL_REPOSITORY_MODE` | `MEMORY` | `MEMORY` or `FIRESTORE` |
| `KNOWLEDGE_PORTAL_RELEASE_DIR` | `data/releases` | Immutable release artifacts |
| `KNOWLEDGE_PORTAL_REQUIRE_DUAL_APPROVAL` | `true` | Block self-publish by contributor |

Release artifacts contain parsed sources, `manifest.json`, and `index/chunks.json`. Agent Service loads the active release when `KNOWLEDGE_RELEASE_MODE` is `AUTO` or `PORTAL`.
