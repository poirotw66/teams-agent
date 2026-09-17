"""Production-parity baseline evaluation primitives.

The target receives only the user question and opaque request identifiers.
Reference answers, rubrics, and expected sources remain exclusively in the
judge process.
"""

from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx

from .baseline_judge import GeminiAnswerJudge
from .baseline_scoring import (
    JudgeAssessment,
    inconclusive_assessment,
    score_retrieval,
)

__all__ = [
    "AgentTargetResult",
    "GeminiAnswerJudge",
    "JudgeAssessment",
    "KnowledgeBaselineCase",
    "ProductionAgentHttpTarget",
    "QuestionBankValidationError",
    "inconclusive_assessment",
    "load_question_bank_csv",
    "score_retrieval",
]

REQUIRED_CSV_HEADERS = (
    "題號",
    "主題",
    "難度",
    "Coverage",
    "題目",
    "詳細答案",
    "解析",
    "來源頁",
)
SOURCE_SEPARATOR = re.compile(r"\s*[｜|]\s*")
MARKDOWN_LINK = re.compile(r"^\[([^\]]+)\]\([^)]+\)$")


class QuestionBankValidationError(ValueError):
    """Raised when a question-bank CSV cannot form an evaluation contract."""


@dataclass(frozen=True)
class KnowledgeBaselineCase:
    case_id: str
    topic: str
    difficulty: str
    coverage: str
    question: str
    reference_answer: str
    rubric: str
    expected_sources: tuple[str, ...]


@dataclass(frozen=True)
class AgentTargetResult:
    answer: str
    citations: tuple[dict[str, object], ...]
    issue_results: tuple[dict[str, object], ...]
    correlation_id: str | None
    latency_ms: float
    error: str | None = None


def load_question_bank_csv(path: Path) -> list[KnowledgeBaselineCase]:
    """Load the approved Traditional Chinese question-bank CSV."""

    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        headers = tuple(reader.fieldnames or ())
        missing = [header for header in REQUIRED_CSV_HEADERS if header not in headers]
        if missing:
            raise QuestionBankValidationError(
                f"Question bank is missing required headers: {', '.join(missing)}"
            )
        rows = list(reader)

    cases = [_parse_case(row, row_number=index) for index, row in enumerate(rows, start=2)]
    if not cases:
        raise QuestionBankValidationError("Question bank must contain at least one case")
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise QuestionBankValidationError("Question bank contains duplicate case IDs")
    return cases


def _parse_case(row: dict[str, str | None], *, row_number: int) -> KnowledgeBaselineCase:
    values = {key: str(row.get(key) or "").strip() for key in REQUIRED_CSV_HEADERS}
    empty = [key for key, value in values.items() if not value]
    if empty:
        raise QuestionBankValidationError(
            f"Question bank row {row_number} has empty fields: {', '.join(empty)}"
        )
    return KnowledgeBaselineCase(
        case_id=values["題號"],
        topic=values["主題"],
        difficulty=values["難度"],
        coverage=values["Coverage"],
        question=values["題目"],
        reference_answer=values["詳細答案"],
        rubric=values["解析"],
        expected_sources=_parse_sources(values["來源頁"]),
    )


def _parse_sources(value: str) -> tuple[str, ...]:
    sources: list[str] = []
    for raw_source in SOURCE_SEPARATOR.split(value):
        source = raw_source.strip()
        markdown_match = MARKDOWN_LINK.fullmatch(source)
        if markdown_match:
            source = markdown_match.group(1).strip()
        if source:
            sources.append(source)
    return tuple(sources)


class ProductionAgentHttpTarget:
    """Execute cases through the secured production Agent workflow contract."""

    def __init__(
        self,
        *,
        base_url: str,
        tenant_id: str,
        token: str | None = None,
        timeout_seconds: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout_seconds,
            transport=transport,
        )
        self._tenant_id = tenant_id

    async def execute(self, *, case_id: str, question: str) -> AgentTargetResult:
        request_id = f"golden-baseline-{case_id}-{uuid4().hex[:12]}"
        payload = {
            "requestId": request_id,
            "channel": "evaluation",
            "conversation": {
                "tenantId": self._tenant_id,
                "conversationId": request_id,
            },
            "user": {
                "teamsUserId": "golden-baseline-user",
                "displayName": "Golden Baseline",
            },
            "message": {"text": question, "locale": "zh-TW"},
            "correlationId": request_id,
        }
        started_at = time.perf_counter()
        try:
            response = await self._client.post("/agent/evaluation/chat", json=payload)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as error:
            return AgentTargetResult(
                answer="",
                citations=(),
                issue_results=(),
                correlation_id=request_id,
                latency_ms=round((time.perf_counter() - started_at) * 1000, 2),
                error=f"{type(error).__name__}: {error}",
            )
        return AgentTargetResult(
            answer=str(body.get("answer") or ""),
            citations=tuple(body.get("citations") or ()),
            issue_results=tuple(body.get("issueResults") or ()),
            correlation_id=body.get("correlationId") or body.get("traceId"),
            latency_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )

    async def aclose(self) -> None:
        await self._client.aclose()
