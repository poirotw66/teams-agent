"""Validate retrieval_eval_v3_blind cases against the local corpus."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_corpus(sources_dir: Path) -> dict[str, str]:
    corpus: dict[str, str] = {}
    for path in sorted(sources_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        title: str | None = None
        for line in text.splitlines()[:30]:
            if line.startswith("title:"):
                title = line.split(":", 1)[1].strip()
                break
            if line.startswith("# "):
                title = line[2:].strip()
                break
        if not title:
            title = path.stem
        corpus[title] = text
        corpus[path.stem] = text
    return corpus


def _body_for_docs(corpus: dict[str, str], docs: list[str]) -> str:
    parts: list[str] = []
    for doc in docs:
        if doc in corpus:
            parts.append(corpus[doc])
            continue
        for title, body in corpus.items():
            if doc in title or title in doc:
                parts.append(body)
    return "\n".join(parts)


def validate_blind_set(
    *,
    blind_path: Path,
    sources_dir: Path,
) -> list[str]:
    corpus = _load_corpus(sources_dir)
    titles = set(corpus)
    blind = json.loads(blind_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    if blind.get("role") != "release_holdout":
        errors.append("role must be release_holdout")

    cases = blind.get("cases") or []
    if len(cases) < int(blind.get("minCaseCount") or 0):
        errors.append(
            f"case count {len(cases)} below minCaseCount {blind.get('minCaseCount')}"
        )

    for case in cases:
        case_id = str(case.get("id") or "<missing-id>")
        query = str(case.get("query") or "").strip()
        if not query:
            errors.append(f"{case_id}: empty query")
            continue
        docs = list(case.get("expectedDocuments") or []) + list(
            case.get("expectedSourceTitles") or []
        )
        if case.get("expectedFound") and not docs:
            errors.append(f"{case_id}: expectedFound without expected documents")
        for doc in docs:
            if doc in titles:
                continue
            if any(doc in title or title in doc for title in titles):
                continue
            errors.append(f"{case_id}: unknown document title {doc!r}")
        body = _body_for_docs(corpus, docs)
        for evidence in case.get("expectedEvidence") or []:
            for marker in evidence.get("mustContain") or []:
                if body and marker not in body:
                    errors.append(
                        f"{case_id}: mustContain {marker!r} not found in expected docs"
                    )
        if case.get("split") not in {"test", "blind"}:
            errors.append(f"{case_id}: split must be test (or legacy blind)")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--blind-set",
        type=Path,
        default=Path("data/eval/retrieval_eval_v3_blind.json"),
    )
    parser.add_argument(
        "--sources-dir",
        type=Path,
        default=Path("data/sources"),
    )
    args = parser.parse_args()
    errors = validate_blind_set(blind_path=args.blind_set, sources_dir=args.sources_dir)
    if errors:
        print(f"validation failed ({len(errors)} issue(s))", file=sys.stderr)
        for error in errors[:50]:
            print(f"  - {error}", file=sys.stderr)
        if len(errors) > 50:
            print(f"  ... and {len(errors) - 50} more", file=sys.stderr)
        return 1
    print("retrieval_eval_v3_blind corpus validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
