#!/usr/bin/env python3
"""Validate hierarchical chunking before rebuilding an immutable release."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from agent_service.document_parsing import MarkdownLayoutParser
from agent_service.documents import parse_front_matter
from agent_service.layout_chunking import (
    ChunkingProfile,
    chunk_parsed_document,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--canary-title", default="")
    parser.add_argument("--canary-pages", type=int, default=14)
    parser.add_argument("--canary-min-chunks", type=int, default=14)
    parser.add_argument("--canary-max-chunks", type=int, default=24)
    args = parser.parse_args()

    report = evaluate_corpus(
        args.sources,
        canary_title=args.canary_title,
        canary_pages=args.canary_pages,
        canary_chunk_range=(args.canary_min_chunks, args.canary_max_chunks),
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0 if report["acceptable"] else 2


def evaluate_corpus(
    sources_dir: Path,
    *,
    canary_title: str,
    canary_pages: int,
    canary_chunk_range: tuple[int, int],
) -> dict[str, object]:
    if not sources_dir.is_dir():
        raise FileNotFoundError(f"Sources directory not found: {sources_dir}")
    documents: list[dict[str, object]] = []
    canary_found = not canary_title
    for source_path in sorted(sources_dir.rglob("*.md")):
        if source_path.name.upper() == "README.MD":
            continue
        raw = source_path.read_text(encoding="utf-8")
        metadata, body = parse_front_matter(raw)
        title = str(metadata.get("title") or source_path.stem)
        document_id = _document_id(source_path.relative_to(sources_dir))
        parsed = MarkdownLayoutParser().parse(body, title=title)
        chunks, quality = chunk_parsed_document(
            parsed,
            document_id=document_id,
            profile=ChunkingProfile.AUTO,
        )
        is_canary = bool(canary_title and canary_title in title)
        canary_ok = True
        if is_canary:
            canary_found = True
            canary_ok = (
                len(parsed.pages) == canary_pages
                and canary_chunk_range[0] <= len(chunks) <= canary_chunk_range[1]
            )
        documents.append(
            {
                "path": source_path.relative_to(sources_dir).as_posix(),
                "title": title,
                "provenance": "CANONICAL_MARKDOWN_FALLBACK",
                "profile": quality.profile.value,
                "pages": len(parsed.pages),
                "chunks": len(chunks),
                "coverageRatio": quality.coverage_ratio,
                "shortChunks": quality.short_chunk_count,
                "headingOnly": quality.heading_only_count,
                "orphanMedia": quality.orphan_media_count,
                "duplicates": quality.duplicate_chunk_count,
                "acceptable": quality.is_acceptable and canary_ok,
                "requiresEmbedding": True,
            }
        )
    return {
        "schemaVersion": 1,
        "acceptable": bool(documents)
        and canary_found
        and all(bool(document["acceptable"]) for document in documents),
        "canaryFound": canary_found,
        "documents": documents,
    }


def _document_id(relative_path: Path) -> str:
    digest = hashlib.sha256(relative_path.as_posix().encode("utf-8")).hexdigest()
    return f"migration-{digest[:16]}"


if __name__ == "__main__":
    raise SystemExit(main())
