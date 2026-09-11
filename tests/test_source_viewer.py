"""Tests for the HTML knowledge-source viewer."""

from pathlib import Path

from teams_agent.settings import AgentSettings
from teams_agent.source_viewer import render_source_document_html


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
