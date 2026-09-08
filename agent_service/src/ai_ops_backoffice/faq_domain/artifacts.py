"""Versioned FAQ file artifacts for audit and handover.

These files are durable exports of ACTIVE FAQ versions. They are not RAG
sources and must never be ingested into knowledge chunks or File Search.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _safe_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned[:120] or "unknown"


def write_faq_activation_artifact(
    artifact_dir: Path,
    *,
    faq: dict[str, Any],
    version: dict[str, Any],
) -> Path:
    """Write markdown + sidecar JSON for one activated FAQ version.

    Layout:
      {artifact_dir}/{faq_key}/v{n}-{version_id}.md
      {artifact_dir}/{faq_key}/v{n}-{version_id}.json
      {artifact_dir}/{faq_key}/ACTIVE.md  (copy of latest active markdown)
    """
    content = version.get("content") or {}
    faq_key = str(content.get("faq_key") or faq.get("faq_key") or "unknown")
    version_id = str(version.get("version_id") or "unknown")
    version_number = int(version.get("version_number") or 0)
    key_dir = artifact_dir / _safe_segment(faq_key)
    key_dir.mkdir(parents=True, exist_ok=True)

    stem = f"v{version_number}-{_safe_segment(version_id)}"
    markdown_path = key_dir / f"{stem}.md"
    json_path = key_dir / f"{stem}.json"
    active_path = key_dir / "ACTIVE.md"

    question = str(content.get("question") or "").strip()
    answer = str(content.get("answer") or "").strip()
    related = content.get("related_document_ids") or []
    markdown = "\n".join(
        [
            f"# {question or faq_key}",
            "",
            f"- FAQ Key: `{faq_key}`",
            f"- FAQ ID: `{faq.get('faq_id', '')}`",
            f"- Version: `v{version_number}` (`{version_id}`)",
            f"- Status: `{version.get('status', '')}`",
            f"- Category: `{content.get('category', '')}`",
            f"- Owner: `{content.get('owner_unit_id', '')}`",
            f"- Issue Types: `{', '.join(content.get('issue_type_ids') or ())}`",
            f"- Related Documents: `{', '.join(related) if related else '(none)'}`",
            "",
            "## Fixed Answer",
            "",
            answer,
            "",
            "> This file is an audit/export artifact. It is not a Knowledge RAG source.",
            "",
        ]
    )
    markdown_path.write_text(markdown, encoding="utf-8")
    active_path.write_text(markdown, encoding="utf-8")
    payload = {
        "faq": faq,
        "version": version,
        "artifactRole": "FAQ_FIXED_ANSWER_EXPORT",
        "indexedForRag": False,
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return markdown_path
