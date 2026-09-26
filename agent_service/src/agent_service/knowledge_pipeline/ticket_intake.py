"""Ticket-intake field coverage for unlock / dispatch answers."""

from __future__ import annotations

_TICKET_INTAKE_QUERY_MARKERS: tuple[str, ...] = (
    "解鎖",
    "帳號鎖定",
    "密碼鎖住",
    "帳號被鎖",
    "轉派工單",
    "建立工單",
)

_TICKET_INTAKE_SECTION_MARKERS: tuple[str, ...] = (
    "建立工單前資訊確認",
)

_TICKET_INTAKE_FIELD_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("requester_name", ("使用者姓名",)),
    ("employee_id", ("員工編號",)),
    ("haomai_account", ("好麥帳號",)),
    ("unlock_layer", ("解鎖層數", "需解鎖層數")),
    ("problem_description", ("問題描述",)),
    ("error_evidence", ("錯誤畫面", "錯誤訊息截圖")),
)

_FIELD_LABELS: dict[str, str] = {
    "requester_name": "使用者姓名",
    "employee_id": "員工編號",
    "haomai_account": "好麥帳號",
    "unlock_layer": "解鎖層數",
    "problem_description": "問題描述",
    "error_evidence": "錯誤畫面",
}


def query_asks_for_ticket_intake(query: str) -> bool:
    text = query or ""
    return any(marker in text for marker in _TICKET_INTAKE_QUERY_MARKERS)


def text_has_ticket_intake_section(text: str) -> bool:
    blob = text or ""
    return any(marker in blob for marker in _TICKET_INTAKE_SECTION_MARKERS)


def ticket_intake_fields_in_text(text: str) -> list[str]:
    folded = (text or "").casefold()
    found: list[str] = []
    for field_id, variants in _TICKET_INTAKE_FIELD_MARKERS:
        if any(variant.casefold() in folded for variant in variants):
            found.append(field_id)
    return found


def answer_covers_ticket_intake_fields(answer: str, field_ids: list[str]) -> bool:
    """Whether the answer retains enough ticket-intake fields from context."""
    if len(field_ids) < 2:
        return True
    answer_fields = set(ticket_intake_fields_in_text(answer))
    hits = sum(1 for field_id in field_ids if field_id in answer_fields)
    if len(field_ids) >= 4:
        required = max(4, (len(field_ids) * 2) // 3)
    else:
        required = max(2, (len(field_ids) + 1) // 2)
    return hits >= required


def missing_ticket_intake_fields(answer: str, field_ids: list[str]) -> list[str]:
    answer_fields = set(ticket_intake_fields_in_text(answer))
    return [field_id for field_id in field_ids if field_id not in answer_fields]


def ticket_intake_field_labels(field_ids: list[str]) -> list[str]:
    return [_FIELD_LABELS.get(field_id, field_id) for field_id in field_ids]


__all__ = [
    "answer_covers_ticket_intake_fields",
    "missing_ticket_intake_fields",
    "query_asks_for_ticket_intake",
    "text_has_ticket_intake_section",
    "ticket_intake_field_labels",
    "ticket_intake_fields_in_text",
]
