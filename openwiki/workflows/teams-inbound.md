---
type: workflow
title: Teams inbound messaging
description: How a Teams activity becomes an agent turn and an Adaptive Card, including feedback and signed images.
tags: [teams, adapter, cards, feedback]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-14T06:27:21.319Z
sources:
  - id: openwiki-source-d747ee51f5798467b8701824
    resource: repo://src/teams_agent/agent.py
  - id: openwiki-source-1e65abfe9a945ea46cabbf21
    resource: repo://src/teams_agent/cards.py
  - id: openwiki-source-fd9a608e1b9dc0c947db88a5
    resource: repo://src/teams_agent/server.py
  - id: openwiki-source-7053a919f2ff79ac83709efa
    resource: repo://src/teams_agent/settings.py
generated: { by: "cursor", at: "2026-09-14T06:27:21.319Z" }
---

# Teams inbound messaging

Teams never calls Agent Service. It calls the adapter's `POST /api/messages`. The Microsoft Teams SDK registers that route and validates the Bot Framework JWT. The adapter then calls Agent Service when it is in `api` mode. See [Runtime topology](/openwiki/architecture/runtime-topology.md) and [Identity and access](/openwiki/integrations/identity-and-access.md).

## Message path

```mermaid
sequenceDiagram
    participant Teams
    participant Adapter
    participant Agent
    Teams->>Adapter: POST /api/messages
    Adapter->>Adapter: Strip mention and generate correlation id
    Adapter->>Agent: POST /agent/chat
    Agent-->>Adapter: Answer, sources, feedback flags
    Adapter-->>Teams: Adaptive Card
```

`on_message` wraps the turn so a handler exception still replies to the user. The SDK reports the error and does not send that reply itself. The user sees a service-unavailable message with a correlation id, not a stack trace.

Empty text after mention stripping gets a short acknowledgement and does not call the agent. A help command reports the current adapter mode and does not call the agent either.

A real turn generates one correlation id and sends it as both `requestId` and `correlationId`. The adapter does not regenerate that id for retries inside the turn. User email comes from the activity when Teams populated it. Graph is used only when that email is missing and directory mode is enabled.

## Card and feedback

The reply is an Adaptive Card built by `build_agent_activity`. Feedback buttons are attached only when the agent response has feedback enabled, a conversation id is present, and the issue result is feedback-eligible. A button submit carries a marker. `on_message` treats that marker as feedback and does not start a new issue turn. The gateway posts it to `/feedback` on the same Agent Service host as `AGENT_API_URL`. Echo mode does not send feedback.

## What else is on the adapter port

`/healthz` and `/readyz` are probes and return no user data. `/rag-assets/{path}` is how Teams loads cited images. Those URLs are HMAC-signed and expiring because the Teams client fetches them without a bearer token. Source viewer routes use enterprise SSO and viewer tokens. They are not the messaging path.

Related: [Issue resolution workflow](/openwiki/workflows/issue-resolution.md).
