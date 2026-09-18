from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

class PromptCandidate(StrictModel):
    candidate_id: str
    prompt_id: str
    version: str
    status: str = "CANDIDATE"
    content: str
    content_hash: str
    active_prompt_version: str
    dataset_version: str
    taxonomy_version: str
    data_range_start: datetime
    data_range_end: datetime
    masking_policy_version: str
    model_id: str = "deterministic-phase2-poc"
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0
    generated_by: str
    correlation_id: str
    created_at: datetime

class PromptAuditEvent(StrictModel):
    audit_id: str
    action: str
    target_id: str
    actor_id: str
    actor_role: str
    correlation_id: str
    occurred_at: datetime

class PromptState(StrictModel):
    revision: int = 0
    candidates: tuple[PromptCandidate, ...] = ()
    audits: tuple[PromptAuditEvent, ...] = ()


Mutation = Callable[[PromptState], tuple[PromptState, dict[str, Any]]]

