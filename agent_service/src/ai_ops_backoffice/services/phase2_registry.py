from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FaqRecord(StrictModel):
    faq_id: str
    faq_key: str
    question: str
    answer: str
    status: str = "DRAFT"
    owner_unit_id: str


class QualityCaseRecord(StrictModel):
    case_id: str
    title: str
    case_type: str
    status: str = "NEW"
    priority: str = "MEDIUM"
    owner_unit_id: str


class SyncJobRecord(StrictModel):
    job_id: str
    scope_type: str
    status: str = "QUEUED"
    reason: str


class BudgetPolicyRecord(StrictModel):
    policy_id: str
    scope: str
    period: str
    measure: str
    warning_threshold: float
    critical_threshold: float
    enabled: bool = True


class Phase2Registry:
    """In-memory scaffold for Phase 2 entities until persistent stores land."""

    def __init__(self) -> None:
        self.faqs: list[FaqRecord] = []
        self.quality_cases: list[QualityCaseRecord] = []
        self.sync_jobs: list[SyncJobRecord] = []
        self.budget_policies: list[BudgetPolicyRecord] = []

    def list_faqs(self) -> list[dict[str, Any]]:
        return [item.model_dump() for item in self.faqs]

    def list_quality_cases(self) -> list[dict[str, Any]]:
        return [item.model_dump() for item in self.quality_cases]

    def list_sync_jobs(self) -> list[dict[str, Any]]:
        return [item.model_dump() for item in self.sync_jobs]

    def list_budget_policies(self) -> list[dict[str, Any]]:
        return [item.model_dump() for item in self.budget_policies]
