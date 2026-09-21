"""Evidence-level retrieval eval labels (RAG v2.1 P0).

Title-only ``expectedSourceTitles`` overstates success when the right document
but wrong chunk is retrieved. Callers should prefer chunk / evidence labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExpectedEvidenceFact:
    """One evidence unit the generator must see in the final context pack."""

    section: str | None = None
    must_contain: tuple[str, ...] = ()
    chunk_id: str | None = None


@dataclass(frozen=True)
class EvidenceLevelCase:
    """Frozen eval case with document + chunk + evidence annotations."""

    case_id: str
    query: str
    expected_found: bool
    expected_documents: tuple[str, ...] = ()
    expected_sections: tuple[str, ...] = ()
    expected_chunk_ids: tuple[str, ...] = ()
    expected_evidence: tuple[ExpectedEvidenceFact, ...] = ()
    forbidden_evidence: tuple[str, ...] = ()
    # Legacy title field kept for gradual migration from title-only sets.
    expected_source_titles: tuple[str, ...] = ()
    prior_turn: str | None = None
    hard_negative_ids: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> EvidenceLevelCase:
        evidence_raw = value.get("expectedEvidence") or value.get("expected_evidence") or []
        facts: list[ExpectedEvidenceFact] = []
        for item in evidence_raw:
            if not isinstance(item, dict):
                continue
            must = item.get("mustContain") or item.get("must_contain") or []
            facts.append(
                ExpectedEvidenceFact(
                    section=(item.get("section") or None),
                    must_contain=tuple(str(token) for token in must),
                    chunk_id=(item.get("chunkId") or item.get("chunk_id") or None),
                )
            )
        titles = tuple(
            str(item)
            for item in (
                value.get("expectedDocuments")
                or value.get("expected_documents")
                or value.get("expectedSourceTitles")
                or ()
            )
        )
        hard_raw = value.get("hardNegatives") or value.get("hard_negatives") or ()
        hard_ids: list[str] = []
        for item in hard_raw:
            if isinstance(item, dict):
                title = item.get("title") or item.get("document") or item.get("id")
                if title:
                    hard_ids.append(str(title))
            elif item:
                hard_ids.append(str(item))
        prior = value.get("priorTurn") or value.get("prior_turn")
        prior_turn = str(prior).strip() if prior else None
        return cls(
            case_id=str(value.get("id") or value.get("caseId") or ""),
            query=str(value.get("query") or ""),
            expected_found=bool(value.get("expectedFound", value.get("expected_found", True))),
            expected_documents=titles,
            expected_sections=tuple(
                str(item)
                for item in (
                    value.get("expectedSections") or value.get("expected_sections") or ()
                )
            ),
            expected_chunk_ids=tuple(
                str(item)
                for item in (
                    value.get("expectedChunkIds") or value.get("expected_chunk_ids") or ()
                )
            ),
            expected_evidence=tuple(facts),
            forbidden_evidence=tuple(
                str(item)
                for item in (
                    value.get("forbiddenEvidence") or value.get("forbidden_evidence") or ()
                )
            ),
            expected_source_titles=tuple(
                str(item) for item in (value.get("expectedSourceTitles") or ())
            ),
            prior_turn=prior_turn or None,
            hard_negative_ids=tuple(hard_ids),
        )

    def primary_relevant_ids(self) -> tuple[str, ...]:
        """Ids to score against ranked retrieval — prefer chunks over titles."""
        if self.expected_chunk_ids:
            return self.expected_chunk_ids
        if self.expected_documents:
            return self.expected_documents
        return self.expected_source_titles

    @property
    def is_multi_turn(self) -> bool:
        return bool(self.prior_turn)


def compose_follow_up_retrieval_query(prior_turn: str, query: str) -> str:
    """Compose prior + follow-up the same way clarification merge does.

    Mirrors ``workflow_clarification_helpers._compose_pending_description`` so
    blind ``priorTurn`` cases exercise a resolved retrieval query rather than
    the short follow-up utterance alone.
    """
    base = str(prior_turn or "").strip().rstrip("。.!！?？")
    addition = str(query or "").strip().rstrip("。.!！?？")
    if not base:
        return addition
    if not addition or addition.lower() in base.lower():
        return base
    return f"{base} {addition}"


__all__ = [
    "EvidenceLevelCase",
    "ExpectedEvidenceFact",
    "compose_follow_up_retrieval_query",
]
