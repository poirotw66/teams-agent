"""Agent-facing Phase 3 governance runtime with fail-safe defaults."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from agent_service.extractor import SYSTEM_PROMPT
from agent_service.settings import RagSettings
from ai_ops_backoffice.governance_domain.constants import (
    FLAG_CATALOG,
    ISSUE_EXTRACTOR_PROMPT_ID,
)
from ai_ops_backoffice.governance_domain.helpers import content_hash
from ai_ops_backoffice.governance_domain.service import GovernanceService

logger = logging.getLogger(__name__)

PromptSource = Literal["governance", "code_baseline"]
ModelSource = Literal["governance", "settings_baseline"]


@dataclass(frozen=True)
class ResolvedExtractorPrompt:
    template: str
    source: PromptSource
    version_id: str | None = None
    version: str | None = None
    content_hash: str | None = None
    canary: bool = False
    sticky_bucket: int | None = None


@dataclass(frozen=True)
class ResolvedModelConfig:
    provider: str
    model_id: str
    model_name: str
    source: ModelSource
    version_id: str | None = None
    secret_ref: str | None = None
    fallback_model_id: str | None = None
    fallback_on: tuple[str, ...] = ()


def _build_governance(settings: RagSettings) -> GovernanceService | None:
    mode = settings.prompt_runtime_mode.upper()
    if mode == "CODE_BASELINE":
        return None
    if mode != "GOVERNED":
        raise ValueError(f"Unsupported prompt runtime mode: {mode}")
    from ai_ops_backoffice.governance_domain.service import GovernanceService
    from ai_ops_backoffice.governance_domain.store_factory import build_governance_repository

    store_mode = settings.prompt_governance_store_mode.upper()
    path = settings.prompt_governance_store_path or (
        settings.data_dir / "ops" / "phase3" / "governance.json"
    )
    repository = build_governance_repository(
        store_mode=store_mode,
        file_path=path,
        firestore_project=settings.prompt_governance_firestore_project,
        firestore_database=settings.prompt_governance_firestore_database,
        firestore_collection=settings.prompt_governance_firestore_collection,
    )
    return GovernanceService(repository)


class GovernanceRuntime:
    """Resolves governed prompts, models, and flags for Agent runtime."""

    def __init__(
        self,
        *,
        mode: str,
        settings: RagSettings,
        governance: GovernanceService | None = None,
        environment: str = "lab",
    ) -> None:
        self._mode = mode.upper()
        self._settings = settings
        self._governance = governance
        self._environment = environment

    @classmethod
    def from_settings(cls, settings: RagSettings) -> GovernanceRuntime:
        environment = (
            "prod"
            if settings.deployment_environment.lower() in {"prod", "production"}
            else "lab"
        )
        return cls(
            mode=settings.prompt_runtime_mode,
            settings=settings,
            governance=_build_governance(settings),
            environment=environment,
        )

    def resolve_prompt(
        self,
        *,
        tenant_id: str | None,
        conversation_id: str | None,
    ) -> ResolvedExtractorPrompt:
        baseline = ResolvedExtractorPrompt(
            template=SYSTEM_PROMPT,
            source="code_baseline",
            content_hash=content_hash(SYSTEM_PROMPT),
        )
        if self._mode != "GOVERNED" or self._governance is None:
            return baseline
        try:
            peeked = self._governance.peek_runtime_prompt(
                ISSUE_EXTRACTOR_PROMPT_ID,
                tenant=tenant_id or "default",
                conversation_id=conversation_id or "anonymous",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "governance prompt lookup failed (%s); using code baseline",
                type(exc).__name__,
            )
            return baseline
        if peeked is None:
            return baseline
        template = str(peeked.get("template") or "")
        if "{max_issues}" not in template or "{faq_keys}" not in template:
            logger.warning("governance prompt failed schema checks; using code baseline")
            return baseline
        return ResolvedExtractorPrompt(
            template=template,
            source="governance",
            version_id=str(peeked.get("versionId") or "") or None,
            version=str(peeked.get("version") or "") or None,
            content_hash=str(peeked.get("contentHash") or "") or None,
            canary=bool(peeked.get("canary")),
            sticky_bucket=int(peeked["stickyBucket"])
            if peeked.get("stickyBucket") is not None
            else None,
        )

    def resolve_model(self, *, config_id: str = "issue-extractor-model") -> ResolvedModelConfig:
        baseline_name = self._settings.agent_model or self._settings.model or ""
        provider, _, model_id = baseline_name.partition(":")
        if not model_id:
            provider, model_id = "google_genai", baseline_name or "gemini-2.5-flash"
        baseline = ResolvedModelConfig(
            provider=provider or "google_genai",
            model_id=model_id or "gemini-2.5-flash",
            model_name=baseline_name or f"google_genai:{model_id or 'gemini-2.5-flash'}",
            source="settings_baseline",
        )
        if self._mode != "GOVERNED" or self._governance is None:
            return baseline
        try:
            peeked = self._governance.peek_runtime_model(config_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "governance model lookup failed (%s); using settings baseline",
                type(exc).__name__,
            )
            return baseline
        if peeked is None:
            return baseline
        provider = str(peeked["provider"])
        model_id = str(peeked["modelId"])
        return ResolvedModelConfig(
            provider=provider,
            model_id=model_id,
            model_name=f"{provider}:{model_id}",
            source="governance",
            version_id=str(peeked.get("versionId") or "") or None,
            secret_ref=str(peeked.get("secretRef") or "") or None,
            fallback_model_id=str(peeked.get("fallbackModelId") or "") or None,
            fallback_on=tuple(peeked.get("fallbackOn") or ()),
        )

    def resolve_flag(self, flag_id: str) -> str:
        catalog = FLAG_CATALOG.get(flag_id, {})
        default = str(catalog.get("default", "false"))
        if self._mode != "GOVERNED" or self._governance is None:
            return default
        try:
            peeked = self._governance.peek_runtime_flag(
                flag_id, environment=self._environment
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "governance flag lookup failed for %s (%s); using default",
                flag_id,
                type(exc).__name__,
            )
            return default
        if peeked is None:
            return default
        return str(peeked["value"])

    def ticket_enabled(self) -> bool:
        if self._settings.ticket_service_mode == "DISABLED":
            return False
        return self.resolve_flag("ticket_mode").upper() in {"ENABLED", "TRUE", "1"}

    def handoff_enabled(self) -> bool:
        return self.resolve_flag("handoff_mode").upper() in {"ENABLED", "TRUE", "1"}

    def feedback_enabled(self) -> bool:
        if not self._settings.feedback_enabled:
            return False
        return self.resolve_flag("feedback").lower() in {"true", "1", "enabled"}

    def cost_display_enabled(self) -> bool:
        return self.resolve_flag("cost_display").lower() in {"true", "1", "enabled"}


class ExtractorPromptRuntime:
    """Backward-compatible prompt resolver used by IssueExtractor."""

    def __init__(self, runtime: GovernanceRuntime) -> None:
        self._runtime = runtime

    @classmethod
    def from_settings(cls, settings: RagSettings) -> ExtractorPromptRuntime:
        return cls(GovernanceRuntime.from_settings(settings))

    def resolve(
        self,
        *,
        tenant_id: str | None,
        conversation_id: str | None,
    ) -> ResolvedExtractorPrompt:
        return self._runtime.resolve_prompt(
            tenant_id=tenant_id, conversation_id=conversation_id
        )
