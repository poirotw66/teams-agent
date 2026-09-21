"""Agent-facing Phase 3 governance runtime with fail-safe defaults."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from agent_service.extractor import SYSTEM_PROMPT
from agent_service.runtime_hooks import build_governance_provider
from agent_service.settings import RagSettings
from platform_kernel.governance_catalog import (
    DEFAULT_AGENT_MODEL_ID,
    DEFAULT_FILE_SEARCH_MODEL_ID,
    DEFAULT_RAG_MODEL_ID,
    FLAG_CATALOG,
    ISSUE_EXTRACTOR_PROMPT_ID,
    MODEL_COMPONENTS,
    ModelComponentSpec,
)
from platform_kernel.hashing import content_hash
from platform_kernel.ports.governance import GovernanceProvider

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
    temperature: float | None = None
    max_output_tokens: int | None = None
    timeout_seconds: int | None = None
    retry: int | None = None
    max_attempts: int = 1


def _build_governance(settings: RagSettings) -> GovernanceProvider | None:
    mode = settings.prompt_runtime_mode.upper()
    if mode == "CODE_BASELINE":
        return None
    if mode != "GOVERNED":
        raise ValueError(f"Unsupported prompt runtime mode: {mode}")
    provider = build_governance_provider(settings)
    if provider is None:
        raise RuntimeError(
            "GOVERNED prompt runtime requires composition.install_agent_hooks(); "
            "no governance provider builder is registered."
        )
    return provider


class GovernanceRuntime:
    """Resolves governed prompts, models, and flags for Agent runtime."""

    def __init__(
        self,
        *,
        mode: str,
        settings: RagSettings,
        governance: GovernanceProvider | None = None,
        environment: str = "lab",
    ) -> None:
        self._mode = mode.upper()
        self._settings = settings
        self._governance = governance
        self._environment = environment
        self._chat_models: dict[tuple[object, ...], object] = {}

    @classmethod
    def from_settings(cls, settings: RagSettings) -> GovernanceRuntime:
        environment = (
            "prod" if settings.deployment_environment.lower() in {"prod", "production"} else "lab"
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
        baseline = self._settings_baseline(config_id)
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
        return self._resolved_from_peek(peeked)

    def chat_model_for(
        self, resolved: ResolvedModelConfig, fallback: object | None = None
    ) -> object | None:
        """Return a cached chat client for this resolved version, or the fallback."""

        if resolved.source != "governance" or not resolved.model_name:
            if fallback is not None:
                return fallback
            key = (
                "settings",
                resolved.model_name,
                resolved.temperature,
                resolved.max_output_tokens,
                resolved.timeout_seconds,
                resolved.retry,
            )
            cached = self._chat_models.get(key)
            if cached is not None:
                return cached
            built = self._build_chat_model(resolved)
            if built is not None:
                self._chat_models[key] = built
            return built
        key = (
            resolved.version_id,
            resolved.model_name,
            resolved.temperature,
            resolved.max_output_tokens,
            resolved.timeout_seconds,
            resolved.retry,
        )
        cached = self._chat_models.get(key)
        if cached is not None:
            return cached
        built = self._build_chat_model(resolved)
        if built is None:
            return fallback
        self._chat_models[key] = built
        return built

    def effective_model_catalog(
        self,
        *,
        embedding_model: str | None = None,
        file_search_model: str | None = None,
    ) -> dict[str, object]:
        """One effective model per component, plus any pending schedule."""

        governed = self._mode == "GOVERNED" and self._governance is not None
        lookup_failed = False
        items: list[dict[str, object]] = []
        for spec in MODEL_COMPONENTS:
            item, failed = self._catalog_item(
                spec,
                governed=governed,
                embedding_model=embedding_model,
                file_search_model=file_search_model,
            )
            lookup_failed = lookup_failed or failed
            items.append(item)
        return {
            "runtimeMode": self._mode,
            "governed": governed,
            "controlPlaneReady": governed and not lookup_failed,
            "items": items,
        }

    def _catalog_item(
        self,
        spec: ModelComponentSpec,
        *,
        governed: bool,
        embedding_model: str | None,
        file_search_model: str | None,
    ) -> tuple[dict[str, object], bool]:
        baseline = self._settings_baseline(spec.config_id)
        resolved = baseline
        failed = False
        schedule: dict[str, object] | None = None
        if governed and self._governance is not None:
            try:
                resolved = self.resolve_model(config_id=spec.config_id)
                schedule = self._governance.peek_model_schedule(spec.config_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "governance catalog lookup failed for %s (%s); using settings baseline",
                    spec.config_id,
                    type(exc).__name__,
                )
                failed = True
                resolved = baseline
        model, source, version_id = self._effective_fields(
            spec,
            resolved=resolved,
            baseline=baseline,
            embedding_model=embedding_model,
            file_search_model=file_search_model,
        )
        fallback = baseline.model_id if spec.family != "chat" else baseline.model_name
        item: dict[str, object] = {
            "configId": spec.config_id,
            "role": spec.role,
            "label": spec.label,
            "effect": spec.effect,
            "component": spec.component,
            "model": model,
            "source": source,
            "versionId": version_id,
            "fallbackModel": fallback if fallback and fallback != model else None,
            "scheduleStatus": None,
            "scheduledVersionId": None,
            "scheduledModel": None,
            "lookupFailed": failed,
        }
        if schedule:
            item["scheduleStatus"] = schedule.get("scheduleStatus")
            item["scheduledVersionId"] = schedule.get("scheduledVersionId")
            item["scheduledModel"] = schedule.get("scheduledModelId")
        return item, failed

    def _effective_fields(
        self,
        spec: ModelComponentSpec,
        *,
        resolved: ResolvedModelConfig,
        baseline: ResolvedModelConfig,
        embedding_model: str | None,
        file_search_model: str | None,
    ) -> tuple[str | None, str, str | None]:
        if spec.role == "embedding":
            serving = embedding_model or baseline.model_id or None
            if resolved.source == "governance" and serving == resolved.model_id:
                return serving, "governance", resolved.version_id
            return serving, "settings_baseline", None
        if spec.role == "file_search":
            serving = file_search_model or baseline.model_id or None
            if resolved.source == "governance" and serving == resolved.model_id:
                return serving, "governance", resolved.version_id
            return serving, "settings_baseline", None
        display = resolved.model_name or resolved.model_id or None
        return display, resolved.source, resolved.version_id

    def _settings_baseline(self, config_id: str) -> ResolvedModelConfig:
        spec = next((item for item in MODEL_COMPONENTS if item.config_id == config_id), None)
        role = spec.role if spec is not None else "agent"
        if role == "answer":
            raw = (
                getattr(self._settings, "rag_answer_model", None)
                or self._settings.model
                or ""
            )
            default_id = DEFAULT_RAG_MODEL_ID
        elif role == "relevance":
            raw = (
                getattr(self._settings, "rag_relevance_model", None)
                or getattr(self._settings, "rag_answer_model", None)
                or self._settings.model
                or ""
            )
            default_id = DEFAULT_RAG_MODEL_ID
        elif role == "rewrite":
            raw = (
                getattr(self._settings, "rag_rewrite_model", None)
                or getattr(self._settings, "rag_relevance_model", None)
                or getattr(self._settings, "rag_answer_model", None)
                or self._settings.model
                or ""
            )
            default_id = DEFAULT_RAG_MODEL_ID
        elif role == "hard_answer":
            raw = getattr(self._settings, "rag_hard_answer_model", None) or ""
            default_id = ""
        elif role == "embedding":
            raw = self._settings.embedding_model or ""
            default_id = raw
        elif role == "file_search":
            raw = self._settings.gemini_file_search_model or ""
            default_id = raw or DEFAULT_FILE_SEARCH_MODEL_ID
        else:
            raw = self._settings.agent_model or self._settings.model or ""
            default_id = DEFAULT_AGENT_MODEL_ID
        provider, _, model_id = raw.partition(":")
        if not model_id:
            provider, model_id = "google_genai", raw or default_id
        bare = model_id or default_id
        model_name = raw or (
            f"google_genai:{bare}" if role in {"agent", "answer"} and bare else bare
        )
        return ResolvedModelConfig(
            provider=provider or "google_genai",
            model_id=bare,
            model_name=model_name or None,
            source="settings_baseline",
        )

    def _resolved_from_peek(self, peeked: dict[str, object]) -> ResolvedModelConfig:
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
            temperature=float(peeked["temperature"])
            if peeked.get("temperature") is not None
            else None,
            max_output_tokens=int(peeked["maxOutputTokens"])
            if peeked.get("maxOutputTokens") is not None
            else None,
            timeout_seconds=int(peeked["timeoutSeconds"])
            if peeked.get("timeoutSeconds") is not None
            else None,
            retry=int(peeked["retry"]) if peeked.get("retry") is not None else None,
            max_attempts=int(peeked.get("maxAttempts") or 1),
        )

    def _build_chat_model(self, resolved: ResolvedModelConfig) -> object | None:
        from .graph import build_chat_model

        if not resolved.model_name:
            return None
        return build_chat_model(
            resolved.model_name,
            temperature=resolved.temperature,
            max_tokens=resolved.max_output_tokens,
            timeout=float(resolved.timeout_seconds)
            if resolved.timeout_seconds is not None
            else None,
            max_retries=resolved.retry,
        )

    def resolve_flag(self, flag_id: str) -> str:
        catalog = FLAG_CATALOG.get(flag_id, {})
        default = str(catalog.get("default", "false"))
        if self._mode != "GOVERNED" or self._governance is None:
            return default
        try:
            peeked = self._governance.peek_runtime_flag(flag_id, environment=self._environment)
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
        return self._runtime.resolve_prompt(tenant_id=tenant_id, conversation_id=conversation_id)

    def resolve_model(self, *, config_id: str = "issue-extractor-model") -> ResolvedModelConfig:
        return self._runtime.resolve_model(config_id=config_id)
