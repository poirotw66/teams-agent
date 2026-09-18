"""Pydantic request models for workbench routes."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class QuickFaqSaveRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str | None = None
    question: str
    answer: str
    category: str = "差勤/人資"
    resolveConversationId: str | None = None


class TicketCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    conversationId: str | None = None
    title: str
    reporterName: str
    reporterDept: str
    reporterExt: str | None = None
    category: str = "HARDWARE"
    assignedTeam: str = "現場硬體組"
    notes: str | None = None


class ConversationActionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    action: str  # "resolve" | "root_cause"
    root_cause: str | None = None


class BroadcastRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message: str
    durationHours: int = 2


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    query: str
