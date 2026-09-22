---
type: operations
title: Cloud deployment
description: How the public Teams adapter and private Agent Service are deployed to Cloud Run, how the adapter proves it may call the agent, and which health endpoint means the deploy is usable.
tags: [cloud-run, deployment, secrets, iam]
sources:
  - id: openwiki-source-27aaccf6ad5dc65eb6ae7af1
    resource: repo://agent_service/src/agent_service/routers/health.py
  - id: openwiki-source-be5d86722759dc30dc22280f
    resource: repo://agent_service/src/agent_service/routers/knowledge_admin_reload.py
  - id: openwiki-source-d2450285e6567903f2c28eb9
    resource: repo://deploy/deploy-gcp.sh
  - id: openwiki-source-bd9b00f5274b5d0f71323fe3
    resource: repo://deploy/README.md
  - id: openwiki-source-d4569d57f05783f4c58c4eda
    resource: repo://deploy/release-gcp.sh
  - id: openwiki-source-23775c3de52f3ab95a13cb8b
    resource: repo://README.md
  - id: openwiki-source-e16c46ec9903f8320fd98313
    resource: repo://src/teams_agent/agent_gateway.py
generated: { by: "cursor", at: "2026-09-22T17:10:06.227Z" }
verified:
  - by: openwiki/0.5.1
    at: 2026-09-22T17:10:06.227Z
---

# Cloud deployment

Production keeps the Teams Adapter and Agent Service as two Cloud Run services. The adapter must be reachable by Teams. The agent holds the model key and the knowledge index, so it stays private. Do not merge them into one service or one env file.

## Exposure

| Service | Cloud Run name | Exposure |
| --- | --- | --- |
| Teams Adapter | `teams-agent-adapter` | `--allow-unauthenticated`. Teams must reach `POST /api/messages`. |
| Agent Service | `teams-rag-agent` | `--no-allow-unauthenticated`. Only the adapter service account has `roles/run.invoker`. |

`deploy-gcp.sh` deploys the agent first, reads its URL, grants the adapter service account `roles/run.invoker`, then deploys the adapter with `AGENT_MODE=api`, `AGENT_API_URL={agent}/agent/chat`, `AGENT_API_AUTH_MODE=google_id_token`, and `AGENT_API_AUDIENCE` set to that agent URL. The adapter fetches a Google identity token for that audience and sends it on the agent call. The agent verifies the caller is the adapter.

If the project is Terraform-managed, `deploy-gcp.sh` refuses a full legacy deploy. Shape comes from `infra/terraform`, secrets are injected separately, and `deploy/release-gcp.sh` updates images only for Agent, Adapter, Backoffice, Portal, PDF converter, and (when configured) the independent console-v2 service. Image-only releases do not rewrite IAM, secrets, scaling, or env vars.

Both services scale to zero (`--min=0`, `--max=3`). That is why the deploy sets `CONVERSATION_REPOSITORY_MODE=FIRESTORE` and `OPS_STORE_MODE=FIRESTORE` even though local defaults are memory or file. A recycled instance must still see the conversation and the operational log. Ticket mode is `DISABLED` until a ticket API token is bound from Secret Manager. Do not put that token in `--set-env-vars`.

Production knowledge loading uses `KNOWLEDGE_RELEASE_STORE_MODE=GCS` against the shared release bucket; the Agent image does not bake corpus or indexes. Console activate / Portal reload must hit an Agent build that syncs the GCS mirror before resolving the new release (`_sync_gcs_mirror_before_reload`). Without that sync-before-reload step, FOLLOW_CLOUD Agents reject a just-activated release with HTTP 409 and the Portal can compensate back to the previous active pointer.

## Secrets

`deploy-gcp.sh` copies secret values into Secret Manager without printing them, then binds each secret to the service account that needs it:

| Secret | Bound to | Env var |
| --- | --- | --- |
| `teams-agent-google-api-key` | Agent | `GOOGLE_API_KEY` |
| `teams-agent-bot-client-secret` | Adapter | `CLIENT_SECRET` |
| `teams-agent-asset-signing-key` | Adapter | `RAG_ASSET_SIGNING_KEY` |

The adapter image does not receive the Gemini key. The agent image does not receive the bot client secret.

## What to check after deploy

Use `/readyz`, not `/healthz`, from the corporate network. Requests to `/healthz` on the Cloud Run URL can be intercepted before they reach the container and come back as a Google 404. `/readyz` on the agent reports the loaded chunk count, knowledge mode, and active backend. A missing index is HTTP 503, not a healthy deploy. Cloud Run's own probe is TCP and does not replace `/readyz`.

Related: [Runtime topology](/openwiki/architecture/runtime-topology.md), [Local runtime](/openwiki/operations/local-runtime.md), [Local GCS knowledge sync](/openwiki/workflows/local-gcs-knowledge-sync.md), [Identity and access](/openwiki/integrations/identity-and-access.md).
