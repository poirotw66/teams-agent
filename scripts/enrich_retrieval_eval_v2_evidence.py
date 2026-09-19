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
            if any(token in blob for token in identifiers):
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


def _enrich_case(
    case: dict[str, Any],
    *,
    chunks_by_title: dict[str, list[dict[str, Any]]],
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

    identifiers = _extract_identifiers(str(case.get("query") or ""))
    query = str(case.get("query") or "")
    matched_chunks: list[dict[str, Any]] = []
    for title in titles:
        matched_chunks.extend(chunks_by_title.get(title, []))

    chunk_ids: list[str] = []
    sections: list[str] = []
    evidence: list[dict[str, Any]] = []

    if identifiers and matched_chunks:
        for chunk in matched_chunks:
            blob = _chunk_blob(chunk)
            if not any(token in blob for token in identifiers):
                continue
            chunk_id = str(chunk.get("chunk_id") or "")
            if chunk_id and chunk_id not in chunk_ids:
                chunk_ids.append(chunk_id)
            section = (
                chunk.get("section")
                or (chunk.get("heading_path") or [None])[-1]
                or None
            )
            if section and section not in sections:
                sections.append(str(section))
            must = [token for token in identifiers if token in blob]
            overlap = _query_overlap_tokens(query, blob)
            for token in overlap:
                if token not in must:
                    must.append(token)
            if must:
                evidence.append(
                    {
                        "section": section,
                        "chunkId": chunk_id or None,
                        "mustContain": must[:6],
                    }
                )
    elif matched_chunks:
        # Prefer the chunk in each expected title with the strongest query overlap.
        for title in titles:
            chunk = _best_chunk_for_title(chunks_by_title.get(title) or [], query=query)
            if chunk is None:
                continue
            chunk_id = str(chunk.get("chunk_id") or "")
            if chunk_id and chunk_id not in chunk_ids:
                chunk_ids.append(chunk_id)
            blob = _chunk_blob(chunk)
            section = (
                chunk.get("section")
                or (chunk.get("heading_path") or [None])[-1]
                or None
            )
            if section and section not in sections:
                sections.append(str(section))
            must = _query_overlap_tokens(query, blob, limit=5)
            if must:
                evidence.append(
                    {
                        "section": section,
                        "chunkId": chunk_id or None,
                        "mustContain": must,
                    }
                )

    if chunk_ids:
        updated["expectedChunkIds"] = chunk_ids
    if sections:
        updated["expectedSections"] = sections
    if evidence:
        updated["expectedEvidence"] = evidence
    elif case.get("expectedEvidence"):
        updated["expectedEvidence"] = case["expectedEvidence"]
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
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    payload = json.loads(args.eval_set.read_text(encoding="utf-8"))
    index_payload = json.loads(args.index.read_text(encoding="utf-8"))
    chunks = list(index_payload.get("chunks") or [])
    chunks_by_title: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        title = str(chunk.get("title") or "")
        chunks_by_title.setdefault(title, []).append(chunk)

    enriched = [_enrich_case(case, chunks_by_title=chunks_by_title) for case in payload["cases"]]
    with_chunks = sum(1 for case in enriched if case.get("expectedChunkIds"))
    with_evidence = sum(1 for case in enriched if case.get("expectedEvidence"))
    splits = {
        "dev": sum(1 for case in enriched if case.get("split") == "dev"),
        "test": sum(1 for case in enriched if case.get("split") == "test"),
    }
    print(
        json.dumps(
            {
                "caseCount": len(enriched),
                "withExpectedChunkIds": with_chunks,
                "withExpectedEvidence": with_evidence,
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
