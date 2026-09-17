"""Regression tests for layout-aware ingestion chunking."""

from agent_service.document_parsing import BlockKind, MarkdownLayoutParser
from agent_service.layout_chunking import (
    ChunkingProfile,
    ChunkQualityIssue,
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


def test_quality_issues_identify_the_short_chunk() -> None:
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

    assert issues[chunks[0].chunk_id] == (ChunkQualityIssue.SHORT,)
    assert chunks[1].chunk_id not in issues


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
