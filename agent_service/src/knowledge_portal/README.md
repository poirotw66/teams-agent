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
- Agent Service hot-loading of active release index
- Email/Teams notifications
- PDF/DOCX ingestion

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `KNOWLEDGE_PORTAL_PORT` | `8090` | HTTP port |
| `KNOWLEDGE_PORTAL_REPOSITORY_MODE` | `MEMORY` | `MEMORY` or `FIRESTORE` |
| `KNOWLEDGE_PORTAL_RELEASE_DIR` | `data/releases` | Immutable release artifacts |
| `KNOWLEDGE_PORTAL_REQUIRE_DUAL_APPROVAL` | `true` | Block self-publish by contributor |

Release artifacts contain parsed sources, `manifest.json`, and `index/chunks.json`. They are written by the portal only; chat runtime must be pointed to the active release separately in a follow-up change.
