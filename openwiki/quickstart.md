---
type: concept
title: Quickstart
description: Where to start a change in this repository, and the few facts that are wrong if assumed the other way.
tags: [quickstart, routing, teams]
sources:
  - id: openwiki-source-b87001a951cc6df431b62bbb
    resource: repo://agent_service/src/agent_service/workflow_subgraphs.py
  - id: openwiki-source-b2a2989e09192cb127da6a87
    resource: repo://src/teams_agent/main.py
  - id: openwiki-source-11164ff60d3496c610fdb78d
    resource: repo://src/teams_agent/settings_env.py
  - id: openwiki-source-7053a919f2ff79ac83709efa
    resource: repo://src/teams_agent/settings.py
  - id: openwiki-source-d61d83066a37e33b8d45f791
    resource: repo://start.sh
generated: { by: "cursor", at: "2026-09-22T17:10:06.227Z" }
verified:
  - by: openwiki/0.5.1
    at: 2026-09-22T17:10:06.227Z
---

# Quickstart

This wiki is the agent memory for the Teams IT assistant. Read the page for the task. Do not treat the README as the runtime contract when it disagrees with `start.sh` or the deploy scripts.

## Do not assume

- This is not Azure Bot Service. The adapter is the Microsoft Teams SDK. Bot registration is the Teams Developer Portal plus an Entra app. Names: `CLIENT_ID`, `CLIENT_SECRET`, `TENANT_ID`.
- The adapter defaults to echo. `./start.sh` and Cloud Run set `AGENT_MODE=api`. A bare `teams-agent` process will not call Agent Service.
- Operators use `http://127.0.0.1:8092/`. Knowledge Portal on 8091 is loopback for the console bridge. Do not add a user-facing portal entry.
- Local conversation and ops stores are not the Cloud Run stores. Cloud Run uses Firestore because instances scale to zero.
- An FAQ hit is verbatim and does not call the model. A ticket route without a confirmed create or query intent does not call the ticket API.
- After a Cloud Run deploy, check `/readyz`, not `/healthz`.
- Cloud ACTIVE after publish is not the same as every local Playground being caught up. Use Sync Now / lag banners for the Console-connected Agent mirror.

## Route the task

| If you are changing | Read |
| --- | --- |
| Ports, who calls whom | [Runtime topology](/openwiki/architecture/runtime-topology.md) |
| Local start, env files, playground login, GCS override | [Local runtime](/openwiki/operations/local-runtime.md) |
| Cloud Run, IAM, Secret Manager, image-only release | [Cloud deployment](/openwiki/operations/cloud-deployment.md) |
| Teams message, card, feedback, images | [Teams inbound messaging](/openwiki/workflows/teams-inbound.md) |
| Issue split, FAQ, clarify, ticket, handoff | [Issue resolution workflow](/openwiki/workflows/issue-resolution.md) |
| Hybrid search or Gemini File Search | [Retrieval backends](/openwiki/workflows/retrieval.md) |
| Draft, review, publish, Portal reload, RELOAD_FAILED | [Knowledge release](/openwiki/workflows/knowledge-release.md) |
| Local Playground lag, Sync Now, FOLLOW_CLOUD mirror | [Local GCS knowledge sync](/openwiki/workflows/local-gcs-knowledge-sync.md) |
| Quality cases, evaluation gates, Sync Now UX | [Quality and governance operations](/openwiki/workflows/quality-operations.md) |
| Entra, RBAC, formal write gate, document access | [Identity and access](/openwiki/integrations/identity-and-access.md) |
| Conversation, events, `data/ops` | [Conversation and operations state](/openwiki/architecture/conversation-and-ops-state.md) |
| Which tests to run | [Verification](/openwiki/testing/verification.md) |

## Minimum local loop

Copy `.env.example` to `.env` and `agent_service/.env.example` to `agent_service/.env`. Copy `data/sources.sample` to `data/sources` if the corpus is missing. Run `./start.sh`. Wait until Agent `/readyz` and Adapter `/readyz` succeed. Open the console at `http://127.0.0.1:8092/` and Playground at `http://127.0.0.1:3979/login`. Use `127.0.0.1`, not `localhost`.

Run the pytest project you changed. Adapter tests are `pytest tests` from the repo root. Agent, portal, and console tests are `pytest tests` from `agent_service`.
