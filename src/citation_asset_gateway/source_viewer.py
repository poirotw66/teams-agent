"""HTML viewer for signed knowledge source documents."""

from __future__ import annotations

import html
from pathlib import Path

import markdown as markdown_lib

from teams_agent.settings import AgentSettings
from .source_viewer_markdown import (
    first_heading,
    mark_evidence_block,
    replace_highlight_tokens,
    rewrite_markdown_images,
    sanitize_rendered_urls,
    strip_front_matter,
)
from .source_viewer_template import highlight_notice, render_page, status_html

__all__ = [
    "render_source_document_html",
    "render_source_markdown_html",
]


def render_source_document_html(
    path: Path,
    settings: AgentSettings,
    *,
    now: int | None = None,
) -> bytes:
    """Render a markdown/text source file as a readable HTML document page."""

    raw = path.read_text(encoding="utf-8")
    return render_source_markdown_html(
        raw,
        settings,
        now=now,
        fallback_title=path.stem,
    )


def render_source_markdown_html(
    raw: str,
    settings: AgentSettings,
    *,
    now: int | None = None,
    fallback_title: str = "引用來源",
    release_id: str | None = None,
    evidence: str | None = None,
    status_message: str | None = None,
    mapping_status: str | None = None,
    download_url: str | None = None,
) -> bytes:
    """Render a complete Markdown source with an optional cited-block highlight."""

    body, meta_title = strip_front_matter(raw)
    source_heading = first_heading(body)
    title = meta_title or source_heading or fallback_title
    body = rewrite_markdown_images(
        body,
        settings,
        now=now,
        release_id=release_id,
    )
    body, is_highlighted = mark_evidence_block(body, evidence)
    body = body.replace("<", "&lt;")
    rendered = markdown_lib.markdown(
        body,
        extensions=[
            "fenced_code",
            "tables",
            "sane_lists",
            "smarty",
        ],
        output_format="html5",
    )
    rendered = replace_highlight_tokens(rendered)
    rendered = sanitize_rendered_urls(rendered)
    if source_heading is None:
        rendered = f"<h1>{html.escape(title)}</h1>\n{rendered}"
    page = render_page(
        title=html.escape(title),
        status=status_html(
            status_message=status_message,
            mapping_status=mapping_status,
            download_url=download_url,
        ),
        highlight_notice_html=highlight_notice(is_highlighted, bool(evidence)),
        content=rendered,
    )
    return page.encode("utf-8")
