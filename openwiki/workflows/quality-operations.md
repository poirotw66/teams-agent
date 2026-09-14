---
type: workflow
title: Quality and governance operations
description: How a quality case moves from triage to observation, and how an evaluation gate can block a knowledge or FAQ activation.
tags: [quality, evaluation, governance, gates]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-14T06:27:21.319Z
sources:
  - id: openwiki-source-1b16db647140da3b1a590f74
    resource: repo://agent_service/src/agent_service/release_gate.py
  - id: openwiki-source-52be07291e599ae2dc29a1e8
    resource: repo://agent_service/src/ai_ops_backoffice/evaluation_domain/gate_evaluator.py
  - id: openwiki-source-d98846c5e7f8177afe1c1e46
    resource: repo://agent_service/src/ai_ops_backoffice/governance_domain/service_helpers.py
  - id: openwiki-source-2dc54d4cd70b0c353e4ad6bd
    resource: repo://agent_service/src/ai_ops_backoffice/quality_domain/service.py
generated: { by: "cursor", at: "2026-09-14T06:27:21.319Z" }
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

Related: [Verification](/openwiki/testing/verification.md), [Cloud deployment](/openwiki/operations/cloud-deployment.md).
