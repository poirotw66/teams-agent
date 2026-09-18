"""FAQ hit aggregation helpers for FeedbackQueryMixin.faq_performance."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from operations_core.contracts import DEFAULT_TIMEZONE, OperationalEvent, utc_now


def aggregate_faq_hits(
    all_hits: list[OperationalEvent],
    hits: list[OperationalEvent],
    *,
    faq_key: str,
    faq_id: str | None,
    as_of: datetime | None,
) -> dict[str, Any]:
    local_tz = ZoneInfo(DEFAULT_TIMEZONE)
    local_now = (as_of or utc_now()).astimezone(local_tz)
    today_date = local_now.date().isoformat()
    current_iso = local_now.isocalendar()[:2]
    current_month = local_now.strftime("%Y-%m")

    def _to_local(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC).astimezone(local_tz)
        return dt.astimezone(local_tz)

    today_hit_count = sum(
        1 for e in all_hits if _to_local(e.occurred_at).date().isoformat() == today_date
    )
    this_week_hit_count = sum(
        1 for e in all_hits if _to_local(e.occurred_at).isocalendar()[:2] == current_iso
    )
    this_month_hit_count = sum(
        1 for e in all_hits if _to_local(e.occurred_at).strftime("%Y-%m") == current_month
    )
    by_day: Counter[str] = Counter()
    by_week: Counter[str] = Counter()
    by_month: Counter[str] = Counter()
    by_version: Counter[str] = Counter()
    for event in hits:
        occurred = _to_local(event.occurred_at)
        iso_year, iso_week, _ = occurred.isocalendar()
        by_day[occurred.date().isoformat()] += 1
        by_week[f"{iso_year}-W{iso_week:02d}"] += 1
        by_month[occurred.strftime("%Y-%m")] += 1
        by_version[str(event.payload.get("faqVersionId") or "legacy-unattributed")] += 1

    resolved_faq_id = faq_id or next(
        (str(e.payload.get("faqId")) for e in all_hits if e.payload.get("faqId")),
        None,
    )
    total_hit_count = len(all_hits)
    return {
        "faqKey": faq_key,
        "faqId": resolved_faq_id,
        "totalHitCount": total_hit_count,
        "totalHits": total_hit_count,
        "todayHitCount": today_hit_count,
        "hitsToday": today_hit_count,
        "thisWeekHitCount": this_week_hit_count,
        "hitsThisWeek": this_week_hit_count,
        "thisMonthHitCount": this_month_hit_count,
        "hitsThisMonth": this_month_hit_count,
        "rangeHitCount": len(hits),
        "byDay": [{"period": key, "hitCount": value} for key, value in sorted(by_day.items())],
        "byWeek": [{"period": key, "hitCount": value} for key, value in sorted(by_week.items())],
        "byMonth": [
            {"period": key, "hitCount": value} for key, value in sorted(by_month.items())
        ],
        "byVersion": [
            {"versionId": key, "hitCount": value}
            for key, value in by_version.most_common()
        ],
        "recentHits": [
            {
                "occurredAt": event.occurred_at.isoformat(),
                "conversationId": event.conversation_id,
                "turnId": event.turn_id,
                "correlationId": event.correlation_id,
                "faqId": event.payload.get("faqId") or resolved_faq_id,
                "versionId": event.payload.get("faqVersionId"),
            }
            for event in sorted(hits, key=lambda item: item.occurred_at, reverse=True)[
                :50
            ]
        ],
    }
