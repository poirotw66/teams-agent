"""HTML viewer for signed knowledge source documents."""

from __future__ import annotations

import html
import re
from difflib import SequenceMatcher
from pathlib import Path

import markdown as markdown_lib

from .media import build_asset_url
from .settings import AgentSettings

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_IMAGE_MD = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_TITLE_LINE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_URL_ATTRIBUTE = re.compile(r'(?P<attribute>href|src)="(?P<url>[^"]*)"', re.IGNORECASE)
_HIGHLIGHT_START = "CITATIONHIGHLIGHTSTARTTOKEN"
_HIGHLIGHT_END = "CITATIONHIGHLIGHTENDTOKEN"
_MAPPING_STATUS_LABELS = {
    "AVAILABLE": "版本已核對",
    "INDEX_PENDING": "索引處理中",
    "ORIGINAL_NOT_PRESERVED": "原始附件未保存",
    "SOURCE_MISSING": "來源檔案遺失",
    "MAPPING_UNAVAILABLE": "版本對應不可用",
    "LEGACY_UNVERIFIED": "歷史版本未確認",
    "EDITED_DERIVATIVE": "已編輯衍生版本",
}


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

    body, meta_title = _strip_front_matter(raw)
    source_heading = _first_heading(body)
    title = meta_title or source_heading or fallback_title
    body = _rewrite_markdown_images(
        body,
        settings,
        now=now,
        release_id=release_id,
    )
    body, is_highlighted = _mark_evidence_block(body, evidence)
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
    rendered = _replace_highlight_tokens(rendered)
    rendered = _sanitize_rendered_urls(rendered)
    if source_heading is None:
        rendered = f"<h1>{html.escape(title)}</h1>\n{rendered}"
    page = _HTML_TEMPLATE.format(
        title=html.escape(title),
        status=_status_html(
            status_message=status_message,
            mapping_status=mapping_status,
            download_url=download_url,
        ),
        highlight_notice=_highlight_notice(is_highlighted, bool(evidence)),
        content=rendered,
    )
    return page.encode("utf-8")


def _strip_front_matter(raw: str) -> tuple[str, str | None]:
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


def _first_heading(body: str) -> str | None:
    match = _TITLE_LINE.search(body)
    return match.group(1).strip() if match else None


def _rewrite_markdown_images(
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


def _normalize_match_text(value: str) -> str:
    without_markup = re.sub(r"[#*_`>|~\[\]()-]+", " ", value)
    return re.sub(r"\s+", "", without_markup).casefold()


def _mark_evidence_block(body: str, evidence: str | None) -> tuple[str, bool]:
    normalized_evidence = _normalize_match_text(evidence or "")
    if len(normalized_evidence) < 8:
        return body, False
    parts = re.split(r"(\n\s*\n)", body)
    candidates: list[tuple[int, str]] = [
        (index, _normalize_match_text(part))
        for index, part in enumerate(parts)
        if index % 2 == 0 and _normalize_match_text(part)
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


def _replace_highlight_tokens(rendered: str) -> str:
    start = (
        '<section class="citation-highlight" id="citation-highlight">'
        '<p class="citation-label">索引命中片段</p>'
    )
    return rendered.replace(f"<p>{_HIGHLIGHT_START}</p>", start).replace(
        f"<p>{_HIGHLIGHT_END}</p>",
        "</section>",
    )


def _sanitize_rendered_urls(rendered: str) -> str:
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


def _status_html(
    *,
    status_message: str | None,
    mapping_status: str | None,
    download_url: str | None,
) -> str:
    if not any((status_message, mapping_status, download_url)):
        return ""
    status_value = mapping_status or ""
    status = html.escape(_MAPPING_STATUS_LABELS.get(status_value, status_value))
    status_title = html.escape(status_value, quote=True)
    message = html.escape(status_message or "")
    download = ""
    if download_url:
        safe_url = html.escape(download_url, quote=True)
        download = f'<a class="download" href="{safe_url}">開啟原始附件</a>'
    return (
        '<aside class="source-status">'
        f'<div><span class="status-code" title="{status_title}">{status}</span>'
        f"<p>{message}</p></div>"
        f"{download}</aside>"
    )


def _highlight_notice(is_highlighted: bool, has_evidence: bool) -> str:
    if is_highlighted or not has_evidence:
        return ""
    return (
        '<p class="highlight-missing" id="citation-highlight">'
        "已顯示完整文件，但無法在此版本中精準定位引用片段。"
        "</p>"
    )


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light dark;
      --ink: #242424;
      --muted: #616161;
      --paper: #f5f5f5;
      --card: #fdfdfd;
      --line: #d1d1d1;
      --line-subtle: #e8e8e8;
      --accent: #5b5fc7;
      --accent-strong: #464775;
      --brand: #5b5fc7;
      --button-bg: #5b5fc7;
      --button-hover: #464775;
      --brand-soft: #f0f0fa;
      --code-bg: #f0f0f0;
      --code-ink: #292a4a;
      --highlight: #fff4ce;
      --highlight-ink: #4d4300;
      --focus: #5b5fc7;
      --shadow: rgb(0 0 0 / 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      background: var(--paper);
      font-family: "Segoe UI", "PingFang TC", "Microsoft JhengHei",
        "Noto Sans TC", sans-serif;
      line-height: 1.7;
      text-rendering: optimizeLegibility;
    }}
    .shell {{
      width: min(920px, calc(100% - 2rem));
      margin: 0 auto;
      padding: 1.5rem 0 3rem;
    }}
    .viewer-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      min-height: 64px;
      margin-bottom: 1rem;
    }}
    .eyebrow {{
      margin: 0;
      color: var(--brand);
      font-size: 0.82rem;
      font-weight: 700;
    }}
    .access-label {{
      flex: 0 0 auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--card);
      color: var(--muted);
      padding: 0.35rem 0.65rem;
      font-size: 0.78rem;
      font-weight: 600;
    }}
    article {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: clamp(1.4rem, 5vw, 3.75rem);
      box-shadow: 0 2px 8px var(--shadow);
    }}
    .source-status {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      margin-bottom: 1rem;
      padding: 0.85rem 1rem;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--card);
    }}
    .source-status p {{
      margin: 0.2rem 0 0;
      color: var(--muted);
      font-size: 0.9rem;
      line-height: 1.5;
    }}
    .status-code {{
      color: var(--brand);
      font-size: 0.8rem;
      font-weight: 700;
    }}
    .download {{
      flex: 0 0 auto;
      border-radius: 8px;
      background: var(--button-bg);
      color: #fdfdfd;
      padding: 0.55rem 0.8rem;
      font-weight: 600;
      text-decoration: none;
    }}
    .download:hover {{ background: var(--button-hover); color: #fdfdfd; }}
    .download:active {{ transform: translateY(1px); }}
    a:focus-visible {{
      border-radius: 4px;
      outline: 3px solid var(--focus);
      outline-offset: 3px;
    }}
    .citation-highlight {{
      position: relative;
      margin: 1.75rem -1rem;
      padding: 1.25rem 1rem 0.3rem;
      border-left: 4px solid var(--brand);
      border-radius: 0 8px 8px 0;
      background: var(--highlight);
      color: var(--highlight-ink);
      scroll-margin-top: 1rem;
    }}
    .citation-label {{
      margin: 0 0 0.65rem;
      color: var(--highlight-ink);
      font-size: 0.78rem;
      font-weight: 700;
    }}
    .highlight-missing {{
      margin: 0 0 1rem;
      padding: 0.75rem 0.9rem;
      border: 1px solid var(--line);
      border-left: 4px solid #8a8886;
      border-radius: 0 8px 8px 0;
      background: var(--card);
      color: var(--muted);
      scroll-margin-top: 1.5rem;
    }}
    h1, h2, h3, h4 {{
      line-height: 1.3;
      font-weight: 700;
      color: var(--ink);
    }}
    h1 {{
      margin: 0 0 1.25rem;
      max-width: 24ch;
      font-size: clamp(1.75rem, 4vw, 2.35rem);
      letter-spacing: -0.02em;
    }}
    h2 {{
      margin: 2.5rem 0 0.85rem;
      font-size: 1.35rem;
    }}
    h3 {{ margin: 1.75rem 0 0.6rem; font-size: 1.1rem; }}
    p, ul, ol, table, pre, blockquote {{ margin: 0 0 1.1rem; }}
    article > p, article > ul, article > ol, article > blockquote {{
      max-width: 72ch;
    }}
    li + li {{ margin-top: 0.35rem; }}
    a {{ color: var(--accent); }}
    a:hover {{ color: var(--accent-strong); }}
    code {{
      font-family: "Cascadia Mono", "Consolas", "SF Mono", Menlo, monospace;
      font-size: 0.92em;
      background: var(--brand-soft);
      color: var(--code-ink);
      padding: 0.1em 0.35em;
      border-radius: 4px;
    }}
    pre {{
      overflow-x: auto;
      background: var(--code-ink);
      color: #f5f5f5;
      border-radius: 8px;
      padding: 1rem 1.1rem;
    }}
    pre code {{
      background: transparent;
      color: inherit;
      padding: 0;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.95rem;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 0.7rem 0.8rem;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: var(--brand-soft);
      color: var(--ink);
      font-size: 0.86rem;
      font-weight: 600;
    }}
    tbody tr:nth-child(even) {{ background: color-mix(in srgb, var(--paper) 55%, transparent); }}
    tr:last-child td {{ border-bottom: none; }}
    img {{
      display: block;
      max-width: 100%;
      height: auto;
      margin: 1rem 0;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: var(--card);
    }}
    blockquote {{
      margin-left: 0;
      padding: 0.35rem 0 0.35rem 1rem;
      border-left: 3px solid var(--brand);
      background: var(--brand-soft);
      color: #424242;
      border-radius: 0 8px 8px 0;
    }}
    .viewer-footer {{
      margin: 1rem 0 0;
      color: var(--muted);
      font-size: 0.78rem;
      text-align: center;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --ink: #f5f5f5;
        --muted: #c7c7c7;
        --paper: #1f1f1f;
        --card: #292929;
        --line: #484848;
        --line-subtle: #3a3a3a;
        --accent: #b4aee8;
        --accent-strong: #c8c3f0;
        --brand: #b4aee8;
        --button-bg: #5b5fc7;
        --button-hover: #7772c8;
        --brand-soft: #37364a;
        --code-bg: #333333;
        --code-ink: #202024;
        --highlight: #4a421f;
        --highlight-ink: #fff4ce;
        --focus: #c8c3f0;
        --shadow: rgb(0 0 0 / 0.28);
      }}
    }}
    @media (max-width: 640px) {{
      .shell {{ width: min(100% - 1rem, 920px); padding-top: 0.75rem; }}
      .viewer-header {{ min-height: 56px; }}
      .source-status {{ align-items: stretch; flex-direction: column; }}
      .download {{ text-align: center; }}
      article {{ padding: 1.35rem 1rem 1.8rem; }}
      .citation-highlight {{ margin-inline: -0.5rem; padding-inline: 0.75rem; }}
      table {{ display: block; overflow-x: auto; }}
    }}
    @media print {{
      :root {{ color-scheme: light; }}
      body {{ background: #fdfdfd; color: #242424; }}
      .shell {{ width: 100%; padding: 0; }}
      .access-label, .download, .viewer-footer {{ display: none; }}
      article {{ border: 0; box-shadow: none; padding: 0; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <header class="viewer-header">
      <p class="eyebrow">知識來源</p>
      <span class="access-label">受控文件</span>
    </header>
    {status}
    {highlight_notice}
    <article>
      {content}
    </article>
    <p class="viewer-footer">文件內容依引用時的知識庫版本呈現</p>
  </main>
</body>
</html>
"""
