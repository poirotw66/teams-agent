from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_service.operations.access import ActorContext
from agent_service.operations.masking import MASKING_POLICY_VERSION, mask_text, redact_secrets

from ..faq_domain.errors import (
    FaqAuthorizationError,
    FaqIdempotencyConflictError,
    FaqNotFoundError,
    FaqTransitionError,
    FaqValidationError,
    FaqVersionConflictError,
)


from .models import *  # noqa: F403
from .repository import *  # noqa: F403

class ExampleService:
    def __init__(self, repository: ExampleRepository, *, taxonomy: Any) -> None:
        self._repository = repository
        self._taxonomy = taxonomy

    @staticmethod
    def _authorize(actor: ActorContext, capability: str, owner_unit_id: str) -> None:
        if not actor.has_capability(capability) or not actor.allows_owner_unit(owner_unit_id):
            raise FaqAuthorizationError("example operation is outside actor capability or scope")

    @staticmethod
    def _fingerprint(actor: ActorContext, payload: dict[str, Any]) -> str:
        value = {"actor_id": actor.user_id, **payload}
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _result(record: ExampleRecord) -> dict[str, Any]:
        return {"example": record.model_dump(mode="json")}

    def list_examples(
        self,
        *,
        actor: ActorContext,
        source_type: str | None = None,
        source_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        visible = []
        for record in self._repository.list_examples():
            try:
                self._authorize(actor, "ops.examples.read", record.owner_unit_id)
            except FaqAuthorizationError:
                continue
            if source_type and record.source_type != source_type:
                continue
            if source_id and record.source_id != source_id:
                continue
            if status and record.status != status:
                continue
            visible.append(record.model_dump(mode="json"))
        return visible

    def detail(self, example_id: str, *, actor: ActorContext) -> dict[str, Any]:
        record = self._require(example_id)
        self._authorize(actor, "ops.examples.read", record.owner_unit_id)
        return {
            **self._result(record),
            "audit": [item.model_dump(mode="json") for item in self._repository.list_audit(example_id)],
        }

    def create(
        self,
        *,
        source_type: str,
        source_id: str,
        source_version_id: str | None,
        source_correlation_id: str | None,
        owner_unit_id: str,
        text: str,
        expected_issue_type_id: str,
        expected_route: str,
        label: str,
        reason: str | None,
        actor: ActorContext,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        self._authorize(actor, "ops.examples.write", owner_unit_id)
        self._taxonomy.require_active(expected_issue_type_id)
        masked = mask_text(text)
        if masked.contains_credential:
            raise FaqValidationError("credentials are not allowed in examples")
        masked_reason = mask_text(reason) if reason else None
        if masked_reason and masked_reason.contains_credential:
            raise FaqValidationError("credentials are not allowed in example reasons")
        if label == "NEGATIVE" and not (reason or "").strip():
            raise FaqValidationError("negative examples require a reason")
        now = datetime.now(UTC)
        request = {
            "action": "EXAMPLE_CREATED",
            "source_type": source_type,
            "source_id": source_id,
            "source_version_id": source_version_id,
            "text": masked.text,
            "expected_issue_type_id": expected_issue_type_id,
            "expected_route": expected_route,
            "label": label,
            "reason": reason,
        }
        fingerprint = self._fingerprint(actor, request)
        replay = self._repository.replay(idempotency_key, "EXAMPLE_CREATED", fingerprint)
        if replay is not None:
            return replay
        record = ExampleRecord(
            example_id=str(uuid.uuid4()),
            source_type=source_type,
            source_id=source_id,
            source_version_id=source_version_id,
            source_correlation_id=source_correlation_id,
            owner_unit_id=owner_unit_id,
            text=masked.text,
            expected_issue_type_id=expected_issue_type_id,
            expected_route=expected_route,
            label=label,
            reason=masked_reason.text if masked_reason else None,
            etag=1,
            created_by=actor.user_id,
            created_at=now,
            updated_by=actor.user_id,
            updated_at=now,
        )
        return self._commit(
            record,
            action="EXAMPLE_CREATED",
            actor=actor,
            before=None,
            expected_etag=None,
            reason=reason,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            correlation_id=correlation_id,
        )

    def update(
        self,
        example_id: str,
        *,
        text: str,
        expected_issue_type_id: str,
        expected_route: str,
        label: str,
        reason: str | None,
        expected_etag: int,
        actor: ActorContext,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        current = self._require(example_id)
        self._authorize(actor, "ops.examples.write", current.owner_unit_id)
        if current.status == "RETIRED":
            raise FaqTransitionError("retired examples cannot be edited")
        self._taxonomy.require_active(expected_issue_type_id)
        masked = mask_text(text)
        if masked.contains_credential:
            raise FaqValidationError("credentials are not allowed in examples")
        masked_reason = mask_text(reason) if reason else None
        if masked_reason and masked_reason.contains_credential:
            raise FaqValidationError("credentials are not allowed in example reasons")
        if label == "NEGATIVE" and not (reason or "").strip():
            raise FaqValidationError("negative examples require a reason")
        fingerprint = self._fingerprint(
            actor,
            {
                "action": "EXAMPLE_UPDATED",
                "example_id": example_id,
                "etag": expected_etag,
                "text": masked.text,
                "expected_issue_type_id": expected_issue_type_id,
                "expected_route": expected_route,
                "label": label,
                "reason": reason,
            },
        )
        replay = self._repository.replay(idempotency_key, "EXAMPLE_UPDATED", fingerprint)
        if replay is not None:
            return replay
        updated = ExampleRecord.model_validate(
            {
                **current.model_dump(mode="python"),
                "text": masked.text,
                "expected_issue_type_id": expected_issue_type_id,
                "expected_route": expected_route,
                "label": label,
                "reason": masked_reason.text if masked_reason else None,
                "status": "DRAFT",
                "etag": expected_etag + 1,
                "dataset_version": None,
                "verified_by": None,
                "verified_at": None,
                "updated_by": actor.user_id,
                "updated_at": datetime.now(UTC),
            },
        )
        return self._commit(
            updated,
            action="EXAMPLE_UPDATED",
            actor=actor,
            before=current,
            expected_etag=expected_etag,
            reason=reason,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            correlation_id=correlation_id,
        )

    def review(
        self,
        example_id: str,
        *,
        approve: bool,
        reason: str,
        expected_etag: int,
        dataset_version: str | None = None,
        actor: ActorContext,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        current = self._require(example_id)
        self._authorize(actor, "ops.examples.verify", current.owner_unit_id)
        if current.status not in {"DRAFT", "REJECTED"}:
            raise FaqTransitionError("only draft or rejected examples can be reviewed")
        action = "EXAMPLE_VERIFIED" if approve else "EXAMPLE_REJECTED"
        fingerprint = self._fingerprint(
            actor,
            {
                "action": action,
                "example_id": example_id,
                "etag": expected_etag,
                "reason": reason,
                "dataset_version": dataset_version,
            },
        )
        replay = self._repository.replay(idempotency_key, action, fingerprint)
        if replay is not None:
            return replay
        now = datetime.now(UTC)
        assigned_dataset = (
            (dataset_version or f"dataset-{now.strftime('%Y%m%dT%H%M%SZ')}")
            if approve
            else None
        )
        updated = current.model_copy(
            update={
                "status": "VERIFIED" if approve else "REJECTED",
                "etag": expected_etag + 1,
                "dataset_version": assigned_dataset,
                "verified_by": actor.user_id if approve else None,
                "verified_at": now if approve else None,
                "updated_by": actor.user_id,
                "updated_at": now,
            }
        )
        return self._commit(
            updated,
            action=action,
            actor=actor,
            before=current,
            expected_etag=expected_etag,
            reason=reason,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            correlation_id=correlation_id,
        )

    def retire(
        self,
        example_id: str,
        *,
        reason: str,
        expected_etag: int,
        actor: ActorContext,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        current = self._require(example_id)
        self._authorize(actor, "ops.examples.retire", current.owner_unit_id)
        if current.status == "RETIRED":
            raise FaqTransitionError("example is already retired")
        fingerprint = self._fingerprint(
            actor,
            {
                "action": "EXAMPLE_RETIRED",
                "example_id": example_id,
                "etag": expected_etag,
                "reason": reason,
            },
        )
        replay = self._repository.replay(idempotency_key, "EXAMPLE_RETIRED", fingerprint)
        if replay is not None:
            return replay
        now = datetime.now(UTC)
        updated = current.model_copy(
            update={
                "status": "RETIRED",
                "etag": expected_etag + 1,
                "retired_by": actor.user_id,
                "retired_at": now,
                "updated_by": actor.user_id,
                "updated_at": now,
            }
        )
        return self._commit(
            updated,
            action="EXAMPLE_RETIRED",
            actor=actor,
            before=current,
            expected_etag=expected_etag,
            reason=reason,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            correlation_id=correlation_id,
        )

    def _require(self, example_id: str) -> ExampleRecord:
        record = self._repository.get(example_id)
        if record is None:
            raise FaqNotFoundError(example_id)
        return record

    def _commit(
        self,
        record: ExampleRecord,
        *,
        action: str,
        actor: ActorContext,
        before: ExampleRecord | None,
        expected_etag: int | None,
        reason: str | None,
        idempotency_key: str | None,
        request_fingerprint: str,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        result = self._result(record)
        audit = ExampleAuditEvent(
            audit_id=str(uuid.uuid4()),
            example_id=record.example_id,
            action=action,
            actor_id=actor.user_id,
            actor_role=actor.role,
            owner_unit_id=record.owner_unit_id,
            before=redact_secrets(before.model_dump(mode="json")) if before else None,
            after=redact_secrets(record.model_dump(mode="json")),
            reason=mask_text(reason).text if reason else None,
            occurred_at=datetime.now(UTC),
            correlation_id=correlation_id,
        )
        return self._repository.commit(
            record,
            audit,
            expected_etag=expected_etag,
            idempotency_key=idempotency_key,
            action=action,
            request_fingerprint=request_fingerprint,
            result=result,
        )

    def purge_expired(
        self,
        *,
        retention_days: int = 365,
        actor: ActorContext | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        target_now = now or datetime.now(UTC)
        return self._repository.purge_expired(
            now=target_now,
            retention_days=retention_days,
            actor=actor,
        )


