"""Two-stage concurrency pipeline for Golden baseline execution."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from .baseline import AgentTargetResult, KnowledgeBaselineCase
from .baseline_scoring import JudgeAssessment, inconclusive_assessment


class BaselineTarget(Protocol):
    async def execute(self, *, case_id: str, question: str) -> AgentTargetResult: ...


class BaselineJudge(Protocol):
    async def judge(
        self,
        case: KnowledgeBaselineCase,
        target: AgentTargetResult,
    ) -> JudgeAssessment: ...


@dataclass(frozen=True)
class BaselinePipelineResult:
    index: int
    case: KnowledgeBaselineCase
    target: AgentTargetResult
    assessment: JudgeAssessment
    judge_queue_ms: float
    judge_latency_ms: float


async def run_baseline_pipeline(
    *,
    cases: list[KnowledgeBaselineCase],
    target: BaselineTarget,
    judge: BaselineJudge,
    agent_concurrency: int,
    judge_concurrency: int,
) -> AsyncIterator[BaselinePipelineResult]:
    """Run target and Judge stages with independent concurrency limits."""

    agent_semaphore = asyncio.Semaphore(max(1, agent_concurrency))
    judge_semaphore = asyncio.Semaphore(max(1, judge_concurrency))

    async def execute_target(case: KnowledgeBaselineCase) -> AgentTargetResult:
        async with agent_semaphore:
            return await target.execute(case_id=case.case_id, question=case.question)

    async def judge_target(
        index: int,
        case: KnowledgeBaselineCase,
        target_task: asyncio.Task[AgentTargetResult],
    ) -> BaselinePipelineResult:
        target_result = await target_task
        queued_at = time.perf_counter()
        async with judge_semaphore:
            judge_queue_ms = (time.perf_counter() - queued_at) * 1000
            started_at = time.perf_counter()
            assessment = await _judge_case(judge, case, target_result)
            judge_latency_ms = (time.perf_counter() - started_at) * 1000
        return BaselinePipelineResult(
            index=index,
            case=case,
            target=target_result,
            assessment=assessment,
            judge_queue_ms=round(judge_queue_ms, 2),
            judge_latency_ms=round(judge_latency_ms, 2),
        )

    target_tasks = [asyncio.create_task(execute_target(case)) for case in cases]
    judge_tasks = [
        asyncio.create_task(judge_target(index, case, target_tasks[index]))
        for index, case in enumerate(cases)
    ]
    try:
        for task in asyncio.as_completed(judge_tasks):
            yield await task
    finally:
        for task in (*target_tasks, *judge_tasks):
            if not task.done():
                task.cancel()
        await asyncio.gather(*target_tasks, *judge_tasks, return_exceptions=True)


async def _judge_case(
    judge: BaselineJudge,
    case: KnowledgeBaselineCase,
    target: AgentTargetResult,
) -> JudgeAssessment:
    try:
        return await judge.judge(case, target)
    except Exception as error:  # noqa: BLE001 - isolate Judge failures per case
        return inconclusive_assessment(
            expected_sources=case.expected_sources,
            citations=target.citations,
            reason=f"Judge execution failed: {type(error).__name__}: {error}",
        )
