from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from operations_core.access import ActorContext
from operations_core.masking import mask_text

from .authorization import (
    AccessPolicyAuthorization,
    DenySelfApprovalException,
    DenyUnknownTaxonomy,
    FaqAuthorizationPort,
    FaqSelfApprovalExceptionPort,
    FaqTaxonomyPort,
)
from .errors import FaqAuthorizationError, FaqNotFoundError, FaqValidationError
from .lifecycle_ops import FaqPublishCommandHandler, FaqPublishOpsMixin
from .models import (
    FaqContent,
    FaqRecord,
    FaqRuntimeSnapshot,
    FaqVersion,
    utc_now,
)
from .repository import FaqCommit, FaqRepository
from .transitions import (
    READ,
    WRITE,
    build_audit_event,
    build_edit_draft,
    build_faq_result,
    build_faq_test_case,
    collect_release_owner_unit_ids,
    command_fingerprint,
    commit_transition,
    ensure_draft_accepts_test,
    replace_model,
    replay_capability,
    require_faq_version,
    validate_faq_content,
    validate_faq_submission,
)


class FaqDomainService(FaqPublishOpsMixin):
    """Governed FAQ lifecycle; it intentionally exposes no HTTP or UI concerns."""

    def __init__(
        self,
        repository: FaqRepository,
        *,
        authorization: FaqAuthorizationPort | None = None,
        taxonomy: FaqTaxonomyPort | None = None,
        self_approval_exception: FaqSelfApprovalExceptionPort | None = None,
        artifact_dir: Path | None = None,
        release_gate_checker: Any | None = None,
    ) -> None:
        self._repository = repository
        self._authorization = authorization or AccessPolicyAuthorization()
        self._taxonomy = taxonomy or DenyUnknownTaxonomy()
        self._self_approval_exception = self_approval_exception or DenySelfApprovalException()
        self._artifact_dir = artifact_dir
        self._release_gate_checker = release_gate_checker
        self.publish_handler = FaqPublishCommandHandler(self)

    def set_release_gate_checker(self, checker: Any | None) -> None:
        self._release_gate_checker = checker

    def _authorize(self, actor: ActorContext, capability: str, owner_unit_id: str) -> None:
        self._authorization.require(actor=actor, capability=capability, owner_unit_id=owner_unit_id)

    @staticmethod
    def _replace(model: Any, **changes: Any) -> Any:
        return replace_model(model, **changes)

    def _authorize_release(
        self, actor: ActorContext, capability: str, faq: FaqRecord, target: FaqVersion
    ) -> None:
        for owner in collect_release_owner_unit_ids(self._repository, faq, target):
            self._authorize(actor, capability, owner)

    def _validate_content(self, content: FaqContent) -> None:
        validate_faq_content(self._taxonomy, content)

    def _validate_submission(self, version: FaqVersion) -> None:
        validate_faq_submission(
            self._taxonomy, version, self._repository.list_tests(version.version_id)
        )

    def _command_fingerprint(self, actor: ActorContext, payload: dict[str, Any]) -> str:
        return command_fingerprint(actor, payload)

    def _replay(
        self, *, actor: ActorContext, key: str | None, action: str, request_fingerprint: str
    ) -> dict[str, Any] | None:
        result = self._repository.replay(
            key=key, action=action, request_fingerprint=request_fingerprint
        )
        if result is not None:
            version_data = result.get("version") or result["test"]
            faq, version = require_faq_version(
                self._repository, result["faq"]["faq_id"], version_data["version_id"]
            )
            self._authorize_release(actor, replay_capability(action), faq, version)
        return result

    def _require(self, faq_id: str, version_id: str) -> tuple[FaqRecord, FaqVersion]:
        return require_faq_version(self._repository, faq_id, version_id)

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
        return commit_transition(
            self._repository,
            action=action,
            before_faq=before_faq,
            after_faq=after_faq,
            versions=versions,
            actor=actor,
            expected_etag=expected_etag,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            reason=reason,
            active_pointer=active_pointer,
            primary_version_id=primary_version_id,
            request_fingerprint=request_fingerprint,
        )

    def list_faqs(self, *, actor: ActorContext) -> list[dict[str, Any]]:
        visible: list[dict[str, Any]] = []
        for faq in self._repository.list_faqs():
            versions = self._repository.list_versions(faq.faq_id)
            if not versions:
                continue
            current = versions[-1]
            try:
                self._authorize(actor, READ, current.content.owner_unit_id)
            except FaqAuthorizationError:
                continue
            visible.append(build_faq_result(faq, current))
        return visible

    def detail(self, *, faq_id: str, actor: ActorContext) -> dict[str, Any]:
        faq = self._repository.get_faq(faq_id)
        if faq is None:
            raise FaqNotFoundError(faq_id)
        versions = self._repository.list_versions(faq_id)
        if not versions:
            raise FaqNotFoundError(faq_id)
        self._authorize(actor, READ, versions[-1].content.owner_unit_id)
        return {
            "faq": faq.model_dump(mode="json"),
            "versions": [version.model_dump(mode="json") for version in versions],
            "tests": [
                test.model_dump(mode="json")
                for version in versions
                for test in self._repository.list_tests(version.version_id)
            ],
            "audit": [
                event.model_dump(mode="json") for event in self._repository.list_audit(faq_id)
            ],
        }

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
            actor=actor,
            key=idempotency_key,
            action="FAQ_CREATED",
            request_fingerprint=request_fingerprint,
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
        result = build_faq_result(faq, version)
        audit = build_audit_event(
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
        masked = mask_text(utterance)
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
            actor=actor,
            key=idempotency_key,
            action="FAQ_TEST_ADDED",
            request_fingerprint=request_fingerprint,
        )
        if replay is not None:
            return replay
        faq, version = self._require(faq_id, version_id)
        self._authorize(actor, WRITE, version.content.owner_unit_id)
        if source_type == "CONVERSATION":
            self._authorize(actor, "ops.conversations.read", version.content.owner_unit_id)
        ensure_draft_accepts_test(faq=faq, version=version, version_id=version_id)
        test = build_faq_test_case(
            faq_id=faq_id,
            version_id=version_id,
            kind=kind,
            utterance=masked.text,
            expected_audience_group_ids=expected_audience_group_ids,
            actor=actor,
            source_type=source_type,
            source_correlation_id=source_correlation_id,
        )
        updated = replace_model(
            faq, updated_by=actor.user_id, updated_at=utc_now(), etag=faq.etag + 1
        )
        result = {"faq": updated.model_dump(mode="json"), "test": test.model_dump(mode="json")}
        audit = build_audit_event(
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
            actor=actor,
            key=idempotency_key,
            action="FAQ_DRAFT_CREATED",
            request_fingerprint=request_fingerprint,
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
        next_faq, changed, draft_version_id = build_edit_draft(
            self._repository, faq=faq, content=content, actor=actor
        )
        return self._commit_transition(
            "FAQ_DRAFT_CREATED",
            faq,
            next_faq,
            changed,
            actor,
            expected_etag,
            idempotency_key,
            correlation_id,
            None,
            primary_version_id=draft_version_id,
            request_fingerprint=request_fingerprint,
        )

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

    def active_snapshots(
        self, *, audience_group_ids: tuple[str, ...]
    ) -> tuple[FaqRuntimeSnapshot, ...]:
        snapshots = (
            self.active_snapshot(
                faq_key=faq.faq_key,
                audience_group_ids=audience_group_ids,
            )
            for faq in self._repository.list_faqs()
        )
        return tuple(
            sorted(
                (snapshot for snapshot in snapshots if snapshot is not None),
                key=lambda snapshot: snapshot.faq_key,
            )
        )
