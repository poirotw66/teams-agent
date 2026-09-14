---
type: integration
title: Identity and access
description: How Teams, the operations console, and the knowledge portal authenticate callers, and which role checks decide review, publish, and document access.
tags: [identity, entra, rbac, teams]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-14T06:27:21.319Z
sources:
  - id: openwiki-source-fb2ea2d6d9d7caf8edd1cb06
    resource: repo://agent_service/src/agent_service/document_authorization.py
  - id: openwiki-source-ed9d83d40556a299ce14f861
    resource: repo://agent_service/src/ai_ops_backoffice/auth.py
  - id: openwiki-source-44a4b5c34ee56bc86826a42e
    resource: repo://agent_service/src/ai_ops_backoffice/entra_auth.py
  - id: openwiki-source-fd8bbf4dc6eadfdb4ceabbf3
    resource: repo://agent_service/src/knowledge_portal/rbac.py
  - id: openwiki-source-e5469538c836c3701334600d
    resource: repo://docs/teams-app-setup.md
  - id: openwiki-source-fd9a608e1b9dc0c947db88a5
    resource: repo://src/teams_agent/server.py
generated: { by: "cursor", at: "2026-09-14T06:27:21.319Z" }
---

# Identity and access

Three identities are easy to collapse into one, and they are not the same. Teams traffic is authenticated by the Teams SDK. The AI Ops Console authenticates an operator. The Knowledge Portal authorizes a portal actor for draft, review, and publish. A caller who can open the console is not automatically allowed to publish a document.

## Teams and Entra

The adapter does not use Azure Bot Service. The group has no Azure subscription, so the bot is registered in the Teams Developer Portal and bound to an Entra app registration. That registration is a Microsoft 365 app registration. It does not require an Azure subscription. Required names are `CLIENT_ID`, `CLIENT_SECRET`, and `TENANT_ID`. Do not copy secret values into docs, logs, or commits.

The Developer Portal endpoint must be the public adapter URL plus `/api/messages`. Locally that is the current Dev Tunnel. In cloud it is the adapter Cloud Run URL. `appPackage/manifest.json` `bots[0].botId` must match that app id.

Inbound activity JWT mode is `TEAMS_INBOUND_AUTH_MODE`: `botframework` (default), `entra`, or `both`. `botframework` keeps the SDK validator. `entra` replaces it with a tenant-scoped Entra validator used by the Playground. `both` tries Bot Framework first and falls back to Entra. `/readyz` reports `teamsAuth` from whether those app credentials are present. That is the Teams SDK equivalent of the old Azure Bot service-connection check, not a reason to restore Azure Bot Service.

Graph directory calls, when enabled, use the app's own client-credentials token. They do not reuse the user's Teams token.

## Operations console

`resolve_actor` has two modes. `ENTRA` requires a bearer token and validates it against the configured tenant and client id, audience, and issuer (`login.microsoftonline.com/{tenant}/v2.0` or `sts.windows.net/{tenant}/`). The actor id is `oid` or `sub`. Role comes from mapped app roles or group claims. Signature validation cannot be turned off outside `dev`, `test`, and `poc`.

Header auth (`X-Backoffice-User-Id` and related headers) is a local shortcut. Outside `dev`/`test` it fails closed and tells the operator to configure Entra. `start.sh` sets `AI_OPS_BACKOFFICE_AUTH_MODE=HEADER` for local use only. Do not treat that as the deployed contract.

## Knowledge portal roles

Portal roles are not the backoffice roles. Ranked operational roles are `CONTRIBUTOR` < `REVIEWER` < `MANAGER` < `PLATFORM`. `AUDITOR` is outside that rank and is read-only.

| Action | Who |
| --- | --- |
| Review | `REVIEWER`, `MANAGER`, `PLATFORM` |
| Publish | `MANAGER`, `PLATFORM` |
| Audit | `AUDITOR`, `MANAGER`, `PLATFORM` |
| Edit | `CONTRIBUTOR`, `MANAGER`, `PLATFORM`, and only inside the actor's tenant and owner unit unless the actor is `PLATFORM` |

A reviewer or manager cannot approve their own submission unless the workflow is explicitly relaxed or the actor is `PLATFORM`. Cross-tenant visibility fails.

## Document access

Retrieval and download use `authorize_document_access`, which is separate from portal workflow roles. A missing actor or document, a tenant mismatch, a deleted document, or an archived document the actor cannot read all fail as not found, not as a hint that the document exists. A revoked actor is forbidden. `PLATFORM` is a tenant-scoped superuser for read. Other callers still have to match owner unit, creator, or ACL.

Related: [Teams inbound messaging](/openwiki/workflows/teams-inbound.md), [Knowledge release](/openwiki/workflows/knowledge-release.md), [Cloud deployment](/openwiki/operations/cloud-deployment.md).
