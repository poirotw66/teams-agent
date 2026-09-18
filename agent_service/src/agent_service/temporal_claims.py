"""Temporal freshness helpers for FAQ body dates vs current status.

ACTIVE documents may still contain historical incident notes and past
deadlines. These helpers annotate retrieval context and rewrite answers so
document-recorded history is not presented as the caller's live state.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

_ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_SLASH_DATE_RE = re.compile(r"\b(20\d{2})/(\d{1,2})/(\d{1,2})\b")
_CHINESE_DATE_RE = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")

_VALIDITY_CONTEXT_RE = re.compile(
    r"(?:有效期至|有效至|有效期限|期限至|available until|Unlicensed VPN access is available until)",
    re.IGNORECASE,
)

_HISTORICAL_ANNOTATION = "【歷史記載日期，不得當成使用者目前狀態或現行有效期】"

_PAST_VALIDITY_CLAIM_RE = re.compile(
    r"(?P<prefix>(?:該|此|其)?(?:授權)?(?:有效期至|有效至|有效期限至|期限至)\s*)"
    r"(?P<bold>\*\*)?(?P<date>20\d{2}-\d{2}-\d{2}|20\d{2}/\d{1,2}/\d{1,2}|"
    r"20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)(?P=bold)?",
    re.IGNORECASE,
)

_ABSOLUTE_PRESENT_DIAGNOSIS_RE = re.compile(
    r"(?:代表|表示)\s*目前\s*(?P<body>[^。\n\[`]{2,48}"
    r"(?:不足|過期|失效|鎖定|異常|錯誤))"
)


def _parse_calendar_date(year: str, month: str, day: str) -> date | None:
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def iter_calendar_dates(text: str) -> list[tuple[re.Match[str], date]]:
    """Return regex matches and parsed calendar dates found in ``text``."""
    found: list[tuple[re.Match[str], date]] = []
    for pattern in (_ISO_DATE_RE, _SLASH_DATE_RE, _CHINESE_DATE_RE):
        for match in pattern.finditer(text):
            parsed = _parse_calendar_date(match.group(1), match.group(2), match.group(3))
            if parsed is not None:
                found.append((match, parsed))
    found.sort(key=lambda item: item[0].start())
    return found


def _resolve_today(evaluated_at: datetime | date | None) -> date:
    if evaluated_at is None:
        return datetime.now(UTC).date()
    if isinstance(evaluated_at, datetime):
        moment = evaluated_at
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        else:
            moment = moment.astimezone(UTC)
        return moment.date()
    return evaluated_at


def annotate_historical_dates_in_text(
    text: str,
    *,
    evaluated_at: datetime | date | None = None,
) -> str:
    """Mark past calendar dates in retrieval context as historical records."""
    today = _resolve_today(evaluated_at)
    if not text or _HISTORICAL_ANNOTATION in text:
        return text

    pieces: list[str] = []
    cursor = 0
    for match, parsed in iter_calendar_dates(text):
        window_start = max(0, match.start() - 40)
        local_context = text[window_start : match.end() + 12]
        if parsed >= today or _HISTORICAL_ANNOTATION in local_context:
            continue
        if not _VALIDITY_CONTEXT_RE.search(local_context) and "有效期" not in local_context:
            continue
        pieces.append(text[cursor : match.end()])
        pieces.append(_HISTORICAL_ANNOTATION)
        cursor = match.end()
    pieces.append(text[cursor:])
    return "".join(pieces)


def sanitize_temporal_claims(
    answer: str,
    *,
    evaluated_at: datetime | date | None = None,
) -> str:
    """Rewrite past-as-current validity and absolute present diagnoses."""
    if not answer:
        return answer

    today = _resolve_today(evaluated_at)
    sanitized = answer

    def _rewrite_past_validity(match: re.Match[str]) -> str:
        raw_date = match.group("date")
        parsed: date | None = None
        for pattern in (_ISO_DATE_RE, _SLASH_DATE_RE, _CHINESE_DATE_RE):
            date_match = pattern.fullmatch(raw_date.strip())
            if date_match is not None:
                parsed = _parse_calendar_date(
                    date_match.group(1),
                    date_match.group(2),
                    date_match.group(3),
                )
                break
        if parsed is None or parsed >= today:
            return match.group(0)
        return (
            f"文件曾記載{match.group('prefix').strip()} {raw_date.strip()}"
            f"（歷史條目，不能當作現行有效期）"
        )

    sanitized = _PAST_VALIDITY_CLAIM_RE.sub(_rewrite_past_validity, sanitized)

    def _rewrite_absolute_diagnosis(match: re.Match[str]) -> str:
        body = match.group("body").strip()
        return f"文件記載可能表示{body}；現況請向權責單位確認"

    sanitized = _ABSOLUTE_PRESENT_DIAGNOSIS_RE.sub(_rewrite_absolute_diagnosis, sanitized)
    sanitized = re.sub(r"[ \t]{2,}", " ", sanitized)
    sanitized = re.sub(r"[。]{2,}", "。", sanitized)
    return sanitized.strip()


__all__ = [
    "annotate_historical_dates_in_text",
    "iter_calendar_dates",
    "sanitize_temporal_claims",
]
