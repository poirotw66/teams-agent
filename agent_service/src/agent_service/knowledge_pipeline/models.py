"""Shared knowledge-pipeline result models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agent_service.contracts import GroundedClaim


class RelevanceDecision(BaseModel):
    relevant: bool


class RewrittenQuery(BaseModel):
    query: str


class StructuredKnowledgeAnswer(BaseModel):
    answerability: Literal["FULL", "PARTIAL", "NONE"]
    answer: str
    claims: list[GroundedClaim]
    unknowns: list[str]


class GroundedClaimRepair(BaseModel):
    claims: list[GroundedClaim] = Field(
        default_factory=list,
        description="List of atomic factual claims supported by context chunks.",
    )
