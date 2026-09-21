"""Source-role assignment for evidence packing and citation precision.

Roles:
- PRIMARY: strongest query-anchor overlap; must stay in context and citations
- SUPPORTING: positive but weaker overlap; keep only when competitive
- CONTRASTIVE: reserved for explicit contrast/negation queries
- POLICY_OVERLAY: security advisories (handled elsewhere)
- INCIDENTAL: low/no overlap peripheral docs; drop before generation
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from enum import Enum

from agent_service.retrieval import SearchResult

from .generator import query_anchor_tokens

# Product/system Latin tokens outweigh generic CJK bigrams like 帳號/解鎖.
_LATIN_ANCHOR_BOOST = 12
_NEGATED_TOPIC_PENALTY = 40

# Alias hints: query cue → title/content cue (casefolded / plain CJK).
_ALIAS_HINTS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("蘋果", "iphone"), ("ios", "iphone", "蘋果")),
    (("公司信", "公司郵件"), ("outlook", "郵件", "信")),
    (("安卓", "android"), ("android", "安卓")),
)


class SourceRole(str, Enum):
    PRIMARY = "PRIMARY"
    SUPPORTING = "SUPPORTING"
    CONTRASTIVE = "CONTRASTIVE"
    POLICY_OVERLAY = "POLICY_OVERLAY"
    INCIDENTAL = "INCIDENTAL"


def _query_is_contrastive(query: str) -> bool:
    normalized = (query or "").casefold()
    markers = ("不是", "而非", "為何不能", "不要", "並非", "排除", "hard-negative")
    return any(marker in normalized for marker in markers)


def _latin_query_tokens(query: str) -> set[str]:
    return {
        match.group(0).lower()
        for match in re.finditer(r"[A-Za-z][A-Za-z0-9_./:-]{1,}", query or "")
    }


def _negated_topic(query: str) -> str | None:
    """Extract the topic the user explicitly rejects (e.g. 不是功能無法點選那篇)."""
    match = re.search(
        r"不是\s*([^\s，,。.!！?？]{2,20}?)(?:那篇|那份|文件|流程|說明)?\s*$",
        query or "",
    )
    if match:
        return match.group(1).strip("，,。 ")
    match = re.search(r"不是\s*([^\s，,。.!！?？]{2,16})", query or "")
    if match:
        return match.group(1).strip("，,。 ")
    return None


def _positive_topic_prefix(query: str) -> str | None:
    """Topic stated before an explicit negation clause."""
    if "不是" not in (query or ""):
        return None
    prefix = (query or "").split("不是", 1)[0]
    prefix = re.sub(r"[，,。.\s]+$", "", prefix).strip()
    return prefix or None


def _doc_blob(
    *,
    doc_key: str,
    results: Sequence[SearchResult],
    document_key: Callable[[SearchResult], str],
) -> tuple[str, str]:
    titles: list[str] = []
    contents: list[str] = []
    for result in results:
        if document_key(result) != doc_key:
            continue
        titles.append(result.chunk.title or "")
        contents.append(result.chunk.content or "")
    title = "\n".join(titles)
    content = "\n".join(contents)
    return title, f"{title}\n{content}"


def _usable_anchors(*, anchors: set[str], query: str) -> set[str]:
    negated = _negated_topic(query)
    if not negated:
        return set(anchors)
    positive = _positive_topic_prefix(query)
    usable: set[str] = set()
    for anchor in anchors:
        # Ignore anchors that only belong to the rejected topic.
        if anchor in negated or (len(anchor) >= 2 and anchor in negated):
            if positive and (anchor in positive or (len(anchor) >= 2 and anchor in positive)):
                usable.add(anchor)
            continue
        usable.add(anchor)
    return usable


def _title_span_bonus(*, title: str, query: str) -> int:
    negated = _negated_topic(query)
    positive = _positive_topic_prefix(query) if negated else None
    score = 0
    title_span_hits = 0
    hit_pieces: set[str] = set()
    stop = {
        "可以",
        "找誰",
        "哪個",
        "哪些",
        "什麼",
        "如何",
        "怎麼",
        "不是",
        "那篇",
        "文件",
        "流程",
        "說明",
        "系統",
        "常見",
        "問題",
        "要找",
        "有哪",
    }
    for run in re.findall(r"[\u3400-\u9fff]+", query or ""):
        for size in (2, 3, 4):
            if len(run) < size:
                continue
            for index in range(len(run) - size + 1):
                piece = run[index : index + size]
                if piece in stop or piece in hit_pieces:
                    continue
                if (
                    negated
                    and piece in negated
                    and (not positive or piece not in positive)
                ):
                    continue
                if piece in title:
                    hit_pieces.add(piece)
                    title_span_hits += 1
                    score += max(5, size + 2)
    if title_span_hits >= 2:
        score += 10
    return score


def _doc_overlap(
    *,
    doc_key: str,
    results: Sequence[SearchResult],
    document_key: Callable[[SearchResult], str],
    anchors: set[str],
    query: str,
) -> int:
    title, blob = _doc_blob(doc_key=doc_key, results=results, document_key=document_key)
    if not blob or not anchors:
        return 0
    blob_l = blob.lower()
    title_l = title.lower()
    usable_anchors = _usable_anchors(anchors=anchors, query=query)
    score = sum(1 for anchor in usable_anchors if anchor.lower() in blob_l)
    for token in _latin_query_tokens(query):
        if token in title_l:
            score += _LATIN_ANCHOR_BOOST
        elif token in blob_l:
            score += _LATIN_ANCHOR_BOOST // 2
    score += _title_span_bonus(title=title, query=query)

    query_l = (query or "").casefold()
    for query_cues, doc_cues in _ALIAS_HINTS:
        if not any(cue.casefold() in query_l or cue in (query or "") for cue in query_cues):
            continue
        if any(cue.casefold() in title_l or cue.casefold() in blob_l for cue in doc_cues):
            score += _LATIN_ANCHOR_BOOST

    negated = _negated_topic(query)
    positive = _positive_topic_prefix(query) if negated else None
    if negated:
        negated_hit = negated in title or negated in blob
        positive_hit = bool(positive) and (positive in title or positive in blob)
        if negated_hit and not positive_hit:
            score -= _NEGATED_TOPIC_PENALTY
    return score


def assign_source_roles(
    *,
    query: str,
    results: Sequence[SearchResult],
    document_key: Callable[[SearchResult], str],
) -> dict[str, SourceRole]:
    """Assign a role to each unique document key in ``results``."""
    keys = list(dict.fromkeys(document_key(result) for result in results if document_key(result)))
    if not keys:
        return {}
    if len(keys) == 1:
        return {keys[0]: SourceRole.PRIMARY}

    anchors = query_anchor_tokens(query)
    scored = [
        (
            key,
            _doc_overlap(
                doc_key=key,
                results=results,
                document_key=document_key,
                anchors=anchors,
                query=query,
            ),
        )
        for key in keys
    ]
    best = max(score for _, score in scored)
    contrastive = _query_is_contrastive(query)
    roles: dict[str, SourceRole] = {}
    for key, score in scored:
        if best <= 0:
            roles[key] = SourceRole.PRIMARY if key == keys[0] else SourceRole.INCIDENTAL
            continue
        if score <= 0:
            roles[key] = SourceRole.INCIDENTAL
        elif score == best:
            roles[key] = SourceRole.PRIMARY
        elif contrastive and score >= max(1, (best + 1) // 2):
            roles[key] = SourceRole.CONTRASTIVE
        elif score >= max(1, (best + 1) // 2):
            roles[key] = SourceRole.SUPPORTING
        else:
            roles[key] = SourceRole.INCIDENTAL
    return roles


def filter_results_for_generation(
    *,
    query: str,
    results: Sequence[SearchResult],
    document_key: Callable[[SearchResult], str],
) -> list[SearchResult]:
    """Drop INCIDENTAL documents and pack PRIMARY evidence first.

    Reordering matters under token budgets: primary docs must consume budget
    before supporting/contrastive peripherals.
    """
    if len(results) <= 1:
        return list(results)
    roles = assign_source_roles(query=query, results=results, document_key=document_key)
    keep_roles = {
        SourceRole.PRIMARY,
        SourceRole.SUPPORTING,
        SourceRole.CONTRASTIVE,
    }
    filtered = [
        result
        for result in results
        if roles.get(document_key(result), SourceRole.PRIMARY) in keep_roles
    ]
    dropped = len(results) - len(filtered)
    if dropped > 0:
        from agent_service.observability import METRIC_EVIDENCE_DROP, record_metric_counter

        record_metric_counter(
            METRIC_EVIDENCE_DROP,
            amount=float(dropped),
            attributes={"result_type": "SOURCE_ROLE"},
        )
    if not filtered:
        return list(results)

    role_rank = {
        SourceRole.PRIMARY: 0,
        SourceRole.SUPPORTING: 1,
        SourceRole.CONTRASTIVE: 2,
    }
    return sorted(
        filtered,
        key=lambda result: (
            role_rank.get(
                roles.get(document_key(result), SourceRole.PRIMARY),
                9,
            ),
            next(
                (
                    index
                    for index, original in enumerate(results)
                    if original is result
                ),
                0,
            ),
        ),
    )


__all__ = [
    "SourceRole",
    "assign_source_roles",
    "filter_results_for_generation",
]
