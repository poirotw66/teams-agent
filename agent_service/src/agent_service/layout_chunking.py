"""Layout-aware, profile-based chunking for knowledge ingestion."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from enum import StrEnum

from .document_parsing import BlockKind, ParsedBlock, ParsedDocument

_TOKEN = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9_]+|[^\s]")


class ChunkingProfile(StrEnum):
    AUTO = "AUTO"
    SLIDE_DECK = "SLIDE_DECK"
    MANUAL = "MANUAL"
    POLICY = "POLICY"


@dataclass(frozen=True)
class ChunkingLimits:
    target_tokens: int
    minimum_tokens: int
    maximum_tokens: int
    overlap_tokens: int


@dataclass(frozen=True)
class RetrievalChunkDraft:
    chunk_id: str
    parent_id: str
    neighbor_ids: tuple[str, ...]
    title: str
    content: str
    page_start: int
    page_end: int
    heading_path: tuple[str, ...]
    token_count: int
    content_hash: str
    parser_version: str
    chunker_version: str = "layout-v1"


@dataclass(frozen=True)
class ChunkQualityReport:
    profile: ChunkingProfile
    source_blocks: int
    covered_blocks: int
    coverage_ratio: float
    chunk_count: int
    short_chunk_count: int
    heading_only_count: int
    orphan_media_count: int
    duplicate_chunk_count: int
    is_acceptable: bool


class ChunkQualityIssue(StrEnum):
    SHORT = "SHORT"
    HEADING_ONLY = "HEADING_ONLY"
    DUPLICATE = "DUPLICATE"


_PROFILE_LIMITS = {
    ChunkingProfile.SLIDE_DECK: ChunkingLimits(500, 120, 700, 80),
    ChunkingProfile.MANUAL: ChunkingLimits(600, 120, 900, 100),
    ChunkingProfile.POLICY: ChunkingLimits(650, 140, 900, 100),
}


def estimate_tokens(text: str) -> int:
    """Return a deterministic conservative token estimate without network I/O."""
    return len(_TOKEN.findall(text))


def detect_profile(document: ParsedDocument) -> ChunkingProfile:
    if len(document.pages) > 1:
        average_blocks = sum(len(page.blocks) for page in document.pages) / len(document.pages)
        if average_blocks <= 10:
            return ChunkingProfile.SLIDE_DECK
    return ChunkingProfile.MANUAL


def chunk_parsed_document(
    document: ParsedDocument,
    *,
    document_id: str,
    profile: ChunkingProfile = ChunkingProfile.AUTO,
) -> tuple[list[RetrievalChunkDraft], ChunkQualityReport]:
    selected = detect_profile(document) if profile == ChunkingProfile.AUTO else profile
    limits = _PROFILE_LIMITS[selected]
    parents = _parent_units(document, selected)
    chunks: list[RetrievalChunkDraft] = []
    covered_blocks = 0
    orphan_media = 0

    for parent_index, blocks in enumerate(parents, 1):
        if not blocks:
            continue
        page_start = min(block.page_number for block in blocks)
        page_end = max(block.page_number for block in blocks)
        parent_id = f"parent-{document_id}-{parent_index}"
        groups = _pack_blocks(blocks, limits)
        if not any(block.kind != BlockKind.IMAGE for block in blocks):
            orphan_media += sum(block.kind == BlockKind.IMAGE for block in blocks)
        covered_blocks += len(blocks)
        for child_index, group in enumerate(groups, 1):
            heading_path = _common_heading_path(group)
            content = _render_group(group, heading_path)
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            chunks.append(
                RetrievalChunkDraft(
                    chunk_id=f"chk-{document_id}-{digest[:16]}",
                    parent_id=parent_id,
                    neighbor_ids=(),
                    title=_chunk_title(document.title, heading_path, page_start),
                    content=content,
                    page_start=page_start,
                    page_end=page_end,
                    heading_path=heading_path,
                    token_count=estimate_tokens(content),
                    content_hash=digest,
                    parser_version=document.parser_version,
                )
            )

    chunks = _with_neighbors(chunks)
    report = _quality_report(
        selected,
        document,
        chunks,
        covered_blocks=covered_blocks,
        orphan_media=orphan_media,
    )
    return chunks, report


def _parent_units(
    document: ParsedDocument,
    profile: ChunkingProfile,
) -> list[list[ParsedBlock]]:
    if profile == ChunkingProfile.SLIDE_DECK:
        return [list(page.blocks) for page in document.pages]
    units: list[list[ParsedBlock]] = []
    current_key: tuple[str, ...] | None = None
    for page in document.pages:
        for block in page.blocks:
            key = block.heading_path[:1] or (f"page-{page.page_number}",)
            if key != current_key:
                units.append([])
                current_key = key
            units[-1].append(block)
    return units


def _pack_blocks(
    blocks: list[ParsedBlock],
    limits: ChunkingLimits,
) -> list[list[ParsedBlock]]:
    groups: list[list[ParsedBlock]] = []
    current: list[ParsedBlock] = []
    current_tokens = 0
    expanded_blocks = [part for block in blocks for part in _split_oversized_block(block, limits)]
    for block in expanded_blocks:
        block_tokens = estimate_tokens(block.text)
        if current and current_tokens + block_tokens > limits.maximum_tokens:
            groups.append(current)
            current = []
            current_tokens = 0
        current.append(block)
        current_tokens += block_tokens
        if current_tokens >= limits.target_tokens:
            groups.append(current)
            current = []
            current_tokens = 0
    if current:
        if groups and current_tokens < limits.minimum_tokens:
            groups[-1].extend(current)
        else:
            groups.append(current)
    return groups


def _split_oversized_block(
    block: ParsedBlock,
    limits: ChunkingLimits,
) -> list[ParsedBlock]:
    matches = list(_TOKEN.finditer(block.text))
    if len(matches) <= limits.maximum_tokens:
        return [block]
    output: list[ParsedBlock] = []
    start_token = 0
    part = 0
    while start_token < len(matches):
        end_token = min(start_token + limits.maximum_tokens, len(matches))
        start_character = matches[start_token].start()
        end_character = matches[end_token - 1].end()
        part += 1
        output.append(
            replace(
                block,
                block_id=f"{block.block_id}-part-{part}",
                text=block.text[start_character:end_character].strip(),
            )
        )
        if end_token == len(matches):
            break
        start_token = max(start_token + 1, end_token - limits.overlap_tokens)
    return output


def _common_heading_path(blocks: list[ParsedBlock]) -> tuple[str, ...]:
    if not blocks:
        return ()
    common = list(blocks[0].heading_path)
    for block in blocks[1:]:
        common = [
            value
            for index, value in enumerate(common)
            if index < len(block.heading_path) and block.heading_path[index] == value
        ]
    return tuple(common)


def _render_group(
    blocks: list[ParsedBlock],
    heading_path: tuple[str, ...],
) -> str:
    parts = [
        "\n".join(
            f"{'#' * min(index + 1, 3)} {heading}" for index, heading in enumerate(heading_path)
        )
    ]
    previous_path = heading_path
    for block in blocks:
        if block.heading_path != previous_path:
            suffix = block.heading_path[len(heading_path) :]
            parts.append(
                "\n".join(
                    f"{'#' * min(len(heading_path) + index + 1, 3)} {heading}"
                    for index, heading in enumerate(suffix)
                )
            )
            previous_path = block.heading_path
        parts.append(block.text)
    return "\n\n".join(part for part in parts if part).strip()


def _chunk_title(
    document_title: str,
    heading_path: tuple[str, ...],
    page_number: int,
) -> str:
    section = heading_path[-1] if heading_path else f"第 {page_number} 頁"
    return f"{document_title} - {section}"


def _with_neighbors(
    chunks: list[RetrievalChunkDraft],
) -> list[RetrievalChunkDraft]:
    output: list[RetrievalChunkDraft] = []
    for index, chunk in enumerate(chunks):
        neighbors = tuple(
            candidate.chunk_id
            for candidate in chunks[max(0, index - 1) : index + 2]
            if candidate.parent_id == chunk.parent_id and candidate.chunk_id != chunk.chunk_id
        )
        output.append(RetrievalChunkDraft(**{**chunk.__dict__, "neighbor_ids": neighbors}))
    return output


def _quality_report(
    profile: ChunkingProfile,
    document: ParsedDocument,
    chunks: list[RetrievalChunkDraft],
    *,
    covered_blocks: int,
    orphan_media: int,
) -> ChunkQualityReport:
    source_blocks = sum(len(page.blocks) for page in document.pages)
    issues = chunk_quality_issues(profile, chunks)
    short_count = _issue_count(issues, ChunkQualityIssue.SHORT)
    heading_only = _issue_count(issues, ChunkQualityIssue.HEADING_ONLY)
    duplicate_count = _duplicate_count(chunks)
    coverage = min(covered_blocks / source_blocks, 1.0) if source_blocks else 0.0
    acceptable = (
        coverage >= 0.995
        and heading_only == 0
        and orphan_media == 0
        and duplicate_count == 0
        and (not chunks or short_count / len(chunks) <= 0.05)
    )
    return ChunkQualityReport(
        profile=profile,
        source_blocks=source_blocks,
        covered_blocks=covered_blocks,
        coverage_ratio=coverage,
        chunk_count=len(chunks),
        short_chunk_count=short_count,
        heading_only_count=heading_only,
        orphan_media_count=orphan_media,
        duplicate_chunk_count=duplicate_count,
        is_acceptable=acceptable,
    )


def chunk_quality_issues(
    profile: ChunkingProfile,
    chunks: list[RetrievalChunkDraft],
) -> dict[str, tuple[ChunkQualityIssue, ...]]:
    short_ids = _short_chunk_ids(profile, chunks)
    duplicate_hashes = _duplicate_hashes(chunks)
    issues: dict[str, tuple[ChunkQualityIssue, ...]] = {}
    for chunk in chunks:
        chunk_issues: list[ChunkQualityIssue] = []
        if chunk.chunk_id in short_ids:
            chunk_issues.append(ChunkQualityIssue.SHORT)
        if not re.sub(r"(?m)^#{1,6}\s+.*$", "", chunk.content).strip():
            chunk_issues.append(ChunkQualityIssue.HEADING_ONLY)
        if chunk.content_hash in duplicate_hashes:
            chunk_issues.append(ChunkQualityIssue.DUPLICATE)
        if chunk_issues:
            issues[chunk.chunk_id] = tuple(chunk_issues)
    return issues


def _short_chunk_ids(
    profile: ChunkingProfile,
    chunks: list[RetrievalChunkDraft],
) -> set[str]:
    if len(chunks) <= 1:
        return set()
    minimum_tokens = _PROFILE_LIMITS[profile].minimum_tokens
    if profile != ChunkingProfile.SLIDE_DECK:
        return {chunk.chunk_id for chunk in chunks if chunk.token_count < minimum_tokens}
    sibling_counts: dict[str, int] = {}
    for chunk in chunks:
        sibling_counts[chunk.parent_id] = sibling_counts.get(chunk.parent_id, 0) + 1
    return {
        chunk.chunk_id
        for chunk in chunks
        if chunk.token_count < minimum_tokens and sibling_counts[chunk.parent_id] > 1
    }


def _duplicate_hashes(chunks: list[RetrievalChunkDraft]) -> set[str]:
    counts: dict[str, int] = {}
    for chunk in chunks:
        counts[chunk.content_hash] = counts.get(chunk.content_hash, 0) + 1
    return {content_hash for content_hash, count in counts.items() if count > 1}


def _duplicate_count(chunks: list[RetrievalChunkDraft]) -> int:
    hashes = [chunk.content_hash for chunk in chunks]
    return len(hashes) - len(set(hashes))


def _issue_count(
    issues: dict[str, tuple[ChunkQualityIssue, ...]],
    target: ChunkQualityIssue,
) -> int:
    return sum(target in chunk_issues for chunk_issues in issues.values())
