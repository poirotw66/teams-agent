"""Deterministic source scoring and baseline assessment contracts."""

from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SOURCE_TITLE_SIMILARITY_THRESHOLD = 0.65


class ClaimAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1, max_length=1000)
    support: Literal["SUPPORTED", "UNSUPPORTED"]
    source_chunk_ids: list[str] = Field(default_factory=list)
    explanation: str = Field(min_length=1, max_length=1000)


class AnswerQualityAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correctness: float = Field(ge=0.0, le=1.0)
    completeness: float = Field(ge=0.0, le=1.0)
    groundedness: float = Field(ge=0.0, le=1.0)
    claims: list[ClaimAssessment] = Field(min_length=1)
    missing_required_facts: list[str] = Field(default_factory=list)
    verdict: Literal["PASS", "PARTIAL", "FAIL", "INCONCLUSIVE"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=2000)


class RetrievalAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_sources: list[str]
    actual_sources: list[str]
    matched_sources: list[str]
    missing_sources: list[str]
    matches: list[SourceMatch] = Field(default_factory=list)
    source_recall: float = Field(ge=0.0, le=1.0)


class SourceMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_source: str
    actual_source: str
    method: Literal["EXACT", "TITLE_SIMILARITY"]
    similarity: float = Field(ge=0.0, le=1.0)


class JudgeAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correctness: float = Field(ge=0.0, le=1.0)
    completeness: float = Field(ge=0.0, le=1.0)
    groundedness: float = Field(ge=0.0, le=1.0)
    source_match: float = Field(ge=0.0, le=1.0)
    claim_assessments: list[ClaimAssessment] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    missing_required_facts: list[str] = Field(default_factory=list)
    retrieval: RetrievalAssessment
    verdict: Literal["PASS", "PARTIAL", "FAIL", "INCONCLUSIVE"]
    confidence: float = Field(ge=0.0, le=1.0)
    review_status: Literal["SINGLE_PASS", "CONFIRMED", "ADJUDICATED"]
    secondary_verdict: Literal["PASS", "PARTIAL", "FAIL", "INCONCLUSIVE"] | None = None
    primary_assessment: AnswerQualityAssessment | None = None
    secondary_assessment: AnswerQualityAssessment | None = None
    adjudication_assessment: AnswerQualityAssessment | None = None
    needs_human_review: bool = False
    reason: str = Field(min_length=1, max_length=2000)


def score_retrieval(
    expected_sources: tuple[str, ...],
    citations: tuple[dict[str, object], ...],
) -> RetrievalAssessment:
    actual = _unique_source_identities(citations)
    unmatched_actual = set(range(len(actual)))
    matches: list[SourceMatch] = []
    for expected in expected_sources:
        match = _match_source(expected, actual, unmatched_actual)
        if match is not None:
            matches.append(match[1])
            unmatched_actual.remove(match[0])
    return _retrieval_assessment(
        expected_sources,
        actual=actual,
        matches=matches,
    )


class _SourceIdentity(BaseModel):
    label: str
    normalized_aliases: set[str]


def _unique_source_identities(
    citations: tuple[dict[str, object], ...],
) -> list[_SourceIdentity]:
    actual: list[_SourceIdentity] = []
    seen_aliases: set[tuple[str, ...]] = set()
    for citation in citations:
        source = _source_identity(citation)
        identity = tuple(sorted(source.normalized_aliases))
        if source.label and identity not in seen_aliases:
            actual.append(source)
            seen_aliases.add(identity)
    return actual


def _retrieval_assessment(
    expected_sources: tuple[str, ...],
    *,
    actual: list[_SourceIdentity],
    matches: list[SourceMatch],
) -> RetrievalAssessment:
    matched_sources = [match.expected_source for match in matches]
    missing_sources = [source for source in expected_sources if source not in matched_sources]
    recall = len(matched_sources) / len(expected_sources) if expected_sources else 1.0
    return RetrievalAssessment(
        expected_sources=list(expected_sources),
        actual_sources=[source.label for source in actual],
        matched_sources=matched_sources,
        missing_sources=missing_sources,
        matches=matches,
        source_recall=round(recall, 4),
    )


def _match_source(
    expected: str,
    actual: list[_SourceIdentity],
    unmatched_actual: set[int],
) -> tuple[int, SourceMatch] | None:
    normalized_expected = _normalize_source(expected)
    for index in unmatched_actual:
        if normalized_expected in actual[index].normalized_aliases:
            return index, SourceMatch(
                expected_source=expected,
                actual_source=actual[index].label,
                method="EXACT",
                similarity=1.0,
            )
    similarities = [
        (
            max(
                (
                    SequenceMatcher(None, normalized_expected, alias).ratio()
                    for alias in actual[index].normalized_aliases
                ),
                default=0.0,
            ),
            index,
        )
        for index in unmatched_actual
    ]
    similarity, index = max(similarities, default=(0.0, -1))
    if similarity < SOURCE_TITLE_SIMILARITY_THRESHOLD:
        return None
    return index, SourceMatch(
        expected_source=expected,
        actual_source=actual[index].label,
        method="TITLE_SIMILARITY",
        similarity=round(similarity, 4),
    )


def _source_identity(citation: dict[str, object]) -> _SourceIdentity:
    title = str(citation.get("title") or "").strip()
    source_path = str(citation.get("sourcePath") or "").strip()
    section = str(citation.get("section") or "").strip()
    raw_aliases = citation.get("sourceAliases") or []
    filename = PurePosixPath(source_path).name if source_path else ""
    stem = PurePosixPath(filename).stem if filename else ""
    alias_candidates = [title, source_path, filename, stem, section]
    if isinstance(raw_aliases, (list, tuple)):
        alias_candidates.extend(str(a) for a in raw_aliases)
    aliases = {normalized for value in alias_candidates if (normalized := _normalize_source(value))}
    return _SourceIdentity(
        label=title or filename or section,
        normalized_aliases=aliases,
    )


def _normalize_source(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def inconclusive_assessment(
    *,
    expected_sources: tuple[str, ...],
    citations: tuple[dict[str, object], ...],
    reason: str,
) -> JudgeAssessment:
    retrieval = score_retrieval(expected_sources, citations)
    return JudgeAssessment(
        correctness=0.0,
        completeness=0.0,
        groundedness=0.0,
        source_match=retrieval.source_recall,
        retrieval=retrieval,
        verdict="INCONCLUSIVE",
        confidence=0.0,
        review_status="SINGLE_PASS",
        needs_human_review=True,
        reason=reason,
    )
