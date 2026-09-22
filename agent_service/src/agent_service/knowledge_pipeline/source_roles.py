"""Source-role assignment for evidence packing and citation precision.

Roles:
- PRIMARY: strongest query-anchor overlap; must stay in context and citations
- SUPPORTING: positive but weaker overlap; keep only when competitive
- CONTRASTIVE: reserved for explicit contrast/negation queries
- POLICY_OVERLAY: legacy synthetic advisories (stripped; out of knowledge scope)
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
    # Portal password contrast queries often say「公司入口網站」not「員工入口網」.
    (
        ("公司入口", "入口網站密碼", "員工入口", "入口網密碼"),
        ("員工入口", "cteam", "並非ad", "並非 ad", "金控網站帳密"),
    ),
)
_SHORT_LATIN_NEGATED = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,3}$")


class SourceRole(str, Enum):
    PRIMARY = "PRIMARY"
    SUPPORTING = "SUPPORTING"
    CONTRASTIVE = "CONTRASTIVE"
    POLICY_OVERLAY = "POLICY_OVERLAY"
    INCIDENTAL = "INCIDENTAL"


# 「是不是同一份 / 同一個」are same-doc confirmations, not topic negation.
_SAME_DOC_CONFIRMATION = re.compile(
    r"是不是\s*同一(?:份|篇|個|文件|手冊|來源)",
)


def _query_is_contrastive(query: str) -> bool:
    # Same-doc confirmations embed「不是」inside「是不是」; do not treat as negation.
    if _SAME_DOC_CONFIRMATION.search(query or ""):
        return False
    normalized = (query or "").casefold()
    markers = ("不是", "而非", "為何不能", "不要", "並非", "排除", "hard-negative")
    return any(marker in normalized for marker in markers)


_VPN_PASSWORD_EXPIRY_PACK_MARKERS: tuple[str, ...] = (
    "密碼到期",
    "怎麼處理",
    "如何處理",
    "要怎麼",
)
_VPN_HOWTO_CONTENT_MARKERS: tuple[str, ...] = (
    "ctrl + alt + delete",
    "ctrl+alt+delete",
    "實體網路線",
)


def _is_vpn_password_expiry_query(query: str) -> bool:
    query_l = (query or "").casefold()
    if "vpn" not in query_l:
        return False
    return any(marker in (query or "") for marker in _VPN_PASSWORD_EXPIRY_PACK_MARKERS)


def _chunk_has_vpn_password_howto(result: SearchResult) -> bool:
    blob = f"{result.chunk.title}\n{result.chunk.content}".casefold()
    return any(marker in blob for marker in _VPN_HOWTO_CONTENT_MARKERS)


def _promote_title_aligned_comparison_docs(
    *,
    query: str,
    results: Sequence[SearchResult],
    roles: dict[str, SourceRole],
    document_key: Callable[[SearchResult], str],
) -> dict[str, SourceRole]:
    """Keep both named manuals packable for same-doc discrimination queries."""
    from .relevance import primary_distinctive_tokens
    from .selector import query_asks_for_comparison

    if not query_asks_for_comparison(query):
        return roles
    tokens = primary_distinctive_tokens(query)
    if not tokens:
        return roles
    promoted = dict(roles)
    for result in results:
        key = document_key(result)
        if not key or promoted.get(key) != SourceRole.INCIDENTAL:
            continue
        title = (result.chunk.title or "").casefold()
        if any(token.casefold() in title for token in tokens):
            promoted[key] = SourceRole.SUPPORTING
    return promoted


def _promote_vpn_password_howto_docs(
    *,
    query: str,
    results: Sequence[SearchResult],
    roles: dict[str, SourceRole],
    document_key: Callable[[SearchResult], str],
) -> dict[str, SourceRole]:
    """Keep FortiClient how-to packable even when VPN Q&A dominates overlap."""
    if not _is_vpn_password_expiry_query(query):
        return roles
    promoted = dict(roles)
    for result in results:
        if not _chunk_has_vpn_password_howto(result):
            continue
        key = document_key(result)
        if not key:
            continue
        if promoted.get(key) in (None, SourceRole.INCIDENTAL, SourceRole.CONTRASTIVE):
            promoted[key] = SourceRole.SUPPORTING
    return promoted


def _vpn_howto_pack_rank(query: str, result: SearchResult) -> int:
    """Prefer executable FortiClient how-to ahead of the long VPN Q&A summary."""
    if not _is_vpn_password_expiry_query(query):
        return 1
    return 0 if _chunk_has_vpn_password_howto(result) else 1


def _latin_query_tokens(query: str) -> set[str]:
    return {
        match.group(0).lower()
        for match in re.finditer(r"[A-Za-z][A-Za-z0-9_./:-]{1,}", query or "")
    }


_NEGATION_SPLIT_MARKERS: tuple[str, ...] = (
    "不要給我",
    "為何不能",
    "不能直接套用",
    "不能套用",
    "不是",
    "而非",
    "不要",
    "排除",
)


def _negated_topic(query: str) -> str | None:
    """Extract the topic the user explicitly rejects (e.g. 不是功能無法點選那篇)."""
    text = query or ""
    # Same-doc discrimination must not treat「同一份」as a rejected topic.
    if _SAME_DOC_CONFIRMATION.search(text):
        return None
    # Confirmation questions「是不是 AD」must not treat the embedded「不是」alone.
    confirm = re.search(
        r"是不是\s*([A-Za-z][A-Za-z0-9_./:-]{0,15}|[^\s，,。.!！?？]{1,16})",
        text,
    )
    if confirm:
        topic = confirm.group(1).strip("，,。 /／對吧嗎呢")
        if len(topic) >= 1:
            return topic
    patterns = (
        r"為何不能(?:直接)?(?:套用|使用|依|照)\s*([A-Za-z][A-Za-z0-9_./:-]{1,24}|[^\s，,。.!！?？]{2,24})",
        r"不能直接(?:套用|使用)\s*([A-Za-z][A-Za-z0-9_./:-]{1,24}|[^\s，,。.!！?？]{2,24})",
        r"(?:不是|而非)\s*([^\s，,。.!！?？]{2,24}?)(?:那篇|那份|文件|流程|說明)?\s*$",
        r"(?<![是])(?:不是|而非)\s*([^\s，,。.!！?？]{2,16})",
        r"不要給我\s*(.+?)(?:\s*$|[。.!！?？])",
        r"不要\s*([^\s，,。.!！?？]{2,24})",
        r"排除\s*([^\s，,。.!！?？]{2,16})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        topic = match.group(1).strip("，,。 /／")
        topic = re.sub(r"(?:步驟|手冊)$", "", topic).strip()
        if len(topic) >= 2:
            return topic
    return None


def _positive_topic_prefix(query: str) -> str | None:
    """Topic stated before an explicit negation clause."""
    text = query or ""
    if _SAME_DOC_CONFIRMATION.search(text):
        prefix = _SAME_DOC_CONFIRMATION.split(text)[0]
        prefix = re.sub(r"[，,。.\s]+$", "", prefix).strip()
        return prefix or None
    if "是不是" in text:
        prefix = text.split("是不是", 1)[0]
        prefix = re.sub(r"[，,。.\s]+$", "", prefix).strip()
        return prefix or None
    for marker in _NEGATION_SPLIT_MARKERS:
        if marker not in text:
            continue
        # Avoid splitting「是不是」on the embedded「不是」marker.
        if marker == "不是" and "是不是" in text:
            continue
        prefix = text.split(marker, 1)[0]
        prefix = re.sub(r"[，,。.\s]+$", "", prefix).strip()
        return prefix or None
    return None


def _compact_cjk_text(text: str) -> str:
    return re.sub(r"[\s\u3000／/·・\-_/]+", "", text or "")


def _cjk_bigrams(text: str) -> list[str]:
    bigrams: list[str] = []
    for run in re.findall(r"[\u3400-\u9fff]+", text or ""):
        if len(run) < 2:
            continue
        if len(run) == 2:
            bigrams.append(run)
            continue
        for index in range(len(run) - 1):
            bigrams.append(run[index : index + 2])
    return bigrams


def _short_latin_token(text: str) -> str | None:
    stripped = (text or "").strip()
    if _SHORT_LATIN_NEGATED.fullmatch(stripped):
        return stripped.lower()
    return None


def _platform_label(text: str) -> str | None:
    """Map free text to ios/android when a platform cue is present."""
    text_l = (text or "").casefold()
    if any(token in text_l for token in ("android", "安卓")):
        return "android"
    if any(token in text_l for token in ("ios", "iphone", "蘋果")):
        return "ios"
    return None


def _title_about_short_latin(*, title: str, token: str) -> bool:
    """True when a short Latin product token is a title subject, not a body aside."""
    title_l = (title or "").casefold()
    needle = token.casefold()
    if not title_l or needle not in title_l:
        return False
    # Titles like「AD 帳號與系統解鎖」or「國金 CRM OTP 綁訂」are about the token.
    return True


def _matches_negated_topic(
    *,
    text: str,
    negated: str,
    title: str | None = None,
) -> bool:
    """True when rejected topic appears in doc text, including interrupted titles.

    Contiguous substring fails on titles like ``外網 CRM 登入連線設定方式`` when
    the user rejects ``外網連線設定``; require strong CJK bigram / Latin overlap.

    Short Latin rejects (AD / OTP) require title-level aboutness so contrast
    phrases like「並非 AD」in an employee-portal FAQ do not demote the primary doc.
    """
    if not negated or not text:
        return False
    short_latin = _short_latin_token(negated)
    if short_latin is not None:
        return _title_about_short_latin(title=title if title is not None else text, token=short_latin)
    if negated in text:
        return True
    compact_negated = _compact_cjk_text(negated)
    compact_text = _compact_cjk_text(text)
    if len(compact_negated) >= 2 and compact_negated in compact_text:
        return True

    text_l = text.casefold()
    compact_text_l = compact_text.casefold()
    latin_tokens = [
        match.group(0).lower()
        for match in re.finditer(r"[A-Za-z][A-Za-z0-9_./:-]{1,}", negated)
    ]
    latin_hit = bool(latin_tokens) and all(
        token in text_l or token in compact_text_l for token in latin_tokens
    )

    bigrams = _cjk_bigrams(negated)
    if not bigrams:
        return latin_hit
    hits = sum(1 for bigram in bigrams if bigram in text)
    coverage = hits / len(bigrams)
    if latin_hit:
        return coverage >= 0.4 or hits >= 1
    if len(bigrams) < 2:
        return False
    return coverage >= 0.6


def _positive_topic_hits(*, title: str, blob: str, positive: str) -> bool:
    """Fuzzy positive-topic match so aliases like 公司入口 ≈ 員工入口 still hit."""
    if not positive:
        return False
    if (
        positive in title
        or positive in blob
        or _compact_cjk_text(positive) in _compact_cjk_text(title)
        or _compact_cjk_text(positive) in _compact_cjk_text(blob)
    ):
        return True
    bigrams = _cjk_bigrams(positive)
    if len(bigrams) < 2:
        return False
    title_hits = sum(1 for bigram in bigrams if bigram in title)
    blob_hits = sum(1 for bigram in bigrams if bigram in blob)
    return (title_hits / len(bigrams)) >= 0.4 or (blob_hits / len(bigrams)) >= 0.5


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
        negated_hit = _matches_negated_topic(
            text=title, negated=negated, title=title
        ) or (
            _short_latin_token(negated) is None
            and _matches_negated_topic(text=blob, negated=negated, title=title)
        )
        positive_hit = bool(positive) and _positive_topic_hits(
            title=title, blob=blob, positive=positive
        )
        negated_platform = _platform_label(negated)
        title_platform = _platform_label(title)
        # Platform handbooks share generic tokens (Outlook); demote the rejected
        # platform even when the positive clause also mentions the product name.
        if (
            negated_platform
            and title_platform == negated_platform
            and _platform_label(positive or "") != negated_platform
        ):
            return min(score - _NEGATED_TOPIC_PENALTY, 0)
        if negated_hit and not positive_hit:
            # Force INCIDENTAL even when retrieval score / Latin boost is high.
            return min(score - _NEGATED_TOPIC_PENALTY, 0)
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


def _rescue_top_score_from_incidental(
    *,
    query: str,
    results: Sequence[SearchResult],
    roles: dict[str, SourceRole],
    document_key: Callable[[SearchResult], str],
) -> dict[str, SourceRole]:
    """Keep a uniquely higher-score hit packable when Latin-boost heuristics misfire.

    Follow-up rewrite can inject a product token (e.g. Outlook) that promotes
    peripheral manuals to PRIMARY while the score=1.0 target becomes INCIDENTAL.
    Only rescue when that seed clearly outscores already-kept evidence.
    Never rescue a doc the user explicitly rejected via contrastive negation.
    """
    if not results:
        return roles
    best = max(results, key=lambda result: float(result.score or 0.0))
    best_key = document_key(best)
    if not best_key:
        return roles
    if roles.get(best_key, SourceRole.PRIMARY) != SourceRole.INCIDENTAL:
        return roles
    negated = _negated_topic(query)
    if negated:
        title = best.chunk.title or ""
        blob = f"{title}\n{best.chunk.content or ''}"
        negated_hit = _matches_negated_topic(
            text=title, negated=negated, title=title
        ) or (
            _short_latin_token(negated) is None
            and _matches_negated_topic(text=blob, negated=negated, title=title)
        )
        if negated_hit:
            return roles
    kept_scores = [
        float(result.score or 0.0)
        for result in results
        if roles.get(document_key(result), SourceRole.PRIMARY) != SourceRole.INCIDENTAL
    ]
    best_score = float(best.score or 0.0)
    if kept_scores and best_score <= max(kept_scores):
        return roles
    rescued = dict(roles)
    rescued[best_key] = SourceRole.PRIMARY
    return rescued


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
    roles = _rescue_top_score_from_incidental(
        query=query,
        results=results,
        roles=roles,
        document_key=document_key,
    )
    roles = _promote_title_aligned_comparison_docs(
        query=query,
        results=results,
        roles=roles,
        document_key=document_key,
    )
    roles = _promote_vpn_password_howto_docs(
        query=query,
        results=results,
        roles=roles,
        document_key=document_key,
    )
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
            _vpn_howto_pack_rank(query, result),
            role_rank.get(
                roles.get(document_key(result), SourceRole.PRIMARY),
                9,
            ),
            -float(result.score or 0.0),
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
