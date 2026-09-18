"""Conversation list, action, and broadcast use cases."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from agent_service.operations.access import ActorContext

from .citations import build_citations_for_turn

logger = logging.getLogger(__name__)


def _feedback_fields(turn: dict[str, Any]) -> tuple[str | None, str | None]:
    fb_raw = turn.get("feedbackRating")
    feedback = "positive" if fb_raw == "UP" else ("negative" if fb_raw == "DOWN" else None)
    comment = turn.get("feedbackReason") if feedback == "negative" else None
    return feedback, comment


def _messages_for_turns(
    turns: list[dict[str, Any]],
    *,
    query_service: Any,
    normalize_ai_text: Callable[[str], str],
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for turn in turns:
        occurred = turn.get("occurredAt", "")[:19].replace("T", " ")
        user_text = (
            turn.get("userMessage") or turn.get("messageMasked") or turn.get("message") or ""
        )
        if user_text:
            messages.append(
                {
                    "id": f"msg-{turn.get('turnId')}-user",
                    "sender": "user",
                    "content": user_text,
                    "timestamp": occurred or "剛剛",
                }
            )

        ai_text = turn.get("aiReply") or turn.get("answerMasked") or turn.get("answer") or ""
        if ai_text:
            feedback, feedback_comment = _feedback_fields(turn)
            messages.append(
                {
                    "id": f"msg-{turn.get('turnId')}-bot",
                    "sender": "bot",
                    "content": normalize_ai_text(ai_text),
                    "timestamp": occurred or "剛剛",
                    "feedback": feedback,
                    "feedback_comment": feedback_comment,
                    "citations": build_citations_for_turn(turn, ai_text, query_service),
                }
            )
    return messages


def _conversation_status(
    conversation_id: str,
    *,
    resolved_set: set[str],
    ticket_map: dict[str, Any],
    messages: list[dict[str, Any]],
) -> str:
    if conversation_id in resolved_set:
        return "RESOLVED"
    if conversation_id in ticket_map:
        return "ESCALATED_TICKET"
    if any(message.get("feedback") == "negative" for message in messages):
        return "PENDING_REVIEW"
    return "RESOLVED"


def _reporter_name(actor_ref: str) -> str:
    if actor_ref.startswith("actor_"):
        return f"同仁 ({actor_ref[6:10]})"
    if actor_ref != "同仁":
        return actor_ref
    return "企業同仁"


def _payload_for_conversation(
    *,
    item: dict[str, Any],
    turns: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    resolved_set: set[str],
    root_causes: dict[str, Any],
    ticket_map: dict[str, Any],
) -> dict[str, Any]:
    conversation_id = item.get("conversationId", "")
    first_user_msg = next(
        (message["content"] for message in messages if message["sender"] == "user"),
        "系統諮詢與帳號服務",
    )
    topic_summary = first_user_msg[:30] + ("..." if len(first_user_msg) > 30 else "")
    started_at = (turns[0].get("occurredAt") if turns else item.get("lastActivity", ""))[
        :19
    ].replace("T", " ")
    actor_ref = item.get("actorRef") or (turns[0].get("actorRef") if turns else None) or "同仁"
    channel = item.get("channelScope") or "Teams"
    dept = f"{channel} 線上諮詢" if channel != "Teams" else "內部同仁"
    return {
        "id": conversation_id,
        "reporter_name": _reporter_name(str(actor_ref)),
        "reporter_dept": dept,
        "reporter_ext": "-",
        "started_at": started_at or "2026-09-16 10:00:00",
        "topic_summary": topic_summary,
        "status": _conversation_status(
            conversation_id,
            resolved_set=resolved_set,
            ticket_map=ticket_map,
            messages=messages,
        ),
        "root_cause": root_causes.get(conversation_id),
        "associated_ticket_id": ticket_map.get(conversation_id),
        "messages": messages,
    }


async def build_conversation_list(
    *,
    actor: ActorContext,
    query_service: Any,
    workbench_state: dict[str, Any],
    tickets: list[dict[str, Any]],
    normalize_ai_text: Callable[[str], str],
) -> list[dict[str, Any]]:
    """Assemble workbench conversation stream payloads from ops query data."""
    resolved_set = set(workbench_state.get("resolved_conversations", []))
    root_causes = workbench_state.get("root_causes", {})
    ticket_map = {
        ticket.get("conversation_id"): ticket.get("ticket_number")
        for ticket in tickets
        if ticket.get("conversation_id")
    }

    conv_res = await query_service.list_conversations(actor, days=365)
    items = conv_res.get("items", [])
    query_actor = actor
    if not items:
        query_actor = ActorContext(
            user_id=actor.user_id,
            display_name=actor.display_name,
            role=actor.role,
            owner_unit_ids=actor.owner_unit_ids,
            tenant_id="local-development",
        )
        conv_res = await query_service.list_conversations(query_actor, days=365)
        items = conv_res.get("items", [])

    results: list[dict[str, Any]] = []
    for item in items:
        conversation_id = item.get("conversationId", "")
        try:
            detail = await query_service.conversation_detail(
                query_actor, conversation_id=conversation_id
            )
        except Exception as err:
            logger.debug("Failed to get detail for conversation %s: %s", conversation_id, err)
            continue
        if not isinstance(detail, dict):
            logger.debug("Conversation %s has no detail payload", conversation_id)
            continue
        turns = detail.get("turns", [])
        messages = _messages_for_turns(
            turns,
            query_service=query_service,
            normalize_ai_text=normalize_ai_text,
        )
        results.append(
            _payload_for_conversation(
                item=item,
                turns=turns,
                messages=messages,
                resolved_set=resolved_set,
                root_causes=root_causes,
                ticket_map=ticket_map,
            )
        )
    return results


def apply_conversation_action(
    *,
    conversation_id: str,
    action: str,
    root_cause: str | None,
    workbench_state: dict[str, Any],
) -> dict[str, Any]:
    """Mutate workbench state for resolve / root-cause actions."""
    if action == "resolve":
        resolved = workbench_state.setdefault("resolved_conversations", [])
        if conversation_id not in resolved:
            resolved.append(conversation_id)
    elif action == "root_cause" and root_cause:
        workbench_state.setdefault("root_causes", {})[conversation_id] = root_cause
    return {"ok": True, "conversation_id": conversation_id, "action": action}


def set_emergency_broadcast(
    *,
    message: str,
    duration_hours: int,
    created_by: str,
    workbench_state: dict[str, Any],
) -> dict[str, Any]:
    """Persist a temporary emergency broadcast on workbench state."""
    expires_at = datetime.now(UTC) + timedelta(hours=duration_hours)
    workbench_state["broadcast"] = {
        "message": message,
        "expires_at": expires_at.isoformat(),
        "created_by": created_by,
    }
    return {"ok": True, "expires_at": expires_at.isoformat()}
