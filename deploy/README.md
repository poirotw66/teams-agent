# GCP Cloud Run deployment

Default target:

```text
Project: itr-aimasteryhub-lab
Region: asia-east1
Agent: teams-rag-agent (private)
Adapter: teams-agent-adapter (public)
```

Deployed on 2026-07-30:

```text
Agent URL:   https://teams-rag-agent-jt7pjdeeoa-de.a.run.app
Adapter URL: https://teams-agent-adapter-jt7pjdeeoa-de.a.run.app
```

Deploy:

```bash
./deploy/deploy-gcp.sh
```

The script:

1. Enables required APIs.
2. Creates Artifact Registry and two service accounts.
3. Copies local secret values into Secret Manager without printing them.
4. Builds both Linux images in Cloud Build.
5. Deploys the private Agent and grants only the Adapter `run.invoker`.
6. Deploys the public Teams Adapter.
7. Configures the Adapter Cloud Run URL for signed RAG images.

After deployment, set Azure Bot Messaging endpoint to:

```text
https://<teams-agent-adapter-url>/api/messages
```

Current endpoint:

```text
https://teams-agent-adapter-jt7pjdeeoa-de.a.run.app/api/messages
```

Do not commit `.env`, `agent_service/.env`, credentials, or exported secrets.

## Two-service split

Spec §2.2 keeps the Teams Adapter and the LangGraph Agent Service as two
separate Cloud Run services with different exposure and different config:

| | Teams Adapter (`teams-agent-adapter`) | Agent Service (`teams-rag-agent`) |
|---|---|---|
| Visibility | `--allow-unauthenticated` (public; Azure Bot must reach it) | `--no-allow-unauthenticated` (private; only the Adapter's service account has `roles/run.invoker`) |
| Auth to the other service | N/A | Verifies each caller is the Adapter, via Cloud Run IAM identity tokens (`AGENT_API_AUTH_MODE=google_id_token`, `AGENT_API_AUDIENCE=<agent-url>`) |
| Config source | `.env` at the project root / `.env.example` | `agent_service/.env` / `agent_service/.env.example` |
| Full env var reference | [`../README.md`](../README.md) | [`../README.md`](../README.md) |

Never merge the two into one Cloud Run service or one `.env` file — the
private/public split is what lets the Agent Service (which holds the
Gemini API key and reaches the knowledge base) stay unauthenticated-free
while the Adapter, which must be internet-reachable for Azure Bot, carries
no AI credentials at all.

## Secrets (spec §17: API keys only via Secret Manager or env, never in code/Git)

`deploy-gcp.sh` provisions these Secret Manager secrets and binds them only
to the service account that needs them:

| Secret | Bound to | Cloud Run env var it becomes |
|---|---|---|
| `teams-agent-google-api-key` | Agent SA | `GOOGLE_API_KEY` |
| `teams-agent-bot-client-secret` | Adapter SA | `CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTSECRET` |
| `teams-agent-asset-signing-key` | Adapter SA | `RAG_ASSET_SIGNING_KEY` |

Not yet wired into `deploy-gcp.sh` (add them the same way, as
`--set-secrets`, if/when the corresponding feature is turned on in
production) — never pass these as plain `--set-env-vars`:

| Secret you'd create | Env var | Needed when |
|---|---|---|
| a ticket-API token secret | `TICKET_SERVICE_TOKEN` | `TICKET_SERVICE_MODE=HTTP` |
| an `AGENT_SERVICE_TOKEN` secret | `AGENT_SERVICE_TOKEN` | You want a second layer of auth on `/agent/chat` in addition to (or instead of) Cloud Run IAM |

## New Agent Service env vars (this phase)

`deploy-gcp.sh` now sets `KNOWLEDGE_SERVICE_MODE=HYBRID`,
`TICKET_SERVICE_MODE=DISABLED`, `CONVERSATION_REPOSITORY_MODE=MEMORY`, and
`FEEDBACK_ENABLED=true` explicitly on the Agent Cloud Run service, even
though these match the code defaults in
`agent_service/src/agent_service/settings.py` — being explicit means the
deployed configuration doesn't silently depend on defaults nobody re-reads.
`FAQ_PATH` and `CONVERSATION_STORE_PATH` are left unset (they default to
`RAG_DATA_DIR/faq.json` and `RAG_DATA_DIR/conversations`, which resolve
correctly under `/app/data` inside the container). See
[`../README.md`](../README.md) for the full table with
defaults and valid ranges, and
[`../docs/gemini-file-search-spike.md`](../docs/gemini-file-search-spike.md)
before ever setting `KNOWLEDGE_SERVICE_MODE=GEMINI_FILE_SEARCH` here — that
mode also needs the `spike` extra installed, which the production image
does not install by default (`RUN pip install --no-cache-dir ./agent_service`
installs only the base dependency set).

## Tuning the §16 knobs

Spec §16's optimization order puts runtime/infra tuning (concurrency, CPU,
memory, external-service timeouts) *after* reducing LLM calls, using the
deterministic formatter, and capping issue/rewrite counts — and explicitly
forbids treating a language rewrite as the first-resort performance fix
without load-test data. Concretely, don't change the values below without
measured evidence (spec §18's performance test):

- **Agent Service** currently deploys with `--concurrency=8 --cpu=1
  --memory=2Gi --timeout=90`. Each request can now run up to
  `MAX_LLM_CALLS_PER_REQUEST` (default 5) LLM calls and processes issues
  concurrently via `asyncio.gather`, so P95 latency and memory headroom are
  the numbers to watch first if load testing shows contention — raise
  `--concurrency` down or `--cpu`/`--memory` up, in that order, only if
  measurements show it's needed.
- **Teams Adapter** deploys with `--concurrency=40 --cpu=1 --memory=512Mi
  --timeout=90`; it does no LLM work itself (it only calls the Agent
  Service and signs image URLs), so it should rarely need to change.
- **External-service timeouts**: `AGENT_API_TIMEOUT_SECONDS` (Adapter →
  Agent Service, default 10s) and `TICKET_SERVICE_TIMEOUT_SECONDS` (Agent
  Service → ticket API, default 10s, valid range 1–60) should both stay
  comfortably under the Cloud Run request `--timeout=90` to leave room for
  a friendly degrade-and-log path instead of a hard Cloud Run timeout.
- **Scale-to-zero**: both services deploy with `--min=0 --max=3`. Raise
  `--max` only after observing sustained concurrency near the current
  limit; `--min=0` is intentional for a POC to avoid idle cost.
