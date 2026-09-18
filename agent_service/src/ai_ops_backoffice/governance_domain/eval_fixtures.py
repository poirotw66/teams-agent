"""Fixture adapters and sandbox services for evaluation runtime.

Provides isolated mock repositories for FAQ, Knowledge (release chunks or
deterministic fixture), and Ticket services during evaluation sandbox runs.
Agent contract types are constructed via composition-registered eval bindings.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ai_ops_backoffice.ports.eval_agent import get_eval_agent_bindings

from .eval_fixtures_search import (
    record_knowledge_tool_call,
    search_eval_fixture,
    search_release_index,
)

logger = logging.getLogger(__name__)


class EvalBindingError(RuntimeError):
    """Candidate prompt, model, FAQ version, or knowledge release could not be bound to eval runtime."""


class _FixtureFaqRepository:
    """FAQ catalog for isolated eval probes: loads requested faq_version_id, or falls back to fixture only when unspecified."""

    def __init__(
        self,
        faq_version_id: str | None = None,
        faq_repository: Any = None,
    ) -> None:
        bindings = get_eval_agent_bindings()
        self.version_id = str(faq_version_id or "eval-faq-v1")
        self._entries: dict[str, Any] = {}

        if faq_version_id and faq_version_id not in ("eval-faq-v1", "default"):
            resolved = False
            if faq_repository is not None:
                try:
                    version_record = faq_repository.get_version(self.version_id)
                    if version_record:
                        faq_rec = faq_repository.get_faq(version_record.faq_id)
                        raw_content = getattr(version_record, "content", None)
                        faq_key = (
                            getattr(faq_rec, "faq_key", None)
                            or getattr(raw_content, "faq_key", None)
                            or self.version_id
                        )
                        if hasattr(raw_content, "answer"):
                            answer_text = raw_content.answer
                        elif isinstance(raw_content, dict):
                            answer_text = raw_content.get("answer", "")
                        elif raw_content is not None:
                            answer_text = str(raw_content)
                        else:
                            answer_text = getattr(version_record, "answer", "")
                        status = getattr(version_record, "status", "ACTIVE")
                        self._entries[faq_key] = bindings.build_faq_entry(
                            id=version_record.version_id,
                            faqKey=faq_key,
                            enabled=status not in ("DISABLED", "SUPERSEDED"),
                            answer=str(answer_text),
                            versionId=self.version_id,
                        )
                        resolved = True
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "FAQ repository lookup failed for version=%s: %s",
                        self.version_id,
                        exc,
                    )
                    resolved = False

            if not resolved:
                raise EvalBindingError(f"faq_version_not_found:{self.version_id}")
        else:
            self._entries["account.unlock"] = bindings.build_faq_entry(
                id="faq-account-unlock",
                faqKey="account.unlock",
                enabled=True,
                answer="帳號鎖定時請至自助解鎖頁面，或聯繫資訊小幫手。",
                versionId=self.version_id,
            )

    def get(self, faq_key: str, audience_group_ids: tuple[str, ...] = ()) -> Any:
        _ = audience_group_ids
        return self._entries.get(faq_key)

    def available_keys(self, audience_group_ids: tuple[str, ...] = ()) -> list[str]:
        _ = audience_group_ids
        return sorted(self._entries)


class _FixtureKnowledgeService:
    """Knowledge search for eval probes: queries release chunks if knowledge_release_id is present, else falls back to fixtures."""

    def __init__(
        self,
        release_id: str | None = None,
        releases_dir: Any | None = None,
    ) -> None:
        self.tool_calls: list[dict[str, Any]] = []
        self.release_id = str(release_id).strip() if release_id else None
        self.releases_dir = releases_dir
        self._chunks: list[dict[str, Any]] | None = None

    def _load_release_chunks(self) -> list[dict[str, Any]]:
        if self._chunks is not None:
            return self._chunks
        if not self.release_id:
            self._chunks = []
            return self._chunks
        if not self.releases_dir:
            raise EvalBindingError(f"releases_dir_not_configured_for_release:{self.release_id}")

        rel_dir = Path(self.releases_dir) / self.release_id
        cand1 = rel_dir / "index" / "chunks.json"
        cand2 = rel_dir / "chunks.json"
        chosen = cand1 if cand1.is_file() else (cand2 if cand2.is_file() else None)
        if not chosen:
            raise EvalBindingError(f"knowledge_release_not_found:{self.release_id}")
        try:
            data = json.loads(chosen.read_text(encoding="utf-8"))
            self._chunks = list(data.get("chunks", []))
        except Exception as exc:
            raise EvalBindingError(f"knowledge_release_read_failed:{self.release_id}:{exc}") from exc
        return self._chunks

    async def search(self, query: str, user_context: Any, **kwargs: Any) -> Any:
        bindings = get_eval_agent_bindings()
        groups = set(
            getattr(user_context, "groups", None)
            or getattr(user_context, "audience_group_ids", None)
            or ()
        )
        _ = kwargs

        if self.release_id:
            result = search_release_index(
                query=query,
                groups=groups,
                chunks=self._load_release_chunks(),
                release_id=self.release_id,
                bindings=bindings,
            )
            record_knowledge_tool_call(
                self.tool_calls,
                query=query,
                groups=groups,
                result=result,
                backend="release-index",
                release_id=self.release_id,
                intercept_reason="sandbox_release_index",
            )
            return result

        result = search_eval_fixture(query=query, bindings=bindings)
        record_knowledge_tool_call(
            self.tool_calls,
            query=query,
            groups=groups,
            result=result,
            backend="eval-fixture",
            intercept_reason="sandbox_fixture",
        )
        return result

    def consume_tool_calls(self) -> list[dict[str, Any]]:
        calls = list(self.tool_calls)
        self.tool_calls = []
        return calls


class _EvalTicketService:
    """Mock ticket service recording ticket creation and tool calls in evaluation sandbox."""

    def __init__(self) -> None:
        self.created_tickets: list[Any] = []
        self.tool_calls: list[dict[str, Any]] = []

    async def get_ticket_items(self, *, correlation_id: str | None = None) -> list[Any]:
        _ = correlation_id
        self.tool_calls.append(
            {
                "call_id": f"ticket-items-{len(self.tool_calls)}",
                "tool_name": "ticket.get_ticket_items",
                "arguments": {"correlation_id": correlation_id},
                "result": {"items": []},
                "duration_ms": 0.0,
                "is_error": False,
                "was_intercepted": True,
                "side_effect_blocked": False,
                "intercept_reason": "sandbox_fixture",
            }
        )
        return []

    async def create_ticket(self, draft: Any, **kwargs: Any) -> Any:
        self.created_tickets.append(draft)
        arguments = {
            "title": getattr(draft, "title", None),
            "description": getattr(draft, "description", None),
            "category": getattr(draft, "category", None),
            "priority": getattr(draft, "priority", None),
        }
        arguments.update({key: kwargs[key] for key in kwargs})
        ticket = get_eval_agent_bindings().build_ticket(
            id=f"EVAL-{len(self.created_tickets)}",
            title=getattr(draft, "title", "eval-ticket") or "eval-ticket",
            status="OPEN",
        )
        self.tool_calls.append(
            {
                "call_id": f"ticket-create-{len(self.tool_calls)}",
                "tool_name": "ticket.create_ticket",
                "arguments": arguments,
                "result": {"ticket_id": ticket.id, "status": ticket.status},
                "duration_ms": 0.0,
                "is_error": False,
                "was_intercepted": True,
                "side_effect_blocked": False,
                "intercept_reason": "sandbox_fixture",
            }
        )
        return ticket

    async def list_tickets_by_requester(
        self, requester_id: str, *, correlation_id: str | None = None
    ) -> list[Any]:
        _ = requester_id, correlation_id
        return []

    async def get_ticket(
        self, ticket_id: str, requester_id: str, *, correlation_id: str | None = None
    ) -> Any:
        _ = ticket_id, requester_id, correlation_id
        return None

    def consume_tool_calls(self) -> list[dict[str, Any]]:
        calls = list(self.tool_calls)
        self.tool_calls = []
        return calls


def resolve_eval_candidate_prompt(*, template: str, model_id: str) -> Any:
    """Build the immutable ResolvedExtractorPrompt used by eval candidate binding."""
    return get_eval_agent_bindings().resolve_candidate_prompt(
        template=template, model_id=model_id
    )


def rebind_eval_workflow_models(workflow: Any, model: Any) -> None:
    """Install the candidate model on supervisor, handoff router, and ticket selector."""
    get_eval_agent_bindings().rebind_workflow_models(workflow, model)


def build_eval_active_handoff_case(
    *,
    tenant_id: str,
    conversation_id: str,
    requester_id: str,
    case_id: str,
    session_id: str,
    correlation_id: str,
    created_at: Any,
    session_expires_at: Any,
    retention_expires_at: Any,
) -> Any:
    """Seed fixture for active SUMMARY_REVIEW handoff state."""
    return get_eval_agent_bindings().build_active_handoff_case(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        requester_id=requester_id,
        case_id=case_id,
        session_id=session_id,
        correlation_id=correlation_id,
        created_at=created_at,
        session_expires_at=session_expires_at,
        retention_expires_at=retention_expires_at,
    )


def build_eval_agent_request(
    *,
    request_id: str,
    tenant_id: str,
    conversation_id: str,
    teams_user_id: str,
    entra_object_id: str,
    display_name: str,
    email: str,
    groups: list[str],
    text: str,
    correlation_id: str,
) -> Any:
    """Build the AgentRequest envelope used by isolated eval turns."""
    return get_eval_agent_bindings().build_agent_request(
        request_id=request_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        teams_user_id=teams_user_id,
        entra_object_id=entra_object_id,
        display_name=display_name,
        email=email,
        groups=groups,
        text=text,
        correlation_id=correlation_id,
    )
