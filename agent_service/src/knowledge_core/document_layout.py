"""Structured document layout contracts for knowledge ingestion.

Pure Markdown layout parsing lives here. Document AI (cloud client)
stays in Agent runtime behind a Portal port.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

_PAGE_HEADING = re.compile(r"^## Page (?P<page>\d+)\s*$", re.IGNORECASE)
_SOURCE_PAGE = re.compile(r"source-map:page_index=(?P<page>\d+)")
_HEADING = re.compile(r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$")
_IMAGE = re.compile(r"!\[[^\]]*]\([^)]+\)")
_METHOD = re.compile(r"^\*\*Method:\*\*\s*\w+\s*$", re.IGNORECASE)


class BlockKind(StrEnum):
    TEXT = "TEXT"
    LIST = "LIST"
    TABLE = "TABLE"
    IMAGE = "IMAGE"


@dataclass(frozen=True)
class ParsedBlock:
    block_id: str
    kind: BlockKind
    text: str
    page_number: int
    heading_path: tuple[str, ...]
    bbox: tuple[float, ...] | None = None
    reading_order: int = 0
    confidence: float | None = None


@dataclass(frozen=True)
class ParsedPage:
    page_number: int
    blocks: tuple[ParsedBlock, ...]


@dataclass(frozen=True)
class ParsedDocument:
    title: str
    pages: tuple[ParsedPage, ...]
    parser_name: str
    parser_version: str


class DocumentParser(Protocol):
    def parse(self, text: str, *, title: str) -> ParsedDocument: ...


class MarkdownLayoutParser:
    """Parse converter Markdown while preserving page and heading ancestry."""

    name = "markdown-layout"
    version = "1"

    def parse(self, text: str, *, title: str) -> ParsedDocument:
        pages: dict[int, list[ParsedBlock]] = {}
        headings: list[str] = []
        page_number = 1
        paragraph: list[str] = []
        block_index = 0

        def flush() -> None:
            nonlocal block_index
            content = "\n".join(paragraph).strip()
            paragraph.clear()
            if not content:
                return
            block_index += 1
            block = ParsedBlock(
                block_id=f"block-{block_index}",
                kind=_block_kind(content),
                text=content,
                page_number=page_number,
                heading_path=tuple(headings),
                reading_order=block_index,
            )
            pages.setdefault(page_number, []).append(block)

        for raw_line in text.splitlines():
            line = raw_line.strip()
            page_match = _PAGE_HEADING.fullmatch(line)
            source_match = _SOURCE_PAGE.search(line)
            if page_match or source_match:
                flush()
                matched_page = int((page_match or source_match).group("page"))
                page_number = matched_page if page_match else matched_page + 1
                headings.clear()
                continue
            if _METHOD.fullmatch(line) or line == "---":
                continue
            heading_match = _HEADING.fullmatch(line)
            if heading_match:
                flush()
                level = len(heading_match.group("marks"))
                heading = heading_match.group("title").strip()
                headings[:] = headings[: level - 1]
                headings.append(heading)
                continue
            if not line:
                flush()
                continue
            paragraph.append(line)
        flush()

        parsed_pages = tuple(
            ParsedPage(page_number=number, blocks=tuple(blocks))
            for number, blocks in sorted(pages.items())
            if blocks
        )
        return ParsedDocument(
            title=title,
            pages=parsed_pages,
            parser_name=self.name,
            parser_version=self.version,
        )


def _block_kind(content: str) -> BlockKind:
    lines = content.splitlines()
    if _IMAGE.search(content):
        return BlockKind.IMAGE
    if len(lines) >= 2 and all("|" in line for line in lines[:2]):
        return BlockKind.TABLE
    if lines and all(re.match(r"^(?:[-*+]|\d+[.、])\s+", line) for line in lines if line):
        return BlockKind.LIST
    return BlockKind.TEXT
