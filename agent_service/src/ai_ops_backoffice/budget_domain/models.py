from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_service.operations.access import ActorContext
from agent_service.operations.masking import mask_text




class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

class BudgetPolicy(StrictModel):
    policy_id: str
    scope_type: Literal["PERSONAL", "SERVICE", "TEAM", "TENANT", "GLOBAL", "MODEL"]
    scope_id: str
    period: Literal["DAILY", "MONTHLY"]
    measure: Literal["TWD", "USD", "TOKEN", "LLM_CALL_COUNT"]
    warning_threshold: float = Field(gt=0)
    critical_threshold: float = Field(gt=0)
    enabled: bool = True
    effective_at: datetime
    expires_at: datetime | None = None
    owner_unit_id: str
    notification_target_ids: tuple[str, ...]
    pricing_version: str
    exchange_rate_version: str
    etag: int = Field(default=1, ge=1)
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime

class AlertEvent(StrictModel):
    alert_id: str
    policy_id: str | None = None
    alert_type: Literal["BUDGET_THRESHOLD", "SYNC_FAILURE", "API_ANOMALY"] = "BUDGET_THRESHOLD"
    severity: Literal["WARNING", "CRITICAL"]
    scope_type: str
    scope_id: str
    period_key: str
    suppression_key: str
    threshold: float = 0.0
    actual_value: float = 0.0
    coverage: float = Field(default=1.0, ge=0, le=1)
    pricing_version: str = "v1"
    exchange_rate_version: str = "v1"
    status: Literal["OPEN", "ACKNOWLEDGED", "RESOLVED"] = "OPEN"
    owner_unit_id: str
    first_triggered_at: datetime
    last_triggered_at: datetime
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    resolution_note: str | None = None
    message: str | None = None
    etag: int = Field(default=1, ge=1)

class NotificationDelivery(StrictModel):
    delivery_id: str
    alert_id: str
    target_id: str
    channel: Literal["TEAMS", "EMAIL", "NOTIFICATION_CENTER"]
    status: Literal["PENDING", "SENT", "FAILED"] = "PENDING"
    summary: str
    attempt_count: int = 0
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime

class BudgetAuditEvent(StrictModel):
    audit_id: str
    target_type: Literal["BUDGET_POLICY", "ALERT"]
    target_id: str
    action: str
    actor_id: str
    actor_role: str
    owner_unit_id: str
    reason: str | None = None
    occurred_at: datetime

class BudgetState(StrictModel):
    revision: int = 0
    policies: tuple[BudgetPolicy, ...] = ()
    alerts: tuple[AlertEvent, ...] = ()
    deliveries: tuple[NotificationDelivery, ...] = ()
    audits: tuple[BudgetAuditEvent, ...] = ()


Mutation = Callable[[BudgetState], tuple[BudgetState, dict[str, Any]]]

