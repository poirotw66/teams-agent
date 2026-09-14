---
type: testing
title: Verification
description: Which test suites prove adapter contracts, workflow behavior, and operations, and which acceptance items are still limited.
tags: [testing, pytest, acceptance]
verified:
  - by: openwiki/0.5.1
    at: 2026-09-14T06:27:21.319Z
sources:
  - id: openwiki-source-0b7d65780d34f9b0269721d3
    resource: repo://agent_service/pyproject.toml
  - id: openwiki-source-16b509124e9048804b230e6e
    resource: repo://docs/poc-acceptance-checklist.md
  - id: openwiki-source-05ccef8d4cf1698187f20464
    resource: repo://pyproject.toml
  - id: openwiki-source-6d1605c4670fb5d84ade6405
    resource: repo://tests/test_agent_gateway.py
generated: { by: "cursor", at: "2026-09-14T06:27:21.319Z" }
---

# Verification

There are two pytest projects. They do not share a root config. Run the one that owns the change, then the other if the change crosses the adapter boundary.

```bash
cd agent_service && .venv/bin/python -m pytest tests -q
cd .. && .venv/bin/python -m pytest tests -q
```

Adapter tests live in `tests/` and use the root `pyproject.toml`. Agent, portal, and backoffice tests live in `agent_service/tests/` and use `agent_service/pyproject.toml` (`asyncio_mode = auto`). Ruff is the linter in both packages. Firestore and BigQuery clients are optional extras. Unit tests should keep using fakes so a default `uv sync` can run them.

## Adapter contracts

`tests/test_agent_gateway.py` is the boundary between the adapter and Agent Service. Echo mode must not call the transport. API mode must send the chat contract with either a bearer service token or a Google identity token. Timeouts become gateway errors. Streaming yields stages and then one response, and refuses when streaming is disabled or the adapter is in echo mode. `tests/test_server.py` covers the messaging endpoint and readiness. A gateway change that is not represented here will still look fine in a local `start.sh` run that stubs the agent.

## Workflow acceptance

`docs/poc-acceptance-checklist.md` maps spec §19 items to named tests in `agent_service/tests/test_integration_acceptance.py` (`test_acceptance_<NN>_<slug>`). Use that map when a behavior change should stay tied to an acceptance item. The counts recorded in the checklist are a dated snapshot, not a live gate. Re-run pytest rather than treating those numbers as current.

Invariants those tests pin, and that a wiki reader should not regress:

- At most three issues per turn. Extra issues ask the user to prioritize.
- An FAQ hit returns the fixed answer and does not call the model to rewrite it.
- Follow-up asks at most two questions.
- A ready issue searches knowledge. The answer stays inside retrieved content and cites sources. Missing knowledge does not invent an answer.
- A ticket is not created until explicit confirmation. HTTP ticket calls are tested, but production ticket mode is disabled and no real ticket system is connected.
- Users can query only their own tickets.
- Every request carries a correlation id that is not regenerated between nodes.

## What a green unit run does not prove

A passing pytest run does not prove Cloud Run IAM, Secret Manager bindings, or Teams sideload. Those stay in `deploy/README.md` smoke checks: agent `/readyz`, adapter invoker IAM, and a Teams end-to-end message. Local `start.sh` readiness is process liveness plus index load. It is not the acceptance suite.

Related: [Issue resolution workflow](/openwiki/workflows/issue-resolution.md), [Local runtime](/openwiki/operations/local-runtime.md), [Quality and governance operations](/openwiki/workflows/quality-operations.md).
