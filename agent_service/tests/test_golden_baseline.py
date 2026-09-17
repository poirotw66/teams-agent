from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.exceptions import OutputParserException

from ai_ops_backoffice.evaluation_domain.baseline import (
    AgentTargetResult,
    GeminiAnswerJudge,
    KnowledgeBaselineCase,
    ProductionAgentHttpTarget,
    QuestionBankValidationError,
    load_question_bank_csv,
    score_retrieval,
)

CSV_HEADERS = "題號,主題,難度,Coverage,題目,詳細答案,解析,來源頁\n"


def test_question_bank_loader_preserves_judge_only_fields(tmp_path: Path) -> None:
    question_bank = tmp_path / "questions.csv"
    question_bank.write_text(
        CSV_HEADERS
        + "QB-001,VPN,進階,vpn-routing,VPN 錯誤怎麼辦？,"
        + "依錯誤碼分流,不得假設唯一根因,"
        + "[VPN 常見問答](../../raw/vpn.md)｜FortiClient 排解\n",
        encoding="utf-8",
    )

    cases = load_question_bank_csv(question_bank)

    assert len(cases) == 1
    assert cases[0].reference_answer == "依錯誤碼分流"
    assert cases[0].rubric == "不得假設唯一根因"
    assert cases[0].expected_sources == ("VPN 常見問答", "FortiClient 排解")


def test_question_bank_loader_rejects_duplicate_ids(tmp_path: Path) -> None:
    question_bank = tmp_path / "questions.csv"
    row = "QB-001,VPN,基礎,vpn,問題,答案,解析,來源\n"
    question_bank.write_text(CSV_HEADERS + row + row, encoding="utf-8")

    with pytest.raises(QuestionBankValidationError, match="duplicate"):
        load_question_bank_csv(question_bank)


@pytest.mark.asyncio
async def test_production_target_receives_question_without_golden_fields() -> None:
    captured: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["request_path"] = request.url.path
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "answer": "請依文件操作。[S1]",
                "traceId": "trace-1",
                "correlationId": "trace-1",
                "citations": [{"title": "VPN 指南"}],
                "issueResults": [],
                "feedbackEnabled": False,
            },
        )

    target = ProductionAgentHttpTarget(
        base_url="https://agent.example",
        tenant_id="tenant-eval",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await target.execute(case_id="QB-001", question="VPN 要如何設定？")
    finally:
        await target.aclose()

    assert result.answer == "請依文件操作。[S1]"
    assert captured["request_path"] == "/agent/evaluation/chat"
    assert captured["message"] == {"text": "VPN 要如何設定？", "locale": "zh-TW"}
    serialized = json.dumps(captured, ensure_ascii=False)
    assert "reference_answer" not in serialized
    assert "rubric" not in serialized
    assert "expected_sources" not in serialized


class FailingJudgeModel:
    def with_structured_output(self, _schema: object) -> FailingJudgeModel:
        return self

    async def ainvoke(self, _messages: object) -> object:
        raise AssertionError("Judge must not run after target failure")


@pytest.mark.asyncio
async def test_judge_marks_target_failure_inconclusive() -> None:
    case = KnowledgeBaselineCase(
        case_id="QB-001",
        topic="VPN",
        difficulty="基礎",
        coverage="vpn",
        question="VPN 要如何設定？",
        reference_answer="依核准流程操作。",
        rubric="不得編造。",
        expected_sources=("VPN 指南",),
    )
    target = AgentTargetResult(
        answer="",
        citations=(),
        issue_results=(),
        correlation_id="trace-1",
        latency_ms=1.0,
        error="HTTPStatusError: unavailable",
    )
    judge = GeminiAnswerJudge(
        model_id="test-judge",
        model=FailingJudgeModel(),  # type: ignore[arg-type]
    )

    assessment = await judge.judge(case, target)

    assert assessment.verdict == "INCONCLUSIVE"
    assert "Target execution failed" in assessment.reason


class SchemaRetryJudgeModel:
    def __init__(self) -> None:
        self.call_count = 0

    def with_structured_output(self, _schema: object) -> SchemaRetryJudgeModel:
        return self

    async def ainvoke(self, messages: object) -> object:
        self.call_count += 1
        if self.call_count == 1:
            raise OutputParserException("reason must not be empty")
        assert "failed validation" in str(messages).lower()
        return {
            "correctness": 1.0,
            "completeness": 1.0,
            "groundedness": 1.0,
            "claims": [
                {
                    "claim": "Follow the approved process.",
                    "support": "SUPPORTED",
                    "source_chunk_ids": ["crm-1"],
                    "explanation": "The cited evidence contains the approved process.",
                }
            ],
            "missing_required_facts": [],
            "verdict": "PASS",
            "confidence": 1.0,
            "reason": "The answer matches the reference and cited evidence.",
        }


class InvalidSchemaJudgeModel:
    def __init__(self) -> None:
        self.call_count = 0

    def with_structured_output(self, _schema: object) -> InvalidSchemaJudgeModel:
        return self

    async def ainvoke(self, _messages: object) -> object:
        self.call_count += 1
        raise OutputParserException("reason must not be empty")


def _judge_retry_case() -> tuple[KnowledgeBaselineCase, AgentTargetResult]:
    return (
        KnowledgeBaselineCase(
            case_id="QB-029",
            topic="CRM",
            difficulty="基礎",
            coverage="crm",
            question="如何處理？",
            reference_answer="依核准流程處理。",
            rubric="回答必須有依據。",
            expected_sources=("CRM 指南",),
        ),
        AgentTargetResult(
            answer="請依核准流程處理。[S1]",
            citations=(
                {
                    "title": "CRM 指南",
                    "chunkId": "crm-1",
                    "evidence": "[chunkId=crm-1]\n依核准流程處理。",
                },
            ),
            issue_results=(),
            correlation_id="trace-29",
            latency_ms=1.0,
        ),
    )


@pytest.mark.asyncio
async def test_judge_retries_invalid_structured_output() -> None:
    case, target = _judge_retry_case()
    model = SchemaRetryJudgeModel()
    judge = GeminiAnswerJudge(
        model_id="test-judge",
        model=model,  # type: ignore[arg-type]
        max_attempts=2,
    )

    assessment = await judge.judge(case, target)

    assert assessment.verdict == "PASS"
    assert model.call_count == 2


class MaterialGapPassJudgeModel:
    def with_structured_output(self, _schema: object) -> MaterialGapPassJudgeModel:
        return self

    async def ainvoke(self, _messages: object) -> object:
        return {
            "correctness": 0.9,
            "completeness": 0.8,
            "groundedness": 1.0,
            "claims": [
                {
                    "claim": "Follow the approved process.",
                    "support": "SUPPORTED",
                    "source_chunk_ids": ["crm-1"],
                    "explanation": "The evidence states the approved process.",
                }
            ],
            "missing_required_facts": ["Confirm the final validation step."],
            "verdict": "PASS",
            "confidence": 0.95,
            "reason": "The answer is mostly correct.",
        }


@pytest.mark.asyncio
async def test_judge_policy_downgrades_pass_with_material_gap() -> None:
    case, target = _judge_retry_case()
    judge = GeminiAnswerJudge(
        model_id="test-judge",
        model=MaterialGapPassJudgeModel(),  # type: ignore[arg-type]
    )

    assessment = await judge.judge(case, target)

    assert assessment.verdict == "PARTIAL"
    assert assessment.needs_human_review is True
    assert assessment.primary_assessment is not None
    assert assessment.primary_assessment.verdict == "PASS"


def test_retrieval_scoring_matches_titles_and_source_paths() -> None:
    assessment = score_retrieval(
        ("VPN 操作手冊", "AD 帳號 FAQ"),
        (
            {"title": "VPN 操作手冊"},
            {
                "title": "帳號解鎖",
                "sourcePath": "sources/AD帳號FAQ.md",
            },
        ),
    )

    assert assessment.source_recall == 1.0
    assert assessment.missing_sources == []


def test_retrieval_scoring_uses_auditable_title_similarity_fallback() -> None:
    assessment = score_retrieval(
        ("GitLab 帳號解鎖與重置",),
        ({"title": "Gitlab帳號解鎖跟重置"},),
    )

    assert assessment.source_recall == 1.0
    assert assessment.matches[0].method == "TITLE_SIMILARITY"
    assert assessment.matches[0].similarity == 0.9231


class AdjudicationJudgeModel:
    def __init__(self) -> None:
        self.call_count = 0

    def with_structured_output(self, _schema: object) -> AdjudicationJudgeModel:
        return self

    async def ainvoke(self, _messages: object) -> object:
        self.call_count += 1
        verdicts = ("PARTIAL", "PASS", "PARTIAL")
        verdict = verdicts[self.call_count - 1]
        return {
            "correctness": 0.8,
            "completeness": 0.7,
            "groundedness": 1.0,
            "claims": [
                {
                    "claim": "Follow the approved process.",
                    "support": "SUPPORTED",
                    "source_chunk_ids": ["crm-1"],
                    "explanation": "The evidence states the approved process.",
                }
            ],
            "missing_required_facts": ["Confirm the final validation step."],
            "verdict": verdict,
            "confidence": 0.7 if self.call_count == 1 else 0.9,
            "reason": f"Independent assessment {self.call_count}.",
        }


@pytest.mark.asyncio
async def test_judge_adjudicates_disagreeing_independent_reviews() -> None:
    case, target = _judge_retry_case()
    model = AdjudicationJudgeModel()
    judge = GeminiAnswerJudge(
        model_id="test-judge",
        model=model,  # type: ignore[arg-type]
    )

    assessment = await judge.judge(case, target)

    assert assessment.verdict == "PARTIAL"
    assert assessment.review_status == "ADJUDICATED"
    assert assessment.secondary_verdict == "PASS"
    assert assessment.primary_assessment is not None
    assert assessment.primary_assessment.verdict == "PARTIAL"
    assert assessment.secondary_assessment is not None
    assert assessment.secondary_assessment.verdict == "PASS"
    assert assessment.adjudication_assessment is not None
    assert assessment.adjudication_assessment.verdict == "PARTIAL"
    assert assessment.needs_human_review is True
    assert model.call_count == 3


class EvidenceReferenceRetryJudgeModel:
    def __init__(self) -> None:
        self.call_count = 0

    def with_structured_output(
        self,
        _schema: object,
    ) -> EvidenceReferenceRetryJudgeModel:
        return self

    async def ainvoke(self, _messages: object) -> object:
        self.call_count += 1
        chunk_id = "unknown" if self.call_count == 1 else "crm-1"
        return {
            "correctness": 1.0,
            "completeness": 1.0,
            "groundedness": 1.0,
            "claims": [
                {
                    "claim": "Follow the approved process.",
                    "support": "SUPPORTED",
                    "source_chunk_ids": [chunk_id],
                    "explanation": "The evidence describes the approved process.",
                }
            ],
            "missing_required_facts": [],
            "verdict": "PASS",
            "confidence": 1.0,
            "reason": "The answer is supported.",
        }


@pytest.mark.asyncio
async def test_judge_retries_unknown_claim_evidence_reference() -> None:
    case, target = _judge_retry_case()
    model = EvidenceReferenceRetryJudgeModel()
    judge = GeminiAnswerJudge(
        model_id="test-judge",
        model=model,  # type: ignore[arg-type]
    )

    assessment = await judge.judge(case, target)

    assert assessment.claim_assessments[0].source_chunk_ids == ["crm-1"]
    assert model.call_count == 2


class ContradictedClaimJudgeModel:
    def with_structured_output(self, _schema: object) -> ContradictedClaimJudgeModel:
        return self

    async def ainvoke(self, _messages: object) -> object:
        return {
            "correctness": 0.0,
            "completeness": 0.0,
            "groundedness": 0.0,
            "claims": [
                {
                    "claim": "Support staff may complete the process for the user.",
                    "support": "UNSUPPORTED",
                    "source_chunk_ids": ["crm-1"],
                    "explanation": "The evidence requires the user to complete it.",
                }
            ],
            "missing_required_facts": [],
            "verdict": "FAIL",
            "confidence": 0.95,
            "reason": "The candidate claim contradicts the evidence.",
        }


@pytest.mark.asyncio
async def test_unsupported_claim_can_reference_contradictory_evidence() -> None:
    case, target = _judge_retry_case()
    judge = GeminiAnswerJudge(
        model_id="test-judge",
        model=ContradictedClaimJudgeModel(),  # type: ignore[arg-type]
    )

    assessment = await judge.judge(case, target)

    assert assessment.verdict == "FAIL"
    assert assessment.claim_assessments[0].source_chunk_ids == ["crm-1"]


@pytest.mark.asyncio
async def test_judge_stops_after_configured_schema_attempts() -> None:
    case, target = _judge_retry_case()
    model = InvalidSchemaJudgeModel()
    judge = GeminiAnswerJudge(
        model_id="test-judge",
        model=model,  # type: ignore[arg-type]
        max_attempts=2,
    )

    with pytest.raises(OutputParserException, match="reason must not be empty"):
        await judge.judge(case, target)

    assert model.call_count == 2
