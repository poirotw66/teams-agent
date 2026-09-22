"""Regression tests for layout-aware ingestion chunking."""

from agent_service.document_parsing import BlockKind, MarkdownLayoutParser
from agent_service.layout_chunking import (
    ChunkingProfile,
    chunk_parsed_document,
    chunk_quality_issues,
)


def _slide_deck(page_count: int = 14) -> str:
    pages = []
    for page in range(1, page_count + 1):
        pages.append(
            f"## Page {page}\n"
            f"# Platform topic {page}\n\n"
            "## Architecture\n"
            "The platform keeps authentication, retrieval, tools, and "
            "observability connected as one governed runtime.\n\n"
            "## Key controls\n"
            "- Preserve source identity and access policy.\n"
            "- Validate retrieval before release activation.\n\n"
            f"![Page {page}](assets/p{page:02d}.png)\n"
        )
    return "\n".join(pages)


def test_slide_deck_keeps_each_page_as_coherent_parent() -> None:
    parsed = MarkdownLayoutParser().parse(
        _slide_deck(),
        title="Financial AI Platform",
    )

    chunks, report = chunk_parsed_document(
        parsed,
        document_id="doc-platform",
    )

    assert report.profile == ChunkingProfile.SLIDE_DECK
    assert 14 <= len(chunks) <= 24
    assert report.coverage_ratio == 1
    assert report.heading_only_count == 0
    assert report.orphan_media_count == 0
    assert all(chunk.page_start == chunk.page_end for chunk in chunks)
    assert all("Architecture" in chunk.content for chunk in chunks)


def test_numbered_list_items_do_not_become_independent_chunks() -> None:
    parsed = MarkdownLayoutParser().parse(
        "## Page 1\n# Runbook\n\n"
        "1. Install the approved client.\n"
        "2. Authenticate with the employee account.\n"
        "3. Validate the connection status.\n",
        title="Runbook",
    )

    chunks, report = chunk_parsed_document(
        parsed,
        document_id="doc-runbook",
        profile=ChunkingProfile.SLIDE_DECK,
    )

    assert len(chunks) == 1
    assert "1. Install" in chunks[0].content
    assert "3. Validate" in chunks[0].content
    assert report.heading_only_count == 0


def test_short_single_child_slide_is_not_rejected_as_fragmented() -> None:
    parsed = MarkdownLayoutParser().parse(
        "## Page 1\n# Overview\n\nShort overview.\n"
        "## Page 2\n# Architecture\n\nShort architecture summary.\n",
        title="Concise deck",
    )

    chunks, report = chunk_parsed_document(
        parsed,
        document_id="doc-concise-deck",
        profile=ChunkingProfile.SLIDE_DECK,
    )

    assert len(chunks) == 2
    assert report.short_chunk_count == 0
    assert report.is_acceptable is True


def test_auto_heal_merges_short_manual_section_into_neighbor() -> None:
    parsed = MarkdownLayoutParser().parse(
        "# Short\n\nBrief.\n\n"
        "# Detailed\n\n" + "This operational instruction contains enough detail. " * 30,
        title="Mixed guide",
    )

    chunks, report = chunk_parsed_document(
        parsed,
        document_id="doc-mixed-guide",
        profile=ChunkingProfile.MANUAL,
    )
    issues = chunk_quality_issues(report.profile, chunks)

    assert len(chunks) == 1
    assert "Brief." in chunks[0].content
    assert issues == {}
    assert report.short_chunk_count == 0
    assert report.is_acceptable is True


def test_short_leftover_is_warning_not_blocking() -> None:
    """When a short chunk cannot merge without exceeding max, accept with warning."""
    long_body = ("Operational detail sentence with enough tokens. " * 120).strip()
    parsed = MarkdownLayoutParser().parse(
        f"# Alpha\n\n{long_body}\n\n"
        "# Tiny\n\nShort note.\n\n"
        f"# Beta\n\n{long_body}\n",
        title="Near max neighbors",
    )

    _chunks, report = chunk_parsed_document(
        parsed,
        document_id="doc-near-max",
        profile=ChunkingProfile.MANUAL,
    )

    assert report.is_acceptable is True
    assert report.heading_only_count == 0
    assert report.orphan_media_count == 0
    assert report.duplicate_chunk_count == 0


def test_auto_heal_dedupes_identical_chunk_payloads() -> None:
    from knowledge_core.layout_chunking import (
        ChunkingLimits,
        _heal_chunks,
        _make_chunk,
    )

    content = "# Shared\n\n" + ("Shared recovery steps for account unlock. " * 20)
    left = _make_chunk(
        document_id="doc-dup",
        document_title="Duplicate guide",
        parent_id="parent-doc-dup-1",
        content=content,
        page_start=1,
        page_end=1,
        heading_path=("Shared",),
        parser_version="1",
    )
    right = _make_chunk(
        document_id="doc-dup",
        document_title="Duplicate guide",
        parent_id="parent-doc-dup-2",
        content=content,
        page_start=1,
        page_end=1,
        heading_path=("Shared",),
        parser_version="1",
    )
    healed = _heal_chunks(
        [left, right],
        profile=ChunkingProfile.MANUAL,
        document_id="doc-dup",
        document_title="Duplicate guide",
        limits=ChunkingLimits(600, 120, 900, 100),
    )

    assert len(healed) == 1
    assert healed[0].content_hash == left.content_hash

def test_faq_style_document_is_acceptable_after_auto_heal() -> None:
    sections = []
    for index in range(1, 8):
        sections.append(
            f"### FAQ-{index:03d}|｜題目 {index}？\n\n"
            f"**問題**：帳號相關問題 {index} 要如何處理？\n\n"
            f"**建議回覆**：請依標準流程處理問題 {index}，並確認系統狀態後回報。\n"
        )
    parsed = MarkdownLayoutParser().parse(
        "# 複委託 AS400 FAQ\n\n## 正文\n\n" + "\n".join(sections),
        title="AS400 FAQ",
    )

    chunks, report = chunk_parsed_document(
        parsed,
        document_id="doc-as400-faq",
        profile=ChunkingProfile.MANUAL,
    )

    assert len(chunks) >= 1
    assert report.is_acceptable is True
    assert report.heading_only_count == 0
    assert report.orphan_media_count == 0
    assert report.duplicate_chunk_count == 0


def test_auto_heal_attaches_orphan_image_parent() -> None:
    parsed = MarkdownLayoutParser().parse(
        "# Guide\n\nFollow the diagram below.\n\n"
        "# Diagram\n\n![Flow](assets/flow.png)\n",
        title="Media guide",
    )

    chunks, report = chunk_parsed_document(
        parsed,
        document_id="doc-media",
        profile=ChunkingProfile.MANUAL,
    )

    assert report.orphan_media_count == 0
    assert report.is_acceptable is True
    assert any("assets/flow.png" in chunk.content for chunk in chunks)
    assert any("Follow the diagram" in chunk.content for chunk in chunks)


def test_parser_preserves_heading_ancestry_and_media_block() -> None:
    parsed = MarkdownLayoutParser().parse(
        "## Page 3\n# Runtime\n\n## Retrieval\n\n"
        "Hybrid retrieval uses lexical and vector scores.\n\n"
        "![Flow](assets/flow.png)",
        title="Platform",
    )

    blocks = parsed.pages[0].blocks

    assert blocks[0].heading_path == ("Runtime", "Retrieval")
    assert blocks[1].kind == BlockKind.IMAGE
    assert blocks[1].heading_path == ("Runtime", "Retrieval")


def test_heading_without_body_is_not_indexed() -> None:
    parsed = MarkdownLayoutParser().parse(
        "## Page 1\n# Heading only\n\n## Actual content\n\n"
        "This paragraph contains the operational instruction.",
        title="Guide",
    )

    chunks, report = chunk_parsed_document(
        parsed,
        document_id="doc-guide",
    )

    assert len(chunks) == 1
    assert chunks[0].content.endswith("operational instruction.")
    assert report.heading_only_count == 0
