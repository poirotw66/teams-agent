"""Markdown preprocessing and citation highlighting for the source viewer."""

from __future__ import annotations

import html
import re
from difflib import SequenceMatcher

from .media import build_asset_url
from .settings import AgentSettings

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_IMAGE_MD = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_TITLE_LINE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_URL_ATTRIBUTE = re.compile(r'(?P<attribute>href|src)="(?P<url>[^"]*)"', re.IGNORECASE)
_HIGHLIGHT_START = "CITATIONHIGHLIGHTSTARTTOKEN"
_HIGHLIGHT_END = "CITATIONHIGHLIGHTENDTOKEN"


def strip_front_matter(raw: str) -> tuple[str, str | None]:
    match = _FRONT_MATTER.match(raw)
    if not match:
        return raw, None
    meta = match.group(1)
    title = None
    for line in meta.splitlines():
        if line.lower().startswith("title:"):
            title = line.split(":", 1)[1].strip().strip("'\"")
            break
    return raw[match.end() :], title


def first_heading(body: str) -> str | None:
    match = _TITLE_LINE.search(body)
    return match.group(1).strip() if match else None


def rewrite_markdown_images(
    body: str,
    settings: AgentSettings,
    *,
    now: int | None,
    release_id: str | None = None,
) -> str:
    def replace(match: re.Match[str]) -> str:
        alt_text = match.group(1)
        target = match.group(2).strip().strip("<>").split()[0]
        if "://" in target or target.startswith("#"):
            return match.group(0)
        asset_path = target.removeprefix("assets/")
        url = build_asset_url(
            asset_path,
            settings,
            now=now,
            release_id=release_id,
        )
        if not url:
            return match.group(0)
        return f"![{alt_text}]({url})"

    return _IMAGE_MD.sub(replace, body)


def normalize_match_text(value: str) -> str:
    without_markup = re.sub(r"[#*_`>|~\[\]()-]+", " ", value)
    return re.sub(r"\s+", "", without_markup).casefold()


def mark_evidence_block(body: str, evidence: str | None) -> tuple[str, bool]:
    normalized_evidence = normalize_match_text(evidence or "")
    if len(normalized_evidence) < 8:
        return body, False
    parts = re.split(r"(\n\s*\n)", body)
    candidates: list[tuple[int, str]] = [
        (index, normalize_match_text(part))
        for index, part in enumerate(parts)
        if index % 2 == 0 and normalize_match_text(part)
    ]
    matches = [
        index
        for index, normalized in candidates
        if len(normalized) >= 8
        and (normalized in normalized_evidence or normalized_evidence in normalized)
    ]
    if not matches:
        best = max(
            candidates,
            key=lambda item: SequenceMatcher(
                None,
                normalized_evidence,
                item[1],
                autojunk=False,
            ).ratio(),
            default=None,
        )
        if best is None:
            return body, False
        ratio = SequenceMatcher(
            None,
            normalized_evidence,
            best[1],
            autojunk=False,
        ).ratio()
        if ratio < 0.55:
            return body, False
        matches = [best[0]]
    first, last = min(matches), max(matches)
    parts[first] = f"\n\n{_HIGHLIGHT_START}\n\n{parts[first]}"
    parts[last] = f"{parts[last]}\n\n{_HIGHLIGHT_END}\n\n"
    return "".join(parts), True


def replace_highlight_tokens(rendered: str) -> str:
    start = (
        '<section class="citation-highlight" id="citation-highlight">'
        '<p class="citation-label">索引命中片段</p>'
    )
    return rendered.replace(f"<p>{_HIGHLIGHT_START}</p>", start).replace(
        f"<p>{_HIGHLIGHT_END}</p>",
        "</section>",
    )


def sanitize_rendered_urls(rendered: str) -> str:
    def replace(match: re.Match[str]) -> str:
        attribute = match.group("attribute").lower()
        url = html.unescape(match.group("url")).strip()
        lower_url = url.casefold()
        allowed_schemes = ("https://", "http://")
        is_safe = (
            lower_url.startswith(allowed_schemes)
            or (attribute == "href" and lower_url.startswith(("mailto:", "#")))
            or (
                ":" not in lower_url
                and not lower_url.startswith("//")
                and not lower_url.startswith("\\")
            )
        )
        if not is_safe:
            return f'{attribute}="#"'
        return match.group(0)

    return _URL_ATTRIBUTE.sub(replace, rendered)
