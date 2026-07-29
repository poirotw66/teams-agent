from pathlib import Path

from agent_service.documents import chunk_markdown, clean_markdown


def test_clean_markdown_removes_archive_metadata_and_gaps() -> None:
    raw = """# VPN

## Archive metadata

- archived: 2026-01-01

---

## 正文（canonical）

VPN 連線方式

## Limitations / Gaps

- 缺圖
"""

    cleaned = clean_markdown(raw)

    assert "Archive metadata" not in cleaned
    assert "Limitations" not in cleaned
    assert "VPN 連線方式" in cleaned


def test_chunk_markdown_preserves_source_metadata(tmp_path: Path) -> None:
    source = tmp_path / "vpn.md"
    source.write_text("# VPN\n\n## 處理方式\n\n請重新啟動網路。", encoding="utf-8")

    chunks = chunk_markdown(
        source,
        "sources/vpn.md",
        chunk_size=300,
        overlap=30,
        metadata={"allowedGroups": ["IT"]},
    )

    assert chunks[0].title == "VPN"
    assert chunks[0].source_path == "sources/vpn.md"
    assert chunks[0].allowed_groups == ["IT"]


def test_chunk_markdown_keeps_related_local_image(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    assets = tmp_path / "assets" / "大州"
    sources.mkdir()
    assets.mkdir(parents=True)
    (assets / "p01.png").write_bytes(b"image")
    source = sources / "大州.md"
    source.write_text(
        """# 大州

## 操作步驟

請調整安全性。

### Visual Evidence

![IE 安全性設定](../assets/大州/p01.png)
""",
        encoding="utf-8",
    )

    chunks = chunk_markdown(
        source,
        "sources/大州.md",
        chunk_size=300,
        overlap=30,
    )

    assert chunks[0].images
    assert chunks[0].images[0].path == "大州/p01.png"
    assert chunks[0].images[0].alt_text == "IE 安全性設定"
