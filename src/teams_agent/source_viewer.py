"""HTML viewer for signed knowledge source documents."""

from __future__ import annotations

import html
import re
from pathlib import Path

import markdown as markdown_lib

from .media import build_asset_url
from .settings import AgentSettings

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_IMAGE_MD = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_TITLE_LINE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def render_source_document_html(
    path: Path,
    settings: AgentSettings,
    *,
    now: int | None = None,
) -> bytes:
    """Render a markdown/text source file as a readable HTML document page."""

    raw = path.read_text(encoding="utf-8")
    body, meta_title = _strip_front_matter(raw)
    body = _rewrite_markdown_images(body, settings, now=now)
    title = meta_title or _first_heading(body) or path.stem
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
    page = _HTML_TEMPLATE.format(
        title=html.escape(title),
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
) -> str:
    def replace(match: re.Match[str]) -> str:
        alt_text = match.group(1)
        target = match.group(2).strip().strip("<>").split()[0]
        if "://" in target or target.startswith("#"):
            return match.group(0)
        asset_path = target.removeprefix("assets/")
        url = build_asset_url(asset_path, settings, now=now)
        if not url:
            return match.group(0)
        return f"![{alt_text}]({url})"

    return _IMAGE_MD.sub(replace, body)


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    :root {{
      --ink: #242424;
      --muted: #616161;
      --paper: #f5f5f5;
      --card: #ffffff;
      --line: #e0e0e0;
      --accent: #5b5fc7;
      --accent-strong: #4f52b2;
      --brand: #6264a7;
      --brand-soft: #ebebf5;
      --code-bg: #f0f0f0;
      --code-ink: #292a4a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      background:
        linear-gradient(180deg, #ebebf5 0%, var(--paper) 180px, var(--paper) 100%);
      font-family: "Segoe UI", "PingFang TC", "Microsoft JhengHei",
        "Noto Sans TC", sans-serif;
      line-height: 1.7;
    }}
    .shell {{
      width: min(760px, calc(100% - 2rem));
      margin: 0 auto;
      padding: 2.5rem 0 4rem;
    }}
    .eyebrow {{
      margin: 0 0 0.75rem;
      color: var(--brand);
      font-size: 0.78rem;
      font-weight: 600;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    article {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 2rem 1.6rem 2.4rem;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
    }}
    h1, h2, h3, h4 {{
      line-height: 1.3;
      font-weight: 700;
      color: var(--ink);
    }}
    h1 {{
      margin: 0 0 1.25rem;
      font-size: clamp(1.7rem, 3vw, 2.1rem);
      color: #201f1f;
    }}
    h2 {{
      margin: 2rem 0 0.8rem;
      padding-top: 0.85rem;
      border-top: 1px solid var(--line);
      font-size: 1.25rem;
      color: var(--brand);
    }}
    h3 {{ margin: 1.4rem 0 0.55rem; font-size: 1.08rem; }}
    p, ul, ol, table, pre, blockquote {{ margin: 0 0 1rem; }}
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
      color: var(--brand);
      font-size: 0.86rem;
      font-weight: 600;
    }}
    tr:last-child td {{ border-bottom: none; }}
    img {{
      display: block;
      max-width: 100%;
      height: auto;
      margin: 1rem 0;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: #fff;
    }}
    blockquote {{
      margin-left: 0;
      padding: 0.35rem 0 0.35rem 1rem;
      border-left: 3px solid var(--brand);
      background: var(--brand-soft);
      color: #424242;
      border-radius: 0 6px 6px 0;
    }}
    @media (max-width: 640px) {{
      article {{ padding: 1.35rem 1.1rem 1.8rem; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <p class="eyebrow">Knowledge source</p>
    <article>
      {content}
    </article>
  </main>
</body>
</html>
"""
