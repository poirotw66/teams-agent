---
type: operations
title: Local runtime
description: How start.sh launches the local stack, which files it requires, and which URLs mean the stack is usable.
tags: [local, startup, readiness, configuration]
sources:
  - id: openwiki-source-5f5b95b3d6a215fa02ceb945
    resource: repo://.env.example
  - id: openwiki-source-b03fddd110ee2dd693bc0987
    resource: repo://agent_service/.env.example
  - id: openwiki-source-35ea64099371cd2b6ea0c6bf
    resource: repo://agent_service/src/agent_service/settings_env.py
  - id: openwiki-source-d61d83066a37e33b8d45f791
    resource: repo://start.sh
generated: { by: "cursor", at: "2026-09-22T17:10:06.227Z" }
verified:
  - by: openwiki/0.5.1
    at: 2026-09-22T17:10:06.227Z
---

# Local runtime

`./start.sh` is the supported way to run the stack locally. Starting one binary and assuming the rest of the topology exists will look healthy and then answer as echo, miss the portal, or collide on port 8090.

## Required before start

The script requires `uv`, `lsof`, `curl`, `awk`, and `ps`. It fails immediately unless both `./.env` and `agent_service/.env` exist. Copy them from `.env.example` and `agent_service/.env.example`. The root example names `CLIENT_ID`, `CLIENT_SECRET`, and `TENANT_ID`, and defaults `AGENT_MODE` to `echo`. Replace the placeholders. Do not commit real values.

It also requires a knowledge corpus directory at `RAG_SOURCES_DIR`, default `data/sources`. A fresh checkout can copy `data/sources.sample` to `data/sources` for Playground. Missing that directory is a hard failure, not an empty index.

## What start.sh changes

The script does not trust process defaults. It forces the local integration shape:

- Agent Service listens on `RAG_PORT` (8000) and must answer `GET /readyz` before the adapter starts.
- The adapter is started with `AGENT_MODE=api` and `AGENT_API_URL=http://127.0.0.1:{RAG_PORT}/agent/chat`. The binary default is echo.
- Knowledge Portal is bound to `127.0.0.1:8091`. The console on `8092` is the only operations URL the script prints as an entry.
- The console uses `HEADER` auth and `OPS_STORE_MODE=FILE`. That is a local label, not the Cloud Run contract. See [Cloud deployment](/openwiki/operations/cloud-deployment.md).
- The knowledge bridge is on unless `AI_OPS_KNOWLEDGE_BRIDGE_ENABLED` is set false. It will not start without a delegation secret.
- Playground is a test client on port 3979. Dev Tunnel stays off unless `START_TUNNEL=true`.

## Local GCS knowledge mirror

Optional `agent_service/.env.knowledge-gcs.local` (gitignored) is sourced by `start.sh` when present and exports `KNOWLEDGE_RELEASE_*` into the Agent process. Typical FOLLOW_CLOUD knobs: `KNOWLEDGE_RELEASE_STORE_MODE=GCS`, bucket/prefix, tenant, `KNOWLEDGE_RELEASE_CACHE_DIR`, `KNOWLEDGE_RELEASE_SYNC_INTERVAL_SECONDS` (default 300), `KNOWLEDGE_RELEASE_SELECTION_MODE=FOLLOW_CLOUD`, and Firestore project/collections. Settings loaders in `settings_env.py` parse the same names. Sync runs in Agent lifespan wiring, not on each Playground turn. Console-v2 Sync Now proxies through Backoffice to the configured `AGENT_API_URL` admin sync endpoint.

Services can be skipped with `START_MOCK_TICKET`, `START_PORTAL`, `START_PDF_CONVERTER`, `START_AI_OPS_BACKOFFICE`, and `START_PLAYGROUND`. Skipping the portal while leaving the bridge enabled leaves the console without its knowledge dependency.

## What ready means

The script waits, in order, for:

| Check | Meaning |
| --- | --- |
| Agent `GET /readyz` | The RAG index loaded. `/healthz` only means the process answered. |
| PDF converter `GET /health` | Converter process is up. Not part of the Teams path. |
| Portal `GET /healthz` | Internal API is up. Do not browse it. |
| Console `GET /healthz` | Operations UI process is up. |
| Adapter `GET /readyz` | Teams credentials and agent mode are reported. |
| Playground `/healthz` and `/login` | Test chat is up. |

Open `http://127.0.0.1:8092/` for operations and `http://127.0.0.1:3979/login` for chat. Do not open the Playground internal port. Do not mix `localhost` and `127.0.0.1`; the login cookie will not match. After login, the knowledge backend switch is Hybrid or Gemini File Search.

Related: [Runtime topology](/openwiki/architecture/runtime-topology.md), [Local GCS knowledge sync](/openwiki/workflows/local-gcs-knowledge-sync.md), [Verification](/openwiki/testing/verification.md).
