"""FAQ list filtering helpers."""

from __future__ import annotations

from typing import Any


def filter_faq_items(
    items: list[dict[str, Any]],
    *,
    status: str | None,
    owner_unit_id: str | None,
    category: str | None,
    keyword: str | None,
    query: str | None,
) -> list[dict[str, Any]]:
    """Apply optional list filters to FAQ detail payloads."""
    filtered = items
    if status:
        filtered = [item for item in filtered if item["faq"]["status"] == status]
    if owner_unit_id:
        filtered = [
            item
            for item in filtered
            if item["version"]["content"]["owner_unit_id"] == owner_unit_id
        ]
    if category:
        cat_needle = category.casefold()
        filtered = [
            item
            for item in filtered
            if str(item["version"]["content"].get("category") or "").casefold()
            == cat_needle
        ]
    if keyword:
        keyword_needle = keyword.casefold()
        filtered = [
            item
            for item in filtered
            if any(
                keyword_needle in str(value).casefold()
                for value in (item["version"]["content"].get("keywords") or ())
            )
        ]
    if query:
        needle = query.casefold()
        filtered = [
            item
            for item in filtered
            if any(
                needle in str(value).casefold()
                for value in (
                    item["faq"]["faq_key"],
                    item["version"]["content"]["question"],
                    item["version"]["content"].get("answer") or "",
                    item["version"]["content"].get("category") or "",
                    " ".join(item["version"]["content"].get("keywords") or ()),
                )
            )
        ]
    return filtered
