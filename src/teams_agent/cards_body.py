"""Adaptive Card body builders for Teams agent replies."""

from __future__ import annotations

import re

from .contracts import AgentResponse, format_teams_answer
from .media import build_asset_url
from .settings import AgentSettings


def build_image_card_body(
    response: AgentResponse,
    settings: AgentSettings,
    now: int | None,
) -> list[dict[str, object]]:
    body: list[dict[str, object]] = [
        {
            "type": "TextBlock",
            "text": format_teams_answer(response.answer),
            "wrap": True,
        }
    ]
    for image in response.images:
        url = build_asset_url(
            image.path,
            settings,
            now,
            release_id=image.releaseId,
        )
        if not url:
            continue
        body.extend(
            [
                {
                    "type": "TextBlock",
                    "text": image.title,
                    "weight": "Bolder",
                    "wrap": True,
                    "spacing": "Medium",
                },
                {
                    "type": "Image",
                    "url": url,
                    "altText": image.altText,
                    "size": "Stretch",
                },
            ]
        )
    if response.citations:
        body.append(_citations_block(response))
    return body


def _citations_block(response: AgentResponse) -> dict[str, object]:
    has_citations_in_answer = bool(re.search(r"\[S\d+\]", response.answer))
    sources = "\n".join(
        (
            f"- [S{index}] [{citation.title}]({citation.url})"
            if citation.url
            else f"- [S{index}] {citation.title}"
        )
        if has_citations_in_answer
        else (
            f"- [{citation.title}]({citation.url})"
            if citation.url
            else f"- {citation.title}"
        )
        for index, citation in enumerate(response.citations, start=1)
    )
    return {
        "type": "TextBlock",
        "text": f"**來源**\n\n{sources}",
        "wrap": True,
        "spacing": "Medium",
        "isSubtle": True,
    }
