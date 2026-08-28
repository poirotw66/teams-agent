import json
from pathlib import Path

from agent_service.documents import (
    DocumentChunk,
    DocumentMetadata,
    chunk_markdown,
    clean_markdown,
    parse_front_matter,
)


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


def test_parse_front_matter_returns_empty_dict_when_absent() -> None:
    raw = "# VPN\n\n內容"

    front_matter, body = parse_front_matter(raw)

    assert front_matter == {}
    assert body == raw


def test_parse_front_matter_extracts_known_fields() -> None:
    raw = """---
title: VPN 登入問題
owner: IT Infrastructure
version: "1.2"
effectiveDate: 2026-07-01
reviewDate: 2026-10-01
audience:
  - all-employees
---

# VPN 登入問題

內容
"""

    front_matter, body = parse_front_matter(raw)

    assert front_matter["title"] == "VPN 登入問題"
    assert front_matter["owner"] == "IT Infrastructure"
    assert front_matter["version"] == "1.2"
    assert front_matter["audience"] == ["all-employees"]
    assert body.strip().startswith("# VPN 登入問題")
    assert "---" not in body.split("\n\n", 1)[0]


def test_parse_front_matter_rejects_unknown_field() -> None:
    raw = """---
title: VPN 登入問題
mystery: value
---

# VPN 登入問題
"""

    try:
        parse_front_matter(raw)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "mystery" in str(exc)


def test_chunk_markdown_parses_front_matter_and_strips_it(tmp_path: Path) -> None:
    source = tmp_path / "vpn.md"
    source.write_text(
        """---
title: VPN 登入問題
owner: IT Infrastructure
version: "1.2"
effectiveDate: 2026-07-01
reviewDate: 2026-10-01
audience:
  - all-employees
---

# VPN

## 處理方式

請重新啟動網路。
""",
        encoding="utf-8",
    )

    chunks = chunk_markdown(source, "sources/vpn.md", chunk_size=300, overlap=30)

    assert chunks[0].title == "VPN 登入問題"
    metadata = chunks[0].metadata
    assert metadata is not None
    assert metadata.owner == "IT Infrastructure"
    assert metadata.version == "1.2"
    assert metadata.effective_date == "2026-07-01"
    assert metadata.review_date == "2026-10-01"
    assert metadata.audience == ["all-employees"]
    # "all-employees" is the open marker and must not restrict visibility.
    assert chunks[0].allowed_groups == []
    for chunk in chunks:
        assert "title:" not in chunk.content
        assert "effectiveDate" not in chunk.content


def test_chunk_markdown_without_front_matter_is_backward_compatible(tmp_path: Path) -> None:
    source = tmp_path / "vpn.md"
    source.write_text("# VPN\n\n## 處理方式\n\n請重新啟動網路。", encoding="utf-8")

    chunks = chunk_markdown(source, "sources/vpn.md", chunk_size=300, overlap=30)

    assert chunks[0].title == "VPN"
    assert chunks[0].metadata is None
    assert chunks[0].allowed_groups == []


def test_chunk_markdown_maps_restrictive_audience_to_allowed_groups(tmp_path: Path) -> None:
    source = tmp_path / "cs-vpn.md"
    source.write_text(
        """---
title: 分公司CS團隊VPN連線可使用權限列表
owner: IT Infrastructure
version: "1.0"
effectiveDate: 2026-08-06
reviewDate: 2026-11-06
audience:
  - branch-cs-team
---

# 分公司CS團隊VPN連線可使用權限列表

## 內容

VPN 權限列表。
""",
        encoding="utf-8",
    )

    chunks = chunk_markdown(source, "sources/cs-vpn.md", chunk_size=300, overlap=30)

    assert chunks[0].allowed_groups == ["branch-cs-team"]


def test_chunk_markdown_metadata_yields_to_explicit_allowed_groups(tmp_path: Path) -> None:
    source = tmp_path / "vpn.md"
    source.write_text(
        """---
title: VPN
audience:
  - branch-cs-team
---

# VPN

內容
""",
        encoding="utf-8",
    )

    chunks = chunk_markdown(
        source,
        "sources/vpn.md",
        chunk_size=300,
        overlap=30,
        metadata={"allowedGroups": ["IT"]},
    )

    assert chunks[0].allowed_groups == ["IT"]


def test_document_chunk_round_trips_metadata() -> None:
    metadata = DocumentMetadata(
        title="VPN 登入問題",
        owner="IT Infrastructure",
        version="1.2",
        effective_date="2026-07-01",
        review_date="2026-10-01",
        audience=["all-employees"],
    )
    chunk = DocumentChunk(
        chunk_id="abc123",
        title="VPN 登入問題",
        source_path="sources/vpn.md",
        content="內容",
        metadata=metadata,
    )

    payload = json.loads(json.dumps(chunk.to_dict(), ensure_ascii=False))
    restored = DocumentChunk.from_dict(payload)

    assert restored.metadata == metadata


def test_document_chunk_from_dict_loads_old_index_without_metadata_key() -> None:
    legacy_payload = {
        "chunk_id": "abc123",
        "title": "VPN",
        "source_path": "sources/vpn.md",
        "content": "內容",
        "classification": "internal",
        "allowed_groups": [],
        "images": [],
        "vector": None,
    }

    chunk = DocumentChunk.from_dict(legacy_payload)

    assert chunk.metadata is None
