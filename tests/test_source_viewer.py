"""Tests for the HTML knowledge-source viewer."""

from pathlib import Path

from teams_agent.settings import AgentSettings
from teams_agent.source_viewer import (
    render_source_document_html,
    render_source_markdown_html,
)


def test_render_source_document_html_includes_title_and_table(tmp_path: Path) -> None:
    path = tmp_path / "guide.md"
    path.write_text(
        "---\ntitle: 大州操作說明\n---\n\n# 大州操作說明\n\n"
        "| 步驟 | 內容 |\n| --- | --- |\n| 1 | 開啟工具 |\n\n"
        "```text\n設定完成\n```\n",
        encoding="utf-8",
    )
    settings = AgentSettings(
        public_base_url="https://bot.example.com",
        asset_signing_key="test-signing-key-long-enough",
    )

    html = render_source_document_html(path, settings, now=1_000).decode("utf-8")

    assert "<title>大州操作說明</title>" in html
    assert "<table>" in html
    assert "<pre>" in html
    assert "開啟工具" in html


def test_render_rewrites_asset_images_to_signed_urls(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "shot.png").write_bytes(b"fake")
    path = tmp_path / "doc.md"
    path.write_text(
        "# Doc\n\n![示意](assets/shot.png)\n",
        encoding="utf-8",
    )
    settings = AgentSettings(
        asset_dir=assets,
        public_base_url="https://bot.example.com",
        asset_signing_key="test-signing-key-long-enough",
    )

    html = render_source_document_html(path, settings, now=1_000).decode("utf-8")

    assert 'src="https://bot.example.com/rag-assets/shot.png?' in html


def test_render_full_source_highlights_matching_indexed_block(
    tmp_path: Path,
) -> None:
    settings = AgentSettings(
        asset_dir=tmp_path,
        public_base_url="https://bot.example.com",
        asset_signing_key="test-signing-key-long-enough",
    )

    html = render_source_markdown_html(
        "# Phone Guide\n\n## Dial\n\nPress 0 before an external number.\n\n"
        "## Transfer\n\nPress Transfer and enter the extension.",
        settings,
        evidence="Press Transfer and enter the extension.",
        mapping_status="AVAILABLE",
    ).decode()

    assert 'id="citation-highlight"' in html
    assert "索引命中片段" in html
    assert "CITATIONHIGHLIGHTSTARTTOKEN" not in html
    assert "版本已核對" in html
    assert "<section" in html
    assert "Press Transfer and enter the extension." in html


def test_render_full_source_reports_when_evidence_cannot_be_located(
    tmp_path: Path,
) -> None:
    settings = AgentSettings(
        asset_dir=tmp_path,
        public_base_url="https://bot.example.com",
        asset_signing_key="test-signing-key-long-enough",
    )

    html = render_source_markdown_html(
        "# Current document\n\nThis version has different content.",
        settings,
        evidence="Archived instructions no longer present.",
    ).decode()

    assert "無法在此版本中精準定位引用片段" in html
    assert "索引命中片段" not in html


def test_render_full_source_escapes_raw_html(tmp_path: Path) -> None:
    settings = AgentSettings(
        asset_dir=tmp_path,
        public_base_url="https://bot.example.com",
        asset_signing_key="test-signing-key-long-enough",
    )

    html = render_source_markdown_html(
        "# Safe\n\n<script>alert('unsafe')</script>\n\n<img onerror='alert(1)'>",
        settings,
    ).decode()

    assert "<script>" not in html
    assert "<img onerror=" not in html
    assert "&lt;script&gt;" in html


def test_render_full_source_neutralizes_unsafe_markdown_urls(tmp_path: Path) -> None:
    settings = AgentSettings(
        asset_dir=tmp_path,
        public_base_url="https://bot.example.com",
        asset_signing_key="test-signing-key-long-enough",
    )

    html = render_source_markdown_html(
        "[Unsafe](javascript:alert(1)) and [safe](https://example.com/guide)",
        settings,
    ).decode()

    assert 'href="javascript:' not in html
    assert '<a href="#">Unsafe</a>' in html
    assert 'href="https://example.com/guide"' in html


def test_render_source_without_heading_adds_accessible_document_title(
    tmp_path: Path,
) -> None:
    settings = AgentSettings(
        asset_dir=tmp_path,
        public_base_url="https://bot.example.com",
        asset_signing_key="test-signing-key-long-enough",
    )

    html = render_source_markdown_html(
        "Document body without a heading.",
        settings,
        fallback_title="Fallback title",
    ).decode()

    assert "<title>Fallback title</title>" in html
    assert "<h1>Fallback title</h1>" in html


def test_render_release_image_uses_release_pinned_signed_url(tmp_path: Path) -> None:
    settings = AgentSettings(
        asset_dir=tmp_path,
        asset_gcs_bucket="knowledge-bucket",
        public_base_url="https://bot.example.com",
        asset_signing_key="test-signing-key-long-enough",
    )

    html = render_source_markdown_html(
        "# Guide\n\n![Panel](assets/phone/panel.png)",
        settings,
        now=1_000,
        release_id="release-1",
    ).decode()

    assert ('src="https://bot.example.com/rag-assets/releases/release-1/phone/panel.png?') in html
