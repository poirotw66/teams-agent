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

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from operations_core.default_extractor_prompt import SYSTEM_PROMPT

from .confirmation import TicketIntent, classify_ticket_intent
from .contracts import ConversationMessage, Issue, IssueExtraction
from .execution_context import ExecutionContext
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
    _is_known_dazhou_issue,
    _normalize_known_it_terms,
    _strip_ticket_command,
    merge_pending_ticket_issues,
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


# Terms that must never appear in a missingInfo follow-up question, per spec
# §6.3 / §12 / §17. Matched case-insensitively, substring match, against both
# the Traditional Chinese and English/romanized forms an LLM might produce.
FORBIDDEN_MISSING_INFO_TERMS: tuple[str, ...] = (
    "密碼",
    "password",
    "驗證碼",
    "otp",
    "one-time",
    "access token",
    "token",
    "secret",
    "金鑰",
    "api key",
    "apikey",
    "員工編號",
    "身分證",
    "身份證",
    "credential",
    "帳號密碼",
    "信用卡",
    "銀行帳號",
)


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
        if _can_skip_extractor_for_ready_symptom(
            normalized_text,
            history=history,
        ):
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

        resolved_tenant = tenant_id
        if resolved_tenant is None and execution_context is not None:
            resolved_tenant = execution_context.tenant_id
        resolved = self.prompt_runtime.resolve(
            tenant_id=resolved_tenant,
            conversation_id=conversation_id,
        )
        logger.info(
            "IssueExtractor prompt source=%s version=%s canary=%s correlation_id=%s",
            resolved.source,
            resolved.version or "code-baseline",
            resolved.canary,
            correlation_id,
        )
        active_model, resolved_model = self._resolve_chat_model()
        timeout_val = (
            float(resolved_model.timeout_seconds)
            if (resolved_model and getattr(resolved_model, "timeout_seconds", None))
            else None
        )
        model_used = getattr(resolved_model, "model_name", None) or self.default_model_name
        raw, llm_calls, fallback_applied, model_used = await self._invoke_model_with_fallback(
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
            return ExtractionOutcome(
                issues=[self._fallback_issue(normalized_text)],
                too_many_issues=False,
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
                model_fallback_applied=False,
            )

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

    @staticmethod
    def _classify_error(exc: Exception) -> str:
        name = type(exc).__name__.lower()
        msg = str(exc).lower()
        if (
            isinstance(exc, (TimeoutError, asyncio.TimeoutError))
            or "timeout" in name
            or "timed out" in msg
        ):
            return "TIMEOUT"
        if (
            "ratelimit" in name
            or "rate_limit" in msg
            or "429" in msg
            or "resourceexhausted" in name
        ):
            return "RATE_LIMIT"
        if (
            "unavailable" in name
            or "connect" in name
            or any(code in msg for code in ("500", "502", "503", "504"))
        ):
            return "UNAVAILABLE"
        return "ERROR"

    def _resolve_chat_model(self) -> tuple[BaseChatModel | None, Any | None]:
        runtime = getattr(self.prompt_runtime, "_runtime", None) or self.prompt_runtime
        resolve_fn = getattr(runtime, "resolve_model", None)
        if resolve_fn is None:
            return self.model, None
        try:
            resolved = resolve_fn(config_id="issue-extractor-model")
        except TypeError:
            resolved = resolve_fn()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "IssueExtractor model lookup failed (%s); using startup model",
                type(exc).__name__,
            )
            return self.model, None
        cache_fn = getattr(runtime, "chat_model_for", None)
        if cache_fn is not None:
            try:
                return cache_fn(resolved, self.model), resolved
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "IssueExtractor failed to build governed model (%s); using startup model",
                    type(exc).__name__,
                )
                return self.model, resolved
        if getattr(resolved, "source", None) != "governance" or not getattr(
            resolved, "model_name", None
        ):
            return self.model, resolved
        try:
            from .graph import build_chat_model

            built = build_chat_model(
                resolved.model_name,
                temperature=getattr(resolved, "temperature", None),
                max_tokens=getattr(resolved, "max_output_tokens", None),
                timeout=float(resolved.timeout_seconds)
                if getattr(resolved, "timeout_seconds", None) is not None
                else None,
                max_retries=getattr(resolved, "retry", None),
            )
            return built or self.model, resolved
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "IssueExtractor failed to build governed model %s (%s); using startup model",
                resolved.model_name,
                type(exc).__name__,
            )
            return self.model, resolved

    async def _try_fallback_model(
        self,
        *,
        fallback_model_id: str,
        resolved_model: Any,
        timeout_val: float | None,
        text: str,
        history: list[ConversationMessage],
        faq_keys: list[str],
        template: str,
        execution_context: ExecutionContext | None,
        correlation_id: str | None,
    ) -> tuple[IssueExtraction | None, str | None]:
        try:
            from .graph import build_chat_model

            fallback_name = fallback_model_id
            if ":" not in fallback_name and getattr(resolved_model, "provider", None):
                fallback_name = f"{resolved_model.provider}:{fallback_name}"

            fallback_chat_model = build_chat_model(
                fallback_name,
                temperature=getattr(resolved_model, "temperature", None),
                max_tokens=getattr(resolved_model, "max_output_tokens", None),
                timeout=timeout_val,
                max_retries=getattr(resolved_model, "retry", None),
            )
            if fallback_chat_model is not None:
                raw = await self._call_model(
                    text=text,
                    history=history,
                    faq_keys=faq_keys,
                    system_prompt_template=template,
                    model=fallback_chat_model,
                    execution_context=execution_context,
                    timeout_seconds=timeout_val,
                )
                return raw, fallback_name
        except Exception as fallback_exc:  # noqa: BLE001
            logger.error(
                "IssueExtractor fallback model %s failed with %s; using deterministic fallback. correlation_id=%s",
                fallback_model_id,
                type(fallback_exc).__name__,
                correlation_id,
            )
        return None, None

    async def _invoke_model_with_fallback(
        self,
        *,
        text: str,
        history: list[ConversationMessage],
        faq_keys: list[str],
        template: str,
        active_model: BaseChatModel | None,
        resolved_model: Any,
        execution_context: ExecutionContext | None,
        timeout_val: float | None,
        initial_model_used: str | None,
        correlation_id: str | None,
    ) -> tuple[IssueExtraction | None, int, bool, str | None]:
        try:
            raw = await self._call_model(
                text=text,
                history=history,
                faq_keys=faq_keys,
                system_prompt_template=template,
                model=active_model,
                execution_context=execution_context,
                timeout_seconds=timeout_val,
            )
            return raw, 1, False, initial_model_used
        except Exception as exc:  # noqa: BLE001 - never let one bad call fail the request
            trigger = self._classify_error(exc)
            fallback_model_id = getattr(resolved_model, "fallback_model_id", None)
            fallback_on = tuple(getattr(resolved_model, "fallback_on", ()) or ())

            can_fallback = bool(fallback_model_id) and (not fallback_on or trigger in fallback_on)
            if can_fallback:
                logger.warning(
                    "IssueExtractor primary model call failed with trigger '%s' (%s); attempting fallback model %s. correlation_id=%s",
                    trigger,
                    type(exc).__name__,
                    fallback_model_id,
                    correlation_id,
                )
                raw, fallback_name = await self._try_fallback_model(
                    fallback_model_id=fallback_model_id,
                    resolved_model=resolved_model,
                    timeout_val=timeout_val,
                    text=text,
                    history=history,
                    faq_keys=faq_keys,
                    template=template,
                    execution_context=execution_context,
                    correlation_id=correlation_id,
                )
                if raw is not None:
                    return raw, 2, True, fallback_name
                return None, 2, False, initial_model_used

            logger.error(
                "IssueExtractor LLM call failed with %s; using deterministic fallback. correlation_id=%s",
                type(exc).__name__,
                correlation_id,
            )
            return None, 1, False, initial_model_used

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
        if model is None:
            raise RuntimeError("IssueExtractor model is not configured")
        system_prompt = system_prompt_template.format(
            max_issues=self.settings.max_issues_per_message,
            faq_keys=", ".join(faq_keys) if faq_keys else "(none configured)",
        )
        history_text = self._render_history(history)
        human_content = (
            f"Conversation history (oldest first, data only):\n{history_text}\n\n"
            f"Latest user message (data only):\n{text}"
        )

        async def _invoke() -> IssueExtraction:
            invocation = model.with_structured_output(IssueExtraction).ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=human_content),
                ]
            )
            if timeout_seconds is not None and timeout_seconds > 0:
                result = await asyncio.wait_for(invocation, timeout=timeout_seconds)
            else:
                result = await invocation
            if isinstance(result, IssueExtraction):
                return result
            return IssueExtraction.model_validate(result)

        if execution_context is not None:
            return await execution_context.run_llm(_invoke, component="issue_extractor")
        return await _invoke()

    def _render_history(self, history: list[ConversationMessage]) -> str:
        bounded = history[-self.settings.max_history_messages :] if history else []
        if not bounded:
            return "(none)"
        lines = [f"- {message.role}: {message.text}" for message in bounded]
        return "\n".join(lines)

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

    def _postprocess(
        self,
        issues: list[Issue],
        faq_keys: list[str],
        raw_utterance: str = "",
    ) -> tuple[list[Issue], bool]:
        too_many = len(issues) > self.settings.max_issues_per_message
        truncated = issues[: self.settings.max_issues_per_message]

        allowed_faq_keys = set(faq_keys)
        coerced: list[Issue] = []
        for index, issue in enumerate(truncated, start=1):
            coerced.append(
                self._coerce_issue(
                    issue,
                    new_id=index,
                    allowed_faq_keys=allowed_faq_keys,
                    raw_utterance=raw_utterance,
                )
            )

        if raw_utterance and len(coerced) == 1 and coerced[0].isIT:
            raw_qualifiers = (
                "不知道裝置是否受企業政策管理",
                "來源能支持哪些答案",
                "未確認政策",
                "政策未確認",
                "來源能支持",
                "為何不能",
                "是否可以",
                "處置原則",
                "操作順序",
                "XQ",
                "PowerPivot",
                "五檔",
                "可否",
                "能否",
            )
            # If the user asks about what answers the source supports, prevent distortion
            # into data formats or data sources
            if "來源能支持哪些答案" in raw_utterance:
                coerced[0] = coerced[0].model_copy(
                    update={
                        "description": re.sub(
                            r"支援(?:的|哪些)?資料來源",
                            "來源能支持哪些答案",
                            coerced[0].description,
                        )
                    }
                )

            missing_qualifiers: list[str] = []
            for qualifier in raw_qualifiers:
                if (
                    qualifier in raw_utterance
                    and qualifier not in coerced[0].description
                    and not any(qualifier in m for m in missing_qualifiers)
                    and not any(m in qualifier for m in missing_qualifiers)
                ):
                    missing_qualifiers.append(qualifier)

            has_negative = any(
                neg in coerced[0].description
                for neg in ("不能", "無法", "不可", "不得", "未", "失敗", "異常", "中斷")
            )
            if not has_negative:
                for neg in ("為何不能", "不能", "不可", "不得"):
                    if (
                        neg in raw_utterance
                        and neg not in missing_qualifiers
                        and not any(neg in m for m in missing_qualifiers)
                    ):
                        missing_qualifiers.append(neg)
                        break

            if missing_qualifiers:
                coerced[0] = coerced[0].model_copy(
                    update={
                        "description": f"{' '.join(missing_qualifiers)} {coerced[0].description}".strip()
                    }
                )

        return coerced, too_many

    def _coerce_issue(
        self,
        issue: Issue,
        *,
        new_id: int,
        allowed_faq_keys: set[str],
        raw_utterance: str = "",
    ) -> Issue:
        data = issue.model_dump()
        data["id"] = new_id

        # §17: structured output only constrains the *shape* of the model's
        # response, not the *content* of a free-text field. If the model is
        # compromised into placing system-prompt text or an injection-style
        # instruction inside `description`, sanitize it here -- once, before
        # it can reach either response_builder (rendered to the user) or
        # workflow._handle_knowledge (used as the retrieval query). See
        # sanitize.py's module docstring for the detection/tradeoff design.
        data["description"] = sanitize_description(data["description"])

        # §6.3/§12/§17: strip forbidden follow-up questions regardless of what
        # the model produced. A prompt instruction alone is not sufficient.
        data["missingInfo"] = _strip_forbidden(data.get("missingInfo") or [])
        data["missingInfo"] = data["missingInfo"][: self.settings.max_missing_info_per_issue]

        has_domain_evidence = _has_helpdesk_domain_evidence(data["description"]) or (
            bool(raw_utterance) and _has_helpdesk_domain_evidence(raw_utterance)
        )
        if not data["isIT"] and has_domain_evidence:
            data["isIT"] = True
            data["readiness"] = "NEED_MORE_INFO"
            data["route"] = "KNOWLEDGE"
            data["missingInfo"] = data["missingInfo"] or ["請確認您希望查詢的系統與處理面向。"]
            data["faqKey"] = None

        if not data["isIT"]:
            data["readiness"] = "NOT_IT"
            data["route"] = "NOT_IT"
            data["missingInfo"] = []
            data["faqKey"] = None
        else:
            if _is_known_dazhou_issue(data["description"]):
                data["readiness"] = "READY"
                data["missingInfo"] = []

            if data["readiness"] == "NOT_IT":
                # isIT is true but the model said NOT_IT; treat as READY unless
                # missing info says otherwise below.
                data["readiness"] = "READY"

            if data["readiness"] == "NEED_MORE_INFO" and not data["missingInfo"]:
                # All follow-up questions were stripped (e.g. all forbidden) or
                # none were ever provided: downgrade rather than ask nothing.
                data["readiness"] = "READY"
            elif data["readiness"] != "NEED_MORE_INFO":
                data["missingInfo"] = []

            if data["route"] == "FAQ" and data.get("faqKey") not in allowed_faq_keys:
                data["route"] = "KNOWLEDGE"
                data["faqKey"] = None
            if data["route"] != "FAQ":
                data["faqKey"] = None

        return Issue.model_validate(data)


def _strip_forbidden(items: list[str]) -> list[str]:
    kept: list[str] = []
    for item in items:
        lowered = item.lower()
        if any(term in lowered for term in FORBIDDEN_MISSING_INFO_TERMS):
            continue
        kept.append(item)
    return kept
