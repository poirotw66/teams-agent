# AI Ops Backoffice FAQ Domain handoff

This handoff covers only the isolated Phase 2 FAQ governance domain. It is not a claim that Phase 2, its API, UI, runtime integration, Quality Case flow, examples dataset, Sync Job, budget policy, or alerts are complete.

## Delivered boundary

`agent_service/src/ai_ops_backoffice/faq_domain/` provides a dependency-injected application domain with no endpoint, UI, settings, or existing runtime changes.

- Stable `faq_id` and globally unique, immutable `faq_key`.
- Immutable FAQ content versions, with `DRAFT`, `IN_REVIEW`, `CHANGES_REQUESTED`, `APPROVED`, `ACTIVE`, `DISABLED`, and `SUPERSEDED` lifecycle metadata.
- New content is a new version. Published answer text is not edited in place.
- Active FAQ pointer switches atomically with the version lifecycle update. Rollback only accepts a previously approved superseded version, and writes `FAQ_ROLLED_BACK` audit.
- Activation, disable, rollback, review and all state writes include an audit event in the same repository commit.
- Etag compare-and-swap prevents stale writes; idempotency keys replay an identical result and reject a changed request.
- Submission requires both a positive and a negative test; group-scoped FAQs additionally require a positive audience test. Issue types must be accepted by an injected active-taxonomy authority.
- `active_snapshot()` is the runtime read contract: it returns only an `ACTIVE` immutable release with a matching audience. Its `answer` is exactly stored content; it has no model or answer-rewrite hook.

## Persistence and atomicity

`InMemoryFaqRepository` is test-only. `FileFaqRepository(path)` is suitable for a single-host local/Poc deployment: it reloads persisted state per operation, uses an advisory OS writer lock, and writes a full state-plus-audit replacement through `os.replace`. A failed replacement does not expose a successful state transition from that commit.

`FirestoreFaqRepository(client)` accepts an injected Firestore-style client, so construction does not use ADC or perform cloud I/O. Its command transaction reads the FAQ/key/idempotency records then writes the FAQ, versions, tests, active pointer, audit, and idempotency response in one Firestore transaction. In a production Firestore adapter, transaction retry/conflict handling must be verified against the installed `google-cloud-firestore` version and Firestore security rules.

This uses transactional co-write, not a best-effort after-the-fact audit. The domain's `FaqAuditEvent` collection is the authoritative, atomic audit record; it is not an outbox. `FaqAuditDeliveryPort` specifies the separate host-owned relay into the Phase 0 global `AuditStore`. That relay must use `audit_id` for idempotency and retry after commit. If a later integration must emit an external operational event (`knowledge.release.activated`), it must add a durable outbox record in the same transaction and run a retrying dispatcher; it must never mark that external event as delivered without such a record.

## Authorization contract

The default authorization adapter reads the existing Phase 0 `ActorContext` capability and owner-unit scope rules. It fails closed. Required capabilities are:

- `ops.faq.write` — create, new draft, test, submit.
- `ops.faq.review` — approve / request changes.
- `ops.faq.activate` — activate and rollback.
- `ops.faq.disable` — emergency disable.

The current global role table only defines `ops.faq.write`; this change deliberately does not alter it. Until the host supplies a governed capability mapping or authorization port implementation for the other three capabilities, those operations reject. A caller cannot bypass this using a boolean flag. Approval also rejects a submitter approving their own version except when the caller records a non-empty POC exception reason.

## Required host-service wiring (not performed here)

1. Construct `FaqDomainService` in the backoffice composition root with `FileFaqRepository` or `FirestoreFaqRepository`; do not use memory outside tests.
2. Adapt the Phase 0 active taxonomy repository to `FaqTaxonomyPort.require_active`; the default rejects all issue types.
3. Supply the approved capability mapping for review/activation/disable without weakening global scope checks. The optional self-approval exception requires an explicit POC-only policy, a non-production environment, and `ops.faq.poc_self_approve`; the default always denies it.
4. Add authenticated API handlers with ETag (`If-Match`) and idempotency-key transport; map domain errors to safe HTTP responses. The existing `phase2_registry.py` and API scaffold must be replaced by a separately reviewed integration change, not dual-written.
5. Make the Agent runtime consume only `FaqRuntimeSnapshot`, resolve audience groups from the trusted ACL source, and emit attribution with `faqId` and `versionId`. Add the durable operational-event outbox described above.
6. Before production Firestore enablement, validate Firestore transactions, document/index limits, IAM/security rules, backup/TTL retention, observability, and transaction retry behavior using an isolated non-production project. Real Firestore was not contacted or verified by this delivery.

`faq_key` renames are intentionally rejected pending a mapping-compatibility adapter for Prompt/Issue references required by the Phase 2 spec. This makes an unsafe rename impossible instead of silently breaking downstream mappings.

Free-text FAQ fields reject credential-like material using the existing Phase 0 masking policy. Test utterances are persisted only after that policy masks them and record its policy version; a future conversation-to-test adapter must also set `source_type="CONVERSATION"` and a permitted correlation reference, never raw transcript text.
