# AI Ops Privacy Boundary Review

## Scope and finding

This review covers the Phase 0 operational-event ingestion and audit-write boundaries only. It does not certify the whole Phase 0 programme, transcript storage, query authorization, application logs, Terraform, retention jobs, or every producer of operational events.

The reviewed failure modes were real persistence bypasses:

| Boundary | Previous gap | Scoped remediation |
| --- | --- | --- |
| `redact_secrets` | Recursed through dictionaries but not lists or tuples. | Recurses through dictionaries, lists, and tuples; strings are cleaned at every depth. |
| Audit | `reason` was saved verbatim. | `reason`, `before`, and `after` now share the credential policy. |
| Ingestion | Arbitrary emitter payloads could reach the store unchanged. | Every `OperationalEvent.payload` is defensively cleaned immediately before append. |
| `reveal=True` | It returned all text before checking for credentials. | It may reveal authorized PII, but never a credential detected by the policy. |

## Persistence policy implemented

`agent_service.operations.masking.redact_secrets` is the structured-data policy used at the Audit and operational persistence boundaries.

- Explicit credential field aliases are redacted case-insensitively after normalizing separators and casing. Coverage includes password, API key, secret, token variants, credential, OTP, verification code, client secret, private key, and the supported Chinese aliases.
- Values under explicit credential fields are replaced by `[REDACTED_CREDENTIAL]` without preserving any part of the original value. Keys remain, so an Audit record can still explain which field changed without storing its credential.
- Free-text strings pass through `mask_text`. Explicit credential values are removed for assignment and natural-language forms such as `password=...`, `password is ...`, `我的密碼是 ...`, `OTP 123456`, `驗證碼為 123456`, JSON-style `{"password":"..."}`, `api key: ...`, and `Bearer ...`. The entire string becomes `[REDACTED_CREDENTIAL]`; email, phone, and employee-ID masking otherwise remains unchanged. This intentionally preserves support text and no-value questions such as “密碼未鎖定”, “password reset”, and “我的密碼是什麼？”.
- Nested dictionaries, lists, and tuples are processed consistently. Other scalar values remain unchanged.
- Whitespace-delimited `password` / `passwd` values are also detected when quoted or when the next token contains a digit or underscore (for example `password SENSITIVE_MARKER`). Ordinary instructions such as `password reset` and `password recovery steps` remain readable.
- Token usage metric aliases (`totalTokens`, `inputTokens`, `outputTokens`, `toolContextTokens`, `cachedInputTokens`, `reasoningTokens`, and related count fields) are deliberately excluded from credential-field detection so numeric cost and usage analytics retain their values and types. A value supplied as a string still passes through free-text cleaning; a metric-shaped field is not permission to persist `password=...`.
- Structured metadata identifiers (`model`, `provider`, `pricingVersion`, `usageSource`, `sourceId`, and the documented attribution/classification identifiers) are not free text. Their values are retained so valid configuration and provenance strings such as `max_tokens` and `tokenized-source-42` do not become false positives. An explicit credential assignment within one is still redacted.
- Cleaning is stable: applying the function again produces the same result. This lets ingestion retain store idempotency when an event is retried.
- The policy is now `v2`. Ingestion writes the persisted event envelope and payload `maskingPolicyVersion` as `v2`, because this boundary actually applied v2 cleaning. If the input envelope or legacy payload declares an older policy, ingestion records that source as `sourceMaskingPolicyVersion` in the newly persisted payload. This is replay provenance only: existing stored records are not mutated and this change does not claim a backfill.

Audit actor and target identifiers are not treated as arbitrary free text because they are required to attribute an action. Callers must continue to put credentials only in structured change values or free-text fields governed by this policy, never in identifier fields.

## Focused verification and remaining producer finding

The privacy, emitter replay, operations Phase 0, backoffice, and operations integration selection currently reports **70 passed, 1 failed**; lint passes for the changed Python files. The remaining failure is `test_turn_replay_has_stable_ids_timestamps_and_payloads_without_secret_leaks`: emitter `_result_events` derives `documentId` from the original citation URL before cleaning it. A synthetic `?token=SENSITIVE_MARKER` becomes `doc-token-SENSITIVE_MARKER` and is copied into citation and retrieval payloads. These events are tested before ingestion. This requires a producer-side fix by the emitter owner; masking arbitrary document IDs would damage attribution and would not repair this pre-ingestion path. The emitter file was not changed by this privacy work.

## Deliberate limits

This is deterministic, policy-based detection, not credential discovery. Unlabelled secrets and unquoted alphabetic values after a bare `password` can remain undetected. Examples or instructional placeholders with assignment syntax or a value-shaped token (such as `password reset_step`) can still be false positives. Explicit credential fields and detected free text are irreversibly removed; a credential placed in a semantically misleading identifier field still requires separate controls. Source producers, logs, transcript stores, query/export controls, retention, and authorization need their own Phase 0 controls and review.
