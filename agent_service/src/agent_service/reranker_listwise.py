"""Gemini listwise PairScorer and title-protect wrapper (RAG v2 §45)."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Sequence

from .reranker import ModelReranker, PairScorer, Reranker
from .retrieval import SearchResult
from .retrieval_blend import blend_soft_and_listwise_top1


def scores_from_listwise_order(count: int, order: Sequence[int]) -> list[float]:
    """Map a 1-based permutation to descending scores (earlier ⇒ higher)."""
    scores = [0.0] * count
    for rank, index in enumerate(order):
        if 1 <= index <= count:
            scores[index - 1] = float(count - rank)
    for index, score in enumerate(scores):
        if score == 0.0:
            scores[index] = 0.1
    return scores


def parse_listwise_order_payload(text: str, count: int) -> list[int] | None:
    """Parse a JSON int array (or id-object array) into a 1-based permutation."""
    if count <= 0:
        return None
    payload = text or ""
    for match in re.finditer(r"\[[\d,\s]+\]", payload):
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, list) or not parsed:
            continue
        if not all(isinstance(item, int) for item in parsed):
            continue
        order = [item for item in parsed if 1 <= item <= count]
        missing = [index for index in range(1, count + 1) if index not in order]
        if order:
            return order + missing
    object_match = re.search(r"\[[\s\S]*?\]", payload)
    if not object_match:
        return None
    try:
        parsed = json.loads(object_match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list) or not parsed or not isinstance(parsed[0], dict):
        return None
    order: list[int] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        for key in ("id", "index", "rank", "n"):
            value = item.get(key)
            if isinstance(value, int) and 1 <= value <= count:
                order.append(value)
                break
    missing = [index for index in range(1, count + 1) if index not in order]
    return order + missing if order else None


def build_gemini_listwise_pair_scorer(model_id: str = "gemini-2.5-flash") -> PairScorer:
    """LLM listwise PairScorer used for §45 offline evidence (optional runtime)."""

    resolved = model_id.strip() or "gemini-2.5-flash"
    if ":" in resolved and not resolved.startswith("google_genai:"):
        resolved = resolved.split(":", 1)[1].strip() or "gemini-2.5-flash"
    langchain_id = (
        resolved if resolved.startswith("google_genai:") else f"google_genai:{resolved}"
    )

    async def score_pairs(query: str, texts: Sequence[str]) -> Sequence[float]:
        from langchain.chat_models import init_chat_model

        if not texts:
            return []
        lines: list[str] = []
        for index, text in enumerate(texts, start=1):
            snippet = (text or "").replace("\n", " ")[:180]
            lines.append(f"{index}. {snippet}")
        prompt = (
            "你是企業 IT 知識庫 listwise reranker。\n"
            "規則：FortiToken/Token OTP→VPN常見Q&A，勿選外網/國金 CRM；"
            "UX-AUDIT測試文件→FortiClient錯訊或VPN常見Q&A；登入不了→FortiClient/VPN優先於AD。\n"
            f"只輸出一個 JSON 整數陣列（長度 {len(texts)}），例如 [3,1,2,...]，"
            "禁止物件、禁止 markdown。\n\n"
            f"查詢：{query}\n\n候選：\n" + "\n".join(lines)
        )
        model = init_chat_model(langchain_id, temperature=0, timeout=90)
        response = await asyncio.to_thread(model.invoke, prompt)
        content = getattr(response, "content", str(response))
        if isinstance(content, list):
            content = "".join(getattr(part, "text", str(part)) for part in content)
        order = parse_listwise_order_payload(str(content), len(texts))
        if not order:
            raise RuntimeError("gemini listwise returned no parseable order")
        return scores_from_listwise_order(len(texts), order)

    return score_pairs


class TitleProtectedListwiseReranker:
    """Run an inner listwise reranker, then blend top-1 with Soft order (§45)."""

    def __init__(self, inner: Reranker) -> None:
        self._inner = inner

    async def rerank(
        self,
        *,
        query: str,
        candidates: list[SearchResult],
        limit: int,
    ) -> list[SearchResult]:
        if not candidates:
            return []
        listwise = await self._inner.rerank(
            query=query,
            candidates=list(candidates),
            limit=max(limit, len(candidates)),
        )
        listwise_top = listwise[0] if listwise else None
        blended = blend_soft_and_listwise_top1(
            query=query,
            soft_ranked=candidates,
            listwise_top=listwise_top,
        )
        return blended[: max(limit, 0)]


def wrap_listwise_title_protect(scorer: PairScorer) -> Reranker:
    """Compose ModelReranker + title-protect for listwise scorers."""
    return TitleProtectedListwiseReranker(ModelReranker(scorer))


__all__ = [
    "TitleProtectedListwiseReranker",
    "build_gemini_listwise_pair_scorer",
    "parse_listwise_order_payload",
    "scores_from_listwise_order",
    "wrap_listwise_title_protect",
]
