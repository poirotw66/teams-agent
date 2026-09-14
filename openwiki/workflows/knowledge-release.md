---
type: workflow
title: Knowledge release
description: How a knowledge document moves from review to an approved publish, and how the agent reloads that release without a portal browser entry.
tags: [knowledge, publish, review, release]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-14T06:27:21.319Z
sources:
  - id: openwiki-source-eefa67e7a7b9e61180b523fa
    resource: repo://agent_service/src/agent_service/deps.py
  - id: openwiki-source-2b57350b87bee282f22fe17e
    resource: repo://agent_service/src/ai_ops_backoffice/knowledge_bridge/delegation.py
  - id: openwiki-source-ac85e9adaa9af1de47286c9a
    resource: repo://agent_service/src/knowledge_portal/publisher.py
  - id: openwiki-source-b917448709307c2df36ffc71
    resource: repo://agent_service/src/knowledge_portal/services/release_service.py
  - id: openwiki-source-8470205e385c544b25585ce2
    resource: repo://agent_service/src/knowledge_portal/services/review_service.py
generated: { by: "cursor", at: "2026-09-14T06:27:21.319Z" }
---

# Knowledge release

Operators do not publish by opening the Knowledge Portal. The AI Ops Console on port 8092 is the product entry. Its knowledge bridge signs a delegation envelope and calls the portal on loopback. The portal remains the owner of draft, review, and release records.

## Review before publish

A review decision is single-use. A decided review cannot be decided again. The reviewer must be allowed to review, must not be the submitter unless the workflow is relaxed or the actor is `PLATFORM`, and must be able to see the document.

| Decision | Version status | Document status |
| --- | --- | --- |
| `APPROVED` | `APPROVED` | `APPROVED` |
| `CHANGES_REQUESTED` | `CHANGES_REQUESTED` | `CHANGES_REQUESTED` |
| otherwise | `REJECTED` | `DRAFT` |

Approval is not publication. Retrieval still sees the previously active release until publish builds a new one.

## Publish

`publish_version` requires a publish role (`MANAGER` or `PLATFORM`). The version must belong to the document and must already be `APPROVED`. When dual approval is required, the version creator cannot publish their own approved content unless they are `PLATFORM`. An idempotency key returns the cached release instead of building a second one.

Publish holds a coordination lock, collects the other active published versions, appends this version as `PUBLISHED`, and activates one release artifact. The artifact directory contains the published sources and `index/chunks.json`. The document then records `current_published_version_id` and clears `draft_version_id`. If activation does not produce a release, publish fails and does not pretend the version is live.

## What the agent reads

Agent Service does not poll the portal on a timer for this path. `sync_knowledge_to_active_pointer` runs on chat and readiness. It reads the active release id under the release directory (`data/releases` by default). If the id is unchanged, it does nothing. If the id moved and `index/chunks.json` exists, it loads a new hybrid index, swaps the `HYBRID` backend, and marks the index source as `portal_release`. A missing index is a warning and leaves the previous index in place.

`KNOWLEDGE_RELEASE_MODE` is `AUTO`, `PORTAL`, or `BUNDLED`. `AUTO` is the default and is what lets a local or deployed agent follow the pointer. A bundled index is the fallback when no portal release is active.

Related: [Retrieval backends](/openwiki/workflows/retrieval.md), [Identity and access](/openwiki/integrations/identity-and-access.md), [Quality and governance operations](/openwiki/workflows/quality-operations.md).
