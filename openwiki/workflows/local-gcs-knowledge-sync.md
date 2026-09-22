---
type: workflow
title: Local GCS knowledge sync
description: Unidirectional cloud-to-local QA artifact mirroring for Agent Playground, selection modes, status honesty, and Console Sync Now versus Portal activate reload.
tags: [knowledge, gcs, sync, playground]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-22T17:10:06.227Z
sources:
  - id: openwiki-source-cdfb3ef715285bf9d0520099
    resource: repo://agent_service/src/agent_service/knowledge_release_cache.py
  - id: openwiki-source-16ddc0709266832daba50e28
    resource: repo://agent_service/src/agent_service/knowledge_release_sync.py
  - id: openwiki-source-974b4c6fbe65da3e660e8e21
    resource: repo://agent_service/src/ai_ops_backoffice/routers/agent_knowledge_sync_routes.py
  - id: openwiki-source-1f192893fd4de715c2b39e62
    resource: repo://console_frontend/src/features/knowledge/components/KnowledgeSyncLagBanner.tsx
  - id: openwiki-source-9eda5df0c20498bd515f5e70
    resource: repo://console_frontend/src/features/knowledge/lib/syncLocalKnowledgeMirror.ts
generated: { by: "cursor", at: "2026-09-22T17:10:06.227Z" }
---

# Local GCS knowledge sync

When `KNOWLEDGE_RELEASE_STORE_MODE=GCS`, cloud Firestore + GCS remain the formal control plane. Local Agent Service pulls a verified QA snapshot into a cache directory and answers Playground chat from that snapshot only. Sync is unidirectional. Local sandbox edits do not write back to cloud. Sync is never on the Playground request path.

## Cache layout

Canonical mirrors live under:

```text
<KNOWLEDGE_RELEASE_CACHE_DIR>/tenants/<tenantId>/releases/<releaseId>/
```

Default cache root is `RAG_DATA_DIR/knowledge_cache`. Only the syncer manages that tree. Local drafts and sandbox releases stay under `KNOWLEDGE_RELEASE_DIR` (`data/releases`), never inside the mirror. A verified mirror carries `manifest.json` and `.qa_snapshot_verified`. Legacy `<cache>/<releaseId>/` remains readable during transition.

## Selection modes

| Mode | Behavior |
| --- | --- |
| `FOLLOW_CLOUD` (GCS default when no pin) | Mirror cloud active release; after a complete QA inventory verify, may hot-switch loaded release. |
| `PINNED` | May download newer mirrors, but loaded release stays on `KNOWLEDGE_ACTIVE_RELEASE_ID`. |
| `LOCAL_SANDBOX` | Syncer does not claim cloud alignment; Agent uses local sandbox/FILE releases. |

`sync_now` / background polling acquire a per-tenant file lock, read the Firestore active pointer, download missing inventory objects at fixed generations, verify size/SHA-256, then atomically promote the mirror. Failures keep the last verified snapshot usable for testing and mark status `FAILED` or `behindCloud`. There is no silent fallback to bundled JSON or unverified FILE trees. Without any verified snapshot, knowledge Q&A fail-closes.

## Three-column honesty

Status APIs expose `cloudActiveReleaseId`, `mirroredReleaseId`, and `loadedReleaseId` separately, plus `selectionMode`, `syncState`, `qaSnapshotComplete` / `runtimeInventoryComplete`, `indexOnlyMirror`, `behindCloud`, and `alignedWithCloud` / `matchesCloudProduction`. Alignment is true only for `FOLLOW_CLOUD` when all three IDs match, inventory is complete, and sync is `IN_SYNC`. Index-only legacy mirrors must not be advertised as aligned with cloud production.

## Console Sync Now versus Portal reload

After Console publish, Portal activate notifies the **cloud** Agent via `/admin/reload-knowledge` (which syncs-before-reload under GCS). That does not update every local laptop Agent.

Console-v2 "立即同步" (`syncLocalKnowledgeMirror`) POSTs `/api/agent/knowledge-sync` through Backoffice (`ops.sync.write`) to whatever Agent `AGENT_API_URL` points at—typically the local Playground Agent when Console is local. Toast copy distinguishes aligned, still-behind, and Agent-unreachable (503) outcomes and never claims Playground updated when the Agent cannot be reached. `KnowledgeSyncLagBanner` shows 「可能落後雲端」 whenever the three columns diverge or the QA snapshot is incomplete.

Related: [Knowledge release](/openwiki/workflows/knowledge-release.md), [Local runtime](/openwiki/operations/local-runtime.md), [Retrieval backends](/openwiki/workflows/retrieval.md), [Verification](/openwiki/testing/verification.md).
