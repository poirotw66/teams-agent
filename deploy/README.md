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

After deployment, set the bot's Endpoint address in the Teams Developer
Portal (https://dev.teams.microsoft.com, Tools -> Bot management) to:

```text
https://<teams-agent-adapter-url>/api/messages
```

Current endpoint:

```text
https://teams-agent-adapter-jt7pjdeeoa-de.a.run.app/api/messages
```

Do not commit `.env`, `agent_service/.env`, credentials, or exported secrets.

## Short-lived external Agents Playground

For a short UAT without Teams access, deploy the Microsoft 365 Agents
Playground behind the repository's server-side password gateway:

```bash
./deploy/deploy-playground.sh
```

The script creates a dedicated Cloud Run service and service account, limits the
service to one instance, and stores both the shared login password and session
signing key in Secret Manager. It reuses the deployed Adapter endpoint and the
existing Bot client secret. The `/_connector` callback namespace remains
reachable without the browser password because Bot replies do not carry the
browser cookie; Agents Playground still validates the Bot JWT on that route.
The container also applies a narrow compatibility patch to version `0.2.28` so
an HTTPS page opens its event streams over `wss://` instead of the package's
hard-coded `ws://` URL.
The generated password is not printed; retrieve it
only when distributing it to approved testers:

```bash
gcloud secrets versions access latest \
  --secret=teams-agent-playground-password \
  --project=itr-aimasteryhub-lab
```

This is intended only for short-lived acceptance testing. Delete the Cloud Run
service after UAT, and rotate or destroy the shared password secret if the test
environment is deployed again.

## Two-service split

Spec §2.2 keeps the Teams Adapter and the LangGraph Agent Service as two
separate Cloud Run services with different exposure and different config:

| | Teams Adapter (`teams-agent-adapter`) | Agent Service (`teams-rag-agent`) |
|---|---|---|
| Visibility | `--allow-unauthenticated` (public; the Bot Framework service must reach it) | `--no-allow-unauthenticated` (private; only the Adapter's service account has `roles/run.invoker`) |
| Auth to the other service | N/A | Verifies each caller is the Adapter, via Cloud Run IAM identity tokens (`AGENT_API_AUTH_MODE=google_id_token`, `AGENT_API_AUDIENCE=<agent-url>`) |
| Config source | `.env` at the project root / `.env.example` | `agent_service/.env` / `agent_service/.env.example` |
| Full env var reference | [`../README.md`](../README.md) ([繁中](../README-TW.md)) | [`../README.md`](../README.md) ([繁中](../README-TW.md)) |

Never merge the two into one Cloud Run service or one `.env` file — the
private/public split is what lets the Agent Service (which holds the
Gemini API key and reaches the knowledge base) stay unauthenticated-free
while the Adapter, which must be internet-reachable for the Bot Framework
service, carries
no AI credentials at all.

## Secrets (spec §17: API keys only via Secret Manager or env, never in code/Git)

`deploy-gcp.sh` provisions these Secret Manager secrets and binds them only
to the service account that needs them:

| Secret | Bound to | Cloud Run env var it becomes |
|---|---|---|
| `teams-agent-google-api-key` | Agent SA | `GOOGLE_API_KEY` |
| `teams-agent-bot-client-secret` | Adapter SA | `CLIENT_SECRET` |
| `teams-agent-asset-signing-key` | Adapter SA | `RAG_ASSET_SIGNING_KEY` |

Not yet wired into `deploy-gcp.sh` (add them the same way, as
`--set-secrets`, if/when the corresponding feature is turned on in
production) — never pass these as plain `--set-env-vars`:

| Secret you'd create | Env var | Needed when |
|---|---|---|
| a ticket-API token secret | `TICKET_SERVICE_TOKEN` | `TICKET_SERVICE_MODE=HTTP` |
| an `AGENT_SERVICE_TOKEN` secret | `AGENT_SERVICE_TOKEN` | You want a second layer of auth on `/agent/chat` in addition to (or instead of) Cloud Run IAM |

## New Agent Service env vars (this phase)

`deploy-gcp.sh` sets `KNOWLEDGE_SERVICE_MODE=HYBRID`,
`TICKET_SERVICE_MODE=DISABLED`, `CONVERSATION_REPOSITORY_MODE=FIRESTORE`,
`CONVERSATION_FIRESTORE_COLLECTION=conversations` and
`HANDOFF_REPOSITORY_MODE=FIRESTORE`, `HANDOFF_FIRESTORE_COLLECTION=handoffs`,
`HANDOFF_DEMO_TIMEOUT_HOURS=24`, `HANDOFF_RETENTION_DAYS=730` and
`FEEDBACK_ENABLED=true` explicitly on the Agent Cloud Run service. Most of
these match the code defaults in
`agent_service/src/agent_service/settings.py` and are stated anyway so the
deployed configuration doesn't silently depend on defaults nobody re-reads.

`CONVERSATION_REPOSITORY_MODE` is the one that deliberately **differs**
from the code default — see the next section. `FAQ_PATH` and
`CONVERSATION_STORE_PATH` are left unset (they default to
`RAG_DATA_DIR/faq.json` and `RAG_DATA_DIR/conversations`, which resolve
correctly under `/app/data` inside the container). See
[`../README.md`](../README.md) for the full table with defaults and valid
ranges ([Traditional Chinese](../README-TW.md)), and
[`../docs/gemini-file-search-spike.md`](../docs/gemini-file-search-spike.md)
before ever setting `KNOWLEDGE_SERVICE_MODE=GEMINI_FILE_SEARCH` here — that
mode also needs the `spike` extra installed, which the production image
does not install (`pip install "./agent_service[firestore]"` installs the
base set plus the Firestore backend only).

## Conversation persistence: Firestore (spec §10.3)

The code default is `MEMORY`, which is right for local dev and tests but
wrong here for two independent reasons:

- Cloud Run **scales to zero**. When the instance is recycled, every
  in-flight conversation disappears — so 連續問答, 使用者補充資訊 and
  工單確認 (spec §10.1) break silently between turns.
- Cloud Run runs **up to 3 instances**. Two turns of the same conversation
  can land on different instances, which do not share memory *or* local
  disk — so `FILE` mode does not fix this either.

`deploy-gcp.sh` therefore provisions and uses Firestore:

| Step in the script | What it does |
|---|---|
| `gcloud services enable firestore.googleapis.com` | Turns the API on |
| `gcloud firestore databases create` | Creates the native-mode database (skipped if it already exists) |
| `gcloud firestore fields ttls update expiresAt` | Enables the TTL policy on `conversations`, `conversations_keys` and the `messages` collection group |
| `gcloud firestore fields ttls update retentionExpiresAt` | Enables the separate 730-day retention TTL on `handoffs` and `handoffs_events`; `sessionExpiresAt` remains application-controlled |
| `roles/datastore.user` on the **Agent SA** | Read/write on Firestore documents. The Adapter SA gets nothing — it never touches conversation data |

Overridable via env when running the script: `GCP_FIRESTORE_DATABASE`
(default `(default)`), `GCP_FIRESTORE_LOCATION` (default = `GCP_REGION`,
i.e. `asia-east1`), `GCP_FIRESTORE_COLLECTION` (default `conversations`).

Document layout, ordering guarantees and the concurrency argument are
documented on `FirestoreConversationRepository` in
`agent_service/src/agent_service/conversation.py`.

### TTL is retention, not timeout

Two separate mechanisms, easily confused:

- **Timeout** (`CONVERSATION_TIMEOUT_HOURS`, spec §10.2) is enforced in
  code on every read: a conversation whose `lastActivityAt` is older than
  the timeout is treated as absent and a fresh one is created. This never
  depends on TTL having run.
- **TTL** is data retention: Firestore deletes documents some time after
  `expiresAt` (collection can lag by ~24h). It exists so the store does
  not grow without bound, not to enforce conversation boundaries.

If a TTL policy fails to apply, the script warns instead of aborting — the
service still behaves correctly, it just accumulates documents until the
policy is fixed. Check with:

```bash
gcloud firestore fields ttls list --database='(default)' --project=itr-aimasteryhub-lab
```

### Live verification (2026-08-07)

`scripts/firestore_verification.py` runs the real repository against real
Firestore in a throwaway collection and deletes everything afterwards:

```bash
cd agent_service
.venv/bin/python ../scripts/firestore_verification.py --project itr-aimasteryhub-lab
```

Result: **10/10 checks passed**, 8 documents written and all 8 deleted;
`collections()` afterwards returned nothing, i.e. the probe left no trace.

The run was worth doing — it caught a real defect that the whole Fake-based
suite had passed. The repository originally ordered the `messages`
subcollection by `__name__` descending; live Firestore rejects that with
`FAILED_PRECONDITION: The query requires an index`, so **every history read
would have failed in production**. Ordering now uses a regular `sortKey`
field, which Firestore auto-indexes in both directions. The Fake was
updated to reject `__name__`-descending the same way, and
`test_fake_rejects_descending_name_ordering_like_real_firestore` pins it.

Also provisioned and verified on `itr-aimasteryhub-lab`:

| Item | State |
|---|---|
| `(default)` Firestore database, `asia-east1`, native mode | created |
| TTL policy on `expiresAt` — `conversations` | enabled |
| TTL policy on `expiresAt` — `conversations_keys` | enabled |
| TTL policy on `expiresAt` — `messages` collection group | enabled |

The Agent service account still needs `roles/datastore.user`; that binding
is applied by `deploy-gcp.sh` on the next deploy.

### Data protection

Conversation documents contain user message text. They inherit
Google-managed encryption at rest and are reachable only by the Agent
service account. Retention is bounded by the TTL policy above. If a
retention window shorter than `CONVERSATION_TIMEOUT_HOURS` is ever
required by policy, lower `CONVERSATION_TIMEOUT_HOURS` — the repository
derives `expiresAt` from it, so the two can never drift apart.

## Build & deploy verification (2026-08-06)

Both images were built and the Agent Service was deployed to a throwaway Cloud
Run service (`teams-rag-agent-verify`, deleted afterwards) to verify packaging
and startup without touching the live services. Results:

| Check | Result |
|---|---|
| `cloudbuild-agent.yaml` build | OK (78s) |
| `cloudbuild-adapter.yaml` build | OK (48s) |
| `data/faq.json` present in image | OK — 1683 bytes, 6 faqKeys parsed |
| `data/index/chunks.json` in image | OK — 1.5 MB |
| Corpus in image | OK — 19 documents |
| Settings resolution in container | OK — `data_dir=/app/data`, index and FAQ paths exist |
| `GET /readyz` | 200, `chunks: 22`, `retrieval: hybrid` |
| `POST /agent/chat` | 200 in 1.37s; correlation ID echoed; IT + non-IT split correctly |
| `POST /feedback` | 200 |
| Structured logging (§15.2) | All required fields present in Cloud Logging |

Note that a local `docker build` has still never been run — Docker is not
installed on the development machine. Verification went through Cloud Build,
which is the path `deploy-gcp.sh` uses anyway.

To repeat this verification without disturbing the live services, build with a
distinct tag (not `:latest`, which the running services reference) and deploy
under a `-verify` service name, then delete it:

```bash
gcloud builds submit . --config=deploy/cloudbuild-agent.yaml \
  --substitutions=_IMAGE=<registry>/teams-rag-agent:verify-poc --project=<project>
# deploy to teams-rag-agent-verify, check /readyz, then:
gcloud run services delete teams-rag-agent-verify --region=<region> --project=<project>
```

## Knowledge corpus and index delivery — known limitation

**Deployment currently requires a developer machine that holds the corpus.**
This is a deliberate, accepted constraint for the POC, recorded here so it is
not rediscovered during an incident.

`agent_service/Dockerfile` does `COPY data ./data`, so the image is built with
whatever `data/` exists **in the upload context**, and
`gcloud builds submit .` uploads the *local working directory* filtered by
[`.gcloudignore`](../.gcloudignore) — not the git tree. Since `.gcloudignore`
does not exclude `data/`, the local corpus (`data/sources/`), the built index
(`data/index/chunks.json`) and the extracted images (`data/assets/`) are all
uploaded and baked into the image. `data/faq.json` ships the same way, and
`FAQ_PATH` resolves to `/app/data/faq.json` inside the container.

The consequence: **`data/sources/` and `data/index/` are gitignored** (internal
IT documents are deliberately kept out of version control), so a build
triggered from a connected Git repository — a Cloud Build GitHub trigger, or
any CI runner doing a clean clone — would produce an image with **no corpus and
no index**. `RAG_AUTO_BUILD_INDEX` cannot rescue it, because there would be no
source documents to build from; the service would start and then fail
readiness.

Practical rules while this stands:

1. Deploy only via `deploy/deploy-gcp.sh` (or a manual `gcloud builds submit .`)
   from a checkout that has the corpus present.
2. Rebuild the index before deploying whenever the corpus changed:
   `cd agent_service && .venv/bin/rag-index`.
3. Do **not** wire up a Git-triggered Cloud Build for the Agent Service without
   first changing how the corpus is delivered.
4. After deploying, check `/readyz` — it reports the chunk count, which is the
   fastest way to catch an image that shipped without an index.

If deployment needs to become automatable later, the options considered were:
fetch the corpus and index from a GCS bucket at container start (keeps
documents out of both git and the image, adds a runtime dependency), or track
the corpus in a private repository (simplest, but puts internal IT documents
into git history and needs an infosec decision). Neither is implemented.

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

## Mock Ticket API 驗收環境

部署 Cloud Run Mock Ticket API 並將 Agent 切換到 HTTP 工單模式：

```bash
./deploy/deploy-mock-ticket.sh
```

Mock API 使用 Secret Manager Bearer Token 保護建立與查詢操作，資料存放於
Firestore `mock_tickets` collection。此服務僅供驗收，不代表正式工單系統。
重新執行完整的 `deploy-gcp.sh` 會把工單模式重設為 `DISABLED`；需要時再執行
本腳本即可恢復 Mock 工單環境。
