---
type: workflow
title: Knowledge release
description: How a knowledge document moves from review to an approved publish, how Portal activation reloads the Agent, and how cloud ACTIVE differs from a local Playground mirror.
tags: [knowledge, publish, review, release]
sources:
  - id: openwiki-source-eefa67e7a7b9e61180b523fa
    resource: repo://agent_service/src/agent_service/deps.py
  - id: openwiki-source-81f2d0e4c05a0c34175e7848
    resource: repo://agent_service/src/agent_service/knowledge_release_gcs.py
  - id: openwiki-source-be5d86722759dc30dc22280f
    resource: repo://agent_service/src/agent_service/routers/knowledge_admin_reload.py
  - id: openwiki-source-2b57350b87bee282f22fe17e
    resource: repo://agent_service/src/ai_ops_backoffice/knowledge_bridge/delegation.py
  - id: openwiki-source-76773aa63f41557933a45ced
    resource: repo://agent_service/src/knowledge_core/runtime_inventory.py
  - id: openwiki-source-ac85e9adaa9af1de47286c9a
    resource: repo://agent_service/src/knowledge_portal/publisher.py
  - id: openwiki-source-e54ea350813aac2e5460cd8e
    resource: repo://agent_service/src/knowledge_portal/release/activation.py
  - id: openwiki-source-c6c065126450268f94f399c2
    resource: repo://agent_service/src/knowledge_portal/release/publish.py
  - id: openwiki-source-a3835bbddd1483caa915ead8
    resource: repo://agent_service/src/knowledge_portal/release/transitions.py
  - id: openwiki-source-8470205e385c544b25585ce2
    resource: repo://agent_service/src/knowledge_portal/services/review_service.py
  - id: openwiki-source-88e83fa90665ebcad8016318
    resource: repo://agent_service/src/platform_kernel/delegation.py
generated: { by: "cursor", at: "2026-09-22T17:10:06.227Z" }
verified:
  - by: openwiki/0.5.1
    at: 2026-09-22T17:10:06.227Z
---

# Knowledge release

Operators do not publish by opening the Knowledge Portal. The AI Ops Console on port 8092 is the product entry. Its knowledge bridge signs a delegation envelope and calls the portal on loopback (or the remote Portal URL in cloud). The portal remains the owner of draft, review, and release records.

## Review before publish

A review decision is single-use. A decided review cannot be decided again. The reviewer must be allowed to review, must not be the submitter unless the workflow is relaxed or the actor is `PLATFORM`, and must be able to see the document.

| Decision | Version status | Document status |
| --- | --- | --- |
| `APPROVED` | `APPROVED` | `APPROVED` |
| `CHANGES_REQUESTED` | `CHANGES_REQUESTED` | `CHANGES_REQUESTED` |
| otherwise | `REJECTED` | `DRAFT` |

Approval is not publication. Retrieval still sees the previously active release until publish builds and activates a new one.

## Publish and activate

`publish_version` requires a publish role (`MANAGER` or `PLATFORM`). The version must belong to the document and must already be `APPROVED`. When dual approval is required, the version creator cannot publish their own approved content unless they are `PLATFORM`. An idempotency key returns the cached release instead of building a second one.

Publish holds a coordination lock, collects the other active published versions, appends this version as `PUBLISHED`, and activates one release artifact through the release activation saga. The artifact directory contains published sources and `index/chunks.json`. When a GCS release bucket is configured, the publisher uploads the release and attaches a `runtimeArtifacts` inventory (paths, sizes, SHA-256) so Agents can sync a complete QA snapshot rather than an index-only mirror. The document then records `current_published_version_id` and clears `draft_version_id`. If activation does not produce a release, publish fails and does not pretend the version is live.

Activation advances the Firestore (or FILE) active-release pointer, then notifies Agent Service via `POST /admin/reload-knowledge`. On Cloud Run / GCS Agents, that reload **syncs the mirror before resolving** the new release. If reload fails while this release still owns the pointer, Portal settles the candidate as `RELOAD_FAILED` and may compensate by restoring the previous active release. Cloud `ACTIVE` therefore means the control plane pointer (and a successful Agent reload for that deploy), not that every local Playground has already mirrored the same id.

## What the agent reads

Two paths must not be collapsed:

| Mode | How the Agent picks knowledge |
| --- | --- |
| `KNOWLEDGE_RELEASE_STORE_MODE=FILE` (local default) | `sync_knowledge_to_active_pointer` on chat/readyz follows `data/releases` active pointer and loads `index/chunks.json` when it moves. A missing index leaves the previous index in place. |
| `KNOWLEDGE_RELEASE_STORE_MODE=GCS` | Chat does **not** follow the FILE pointer. Background sync (and reload-triggered sync) mirrors cloud active release into `knowledge_cache`; RAG loads that verified snapshot. Console "Sync Now" is a Backoffice→Agent admin call, separate from Portal activate reload. |

`KNOWLEDGE_RELEASE_MODE` is `AUTO`, `PORTAL`, or `BUNDLED`. `AUTO` is the default for local FILE pointer following. A bundled index is the fallback when no portal release is active under FILE mode.

Related: [Retrieval backends](/openwiki/workflows/retrieval.md), [Local GCS knowledge sync](/openwiki/workflows/local-gcs-knowledge-sync.md), [Identity and access](/openwiki/integrations/identity-and-access.md), [Quality and governance operations](/openwiki/workflows/quality-operations.md).
