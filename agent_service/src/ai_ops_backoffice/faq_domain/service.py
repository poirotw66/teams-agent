from __future__ import annotations

import uuid
from typing import Any

from agent_service.operations.access import ActorContext
from agent_service.operations.masking import MASKING_POLICY_VERSION, mask_text

from .authorization import (
    AccessPolicyAuthorization,
    DenySelfApprovalException,
    DenyUnknownTaxonomy,
    FaqAuthorizationPort,
    FaqSelfApprovalExceptionPort,
    FaqTaxonomyPort,
)
from .errors import FaqAuthorizationError, FaqNotFoundError, FaqTransitionError, FaqValidationError
from .models import (
    FaqAuditEvent,
    FaqContent,
    FaqRecord,
    FaqRuntimeSnapshot,
    FaqTestCase,
    FaqVersion,
    utc_now,
)
from .repository import FaqCommit, FaqRepository, fingerprint

WRITE = "ops.faq.write"
REVIEW = "ops.faq.review"
ACTIVATE = "ops.faq.activate"
DISABLE = "ops.faq.disable"


class FaqDomainService:
    """Governed FAQ lifecycle; it intentionally exposes no HTTP or UI concerns."""

    def __init__(
        self,
        repository: FaqRepository,
        *,
        authorization: FaqAuthorizationPort | None = None,
        taxonomy: FaqTaxonomyPort | None = None,
        self_approval_exception: FaqSelfApprovalExceptionPort | None = None,
    ) -> None:
        self._repository = repository
        self._authorization = authorization or AccessPolicyAuthorization()
        self._taxonomy = taxonomy or DenyUnknownTaxonomy()
        self._self_approval_exception = self_approval_exception or DenySelfApprovalException()

    def _authorize(self, actor: ActorContext, capability: str, owner_unit_id: str) -> None:
        self._authorization.require(actor=actor, capability=capability, owner_unit_id=owner_unit_id)

    def _authorize_release(self, actor: ActorContext, capability: str, faq: FaqRecord, target: FaqVersion) -> None:
        """Historical versions cannot bypass the current owner's scope."""
        owners = {target.content.owner_unit_id}
        for version_id in (faq.draft_version_id, faq.published_version_id):
            if version_id:
                version = self._repository.get_version(version_id)
                if version is None:
                    raise FaqNotFoundError(version_id)
                owners.add(version.content.owner_unit_id)
        for owner in owners:
            self._authorize(actor, capability, owner)

    @staticmethod
    def _replace(model: Any, **changes: Any) -> Any:
        return type(model).model_validate({**model.model_dump(), **changes})

    def _validate_content(self, content: FaqContent) -> None:
        for issue_type_id in content.issue_type_ids:
            self._taxonomy.require_active(issue_type_id)
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

    def _command_fingerprint(self, actor: ActorContext, payload: dict[str, Any]) -> str:
        return fingerprint({"actorId": actor.user_id, **payload})

    def _replay(
        self, *, actor: ActorContext, key: str | None, action: str, request_fingerprint: str
    ) -> dict[str, Any] | None:
        result = self._repository.replay(
            key=key, action=action, request_fingerprint=request_fingerprint
        )
        if result is not None:
            version_data = result.get("version") or result["test"]
            faq, version = self._require(result["faq"]["faq_id"], version_data["version_id"])
            capability = {
                "FAQ_APPROVED": REVIEW, "FAQ_CHANGES_REQUESTED": REVIEW,
                "FAQ_ACTIVATED": ACTIVATE, "FAQ_ROLLED_BACK": ACTIVATE,
                "FAQ_DISABLED": DISABLE,
            }.get(action, WRITE)
            self._authorize_release(actor, capability, faq, version)
        return result

    @staticmethod
    def _audit(
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

    @staticmethod
    def _result(faq: FaqRecord, version: FaqVersion) -> dict[str, Any]:
        return {"faq": faq.model_dump(mode="json"), "version": version.model_dump(mode="json")}

    def create(
        self,
        *,
        content: FaqContent,
        actor: ActorContext,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        content = FaqContent.model_validate(content.model_dump())
        request_fingerprint = self._command_fingerprint(
            actor, {"action": "FAQ_CREATED", "content": content.model_dump(mode="json")}
        )
        replay = self._replay(
            actor=actor, key=idempotency_key, action="FAQ_CREATED", request_fingerprint=request_fingerprint
        )
        if replay is not None:
            return replay
        self._authorize(actor, WRITE, content.owner_unit_id)
        self._validate_content(content)
        now = utc_now()
        faq_id, version_id = str(uuid.uuid4()), str(uuid.uuid4())
        version = FaqVersion(
            version_id=version_id,
            faq_id=faq_id,
            version_number=1,
            content=content,
            created_by=actor.user_id,
            created_at=now,
        )
        faq = FaqRecord(
            faq_id=faq_id,
            faq_key=content.faq_key,
            status="DRAFT",
            draft_version_id=version_id,
            created_by=actor.user_id,
            created_at=now,
            updated_by=actor.user_id,
            updated_at=now,
            etag=1,
        )
        result = self._result(faq, version)
        audit = self._audit(
            action="FAQ_CREATED",
            actor=actor,
            faq_id=faq_id,
            version_id=version_id,
            reason=None,
            before=None,
            after={"status": "DRAFT", "faqKey": content.faq_key},
            correlation_id=correlation_id,
        )
        return self._repository.commit(
            FaqCommit(
                faq=faq,
                versions=(version,),
                tests=(),
                audit=audit,
                expected_etag=None,
                idempotency_key=idempotency_key,
                action="FAQ_CREATED",
                request_fingerprint=request_fingerprint,
                result=result,
            )
        )

    def add_test(
        self,
        *,
        faq_id: str,
        version_id: str,
        kind: str,
        utterance: str,
        expected_audience_group_ids: tuple[str, ...],
        actor: ActorContext,
        expected_etag: int,
        source_type: str = "MANUAL",
        source_correlation_id: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        masked_utterance = mask_text(utterance)
        request_fingerprint = self._command_fingerprint(
            actor,
            {
                "action": "FAQ_TEST_ADDED",
                "faqId": faq_id,
                "versionId": version_id,
                "kind": kind,
                "utterance": utterance,
                "audience": expected_audience_group_ids,
                "etag": expected_etag,
                "sourceType": source_type,
                "sourceCorrelationId": source_correlation_id,
            },
        )
        replay = self._replay(
            actor=actor, key=idempotency_key, action="FAQ_TEST_ADDED", request_fingerprint=request_fingerprint
        )
        if replay is not None:
            return replay
        faq, version = self._require(faq_id, version_id)
        self._authorize(actor, WRITE, version.content.owner_unit_id)
        if source_type == "CONVERSATION":
            self._authorize(actor, "ops.conversations.read", version.content.owner_unit_id)
        if faq.draft_version_id != version_id:
            raise FaqTransitionError("test cases must belong to the current draft")
        if version.status not in {"DRAFT", "CHANGES_REQUESTED"}:
            raise FaqTransitionError(
                "tests can only be added to DRAFT or CHANGES_REQUESTED versions"
            )
        expected_match = kind == "POSITIVE"
        test = FaqTestCase(
            test_case_id=str(uuid.uuid4()),
            faq_id=faq_id,
            version_id=version_id,
            kind=kind,
            utterance=masked_utterance.text,
            expected_audience_group_ids=expected_audience_group_ids,
            expected_match=expected_match,
            created_by=actor.user_id,
            created_at=utc_now(),
            source_type=source_type,
            source_correlation_id=source_correlation_id,
            masking_policy_version=MASKING_POLICY_VERSION,
        )
        updated = self._replace(
            faq, updated_by=actor.user_id, updated_at=utc_now(), etag=faq.etag + 1
        )
        result = {"faq": updated.model_dump(mode="json"), "test": test.model_dump(mode="json")}
        audit = self._audit(
            action="FAQ_TEST_ADDED",
            actor=actor,
            faq_id=faq_id,
            version_id=version_id,
            reason=None,
            before={"etag": faq.etag},
            after={"etag": updated.etag, "kind": kind},
            correlation_id=correlation_id,
        )
        return self._repository.commit(
            FaqCommit(
                faq=updated,
                versions=(),
                tests=(test,),
                audit=audit,
                expected_etag=expected_etag,
                idempotency_key=idempotency_key,
                action="FAQ_TEST_ADDED",
                request_fingerprint=request_fingerprint,
                result=result,
            )
        )

    def edit(
        self,
        *,
        faq_id: str,
        content: FaqContent,
        actor: ActorContext,
        expected_etag: int,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new immutable draft; published answer text is never overwritten."""
        content = FaqContent.model_validate(content.model_dump())
        faq = self._repository.get_faq(faq_id)
        if faq is None:
            raise FaqNotFoundError(faq_id)
        if content.faq_key != faq.faq_key:
            raise FaqValidationError(
                "faq_key changes require the future mapping-compatibility adapter"
            )
        request_fingerprint = self._command_fingerprint(
            actor,
            {
                "action": "FAQ_DRAFT_CREATED",
                "faqId": faq_id,
                "content": content.model_dump(mode="json"),
                "etag": expected_etag,
            },
        )
        replay = self._replay(
            actor=actor, key=idempotency_key, action="FAQ_DRAFT_CREATED", request_fingerprint=request_fingerprint
        )
        if replay is not None:
            return replay
        # Owner transfer is a dual-scope operation; possession of only the new
        # unit's authority cannot be used to seize an existing FAQ.
        current = self._repository.get_version(
            faq.draft_version_id or faq.published_version_id or ""
        )
        if current is None:
            raise FaqNotFoundError(faq_id)
        self._authorize(actor, WRITE, current.content.owner_unit_id)
        if faq.published_version_id:
            published = self._repository.get_version(faq.published_version_id)
            if published is None:
                raise FaqNotFoundError(faq.published_version_id)
            self._authorize(actor, WRITE, published.content.owner_unit_id)
        self._authorize(actor, WRITE, content.owner_unit_id)
        self._validate_content(content)
        current_versions = self._repository.list_versions(faq_id)
        now = utc_now()
        draft = FaqVersion(
            version_id=str(uuid.uuid4()),
            faq_id=faq_id,
            version_number=max((item.version_number for item in current_versions), default=0) + 1,
            content=content,
            created_by=actor.user_id,
            created_at=now,
        )
        changed: list[FaqVersion] = [draft]
        if faq.draft_version_id:
            prior = self._repository.get_version(faq.draft_version_id)
            if prior and prior.status == "IN_REVIEW":
                raise FaqTransitionError("request changes before revising an IN_REVIEW draft")
            if prior and prior.status in {"DRAFT", "CHANGES_REQUESTED", "APPROVED"}:
                changed.append(self._replace(prior, status="SUPERSEDED"))
        next_faq = self._replace(
            faq,
            status=faq.status if faq.published_version_id else "DRAFT",
            draft_version_id=draft.version_id,
            updated_by=actor.user_id,
            updated_at=now,
            etag=faq.etag + 1,
        )
        return self._commit_transition(
            "FAQ_DRAFT_CREATED",
            faq,
            next_faq,
            tuple(changed),
            actor,
            expected_etag,
            idempotency_key,
            correlation_id,
            None,
            primary_version_id=draft.version_id,
            request_fingerprint=request_fingerprint,
        )

    def submit(
        self,
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
            actor=actor, key=idempotency_key, action="FAQ_SUBMITTED", request_fingerprint=request_fingerprint
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
        next_version = self._replace(
            version, status="IN_REVIEW", submitted_at=now, submitted_by=actor.user_id
        )
        next_faq = self._replace(
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
        self,
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
        request_fingerprint = self._command_fingerprint(
            actor,
            {
                "action": "FAQ_APPROVED" if approve else "FAQ_CHANGES_REQUESTED",
                "faqId": faq_id,
                "versionId": version_id,
                "etag": expected_etag,
                "reason": reason,
                "poc": poc_exception_reason,
            },
        )
        action = "FAQ_APPROVED" if approve else "FAQ_CHANGES_REQUESTED"
        replay = self._replay(
            actor=actor, key=idempotency_key, action=action, request_fingerprint=request_fingerprint
        )
        if replay is not None:
            return replay
        faq, version = self._require(faq_id, version_id)
        self._authorize(actor, REVIEW, version.content.owner_unit_id)
        if faq.draft_version_id != version_id:
            raise FaqTransitionError("review must target the current draft")
        if version.status != "IN_REVIEW":
            raise FaqTransitionError("only IN_REVIEW versions can be reviewed")
        if not reason.strip():
            raise FaqValidationError("review reason is required")
        if approve and actor.user_id == version.submitted_by:
            if not poc_exception_reason:
                raise FaqAuthorizationError("submitter and approver must be different")
            self._self_approval_exception.require(
                actor=actor,
                owner_unit_id=version.content.owner_unit_id,
                reason=poc_exception_reason,
            )
        if approve:
            self._validate_submission(version)
        now = utc_now()
        if approve:
            next_version = self._replace(
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
            next_status = "APPROVED" if faq.published_version_id is None else faq.status
        else:
            next_version = self._replace(
                version,
                status="CHANGES_REQUESTED",
                reviewed_by=actor.user_id,
                reviewed_at=now,
                review_reason=reason,
            )
            next_status = "CHANGES_REQUESTED" if faq.published_version_id is None else faq.status
        next_faq = self._replace(
            faq, status=next_status, updated_by=actor.user_id, updated_at=now, etag=faq.etag + 1
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
        self,
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
            actor=actor, key=idempotency_key, action=action, request_fingerprint=request_fingerprint
        )
        if replay is not None:
            return replay
        faq, version = self._require(faq_id, version_id)
        self._authorize_release(actor, ACTIVATE, faq, version)
        if not reason.strip():
            raise FaqValidationError("activation reason is required")
        if version.status != "APPROVED" and not (
            rollback and version.status in {"SUPERSEDED", "DISABLED"} and version.approved_by
        ):
            raise FaqTransitionError(
                "activation requires an APPROVED version; rollback requires a previously approved SUPERSEDED version"
            )
        self._validate_submission(version)
        previous_id = self._repository.get_active_version_id(faq.faq_key)
        changed = [self._replace(version, status="ACTIVE")]
        if previous_id and previous_id != version_id:
            previous = self._repository.get_version(previous_id)
            if previous:
                changed.append(self._replace(previous, status="SUPERSEDED"))
        now = utc_now()
        next_faq = self._replace(
            faq,
            status="ACTIVE",
            draft_version_id=None if faq.draft_version_id == version_id else faq.draft_version_id,
            published_version_id=version_id,
            updated_by=actor.user_id,
            updated_at=now,
            etag=faq.etag + 1,
        )
        return self._commit_transition(
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

    def disable(
        self,
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
            {"action": "FAQ_DISABLED", "faqId": faq_id, "etag": expected_etag, "reason": reason},
        )
        replay = self._replay(
            actor=actor, key=idempotency_key, action="FAQ_DISABLED", request_fingerprint=request_fingerprint
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
        if version.status != "ACTIVE":
            raise FaqTransitionError("only ACTIVE versions can be disabled")
        if not reason.strip():
            raise FaqValidationError("disable reason is required")
        now = utc_now()
        next_version = self._replace(
            version,
            status="DISABLED",
            disabled_by=actor.user_id,
            disabled_at=now,
            disabled_reason=reason,
        )
        next_faq = self._replace(
            faq,
            status="DISABLED",
            published_version_id=version.version_id,
            updated_by=actor.user_id,
            updated_at=now,
            etag=faq.etag + 1,
        )
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
        return self.activate(rollback=True, **kwargs)

    def active_snapshot(
        self, *, faq_key: str, audience_group_ids: tuple[str, ...]
    ) -> FaqRuntimeSnapshot | None:
        version = self._repository.get_active_version(faq_key)
        if version is None or version.status != "ACTIVE":
            return None
        content = version.content
        if content.effective_at and content.effective_at > utc_now():
            return None
        if content.audience_type == "GROUPS" and not set(content.audience_group_ids).intersection(
            audience_group_ids
        ):
            return None
        return FaqRuntimeSnapshot(
            faq_id=version.faq_id,
            faq_key=content.faq_key,
            version_id=version.version_id,
            question=content.question,
            answer=content.answer,
            category=content.category,
            keywords=content.keywords,
            issue_type_ids=content.issue_type_ids,
            audience_type=content.audience_type,
            audience_group_ids=content.audience_group_ids,
            effective_at=content.effective_at,
        )

    def _require(self, faq_id: str, version_id: str) -> tuple[FaqRecord, FaqVersion]:
        faq, version = self._repository.get_faq(faq_id), self._repository.get_version(version_id)
        if faq is None or version is None or version.faq_id != faq_id:
            raise FaqNotFoundError(f"FAQ/version not found: {faq_id}/{version_id}")
        return faq, version

    def _validate_submission(self, version: FaqVersion) -> None:
        self._validate_content(version.content)
        tests = self._repository.list_tests(version.version_id)
        kinds = {item.kind for item in tests}
        if {"POSITIVE", "NEGATIVE"} - kinds:
            raise FaqValidationError("submit requires at least one POSITIVE and one NEGATIVE test")
        positive_text = {item.utterance.casefold().strip() for item in tests if item.kind == "POSITIVE"}
        negative_text = {item.utterance.casefold().strip() for item in tests if item.kind == "NEGATIVE"}
        if positive_text & negative_text:
            raise FaqValidationError("the same utterance cannot be both a positive and a negative test")
        if any(not item.utterance.strip() or item.utterance == "[REDACTED_CREDENTIAL]" for item in tests):
            raise FaqValidationError("tests must contain usable masked utterances")
        if version.content.audience_type == "GROUPS":
            positive_groups = {
                group
                for item in tests
                if item.kind == "POSITIVE"
                for group in item.expected_audience_group_ids
            }
            if not set(version.content.audience_group_ids).intersection(positive_groups):
                raise FaqValidationError("GROUPS audience requires a positive audience test")
            if any(
                item.kind == "POSITIVE" and not set(version.content.audience_group_ids).intersection(item.expected_audience_group_ids)
                for item in tests
            ):
                raise FaqValidationError("positive test audience must be allowed by the version")

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
    ) -> dict[str, Any]:
        primary = next(
            item for item in versions if item.version_id == (primary_version_id or item.version_id)
        )
        result = self._result(after_faq, primary)
        audit = self._audit(
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
        return self._repository.commit(
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
