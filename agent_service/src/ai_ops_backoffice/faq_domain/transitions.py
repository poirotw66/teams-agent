"""Persistence, validation, and draft helpers for governed FAQ mutations."""

from __future__ import annotations

import uuid
from typing import Any

from operations_core.access import ActorContext
from operations_core.masking import MASKING_POLICY_VERSION, mask_text

from .authorization import FaqSelfApprovalExceptionPort, FaqTaxonomyPort
from .errors import (
    FaqAuthorizationError,
    FaqNotFoundError,
    FaqTransitionError,
    FaqValidationError,
)
from .models import (
    FaqAuditEvent,
    FaqContent,
    FaqRecord,
    FaqTestCase,
    FaqVersion,
    utc_now,
)
from .repository import FaqCommit, FaqRepository, fingerprint

__all__ = [
    "ACTIVATE",
    "DISABLE",
    "READ",
    "REVIEW",
    "WRITE",
    "build_audit_event",
    "build_edit_draft",
    "build_faq_result",
    "build_faq_test_case",
    "build_review_version",
    "collect_release_owner_unit_ids",
    "command_fingerprint",
    "commit_transition",
    "enforce_distinct_approver",
    "ensure_draft_accepts_test",
    "ensure_review_allowed",
    "replace_model",
    "replay_capability",
    "require_faq_version",
    "validate_faq_content",
    "validate_faq_submission",
]

READ = "ops.faq.read"
WRITE = "ops.faq.write"
REVIEW = "ops.faq.review"
ACTIVATE = "ops.faq.activate"
DISABLE = "ops.faq.disable"

_REPLAY_CAPABILITIES = {
    "FAQ_APPROVED": REVIEW,
    "FAQ_CHANGES_REQUESTED": REVIEW,
    "FAQ_ACTIVATED": ACTIVATE,
    "FAQ_ROLLED_BACK": ACTIVATE,
    "FAQ_DISABLED": DISABLE,
}


def replace_model(model: Any, **changes: Any) -> Any:
    return type(model).model_validate({**model.model_dump(), **changes})


def build_faq_result(faq: FaqRecord, version: FaqVersion) -> dict[str, Any]:
    return {"faq": faq.model_dump(mode="json"), "version": version.model_dump(mode="json")}


def command_fingerprint(actor: ActorContext, payload: dict[str, Any]) -> str:
    return fingerprint({"actorId": actor.user_id, **payload})


def replay_capability(action: str) -> str:
    return _REPLAY_CAPABILITIES.get(action, WRITE)


def require_faq_version(
    repository: FaqRepository, faq_id: str, version_id: str
) -> tuple[FaqRecord, FaqVersion]:
    faq, version = repository.get_faq(faq_id), repository.get_version(version_id)
    if faq is None or version is None or version.faq_id != faq_id:
        raise FaqNotFoundError(f"FAQ/version not found: {faq_id}/{version_id}")
    return faq, version


def collect_release_owner_unit_ids(
    repository: FaqRepository, faq: FaqRecord, target: FaqVersion
) -> set[str]:
    """Historical versions cannot bypass the current owner's scope."""
    owners = {target.content.owner_unit_id}
    for version_id in (faq.draft_version_id, faq.published_version_id):
        if not version_id:
            continue
        version = repository.get_version(version_id)
        if version is None:
            raise FaqNotFoundError(version_id)
        owners.add(version.content.owner_unit_id)
    return owners


def validate_faq_content(taxonomy: FaqTaxonomyPort, content: FaqContent) -> None:
    for issue_type_id in content.issue_type_ids:
        taxonomy.require_active(issue_type_id)
    for label, value in (
        ("question", content.question),
        ("answer", content.answer),
        ("category", content.category),
        ("business_contact", content.business_contact),
        ("owner_unit_id", content.owner_unit_id),
        *[("keyword", item) for item in content.keywords],
    ):
        if mask_text(value).contains_credential:
            raise FaqValidationError(
                f"{label} contains credential-like content and cannot be persisted"
            )


def validate_faq_submission(
    taxonomy: FaqTaxonomyPort,
    version: FaqVersion,
    tests: tuple[FaqTestCase, ...] | list[FaqTestCase],
) -> None:
    validate_faq_content(taxonomy, version.content)
    kinds = {item.kind for item in tests}
    if {"POSITIVE", "NEGATIVE"} - kinds:
        raise FaqValidationError("submit requires at least one POSITIVE and one NEGATIVE test")
    positive_text = {item.utterance.casefold().strip() for item in tests if item.kind == "POSITIVE"}
    negative_text = {item.utterance.casefold().strip() for item in tests if item.kind == "NEGATIVE"}
    if positive_text & negative_text:
        raise FaqValidationError("the same utterance cannot be both a positive and a negative test")
    if any(
        not item.utterance.strip() or item.utterance == "[REDACTED_CREDENTIAL]" for item in tests
    ):
        raise FaqValidationError("tests must contain usable masked utterances")
    if version.content.audience_type != "GROUPS":
        return
    positive_groups = {
        group
        for item in tests
        if item.kind == "POSITIVE"
        for group in item.expected_audience_group_ids
    }
    if not set(version.content.audience_group_ids).intersection(positive_groups):
        raise FaqValidationError("GROUPS audience requires a positive audience test")
    if any(
        item.kind == "POSITIVE"
        and not set(version.content.audience_group_ids).intersection(
            item.expected_audience_group_ids
        )
        for item in tests
    ):
        raise FaqValidationError("positive test audience must be allowed by the version")


def build_faq_test_case(
    *,
    faq_id: str,
    version_id: str,
    kind: str,
    utterance: str,
    expected_audience_group_ids: tuple[str, ...],
    actor: ActorContext,
    source_type: str,
    source_correlation_id: str | None,
) -> FaqTestCase:
    return FaqTestCase(
        test_case_id=str(uuid.uuid4()),
        faq_id=faq_id,
        version_id=version_id,
        kind=kind,
        utterance=utterance,
        expected_audience_group_ids=expected_audience_group_ids,
        expected_match=kind == "POSITIVE",
        created_by=actor.user_id,
        created_at=utc_now(),
        source_type=source_type,
        source_correlation_id=source_correlation_id,
        masking_policy_version=MASKING_POLICY_VERSION,
    )


def build_edit_draft(
    repository: FaqRepository,
    *,
    faq: FaqRecord,
    content: FaqContent,
    actor: ActorContext,
) -> tuple[FaqRecord, tuple[FaqVersion, ...], str]:
    current_versions = repository.list_versions(faq.faq_id)
    now = utc_now()
    draft = FaqVersion(
        version_id=str(uuid.uuid4()),
        faq_id=faq.faq_id,
        version_number=max((item.version_number for item in current_versions), default=0) + 1,
        content=content,
        created_by=actor.user_id,
        created_at=now,
    )
    changed: list[FaqVersion] = [draft]
    if faq.draft_version_id:
        prior = repository.get_version(faq.draft_version_id)
        if prior and prior.status == "IN_REVIEW":
            raise FaqTransitionError("request changes before revising an IN_REVIEW draft")
        if prior and prior.status in {"DRAFT", "CHANGES_REQUESTED", "APPROVED"}:
            changed.append(replace_model(prior, status="SUPERSEDED"))
    next_faq = replace_model(
        faq,
        status=faq.status if faq.published_version_id else "DRAFT",
        draft_version_id=draft.version_id,
        updated_by=actor.user_id,
        updated_at=now,
        etag=faq.etag + 1,
    )
    return next_faq, tuple(changed), draft.version_id


def build_review_version(
    version: FaqVersion,
    *,
    approve: bool,
    reason: str,
    actor: ActorContext,
    poc_exception_reason: str | None,
) -> tuple[FaqVersion, str]:
    """Return the next version and FAQ status when no published version exists."""
    now = utc_now()
    if approve:
        next_version = replace_model(
            version,
            status="APPROVED",
            reviewed_by=actor.user_id,
            reviewed_at=now,
            review_reason=reason,
            approved_by=actor.user_id,
            approved_at=now,
            self_approval_exception=actor.user_id == version.submitted_by,
            self_approval_exception_reason=(
                poc_exception_reason if actor.user_id == version.submitted_by else None
            ),
        )
        return next_version, "APPROVED"
    next_version = replace_model(
        version,
        status="CHANGES_REQUESTED",
        reviewed_by=actor.user_id,
        reviewed_at=now,
        review_reason=reason,
    )
    return next_version, "CHANGES_REQUESTED"


def ensure_review_allowed(
    *, faq: FaqRecord, version: FaqVersion, version_id: str, reason: str
) -> None:
    if faq.draft_version_id != version_id:
        raise FaqTransitionError("review must target the current draft")
    if version.status != "IN_REVIEW":
        raise FaqTransitionError("only IN_REVIEW versions can be reviewed")
    if not reason.strip():
        raise FaqValidationError("review reason is required")


def enforce_distinct_approver(
    *,
    version: FaqVersion,
    actor: ActorContext,
    poc_exception_reason: str | None,
    self_approval_exception: FaqSelfApprovalExceptionPort,
) -> None:
    if actor.user_id != version.submitted_by:
        return
    if not poc_exception_reason:
        raise FaqAuthorizationError("submitter and approver must be different")
    self_approval_exception.require(
        actor=actor,
        owner_unit_id=version.content.owner_unit_id,
        reason=poc_exception_reason,
    )


def ensure_draft_accepts_test(*, faq: FaqRecord, version: FaqVersion, version_id: str) -> None:
    if faq.draft_version_id != version_id:
        raise FaqTransitionError("test cases must belong to the current draft")
    if version.status not in {"DRAFT", "CHANGES_REQUESTED"}:
        raise FaqTransitionError("tests can only be added to DRAFT or CHANGES_REQUESTED versions")


def build_audit_event(
    *,
    action: str,
    actor: ActorContext,
    faq_id: str,
    version_id: str | None,
    reason: str | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    correlation_id: str | None,
) -> FaqAuditEvent:
    return FaqAuditEvent(
        audit_id=str(uuid.uuid4()),
        action=action,
        actor_id=actor.user_id,
        actor_role=actor.role,
        faq_id=faq_id,
        version_id=version_id,
        reason=reason,
        before=before,
        after=after,
        occurred_at=utc_now(),
        correlation_id=correlation_id,
    )


def commit_transition(
    repository: FaqRepository,
    *,
    action: str,
    before_faq: FaqRecord,
    after_faq: FaqRecord,
    versions: tuple[FaqVersion, ...],
    actor: ActorContext,
    expected_etag: int,
    idempotency_key: str | None,
    correlation_id: str | None,
    reason: str | None,
    active_pointer: tuple[str, str | None] | None = None,
    primary_version_id: str | None = None,
    request_fingerprint: str = "",
) -> dict[str, Any]:
    primary = next(
        item for item in versions if item.version_id == (primary_version_id or item.version_id)
    )
    result = build_faq_result(after_faq, primary)
    audit = build_audit_event(
        action=action,
        actor=actor,
        faq_id=after_faq.faq_id,
        version_id=primary.version_id,
        reason=reason,
        before={
            "status": before_faq.status,
            "etag": before_faq.etag,
            "publishedVersionId": before_faq.published_version_id,
            "draftVersionId": before_faq.draft_version_id,
        },
        after={
            "status": after_faq.status,
            "etag": after_faq.etag,
            "publishedVersionId": after_faq.published_version_id,
            "draftVersionId": after_faq.draft_version_id,
            "versionStatus": primary.status,
            "approvedBy": primary.approved_by,
            "approvedAt": primary.approved_at.isoformat() if primary.approved_at else None,
            "selfApprovalException": primary.self_approval_exception,
        },
        correlation_id=correlation_id,
    )
    return repository.commit(
        FaqCommit(
            faq=after_faq,
            versions=versions,
            tests=(),
            audit=audit,
            expected_etag=expected_etag,
            idempotency_key=idempotency_key,
            action=action,
            request_fingerprint=request_fingerprint,
            result=result,
            active_pointer=active_pointer,
        )
    )
