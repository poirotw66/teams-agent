---
type: architecture
title: Runtime topology
description: Process boundaries, default ports, and call directions among the Teams adapter, Agent Service, AI Ops Console, Knowledge Portal, and supporting processes.
tags: [architecture, ports, processes, teams]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-14T06:27:21.319Z
sources:
  - id: openwiki-source-cde372bc3fe9c7b85835a0eb
    resource: repo://agent_service/src/knowledge_portal/main.py
  - id: openwiki-source-5a7466d2024d71b2c73525f3
    resource: repo://services/pdf_converter/app/main.py
  - id: openwiki-source-7053a919f2ff79ac83709efa
    resource: repo://src/teams_agent/settings.py
  - id: openwiki-source-d61d83066a37e33b8d45f791
    resource: repo://start.sh
generated: { by: "cursor", at: "2026-09-14T06:27:21.319Z" }
---

# Runtime topology

This repository is several processes, not one server. `./start.sh` is the local composer. Each process owns its own port and must not be treated as a library of the others. Users and Teams clients enter through the public edges. Knowledge Portal and the PDF converter stay behind the AI Ops Console.

## Processes

| Process | Local port | Who calls it |
| --- | --- | --- |
| Teams Adapter (`teams-agent`) | `3978` (`PORT`) | Teams, the Dev Tunnel, and the Playground. It calls Agent Service. |
| Agent Service | `8000` (`RAG_PORT` / `PORT`) | The adapter, the portal, and the backoffice. Not a user entry. |
| AI Ops Console | `8092` | Operators. This is the only operations product entry. |
| Knowledge Portal | `8091` under `start.sh`, bound to `127.0.0.1` | The console's knowledge bridge. Not a browser entry. |
| Mock Ticket | `8090` | Agent Service in local ticket tests. |
| PDF converter | `8095` | Knowledge Portal, for PDF-to-Markdown. |
| Agents Playground | `3979` | Local testers. It forwards chat to the adapter. |

`start.sh` refuses to start if Knowledge Portal and Mock Ticket share a port. The portal binary's own default is `8090`, which collides with Mock Ticket, so an orchestrated run must keep `KNOWLEDGE_PORTAL_PORT=8091`. Do not open `8091` as a product UI.

## Call directions

```mermaid
flowchart LR
    teams[Teams or Playground] --> adapter[Teams Adapter :3978]
    adapter -->|AGENT_MODE=api| agent[Agent Service :8000]
    agent --> tickets[Mock Ticket :8090]
    operator[Operator] --> console[AI Ops Console :8092]
    console --> portal[Knowledge Portal :8091 loopback]
    portal --> pdf[PDF converter :8095]
    portal --> agent
    console --> agent
```

`start.sh` starts the adapter with `AGENT_MODE=api` and `AGENT_API_URL` pointed at `http://127.0.0.1:{RAG_PORT}/agent/chat`. The adapter binary itself defaults to `AGENT_MODE=echo` and will not call Agent Service unless `AGENT_MODE=api` and `AGENT_API_URL` are set. A process started outside `start.sh` can therefore look healthy while answering with echo behavior.

The Playground is a test client, not a second adapter. Its `ADAPTER_TARGET_URL` is the Teams Adapter. Its own `/_adapter/api/messages` path is the bot endpoint the playground UI posts to; the gateway then forwards to the adapter.

The console talks to the portal on `KNOWLEDGE_PORTAL_INTERNAL_URL`. `start.sh` sets that to the loopback portal and sets `KNOWLEDGE_PORTAL_PUBLIC_URL` to the console origin so browsers stay on `8092`. The knowledge bridge is on by default (`AI_OPS_KNOWLEDGE_BRIDGE_ENABLED=true`) and will not start without a delegation secret. Do not copy that secret into docs or chat.

The PDF converter is an integration helper for the portal (`POST /api/v1/convert-pdf`). It is not part of the Teams message path. Production prefers the upstream converter image; the in-repo service is the contract shim and local fallback.

Related: [Local runtime](/openwiki/operations/local-runtime.md), [Teams inbound messaging](/openwiki/workflows/teams-inbound.md), [Cloud deployment](/openwiki/operations/cloud-deployment.md).
