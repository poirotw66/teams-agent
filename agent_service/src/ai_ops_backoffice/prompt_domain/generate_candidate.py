"""Prompt candidate generation helpers for PromptPocService.generate."""

from __future__ import annotations

import hashlib
import re
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from operations_core.access import ActorContext
from operations_core.default_extractor_prompt import SYSTEM_PROMPT

from ..faq_domain.errors import FaqValidationError
from .models import PromptAuditEvent, PromptCandidate, PromptState


def _select_verified_examples(
    verified_examples: list[dict[str, Any]],
    *,
    dataset_version: str,
    data_range_start: datetime,
    data_range_end: datetime,
    secret_pattern: re.Pattern[str],
    injection_signatures: tuple[str, ...],
) -> list[dict[str, Any]]:
    selected = [
        item
        for item in verified_examples
        if item.get("status") == "VERIFIED"
        and item.get("dataset_version") == dataset_version
        and data_range_start
        <= datetime.fromisoformat(item["created_at"])
        <= data_range_end
    ]
    if not selected:
        raise FaqValidationError(
            "dataset version has no VERIFIED examples in the data range"
        )
    for item in selected:
        text = str(item.get("text") or "")
        lowered = text.casefold()
        if secret_pattern.search(text):
            raise FaqValidationError("dataset failed secret inspection")
        if any(signature in lowered for signature in injection_signatures):
            raise FaqValidationError("dataset failed prompt injection inspection")
    return selected


def _build_candidate_content(
    *,
    dataset_version: str,
    selected: list[dict[str, Any]],
    max_prompt_length: int,
) -> str:
    route_labels = Counter(
        (str(item["expected_route"]), str(item["label"])) for item in selected
    )
    guidance = "\n".join(
        f"- {route} {label}: {count} verified examples"
        for (route, label), count in sorted(route_labels.items())
    )
    content = f"{SYSTEM_PROMPT}\n\nVerified dataset guidance ({dataset_version}):\n{guidance}\n"
    if "{max_issues}" not in content or "{faq_keys}" not in content:
        raise FaqValidationError("candidate failed prompt schema inspection")
    if len(content) > max_prompt_length:
        raise FaqValidationError("candidate exceeds maximum prompt length")
    return content


def build_prompt_candidate(
    *,
    service: Any,
    active_prompt_version: str,
    dataset_version: str,
    taxonomy_version: str,
    data_range_start: datetime,
    data_range_end: datetime,
    masking_policy_version: str,
    verified_examples: list[dict[str, Any]],
    correlation_id: str | None,
    actor: ActorContext,
    secret_pattern: re.Pattern[str],
    injection_signatures: tuple[str, ...],
) -> dict[str, Any]:
    if active_prompt_version != service._active_version:
        raise FaqValidationError("active prompt version is stale")
    if data_range_end < data_range_start:
        raise FaqValidationError("data range end must not precede start")
    selected = _select_verified_examples(
        verified_examples,
        dataset_version=dataset_version,
        data_range_start=data_range_start,
        data_range_end=data_range_end,
        secret_pattern=secret_pattern,
        injection_signatures=injection_signatures,
    )
    content = _build_candidate_content(
        dataset_version=dataset_version,
        selected=selected,
        max_prompt_length=service.MAX_PROMPT_LENGTH,
    )
    now = datetime.now(UTC)
    resolved_correlation_id = correlation_id or str(uuid.uuid4())
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    candidate = PromptCandidate(
        candidate_id=str(uuid.uuid4()),
        prompt_id=service.PROMPT_ID,
        version=content_hash[:12],
        content=content,
        content_hash=content_hash,
        active_prompt_version=service._active_version,
        dataset_version=dataset_version,
        taxonomy_version=taxonomy_version,
        data_range_start=data_range_start,
        data_range_end=data_range_end,
        masking_policy_version=masking_policy_version,
        generated_by=actor.user_id,
        correlation_id=resolved_correlation_id,
        created_at=now,
    )
    audit = PromptAuditEvent(
        audit_id=str(uuid.uuid4()),
        action="PROMPT_CANDIDATE_GENERATED",
        target_id=candidate.candidate_id,
        actor_id=actor.user_id,
        actor_role=actor.role,
        correlation_id=resolved_correlation_id,
        occurred_at=now,
    )

    def operation(state: PromptState) -> tuple[PromptState, dict[str, Any]]:
        return PromptState(
            revision=state.revision + 1,
            candidates=(*state.candidates, candidate),
            audits=(*state.audits, audit),
        ), {"candidate": candidate.model_dump(mode="json", exclude={"content"})}

    return service._repository.mutate(operation)
