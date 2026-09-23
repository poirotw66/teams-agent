"""Backoffice wiring helpers that do not import Agent runtime modules."""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

import httpx
from fastapi import FastAPI

from ai_ops_backoffice.evaluation_domain import (
    CandidateGenerationManager,
    EvalScheduler,
    EvaluationImportExportManager,
    EvaluationRunner,
    EvaluationRunService,
    EvaluationService,
    ExecutionJobWorker,
    QualityGateService,
    ToolFixtureService,
)
from ai_ops_backoffice.faq_domain import FaqValidationError
from ai_ops_backoffice.prompt_domain import PromptPocService
from ai_ops_backoffice.runtime_hooks import get_portal_app_factory
from ai_ops_backoffice.services.query_service import BackofficeQueryService
from ai_ops_backoffice.settings import BackofficeSettings

logger = logging.getLogger(__name__)

_VALID_NOTIFICATION_CHANNELS = frozenset({"TEAMS", "EMAIL", "NOTIFICATION_CENTER"})


class ActiveFaqTaxonomy:
    def __init__(self, query_service: BackofficeQueryService) -> None:
        self._query_service = query_service

    def require_active(self, issue_type_id: str) -> None:
        issue_type = self._query_service.taxonomy.get(issue_type_id)
        if issue_type is None or issue_type.status != "ACTIVE":
            raise FaqValidationError(f"inactive issue type: {issue_type_id}")


@dataclass
class EvaluationStack:
    evaluation_service: EvaluationService
    import_export_manager: EvaluationImportExportManager
    candidate_manager: CandidateGenerationManager
    eval_runner: EvaluationRunner
    evaluation_run_service: EvaluationRunService
    tool_fixture_service: ToolFixtureService
    quality_gate_service: QualityGateService
    job_repository: object
    job_worker: ExecutionJobWorker
    eval_scheduler: EvalScheduler


def parse_budget_notification_targets(settings: BackofficeSettings) -> dict[str, str]:
    configured_targets: dict[str, str] = {}
    for entry in settings.budget_notification_targets:
        target_id, separator, channel = entry.partition("=")
        normalized_channel = channel.strip().upper()
        if (
            not separator
            or not target_id.strip()
            or normalized_channel not in _VALID_NOTIFICATION_CHANNELS
        ):
            raise ValueError(f"Invalid budget notification target configuration: {entry}")
        configured_targets[target_id.strip()] = normalized_channel
    return configured_targets


def build_prompt_service(
    settings: BackofficeSettings,
    prompt_repository: object,
) -> PromptPocService:
    prompt_effective_at = (
        datetime.fromisoformat(settings.prompt_active_effective_at.replace("Z", "+00:00"))
        if settings.prompt_active_effective_at
        else None
    )
    if prompt_effective_at is not None and prompt_effective_at.utcoffset() is None:
        raise ValueError("AI_OPS_PROMPT_ACTIVE_EFFECTIVE_AT requires a timezone")
    return PromptPocService(
        prompt_repository,
        active_effective_at=prompt_effective_at,
    )


def maybe_build_in_process_portal(
    settings: BackofficeSettings,
    *,
    knowledge_transport: httpx.AsyncBaseTransport | None,
    delegation_secret: str | None,
    portal_app_factory: Callable[..., FastAPI] | None = None,
) -> tuple[FastAPI | None, httpx.AsyncBaseTransport | None, str | None]:
    portal_app: FastAPI | None = None
    resolved_secret = delegation_secret
    resolved_transport = knowledge_transport
    factory = portal_app_factory or get_portal_app_factory()
    if (
        knowledge_transport is None
        and settings.knowledge_bridge_enabled
        and getattr(settings, "knowledge_in_process", True)
        and factory is not None
    ):
        try:
            from knowledge_portal.settings import PortalSettings

            if not resolved_secret:
                resolved_secret = secrets.token_hex(32)

            portal_settings = PortalSettings.from_env()
            portal_settings = replace(
                portal_settings,
                delegation_secret=resolved_secret,
                require_service_token_with_delegation=bool(
                    settings.knowledge_service_token
                ),
                # In-process lab portal must stay deterministic: no live
                # embedding calls from ambient GOOGLE_API_KEY / .env.
                embedding_model=None,
            )
            portal_app = factory(portal_settings)
            resolved_transport = httpx.ASGITransport(app=portal_app)
            logger.info("In-process Knowledge Portal initialized successfully.")
        except Exception:
            logger.exception(
                "Failed to initialize in-process Knowledge Portal; falling back to remote URL."
            )
    return portal_app, resolved_transport, resolved_secret


__all__ = [
    "ActiveFaqTaxonomy",
    "EvaluationStack",
    "build_prompt_service",
    "maybe_build_in_process_portal",
    "parse_budget_notification_targets",
]
