"""Deterministic and offline relevance decision helpers.

LLM grading still runs through ``HybridKnowledgeService`` (needs model I/O);
this module owns lexical guards, confidence routing, and grade-prompt context.
"""

from __future__ import annotations

import re

from agent_service.contracts import RetrievalAttempt
from agent_service.retrieval import SearchResult, tokenize

# ponytail: without an LLM grader, BM25 alone over-matches the sample corpus.
# Require distinctive query tokens to overlap the retrieved text before accepting
# a hit; upgrade path is enabling RAG_MODEL relevance grading.
_GENERIC_LEXICAL_TOKENS = frozenset(
    {
        "vpn",
        "it",
        "ai",
        "bot",
        "teams",
        "agent",
        "demo",
        "test",
        "help",
        "cancel",
        "close",
        "請",
        "協",
        "助",
        "幫",
        "我",
        "要",
        "想",
        "問",
        "查",
        "詢",
        "怎",
        "麼",
        "如",
        "何",
        "為",
        "什",
        "可",
        "以",
        "不",
        "能",
        "無",
        "法",
        "有",
        "沒",
        "是",
        "的",
        "了",
        "嗎",
        "呢",
        "在",
        "和",
        "或",
        "及",
        "與",
        "開",
        "建",
        "立",
        "工",
        "單",
        "派",
        "取",
        "消",
        "公",
        "司",
        "內",
        "部",
        "企",
        "業",
        "知",
        "識",
        "庫",
        "測",
        "試",
        "問題",
        "資訊",
        "系統",
        "無法",
        "怎麼",
        "如何",
        "請問",
        "協助",
        "建立",
        "開工",
        "工單",
        "派工",
        "取消",
    }
)
_OFFLINE_RELEVANCE_MIN_OVERLAP = 2
_OFFLINE_RELEVANCE_MIN_RATIO = 0.34
_OFFLINE_SINGLE_TOKEN_MIN_SCORE = 0.5
HIGH_CONFIDENCE_RETRIEVAL_MIN_SCORE = 0.78
_SUBJECT_CHAR_STOP = frozenset("解鎖無法怎嗎呢的了是在和或及與請協助建立開取消")
_CLOSE_SCORE_GAP = 0.08
_LOW_CONFIDENCE_MAX_SCORE = 0.60

_INSUFFICIENT_INFORMATION_MARKERS: tuple[str, ...] = (
    "資訊不足",
    "信息不足",
    "資料不足",
    "沒有足夠資訊",
    "沒有足夠信息",
    "無法提供答案",
    "無法回答",
    "查無相關資訊",
    "查無相關信息",
    "沒有相關資訊",
    "沒有相關信息",
    "找不到相關資訊",
    "找不到相關信息",
    "並未記載",
    "未記載",
    "未特別說明",
    "未提供相關",
    "無法從企業知識庫",
    "無法從知識庫",
    "找不到可確認",
    "尚無可確認",
    "知識庫未提供",
    "知識庫中並無",
    "知識庫中並未",
    "目前知識庫中並無",
    "目前知識庫中並未",
)
_KNOWLEDGE_GAP_PATTERN = re.compile(
    r"(?:知識庫|知識內容|企業知識庫)(?:中|內)?"
    r"(?:沒有足夠|缺乏|不足|並未記載|未記載|並無|並未|未提供|找不到)"
)

GRADE_PROMPT = """\
Determine whether the retrieved internal documents contain information relevant to the
user question. Be lenient about synonyms but reject unrelated documents.

Special Instructions:
- For questions asking what a source can support, its coverage, boundaries, or limitations (e.g. 來源能支持哪些答案, 支援範圍, 限制, 單一窗口), the document describing that system or its responsible window IS RELEVANT, even if the document only designates an escalation unit or contact.
- If any retrieved document directly discusses the specific system, feature, or error mentioned in the question, mark relevant=True.

Question:
{question}

Retrieved context:
{context}
"""


def distinctive_query_tokens(query: str) -> set[str]:
    tokens: set[str] = set()
    for token in tokenize(query):
        if token in _GENERIC_LEXICAL_TOKENS:
            continue
        if re.fullmatch(r"[a-z0-9_./:-]+", token):
            if len(token) >= 2:
                tokens.add(token)
            continue
        if len(token) >= 2:
            tokens.add(token)
            continue
        if re.fullmatch(r"[\u3400-\u9fff]", token):
            tokens.add(token)
    return tokens


def primary_distinctive_tokens(query: str) -> set[str]:
    primary: set[str] = set()
    for token in distinctive_query_tokens(query):
        if re.fullmatch(r"[a-z0-9_./:-]+", token):
            primary.add(token)
            continue
        if len(token) >= 2 and not all(character in _SUBJECT_CHAR_STOP for character in token):
            primary.add(token)
    return primary


def high_confidence_retrieval_hit(query: str, top: SearchResult) -> bool:
    """Accept a strong top hit without LLM grading when terms clearly overlap."""

    if top.score < HIGH_CONFIDENCE_RETRIEVAL_MIN_SCORE:
        return False
    document_tokens = set(tokenize(f"{top.chunk.title}\n{top.chunk.content}"))
    primary = primary_distinctive_tokens(query)
    if not primary:
        return False
    return bool(primary & document_tokens)


def query_lexically_matches_results(query: str, results: list[SearchResult]) -> bool:
    """Conservative offline relevance guard when no LLM grader is configured."""
    if not results:
        return False

    distinctive = distinctive_query_tokens(query)
    primary = primary_distinctive_tokens(query)
    if not distinctive or not primary:
        return False

    document_tokens: set[str] = set()
    for result in results:
        document_tokens.update(tokenize(f"{result.chunk.title}\n{result.chunk.content}"))
    if not primary & document_tokens:
        return False

    overlap = distinctive & document_tokens
    if len(distinctive) == 1:
        token = next(iter(distinctive))
        return token in document_tokens and results[0].score >= _OFFLINE_SINGLE_TOKEN_MIN_SCORE

    overlap_count = len(overlap)
    overlap_ratio = overlap_count / len(distinctive)
    return (
        overlap_count >= _OFFLINE_RELEVANCE_MIN_OVERLAP
        and overlap_ratio >= _OFFLINE_RELEVANCE_MIN_RATIO
    )


def answer_indicates_insufficient_information(answer: str) -> bool:
    """Whether a generated answer explicitly says the KB cannot answer.

    In that case sources and images would imply support that the answer just
    denied, so HYBRID reports a strict miss instead.
    """
    normalized = answer.lower()
    return bool(_KNOWLEDGE_GAP_PATTERN.search(normalized)) or any(
        marker in normalized for marker in _INSUFFICIENT_INFORMATION_MARKERS
    )


def conflicting_top_candidates(results: list[SearchResult]) -> bool:
    """True when top-1/top-2 scores are close but domain cues conflict."""
    if len(results) < 2:
        return False
    top1 = results[0]
    top2 = results[1]
    if top1.score - top2.score >= _CLOSE_SCORE_GAP:
        return False
    t1 = f"{top1.chunk.title} {top1.chunk.section or ''}".lower()
    t2 = f"{top2.chunk.title} {top2.chunk.section or ''}".lower()
    return (
        ("outlook" in t1 and ("話機" in t2 or "ip話機" in t2))
        or ("outlook" in t2 and ("話機" in t1 or "ip話機" in t1))
        or ("外部客戶" in t1 and "外部客戶" not in t2)
        or ("外部客戶" in t2 and "外部客戶" not in t1)
        or ("webex" in t1 and "webex" not in t2)
        or ("webex" in t2 and "webex" not in t1)
        or ("xq" in t1 and "xq" not in t2)
        or ("xq" in t2 and "xq" not in t1)
    )


def evaluate_retrieval_confidence(
    *,
    query: str,
    results: list[SearchResult],
    min_score: float,
    filter_displaced_top1: bool,
) -> tuple[str, bool]:
    """Return ``(decision_label, is_deterministic_pass)`` for a retrieval pool.

    Delegates to the shared Confidence Contract so eval No-answer predictors and
    production relevance routing stay aligned.
    """
    from .retrieval_confidence import evaluate_retrieval_confidence as _shared

    return _shared(
        query=query,
        results=results,
        min_score=min_score,
        filter_displaced_top1=filter_displaced_top1,
    )


def annotate_relevance_attempts(
    attempts: list[RetrievalAttempt],
    *,
    decision: str,
    is_relevant: bool,
) -> None:
    for attempt in attempts:
        if attempt.decision is None:
            attempt.decision = decision
            attempt.isRelevant = is_relevant


def deterministic_relevance_without_model(
    *,
    query: str,
    results: list[SearchResult],
    is_deterministic: bool,
) -> bool:
    """Offline relevance when no chat model is configured for grading."""
    return (
        is_deterministic
        or query_lexically_matches_results(query, results)
        or (
            bool(results)
            and high_confidence_retrieval_hit(query, results[0])
        )
    )


def build_relevance_grade_context(results: list[SearchResult], *, limit: int = 3) -> str:
    """Format top candidates for the LLM relevance grader.

    Prefer highest-score unique titles. Fusion/document-selection order can put
    hard-negatives first while the answerable hit sits just outside the top-N
    window the grader sees.
    """
    ranked = sorted(
        results,
        key=lambda result: float(result.score or 0.0),
        reverse=True,
    )
    grade_results: list[SearchResult] = []
    seen_titles: set[str] = set()
    for result in ranked:
        title = (result.chunk.title or "").strip() or result.chunk.chunk_id
        if title in seen_titles:
            continue
        seen_titles.add(title)
        grade_results.append(result)
        if len(grade_results) >= limit:
            break
    return "\n\n".join(
        f"[{result.chunk.title}]\n{result.chunk.content}" for result in grade_results
    )


def format_grade_prompt(*, question: str, context: str) -> str:
    return GRADE_PROMPT.format(question=question, context=context)
