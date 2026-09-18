"""Tabular row extraction helpers for export CSV/XLSX flattening."""

from __future__ import annotations

import json
from typing import Any

_CONVERSATION_HEADERS = [
    "conversationId",
    "turnId",
    "occurredAt",
    "actorRef",
    "userMessage",
    "aiReply",
    "model",
    "issueTypeId",
    "route",
    "faqKey",
    "documentIds",
    "sourcePaths",
    "feedbackRating",
    "feedbackReason",
    "resolvedStatus",
    "handoffStatus",
    "ticketId",
    "ticketStatus",
    "ticketBackend",
    "channelScope",
]


def sanitize_csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{text}"
    return text


def _join_list(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return str(value or "")


def _conversation_turn_row(
    *,
    conv_id: str,
    actor_ref: str,
    channel_scope: str,
    turn: dict[str, Any],
) -> list[str]:
    return [
        sanitize_csv_cell(conv_id),
        sanitize_csv_cell(turn.get("turnId") or ""),
        sanitize_csv_cell(turn.get("occurredAt") or ""),
        sanitize_csv_cell(turn.get("actorRef") or actor_ref),
        sanitize_csv_cell(turn.get("userMessage") or ""),
        sanitize_csv_cell(turn.get("aiReply") or ""),
        sanitize_csv_cell(turn.get("model") or ""),
        sanitize_csv_cell(turn.get("issueTypeId") or ""),
        sanitize_csv_cell(turn.get("route") or ""),
        sanitize_csv_cell(turn.get("faqKey") or ""),
        sanitize_csv_cell(_join_list(turn.get("documentIds"))),
        sanitize_csv_cell(_join_list(turn.get("sourcePaths"))),
        sanitize_csv_cell(turn.get("feedbackRating") or ""),
        sanitize_csv_cell(turn.get("feedbackReason") or ""),
        sanitize_csv_cell(turn.get("resolvedStatus") or ""),
        sanitize_csv_cell(turn.get("handoffStatus") or ""),
        sanitize_csv_cell(turn.get("ticketId") or ""),
        sanitize_csv_cell(turn.get("ticketStatus") or ""),
        sanitize_csv_cell(turn.get("ticketBackend") or ""),
        sanitize_csv_cell(channel_scope),
    ]


def _conversation_summary_row(conv: dict[str, Any]) -> list[str]:
    conv_id = str(conv.get("conversationId") or "")
    actor_ref = str(conv.get("actorRef") or "")
    channel_scope = str(conv.get("channelScope") or "")
    return [
        sanitize_csv_cell(conv_id),
        "",
        sanitize_csv_cell(conv.get("lastOccurredAt") or ""),
        sanitize_csv_cell(actor_ref),
        "",
        "",
        "",
        "",
        sanitize_csv_cell(_join_list(conv.get("routes"))),
        "",
        "",
        "",
        "",
        "",
        "",
        sanitize_csv_cell(conv.get("handoffStatus") or ""),
        sanitize_csv_cell(_join_list(conv.get("ticketIds"))),
        sanitize_csv_cell(conv.get("ticketStatus") or ""),
        "",
        sanitize_csv_cell(channel_scope),
    ]


def extract_conversation_rows(items: list[Any]) -> list[list[str]]:
    rows: list[list[str]] = [_CONVERSATION_HEADERS]
    for conv in items:
        if not isinstance(conv, dict):
            continue
        conv_id = str(conv.get("conversationId") or "")
        actor_ref = str(conv.get("actorRef") or "")
        channel_scope = str(conv.get("channelScope") or "")
        turns = conv.get("turns")
        if isinstance(turns, list) and turns:
            for turn in turns:
                if not isinstance(turn, dict):
                    continue
                rows.append(
                    _conversation_turn_row(
                        conv_id=conv_id,
                        actor_ref=actor_ref,
                        channel_scope=channel_scope,
                        turn=turn,
                    )
                )
        else:
            rows.append(_conversation_summary_row(conv))
    return rows


def extract_dict_list_rows(items: list[Any]) -> list[list[str]]:
    keys = list(items[0].keys())
    for item in items[1:]:
        if isinstance(item, dict):
            for key in item:
                if key not in keys:
                    keys.append(key)
    rows: list[list[str]] = [keys]
    for item in items:
        if isinstance(item, dict):
            rows.append([sanitize_csv_cell(item.get(key)) for key in keys])
    return rows


def key_value_rows(payload: dict[str, Any]) -> list[list[str]]:
    rows = [["key", "value"]]
    for key, value in payload.items():
        rows.append([sanitize_csv_cell(key), sanitize_csv_cell(value)])
    return rows


def is_conversation_export(export_type: str, items: Any) -> bool:
    if export_type == "conversations":
        return True
    if not isinstance(items, list) or not items:
        return False
    return any(isinstance(item, dict) and "turns" in item for item in items)
