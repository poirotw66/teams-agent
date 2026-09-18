"""Publish, review, and release-gate helpers for governed FAQ lifecycle."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from knowledge_core.release_gate import ReleaseGateBlockedError, require_release_gate
from knowledge_core.target_manifest import faq_version_target_manifest_hash
from operations_core.access import ActorContext

from .artifacts import write_faq_activation_artifact
from .authorization import FaqSelfApprovalExceptionPort
from .errors import FaqNotFoundError, FaqTransitionError, FaqValidationError
from .models import FaqRecord, FaqVersion, utc_now
from .repository import FaqRepository
from .transitions import (
    ACTIVATE,
    DISABLE,
    REVIEW,
    WRITE,
    build_review_version,
    enforce_distinct_approver,
    ensure_review_allowed,
    replace_model,
)

__all__ = [
    "FaqPublishOpsMixin",
    "build_activated_faq",
    "build_activated_versions",
    "build_disabled_faq",
    "build_disabled_version",
    "enforce_release_gate",
    "ensure_activation_allowed",
    "ensure_disable_allowed",
    "write_activation_artifact",
]


class _FaqPublishHost(Protocol):
    _repository: FaqRepository
    _release_gate_checker: Any | None
    _artifact_dir: Path | None
    _self_approval_exception: FaqSelfApprovalExceptionPort

    def _authorize(self, actor: ActorContext, capability: str, owner_unit_id: str) -> None: ...

    def _authorize_release(
        self, actor: ActorContext, capability: str, faq: FaqRecord, target: FaqVersion
    ) -> None: ...

    def _validate_submission(self, version: FaqVersion) -> None: ...

    def _command_fingerprint(self, actor: ActorContext, payload: dict[str, Any]) -> str: ...

    def _replay(
        self, *, actor: ActorContext, key: str | None, action: str, request_fingerprint: str
    ) -> dict[str, Any] | None: ...

    def _require(self, faq_id: str, version_id: str) -> tuple[FaqRecord, FaqVersion]: ...

    def _commit_transition(
        self,
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
    ) -> dict[str, Any]: ...


def ensure_activation_allowed(*, version: FaqVersion, reason: str, rollback: bool) -> None:
    if not reason.strip():
        raise FaqValidationError("activation reason is required")
    if version.status != "APPROVED" and not (
        rollback and version.status in {"SUPERSEDED", "DISABLED"} and version.approved_by
    ):
        raise FaqTransitionError(
            "activation requires an APPROVED version; "
            "rollback requires a previously approved SUPERSEDED version"
        )


def ensure_disable_allowed(*, version: FaqVersion, reason: str) -> None:
    if version.status != "ACTIVE":
        raise FaqTransitionError("only ACTIVE versions can be disabled")
    if not reason.strip():
        raise FaqValidationError("disable reason is required")


def enforce_release_gate(
    *,
    release_gate_checker: Any | None,
    version: FaqVersion,
    actor: ActorContext,
    faq: FaqRecord,
) -> None:
    try:
        require_release_gate(
            release_gate_checker,
            target_manifest_hash=faq_version_target_manifest_hash(
                faq_version_id=version.version_id
            ),
            target_type="FAQ",
            tenant_id=getattr(actor, "tenant_id", None) or getattr(faq, "tenant_id", None),
        )
    except ReleaseGateBlockedError as exc:
        raise FaqValidationError(str(exc)) from exc


def build_activated_versions(
    repository: FaqRepository, *, faq: FaqRecord, version: FaqVersion, version_id: str
) -> list[FaqVersion]:
    previous_id = repository.get_active_version_id(faq.faq_key)
    changed = [replace_model(version, status="ACTIVE")]
    if previous_id and previous_id != version_id:
        previous = repository.get_version(previous_id)
        if previous:
            changed.append(replace_model(previous, status="SUPERSEDED"))
    return changed


def build_activated_faq(faq: FaqRecord, *, version_id: str, actor: ActorContext) -> FaqRecord:
    now = utc_now()
    return replace_model(
        faq,
        status="ACTIVE",
        draft_version_id=None if faq.draft_version_id == version_id else faq.draft_version_id,
        published_version_id=version_id,
        updated_by=actor.user_id,
        updated_at=now,
        etag=faq.etag + 1,
    )


def build_disabled_version(version: FaqVersion, *, actor: ActorContext, reason: str) -> FaqVersion:
    return replace_model(
        version,
        status="DISABLED",
        disabled_by=actor.user_id,
        disabled_at=utc_now(),
        disabled_reason=reason,
    )


def build_disabled_faq(faq: FaqRecord, *, version: FaqVersion, actor: ActorContext) -> FaqRecord:
    now = utc_now()
    return replace_model(
        faq,
        status="DISABLED",
        published_version_id=version.version_id,
        updated_by=actor.user_id,
        updated_at=now,
        etag=faq.etag + 1,
    )


def write_activation_artifact(artifact_dir: Path | None, result: dict[str, Any]) -> None:
    """Persist a versioned FAQ file export; never indexes into Knowledge RAG."""
    if artifact_dir is None:
        return
    faq = result.get("faq")
    version = result.get("version")
    if not isinstance(faq, dict) or not isinstance(version, dict):
        return
    write_faq_activation_artifact(artifact_dir, faq=faq, version=version)


class FaqPublishOpsMixin:
    """Activate, disable, submit, and review transitions for FaqDomainService."""

    def submit(
        self: _FaqPublishHost,
        *,
        faq_id: str,
        version_id: str,
        actor: ActorContext,
        expected_etag: int,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        request_fingerprint = self._command_fingerprint(
            actor,
            {
                "action": "FAQ_SUBMITTED",
                "faqId": faq_id,
                "versionId": version_id,
                "etag": expected_etag,
            },
        )
        replay = self._replay(
            actor=actor,
            key=idempotency_key,
            action="FAQ_SUBMITTED",
            request_fingerprint=request_fingerprint,
        )
        if replay is not None:
            return replay
        faq, version = self._require(faq_id, version_id)
        self._authorize(actor, WRITE, version.content.owner_unit_id)
        if faq.draft_version_id != version_id:
            raise FaqTransitionError("submit must target the current draft")
        if version.status not in {"DRAFT", "CHANGES_REQUESTED"}:
            raise FaqTransitionError("only DRAFT or CHANGES_REQUESTED versions can be submitted")
        self._validate_submission(version)
        now = utc_now()
        next_version = replace_model(
            version, status="IN_REVIEW", submitted_at=now, submitted_by=actor.user_id
        )
        next_faq = replace_model(
            faq,
            status="IN_REVIEW" if faq.published_version_id is None else faq.status,
            updated_by=actor.user_id,
            updated_at=now,
            etag=faq.etag + 1,
        )
        return self._commit_transition(
            "FAQ_SUBMITTED",
            faq,
            next_faq,
            (next_version,),
            actor,
            expected_etag,
            idempotency_key,
            correlation_id,
            None,
            primary_version_id=version_id,
            request_fingerprint=request_fingerprint,
        )

    def review(
        self: _FaqPublishHost,
        *,
        faq_id: str,
        version_id: str,
        approve: bool,
        reason: str,
        actor: ActorContext,
        expected_etag: int,
        poc_exception_reason: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        action = "FAQ_APPROVED" if approve else "FAQ_CHANGES_REQUESTED"
        request_fingerprint = self._command_fingerprint(
            actor,
            {
                "action": action,
                "faqId": faq_id,
                "versionId": version_id,
                "etag": expected_etag,
                "reason": reason,
                "poc": poc_exception_reason,
            },
        )
        replay = self._replay(
            actor=actor,
            key=idempotency_key,
            action=action,
            request_fingerprint=request_fingerprint,
        )
        if replay is not None:
            return replay
        faq, version = self._require(faq_id, version_id)
        self._authorize(actor, REVIEW, version.content.owner_unit_id)
        ensure_review_allowed(faq=faq, version=version, version_id=version_id, reason=reason)
        if approve:
            enforce_distinct_approver(
                version=version,
                actor=actor,
                poc_exception_reason=poc_exception_reason,
                self_approval_exception=self._self_approval_exception,
            )
            self._validate_submission(version)
        next_version, approved_status = build_review_version(
            version,
            approve=approve,
            reason=reason,
            actor=actor,
            poc_exception_reason=poc_exception_reason,
        )
        next_status = approved_status if faq.published_version_id is None else faq.status
        next_faq = replace_model(
            faq,
            status=next_status,
            updated_by=actor.user_id,
            updated_at=utc_now(),
            etag=faq.etag + 1,
        )
        full_reason = (
            reason
            if not poc_exception_reason
            else f"{reason}; POC exception: {poc_exception_reason}"
        )
        return self._commit_transition(
            action,
            faq,
            next_faq,
            (next_version,),
            actor,
            expected_etag,
            idempotency_key,
            correlation_id,
            full_reason,
            primary_version_id=version_id,
            request_fingerprint=request_fingerprint,
        )

    def activate(
        self: _FaqPublishHost,
        *,
        faq_id: str,
        version_id: str,
        actor: ActorContext,
        expected_etag: int,
        reason: str,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        rollback: bool = False,
    ) -> dict[str, Any]:
        action = "FAQ_ROLLED_BACK" if rollback else "FAQ_ACTIVATED"
        request_fingerprint = self._command_fingerprint(
            actor,
            {
                "action": action,
                "faqId": faq_id,
                "versionId": version_id,
                "etag": expected_etag,
                "reason": reason,
            },
        )
        replay = self._replay(
            actor=actor,
            key=idempotency_key,
            action=action,
            request_fingerprint=request_fingerprint,
        )
        if replay is not None:
            return replay
        faq, version = self._require(faq_id, version_id)
        self._authorize_release(actor, ACTIVATE, faq, version)
        ensure_activation_allowed(version=version, reason=reason, rollback=rollback)
        self._validate_submission(version)
        enforce_release_gate(
            release_gate_checker=self._release_gate_checker,
            version=version,
            actor=actor,
            faq=faq,
        )
        changed = build_activated_versions(
            self._repository, faq=faq, version=version, version_id=version_id
        )
        next_faq = build_activated_faq(faq, version_id=version_id, actor=actor)
        result = self._commit_transition(
            action,
            faq,
            next_faq,
            tuple(changed),
            actor,
            expected_etag,
            idempotency_key,
            correlation_id,
            reason,
            active_pointer=(faq.faq_key, version_id),
            primary_version_id=version_id,
            request_fingerprint=request_fingerprint,
        )
        write_activation_artifact(self._artifact_dir, result)
        return result

    def disable(
        self: _FaqPublishHost,
        *,
        faq_id: str,
        actor: ActorContext,
        expected_etag: int,
        reason: str,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        request_fingerprint = self._command_fingerprint(
            actor,
            {
                "action": "FAQ_DISABLED",
                "faqId": faq_id,
                "etag": expected_etag,
                "reason": reason,
            },
        )
        replay = self._replay(
            actor=actor,
            key=idempotency_key,
            action="FAQ_DISABLED",
            request_fingerprint=request_fingerprint,
        )
        if replay is not None:
            return replay
        faq = self._repository.get_faq(faq_id)
        if faq is None or faq.published_version_id is None:
            raise FaqNotFoundError(faq_id)
        version = self._repository.get_version(faq.published_version_id)
        if version is None:
            raise FaqNotFoundError(faq.published_version_id)
        self._authorize_release(actor, DISABLE, faq, version)
        ensure_disable_allowed(version=version, reason=reason)
        next_version = build_disabled_version(version, actor=actor, reason=reason)
        next_faq = build_disabled_faq(faq, version=version, actor=actor)
        return self._commit_transition(
            "FAQ_DISABLED",
            faq,
            next_faq,
            (next_version,),
            actor,
            expected_etag,
            idempotency_key,
            correlation_id,
            reason,
            active_pointer=(faq.faq_key, None),
            primary_version_id=version.version_id,
            request_fingerprint=request_fingerprint,
        )

    def rollback(self, **kwargs: Any) -> dict[str, Any]:
        return FaqPublishOpsMixin.activate(self, rollback=True, **kwargs)
