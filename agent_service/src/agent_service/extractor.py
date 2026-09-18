"""Issue Extractor (spec §6).

Narrow responsibility only (spec §6.1):

1. Split a message into at most ``max_issues_per_message`` issues.
2. Decide whether each issue is an IT issue.
3. Decide whether each issue has enough information (``readiness``).
4. Choose a high-level ``route``.
5. Provide the minimum necessary ``missingInfo`` follow-up questions.

It must NOT judge whether a problem is actually resolved, maintain an issue
lifecycle, invent a large intent taxonomy, generate FAQ answers, produce
ticket category ids, or create tickets. All of that lives elsewhere in the
workflow.

Everything the LLM is asked not to do is also *enforced in Python* after the
call returns, because a prompt alone is not a security boundary (spec §17).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel

from operations_core.default_extractor_prompt import SYSTEM_PROMPT

from .confirmation import TicketIntent, classify_ticket_intent
from .contracts import ConversationMessage, Issue, IssueExtraction
from .execution_context import ExecutionContext
from .extractor_fallback import invoke_model_with_fallback
from .extractor_heuristics import (
    _GENERIC_TICKET_DESCRIPTION,
    _SAFE_FALLBACK_DESCRIPTION_MAX_LEN,
    HUMAN_ESCALATION_ISSUE_DESCRIPTION,
    _can_skip_extractor_for_ready_symptom,
    _has_helpdesk_domain_evidence,
    _is_assistant_scope_question,
    _is_generic_ticket_description,
    _is_generic_ticket_request,
    _is_human_escalation_request,
    _normalize_known_it_terms,
    _strip_ticket_command,
    merge_pending_ticket_issues,
)
from .extractor_invoke import call_extractor_model, resolve_chat_model
from .extractor_normalize import (
    FORBIDDEN_MISSING_INFO_TERMS,
    coerce_issue,
    postprocess_issues,
)
from .sanitize import sanitize_description
from .settings import RagSettings

logger = logging.getLogger(__name__)

# Compatibility re-exports: other modules historically import heuristics via extractor.
__all__ = [
    "FORBIDDEN_MISSING_INFO_TERMS",
    "HUMAN_ESCALATION_ISSUE_DESCRIPTION",
    "SYSTEM_PROMPT",
    "_GENERIC_TICKET_DESCRIPTION",
    "IssueExtractor",
    "_has_helpdesk_domain_evidence",
    "_is_assistant_scope_question",
    "_is_generic_ticket_description",
    "_is_generic_ticket_request",
    "_is_human_escalation_request",
    "_strip_ticket_command",
    "merge_pending_ticket_issues",
]


@dataclass(frozen=True)
class ExtractionOutcome:
    """Result of :meth:`IssueExtractor.extract`."""

    issues: list[Issue] = field(default_factory=list)
    too_many_issues: bool = False
    llm_calls: int = 0
    prompt_source: str = "code_baseline"
    prompt_version_id: str | None = None
    prompt_version: str | None = None
    prompt_canary: bool = False
    model_source: str = "settings_baseline"
    model_version_id: str | None = None
    model_used: str | None = None
    model_fallback_applied: bool = False


class IssueExtractor:
    """Splits a user message into IT issues per spec §6."""

    def __init__(
        self,
        settings: RagSettings,
        model: BaseChatModel | None,
        *,
        prompt_runtime: object | None = None,
        default_model_name: str | None = None,
    ) -> None:
        self.settings = settings
        self.model = model
        self.default_model_name = default_model_name or settings.agent_model or settings.model
        if prompt_runtime is None:
            from .prompt_runtime import ExtractorPromptRuntime

            prompt_runtime = ExtractorPromptRuntime.from_settings(settings)
        self.prompt_runtime = prompt_runtime

    async def extract(
        self,
        *,
        text: str,
        history: list[ConversationMessage],
        faq_keys: list[str],
        correlation_id: str | None = None,
        conversation_id: str | None = None,
        tenant_id: str | None = None,
        presolved_ticket_intent: TicketIntent | None = None,
        execution_context: ExecutionContext | None = None,
    ) -> ExtractionOutcome:
        normalized_text = _normalize_known_it_terms(text)
        short_circuit = self._try_deterministic_outcome(
            normalized_text,
            history=history,
            presolved_ticket_intent=presolved_ticket_intent,
            correlation_id=correlation_id,
        )
        if short_circuit is not None:
            return short_circuit

        return await self._extract_with_model(
            normalized_text=normalized_text,
            history=history,
            faq_keys=faq_keys,
            correlation_id=correlation_id,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            execution_context=execution_context,
        )

    def _try_deterministic_outcome(
        self,
        normalized_text: str,
        *,
        history: list[ConversationMessage],
        presolved_ticket_intent: TicketIntent | None,
        correlation_id: str | None,
    ) -> ExtractionOutcome | None:
        ticket_intent = presolved_ticket_intent or classify_ticket_intent(normalized_text)

        # Ticket intent is a deterministic guardrail, not an LLM suggestion.
        # These operations must never become a third issue or a knowledge
        # lookup because the extractor happened to split the wording poorly.
        if ticket_intent in {
            TicketIntent.DELETE_DENIED,
            TicketIntent.CANCEL,
            TicketIntent.QUERY,
            TicketIntent.CREATE,
        }:
            return ExtractionOutcome(
                issues=[self._ticket_intent_issue(normalized_text, ticket_intent)],
                too_many_issues=False,
                llm_calls=0,
            )

        # Ready IT symptoms (named system + failure, dazhou, error codes) are a
        # closed READY knowledge set. Skip the extractor LLM when history and
        # multi-issue gates pass — same shape as ticket-intent short circuits.
        if _can_skip_extractor_for_ready_symptom(normalized_text, history=history):
            return ExtractionOutcome(
                issues=[self._fallback_issue(normalized_text)],
                too_many_issues=False,
                llm_calls=0,
            )

        if self.model is None:
            logger.warning(
                "IssueExtractor running without a model (no API key); "
                "using deterministic single-issue fallback. correlation_id=%s",
                correlation_id,
            )
            return ExtractionOutcome(
                issues=[self._fallback_issue(normalized_text)],
                too_many_issues=False,
                llm_calls=0,
            )
        return None

    async def _extract_with_model(
        self,
        *,
        normalized_text: str,
        history: list[ConversationMessage],
        faq_keys: list[str],
        correlation_id: str | None,
        conversation_id: str | None,
        tenant_id: str | None,
        execution_context: ExecutionContext | None,
    ) -> ExtractionOutcome:
        resolved = self._resolve_prompt(tenant_id, conversation_id, execution_context)
        logger.info(
            "IssueExtractor prompt source=%s version=%s canary=%s correlation_id=%s",
            resolved.source,
            resolved.version or "code-baseline",
            resolved.canary,
            correlation_id,
        )
        active_model, resolved_model = resolve_chat_model(
            prompt_runtime=self.prompt_runtime,
            startup_model=self.model,
        )
        timeout_val = (
            float(resolved_model.timeout_seconds)
            if (resolved_model and getattr(resolved_model, "timeout_seconds", None))
            else None
        )
        model_used = getattr(resolved_model, "model_name", None) or self.default_model_name
        raw, llm_calls, fallback_applied, model_used = await invoke_model_with_fallback(
            call_model=self._call_model,
            text=normalized_text,
            history=history,
            faq_keys=faq_keys,
            template=resolved.template,
            active_model=active_model,
            resolved_model=resolved_model,
            execution_context=execution_context,
            timeout_val=timeout_val,
            initial_model_used=model_used,
            correlation_id=correlation_id,
        )
        if raw is None:
            return self._outcome_from_fallback(
                normalized_text,
                llm_calls=llm_calls,
                resolved=resolved,
                resolved_model=resolved_model,
                model_used=model_used,
            )
        return self._outcome_from_extraction(
            raw,
            faq_keys=faq_keys,
            normalized_text=normalized_text,
            llm_calls=llm_calls,
            resolved=resolved,
            resolved_model=resolved_model,
            model_used=model_used,
            fallback_applied=fallback_applied,
        )

    def _resolve_prompt(
        self,
        tenant_id: str | None,
        conversation_id: str | None,
        execution_context: ExecutionContext | None,
    ) -> Any:
        resolved_tenant = tenant_id
        if resolved_tenant is None and execution_context is not None:
            resolved_tenant = execution_context.tenant_id
        return self.prompt_runtime.resolve(
            tenant_id=resolved_tenant,
            conversation_id=conversation_id,
        )

    def _outcome_from_extraction(
        self,
        raw: IssueExtraction,
        *,
        faq_keys: list[str],
        normalized_text: str,
        llm_calls: int,
        resolved: Any,
        resolved_model: Any | None,
        model_used: str | None,
        fallback_applied: bool,
    ) -> ExtractionOutcome:
        issues, too_many = self._postprocess(
            raw.issues,
            faq_keys,
            raw_utterance=normalized_text,
        )
        return ExtractionOutcome(
            issues=issues,
            too_many_issues=too_many,
            llm_calls=llm_calls,
            prompt_source=resolved.source,
            prompt_version_id=resolved.version_id,
            prompt_version=resolved.version,
            prompt_canary=resolved.canary,
            model_source=getattr(resolved_model, "source", "settings_baseline")
            if resolved_model
            else "settings_baseline",
            model_version_id=getattr(resolved_model, "version_id", None)
            if resolved_model
            else None,
            model_used=model_used,
            model_fallback_applied=fallback_applied,
        )

    def _outcome_from_fallback(
        self,
        normalized_text: str,
        *,
        llm_calls: int,
        resolved: object,
        resolved_model: object | None,
        model_used: str | None,
    ) -> ExtractionOutcome:
        return ExtractionOutcome(
            issues=[self._fallback_issue(normalized_text)],
            too_many_issues=False,
            llm_calls=llm_calls,
            prompt_source=getattr(resolved, "source", "code_baseline"),
            prompt_version_id=getattr(resolved, "version_id", None),
            prompt_version=getattr(resolved, "version", None),
            prompt_canary=bool(getattr(resolved, "canary", False)),
            model_source=getattr(resolved_model, "source", "settings_baseline")
            if resolved_model
            else "settings_baseline",
            model_version_id=getattr(resolved_model, "version_id", None)
            if resolved_model
            else None,
            model_used=model_used,
            model_fallback_applied=False,
        )

    async def _call_model(
        self,
        *,
        text: str,
        history: list[ConversationMessage],
        faq_keys: list[str],
        system_prompt_template: str,
        model: BaseChatModel | None,
        execution_context: ExecutionContext | None = None,
        timeout_seconds: float | None = None,
    ) -> IssueExtraction:
        # Kept as an instance method so eval harnesses can monkeypatch it.
        return await call_extractor_model(
            settings=self.settings,
            text=text,
            history=history,
            faq_keys=faq_keys,
            system_prompt_template=system_prompt_template,
            model=model,
            execution_context=execution_context,
            timeout_seconds=timeout_seconds,
        )

    def _postprocess(
        self,
        issues: list[Issue],
        faq_keys: list[str],
        raw_utterance: str = "",
    ) -> tuple[list[Issue], bool]:
        return postprocess_issues(
            issues,
            faq_keys,
            max_issues=self.settings.max_issues_per_message,
            max_missing_info=self.settings.max_missing_info_per_issue,
            raw_utterance=raw_utterance,
        )

    def _coerce_issue(
        self,
        issue: Issue,
        *,
        new_id: int,
        allowed_faq_keys: set[str],
        raw_utterance: str = "",
    ) -> Issue:
        return coerce_issue(
            issue,
            new_id=new_id,
            allowed_faq_keys=allowed_faq_keys,
            max_missing_info=self.settings.max_missing_info_per_issue,
            raw_utterance=raw_utterance,
        )

    def _fallback_issue(self, text: str) -> Issue:
        description = text.strip()[:_SAFE_FALLBACK_DESCRIPTION_MAX_LEN] or text
        return Issue(
            id=1,
            description=description,
            isIT=True,
            readiness="READY",
            missingInfo=[],
            route="KNOWLEDGE",
            faqKey=None,
            ticketAction=None,
        )

    def _ticket_intent_issue(self, text: str, ticket_intent: TicketIntent) -> Issue:
        """Build one safe ticket issue directly from the user's current turn.

        For explicit creation, keeping the command-stripped original wording
        preserves every actual problem in a multi-problem message.  It is more
        reliable than asking an LLM to split the message and then trying to
        infer which extracted item was merely "請建立工單".
        """
        if ticket_intent == TicketIntent.CREATE:
            description = _strip_ticket_command(text)
            description = sanitize_description(description)
            if not description:
                description = _GENERIC_TICKET_DESCRIPTION
        elif ticket_intent == TicketIntent.QUERY:
            description = "查詢目前使用者的派工單"
        elif ticket_intent == TicketIntent.DELETE_DENIED:
            description = "刪除工單"
        else:
            description = "取消建立工單"

        return Issue(
            id=1,
            description=description[:_SAFE_FALLBACK_DESCRIPTION_MAX_LEN],
            isIT=True,
            readiness="READY",
            missingInfo=[],
            route="TICKET",
            faqKey=None,
            ticketAction=None,
        )
