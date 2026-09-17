from __future__ import annotations

import asyncio

import pytest

from ai_ops_backoffice.evaluation_domain.baseline import (
    AgentTargetResult,
    KnowledgeBaselineCase,
)
from ai_ops_backoffice.evaluation_domain.baseline_pipeline import (
    run_baseline_pipeline,
)
from ai_ops_backoffice.evaluation_domain.baseline_scoring import (
    JudgeAssessment,
    inconclusive_assessment,
)


def _cases(count: int) -> list[KnowledgeBaselineCase]:
    return [
        KnowledgeBaselineCase(
            case_id=f"QB-{index:03d}",
            topic="VPN",
            difficulty="基礎",
            coverage="pipeline",
            question=f"Question {index}",
            reference_answer="Reference",
            rubric="Rubric",
            expected_sources=(),
        )
        for index in range(1, count + 1)
    ]


class ControlledTarget:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.two_started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(self, *, case_id: str, question: str) -> AgentTargetResult:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        if self.active == 2:
            self.two_started.set()
        await self.release.wait()
        self.active -= 1
        return AgentTargetResult(
            answer=question,
            citations=(),
            issue_results=(),
            correlation_id=case_id,
            latency_ms=1.0,
        )


class ControlledJudge:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.three_started = asyncio.Event()
        self.release = asyncio.Event()

    async def judge(
        self,
        case: KnowledgeBaselineCase,
        target: AgentTargetResult,
    ) -> JudgeAssessment:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        if self.active == 3:
            self.three_started.set()
        await self.release.wait()
        self.active -= 1
        return inconclusive_assessment(
            expected_sources=case.expected_sources,
            citations=target.citations,
            reason="Controlled test result.",
        )


@pytest.mark.asyncio
async def test_pipeline_uses_independent_stage_concurrency() -> None:
    target = ControlledTarget()
    judge = ControlledJudge()

    async def collect_results() -> list[object]:
        return [
            result
            async for result in run_baseline_pipeline(
                cases=_cases(6),
                target=target,
                judge=judge,
                agent_concurrency=2,
                judge_concurrency=3,
            )
        ]

    collection = asyncio.create_task(collect_results())
    await asyncio.wait_for(target.two_started.wait(), timeout=1.0)
    assert target.max_active == 2

    target.release.set()
    await asyncio.wait_for(judge.three_started.wait(), timeout=1.0)
    assert judge.max_active == 3

    judge.release.set()
    results = await asyncio.wait_for(collection, timeout=1.0)
    assert len(results) == 6
    assert all(result.judge_queue_ms >= 0 for result in results)
    assert all(result.judge_latency_ms >= 0 for result in results)


class FailingJudge:
    async def judge(
        self,
        case: KnowledgeBaselineCase,
        target: AgentTargetResult,
    ) -> JudgeAssessment:
        raise RuntimeError(f"Judge unavailable for {case.case_id}")


@pytest.mark.asyncio
async def test_pipeline_isolates_judge_failure_per_case() -> None:
    target = ControlledTarget()
    target.release.set()
    results = [
        result
        async for result in run_baseline_pipeline(
            cases=_cases(1),
            target=target,
            judge=FailingJudge(),
            agent_concurrency=1,
            judge_concurrency=1,
        )
    ]

    assert results[0].assessment.verdict == "INCONCLUSIVE"
    assert "Judge unavailable" in results[0].assessment.reason
