from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PromptVersionRecord(StrictModel):
    prompt_id: str
    version: str
    status: str = "DRAFT"
    content_hash: str
    change_reason: str | None = None


class ModelConfigRecord(StrictModel):
    config_id: str
    provider: str
    model_id: str
    component: str
    status: str = "DRAFT"


class FeatureFlagRecord(StrictModel):
    flag_id: str
    description: str
    flag_type: str = "boolean"
    status: str = "DRAFT"
    default_value: str | bool = False


class Phase3Registry:
    """In-memory scaffold for Phase 3 governance entities."""

    def __init__(self) -> None:
        self.prompts: list[PromptVersionRecord] = []
        self.model_configs: list[ModelConfigRecord] = []
        self.feature_flags: list[FeatureFlagRecord] = []

    def list_prompts(self) -> list[dict[str, Any]]:
        return [item.model_dump() for item in self.prompts]

    def list_model_configs(self) -> list[dict[str, Any]]:
        return [item.model_dump() for item in self.model_configs]

    def list_feature_flags(self) -> list[dict[str, Any]]:
        return [item.model_dump() for item in self.feature_flags]
