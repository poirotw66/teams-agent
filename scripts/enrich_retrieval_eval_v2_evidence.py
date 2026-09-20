#!/usr/bin/env python3
"""Enrich retrieval_eval_v2.json with evidence-level labels (RAG v2.1 P0).

Deterministic, offline: matches expected document titles to index chunks, then
binds exact identifiers from the query to chunk ids / mustContain tokens.
Adds a frozen ``split`` field (dev/test) from case-id hashing.

Usage:

    uv run python scripts/enrich_retrieval_eval_v2_evidence.py \\
        --eval-set data/eval/retrieval_eval_v2.json \\
        --index data/index/chunks.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

IDENTIFIER_RE = re.compile(
    r"(?:"
    r"\(-?\d{1,5}\)"  # (-455), (-14)
    r"|-?\b\d{3,5}\b"  # bare 455 / -200 when clearly an error code context
    r"|[A-Z]{2,}[-_][A-Z0-9]{2,}"  # UX-AUDIT style tokens (not used as answers)
    r"|FAQ-\d+"
    r"|Error\s+\d+"
    r")",
    re.IGNORECASE,
)
_QUERY_TOKEN_RE = re.compile(r"[A-Za-z0-9_./:\\-]{2,}|[\u3400-\u9fff]{2,}")
_STOP_TOKENS = frozenset(
    {
        "怎麼",
        "如何",
        "什麼",
        "請問",
        "可以",
        "怎麼辦",
        "處理",
        "設定",
        "問題",
        "the",
        "and",
        "for",
        "with",
        "from",
    }
)


def _extract_identifiers(query: str) -> list[str]:
    found: list[str] = []
    for match in IDENTIFIER_RE.finditer(query or ""):
        token = match.group(0).strip()
        if token and token not in found:
            found.append(token)
    # Prefer parenthesized codes as canonical form.
    normalized: list[str] = []
    for token in found:
        if re.fullmatch(r"-?\d{3,5}", token):
            normalized.append(f"({token})" if not token.startswith("(") else token)
        else:
            normalized.append(token)
    # Dedupe while preferring parenthesized forms.
    out: list[str] = []
    for token in normalized:
        if token not in out:
            out.append(token)
    return out


def _identifier_forms(token: str) -> list[str]:
    """Match both ``(-200)`` and ``-200`` spellings in chunk text."""
    forms = [token]
    bare = token.strip("()")
    if bare and bare != token:
        forms.append(bare)
    elif re.fullmatch(r"-?\d{3,5}", token):
        forms.append(f"({token})")
    return forms


def _blob_has_identifier(blob: str, identifiers: Sequence[str]) -> bool:
    return any(
        form in blob for token in identifiers for form in _identifier_forms(token)
    )


def _must_contain_for_identifiers(blob: str, identifiers: Sequence[str]) -> list[str]:
    must: list[str] = []
    for token in identifiers:
        for form in _identifier_forms(token):
            if form in blob and form not in must:
                must.append(form)
                break
    return must


def _query_overlap_tokens(query: str, blob: str, *, limit: int = 4) -> list[str]:
    """Distinctive query tokens that also appear in the chunk text."""
    tokens: list[str] = []
    for match in _QUERY_TOKEN_RE.finditer(query or ""):
        token = match.group(0)
        lowered = token.casefold()
        if lowered in _STOP_TOKENS or token in tokens:
            continue
        if token in blob or lowered in blob.casefold():
            tokens.append(token)
        if len(tokens) >= limit:
            break
    return tokens


def _title_anchor_tokens(title: str, blob: str, *, limit: int = 4) -> list[str]:
    """Fallback anchors from the expected title when query overlap is empty."""
    tokens: list[str] = []
    for match in _QUERY_TOKEN_RE.finditer(title or ""):
        token = match.group(0)
        lowered = token.casefold()
        if lowered in _STOP_TOKENS or token in tokens:
            continue
        if token in blob or lowered in blob.casefold():
            tokens.append(token)
        if len(tokens) >= limit:
            break
    return tokens


def _best_chunk_for_title(
    title_chunks: list[dict[str, Any]],
    *,
    query: str,
) -> dict[str, Any] | None:
    if not title_chunks:
        return None
    identifiers = _extract_identifiers(query)
    if identifiers:
        for chunk in title_chunks:
            blob = _chunk_blob(chunk)
            if _blob_has_identifier(blob, identifiers):
                return chunk
    scored: list[tuple[int, dict[str, Any]]] = []
    for chunk in title_chunks:
        blob = _chunk_blob(chunk)
        scored.append((len(_query_overlap_tokens(query, blob)), chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1] if scored else title_chunks[0]


def _chunk_blob(chunk: dict[str, Any]) -> str:
    parts = [
        chunk.get("title") or "",
        chunk.get("section") or "",
        " ".join(chunk.get("heading_path") or []),
        chunk.get("content") or "",
        chunk.get("retrieval_text") or "",
    ]
    return "\n".join(parts)


def _split_for_case(case_id: str) -> str:
    digest = hashlib.sha256(case_id.encode("utf-8")).hexdigest()
    # ~70% dev / 30% test, stable across runs.
    return "test" if int(digest[:8], 16) % 10 < 3 else "dev"


def _evidence_from_chunk(
    chunk: dict[str, Any],
    *,
    query: str,
    title: str,
    identifiers: Sequence[str],
) -> dict[str, Any] | None:
    blob = _chunk_blob(chunk)
    chunk_id = str(chunk.get("chunk_id") or "")
    section = (
        chunk.get("section")
        or (chunk.get("heading_path") or [None])[-1]
        or None
    )
    must = _must_contain_for_identifiers(blob, identifiers)
    for token in _query_overlap_tokens(query, blob, limit=5):
        if token not in must:
            must.append(token)
    if not must:
        for token in _title_anchor_tokens(title or str(chunk.get("title") or ""), blob):
            if token not in must:
                must.append(token)
    if not must:
        return None
    return {
        "section": section,
        "chunkId": chunk_id or None,
        "mustContain": must[:6],
    }


def _enrich_case(
    case: dict[str, Any],
    *,
    chunks_by_title: dict[str, list[dict[str, Any]]],
    chunks_by_id: dict[str, dict[str, Any]] | None = None,
    fill_empty_only: bool = False,
) -> dict[str, Any]:
    updated = dict(case)
    titles = list(case.get("expectedSourceTitles") or case.get("expectedDocuments") or [])
    updated.setdefault("expectedDocuments", titles)
    updated.setdefault("forbiddenEvidence", list(case.get("forbiddenSourceTitles") or []))
    updated["split"] = case.get("split") or _split_for_case(str(case.get("id") or ""))

    if not case.get("expectedFound", True):
        updated.setdefault("expectedChunkIds", [])
        updated.setdefault("expectedSections", [])
        updated.setdefault("expectedEvidence", [])
        return updated

    existing_evidence = list(case.get("expectedEvidence") or [])
    if fill_empty_only and existing_evidence:
        return updated

    identifiers = _extract_identifiers(str(case.get("query") or ""))
    query = str(case.get("query") or "")
    chunk_lookup = chunks_by_id or {}

    preferred_chunks: list[tuple[str, dict[str, Any]]] = []
    for chunk_id in case.get("expectedChunkIds") or []:
        chunk = chunk_lookup.get(str(chunk_id))
        if chunk is not None:
            preferred_chunks.append((str(chunk.get("title") or ""), chunk))

    matched_by_title: list[tuple[str, dict[str, Any]]] = []
    for title in titles:
        for chunk in chunks_by_title.get(title, []):
            matched_by_title.append((title, chunk))

    chunk_ids: list[str] = []
    sections: list[str] = []
    evidence: list[dict[str, Any]] = []

    def _record(title: str, chunk: dict[str, Any]) -> None:
        fact = _evidence_from_chunk(
            chunk,
            query=query,
            title=title,
            identifiers=identifiers,
        )
        if fact is None:
            return
        chunk_id = str(fact.get("chunkId") or "")
        if chunk_id and chunk_id not in chunk_ids:
            chunk_ids.append(chunk_id)
        section = fact.get("section")
        if section and section not in sections:
            sections.append(str(section))
        evidence.append(fact)

    if preferred_chunks:
        for title, chunk in preferred_chunks:
            _record(title, chunk)
    elif identifiers and matched_by_title:
        for title, chunk in matched_by_title:
            if _blob_has_identifier(_chunk_blob(chunk), identifiers):
                _record(title, chunk)
        if not evidence:
            for title in titles:
                chunk = _best_chunk_for_title(
                    chunks_by_title.get(title) or [],
                    query=query,
                )
                if chunk is not None:
                    _record(title, chunk)
    else:
        for title in titles:
            chunk = _best_chunk_for_title(chunks_by_title.get(title) or [], query=query)
            if chunk is not None:
                _record(title, chunk)

    if chunk_ids:
        updated["expectedChunkIds"] = chunk_ids
    elif case.get("expectedChunkIds"):
        updated["expectedChunkIds"] = case["expectedChunkIds"]
    if sections:
        updated["expectedSections"] = sections
    if evidence:
        updated["expectedEvidence"] = evidence
    elif existing_evidence:
        updated["expectedEvidence"] = existing_evidence
    else:
        updated.setdefault("expectedEvidence", [])

    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--eval-set",
        type=Path,
        default=Path("data/eval/retrieval_eval_v2.json"),
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=Path("data/index/chunks.json"),
    )
    parser.add_argument(
        "--fill-empty-only",
        action="store_true",
        help="Only populate cases whose expectedEvidence is currently empty.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    payload = json.loads(args.eval_set.read_text(encoding="utf-8"))
    index_payload = json.loads(args.index.read_text(encoding="utf-8"))
    chunks = list(index_payload.get("chunks") or [])
    chunks_by_title: dict[str, list[dict[str, Any]]] = {}
    chunks_by_id: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        title = str(chunk.get("title") or "")
        chunks_by_title.setdefault(title, []).append(chunk)
        chunk_id = str(chunk.get("chunk_id") or "")
        if chunk_id:
            chunks_by_id[chunk_id] = chunk

    before_empty = sum(
        1
        for case in payload["cases"]
        if case.get("expectedFound") and not case.get("expectedEvidence")
    )
    enriched = [
        _enrich_case(
            case,
            chunks_by_title=chunks_by_title,
            chunks_by_id=chunks_by_id,
            fill_empty_only=args.fill_empty_only,
        )
        for case in payload["cases"]
    ]
    with_chunks = sum(1 for case in enriched if case.get("expectedChunkIds"))
    with_evidence = sum(1 for case in enriched if case.get("expectedEvidence"))
    answerable = sum(1 for case in enriched if case.get("expectedFound"))
    answerable_with_evidence = sum(
        1
        for case in enriched
        if case.get("expectedFound") and case.get("expectedEvidence")
    )
    after_empty = sum(
        1
        for case in enriched
        if case.get("expectedFound") and not case.get("expectedEvidence")
    )
    splits = {
        "dev": sum(1 for case in enriched if case.get("split") == "dev"),
        "test": sum(1 for case in enriched if case.get("split") == "test"),
    }
    print(
        json.dumps(
            {
                "caseCount": len(enriched),
                "answerable": answerable,
                "withExpectedChunkIds": with_chunks,
                "withExpectedEvidence": with_evidence,
                "answerableWithEvidence": answerable_with_evidence,
                "answerableMissingEvidenceBefore": before_empty,
                "answerableMissingEvidenceAfter": after_empty,
                "splits": splits,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.dry_run:
        return 0

    payload["cases"] = enriched
    payload["description"] = (
        "Hard retrieval benchmark for RAG v2 / v2.1. Prefer expectedChunkIds / "
        "expectedEvidence for Evidence Recall@4; expectedSourceTitles kept for "
        "compatibility. Cases carry split=dev|test (docs/rag-v2.1-plan.md)."
    )
    args.eval_set.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
