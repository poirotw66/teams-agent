"""Helpers for building evaluation case create inputs from HTTP payloads."""

from __future__ import annotations

from typing import Any

from operations_core.access import ActorContext

from ...evaluation_domain import (
    EvaluationCriteria,
    EvidenceItem,
    EvidenceRequirement,
    ProvenanceSpec,
)
from .models import CaseCreatePayload


def build_create_case_kwargs(
    payload: CaseCreatePayload,
    *,
    actor: ActorContext,
    idempotency_key: str | None,
    correlation_id: str | None,
) -> dict[str, Any]:
    """Translate a create-case payload into EvaluationService.create_case kwargs."""
    from ...evaluation_domain.models import CriterionItem

    crit_items = tuple(CriterionItem(**c) for c in payload.required_facts)
    criteria = EvaluationCriteria(
        required_facts=crit_items,
        forbidden_claims=tuple(payload.forbidden_claims),
        reference_answer=payload.reference_answer,
    )

    evidence_reqs: list[EvidenceRequirement] = []
    for ev in payload.evidence:
        items = tuple(EvidenceItem(**item) for item in ev.get("items", []))
        evidence_reqs.append(
            EvidenceRequirement(group_id=ev.get("group_id", "default"), items=items)
        )

    provenance = ProvenanceSpec(
        source_type=payload.source_type,
        source_id=payload.source_id or f"manual:{actor.user_id}",
        source_version_id=payload.source_version_id,
    )

    return {
        "title": payload.title,
        "query": payload.query,
        "owner_unit_id": payload.owner_unit_id,
        "behavior": payload.behavior,
        "criteria": criteria,
        "evidence": tuple(evidence_reqs),
        "tags": tuple(payload.tags),
        "criticality": payload.criticality,
        "provenance": provenance,
        "actor": actor,
        "metadata": payload.metadata,
        "idempotency_key": idempotency_key,
        "correlation_id": correlation_id,
    }
