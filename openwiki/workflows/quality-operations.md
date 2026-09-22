---
type: workflow
title: Quality and governance operations
description: How a quality case moves from triage to observation, and how an evaluation gate can block a knowledge or FAQ activation.
tags: [quality, evaluation, governance, gates]
sources:
  - id: openwiki-source-7b79dfc8132f204fb40adf18
    resource: repo://agent_service/src/ai_ops_backoffice/evaluation_domain/gate_checks.py
  - id: openwiki-source-52be07291e599ae2dc29a1e8
    resource: repo://agent_service/src/ai_ops_backoffice/evaluation_domain/gate_evaluator.py
  - id: openwiki-source-ed53850e6c355061ab149276
    resource: repo://agent_service/src/ai_ops_backoffice/governance_domain/helpers.py
  - id: openwiki-source-7e0a7daf9aa96937bfd92b87
    resource: repo://agent_service/src/ai_ops_backoffice/quality_domain/case_lifecycle_ops.py
  - id: openwiki-source-62ee4046051a356785a72ea9
    resource: repo://agent_service/src/ai_ops_backoffice/quality_domain/case_ops.py
  - id: openwiki-source-abf55aa4066270e53ad23e4d
    resource: repo://agent_service/src/knowledge_core/release_gate.py
  - id: openwiki-source-f4515829e97820b021f34d4d
    resource: repo://console_frontend/src/features/knowledge/components/DocumentGovernanceActions.tsx
  - id: openwiki-source-8add648ab1337cba4a3734fb
    resource: repo://console_frontend/src/features/knowledge/components/KnowledgeWorkspaceBanner.tsx
  - id: openwiki-source-9112d5f823ae8eb5419e1db2
    resource: repo://console_frontend/src/features/knowledge/pages/ReleasesPage.tsx
generated: { by: "cursor", at: "2026-09-22T17:10:06.227Z" }
verified:
  - by: openwiki/0.5.1
    at: 2026-09-22T17:10:06.227Z
---

# Quality and governance operations

Quality cases and evaluation gates are separate mechanisms. A case tracks an operator's response to a bad answer. A gate decides whether a candidate may become the active knowledge or FAQ target. Closing a case does not publish knowledge. Publishing knowledge does not close a case.

## Quality case lifecycle

Allowed transitions are closed. Any other move is rejected.

```mermaid
stateDiagram-v2
    [*] --> NEW
    NEW --> TRIAGED
    TRIAGED --> IN_PROGRESS
    IN_PROGRESS --> WAITING_REVIEW
    IN_PROGRESS --> OBSERVING
    WAITING_REVIEW --> IN_PROGRESS
    WAITING_REVIEW --> OBSERVING
    OBSERVING --> IN_PROGRESS
    OBSERVING --> RESOLVED
    NEW --> WONT_FIX
    TRIAGED --> WONT_FIX
    IN_PROGRESS --> WONT_FIX
    WAITING_REVIEW --> WONT_FIX
    OBSERVING --> WONT_FIX
    NEW --> DUPLICATE
    TRIAGED --> DUPLICATE
    IN_PROGRESS --> DUPLICATE
    RESOLVED --> [*]
    WONT_FIX --> [*]
    DUPLICATE --> [*]
```

`RESOLVED`, `WONT_FIX`, and `DUPLICATE` are terminal. Candidates can be merged into a case only while they are open. Linking an FAQ from `IN_PROGRESS` or `WAITING_REVIEW` moves the case to `OBSERVING`. Observation metrics are refused unless the case is already `OBSERVING`.

The console is the operator surface. It does not replace the knowledge release path. A knowledge edit still has to go through review and publish before retrieval changes. See [Knowledge release](/openwiki/workflows/knowledge-release.md).

## Knowledge workspace honesty and Sync Now

Console-v2 shows `LOCAL_SANDBOX` versus `CLOUD_FORMAL` workspace banners so operators know whether they are editing a local test workspace or the formal cloud path. Switching workspace does not by itself enable formal publish (see [Identity and access](/openwiki/integrations/identity-and-access.md)).

After a successful publish action, Document governance auto-runs Console Sync Now against the Console-connected Agent (local Playground when the BFF points locally). That is separate from Portal cloud `/admin/reload-knowledge`. Releases page surfaces stuck `RELOAD_FAILED` candidates that never became cloud-active and offers 「重試啟用」 for that Portal compensate path—not the same control as 「立即同步」 for the Console-connected Agent mirror. Lag banners warn 「可能落後雲端」 when cloud / mirrored / loaded diverge.

## Evaluation gate

An activation checker, when wired, evaluates the candidate run against the gate policy before the active pointer moves. Blocking reasons include:

- The run's manifest hash is not the target being activated.
- The set version is not in the policy's required set.
- The run has no summary.
- Coverage is below the policy minimum.
- A zero-tolerance policy has any critical failure.
- Pass rate is below the policy minimum.
- Regressions exceed the policy maximum.

`ENFORCE` fails closed and raises. A missing checker is treated as report-only allow so local unit tests that do not wire the gate service can still run. Do not treat a missing checker as proof that production allows the activation. When the checker is injected, an enforce failure must stop the activation.

## Governance inputs

Prompt and model governance is a different store from the case file. Candidate prompt text and datasets are rejected if they contain secret material or injection markers. Production model credentials stay secret references, not copied values. A governance change that is not activated through the release gate does not by itself change what the agent answers.

Related: [Verification](/openwiki/testing/verification.md), [Local GCS knowledge sync](/openwiki/workflows/local-gcs-knowledge-sync.md), [Cloud deployment](/openwiki/operations/cloud-deployment.md).
