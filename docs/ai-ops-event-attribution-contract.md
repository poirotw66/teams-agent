# AI Operations event identity and usage-attribution contract

Status: Phase 0 implementation boundary, pending query/API wiring.

This document defines the facts produced by
`agent_service.operations.emitter`. It does not make the existing query
service, API request models, or stores claim capabilities they do not yet
have.

## Logical request and immutable event identity

One turn is identified by the tuple:

```text
(tenantId, conversationId, requestId)
```

The emitter derives a deterministic, UUID-shaped `turnId`,
`issueOccurrenceId`, and `eventId` from that tuple and the event's stable
semantic discriminator. The input identifiers are hashed before they become
an event identifier. `correlationId` remains a tracing/join value only: it is
not an idempotency key and may be reused by a client.

Consequences:

- Replaying the same logical request produces the same IDs for the turn,
  issues, route/result events, handoff, each usage call, and the request
  summary.
- A matching request/conversation pair in a different tenant produces a
  disjoint ID set, including `conversation.started`.
- A distinct `requestId` is a new turn, even if a client reuses a
  correlation ID.
- The emitter never substitutes an old payload for a new one. It keeps only
  in-process fingerprints and raises a replay conflict when an already-seen
  logical request changes its message, actor, or workflow facts, or an event
  ID is rebuilt with a changed immutable payload. Stores must add durable
  payload-fingerprint comparison for the equivalent cross-process guarantee.
  An event ID collision with changed immutable content is a producer/data-
  quality fault, not an update operation.

`occurredAt` is taken, in order, from `state.operational_occurred_at`, a user
conversation message matching the correlation ID, or persisted conversation
activity/start time. Missing time is rejected outside `dev`/`test`. The
temporary dev/test compatibility fallback is explicitly non-durable and must
not be used to claim restart-stable replay.

### Required next API/workflow integration

The Agent API must create one UTC `operational_occurred_at` when it accepts a
request, preserve it through retries and hand it to the emitter state. This
is necessary for durable, byte-equivalent replay across processes; the
current `AgentRequest` has no timestamp field.

The feedback API must add a tenant-scoped `feedbackId` (idempotency key) and
an occurred-at timestamp. `FeedbackRequest` currently has neither tenant ID
nor feedback ID, so the emitter derives a safe replay key from the available
feedback fact fields, but cannot prove that two otherwise identical feedback
submissions came from different tenants. No correlation-ID uniqueness is
assumed.

## Text safety at the emitter boundary

All free-text values that the emitter persists pass through the current
versioned `mask_text` policy. This includes user message and issue text,
classifier `normalizedDescription`, answer text, ticket errors, feedback
reason, and citation title/source path. The raw issue description is still
provided to the classifier in memory, but is not written to analytics.

Identifiers and controlled enums (for example route, backend, FAQ key,
document ID, chunk ID, status) are not treated as free prose by this layer.
If an upstream system permits secrets in those identifier fields, that system
must validate them before it calls the emitter.

## Usage records

Every `UsageEventCollector.events()` item emits one `usage.recorded` event
with:

```text
attributionScope = CALL
collectorEventId, collectorTimestamp  # original UsageEvent trace fields
collectorOrdinal  # stable emitter mapping only; not a provider retry attempt
component, provider, model, knowledgeBackend
inputTokens, toolContextTokens, outputTokens, embeddingTokens, totalTokens
llmCallCount, estimatedCostUsd, pricingVersion, usageSource, status, elapsedMs
```

CALL `occurredAt` is the collector's original timestamp, rather than request
completion time. These fields are copied from genuine collector data. The collector currently
does **not** contain an action name, provider attempt number, durable per-call
ID, or per-call issue occurrence. The emitter therefore does not invent any
of those fields or allocate a request's cost over multiple issues.

One additional `usage.recorded` event is emitted with:

```text
attributionScope = REQUEST_SUMMARY
summary = { request-level totals from RequestCostSummary }
perCallReconciliation = { observed comparison only }
```

Summary token/cost fields are deliberately nested. They are not top-level
usage metrics, so legacy cost summation cannot add the request total to the
per-call totals. An unknown call price remains `null`; reconciliation reports
that the comparison is unknown and never upgrades `costComplete`.
`costComplete` is only the value calculated by `RequestCostSummary`, including
the valid zero-call case.

### Required query-adapter integration

Before exposing the new events in Phase 1, the query adapter must:

1. Aggregate provider/model/component token and cost metrics from
   `attributionScope == "CALL"` only.
2. Count cost coverage from CALL records only; it must exclude
   `REQUEST_SUMMARY` from both numerator and denominator.
3. Use the nested `summary` only for request-level drilldown and reconciliation,
   never add it to a CALL aggregate.
4. Surface `null` price as unknown coverage, not USD 0.

For per-issue cost attribution, a later runtime contract must attach a stable
issue occurrence reference (or an explicit, versioned allocation policy) to
each collector record before the emitter runs. The current collector is only
request-scoped, so assigning its calls to every issue would be false.
