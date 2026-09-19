#!/usr/bin/env python3
"""Fail if Agent Dockerfile re-bakes knowledge corpus/index into the image.

Knowledge Release Artifacts in GCS are the production Source of Truth
(docs/0919-arch.md P0). The Agent image may copy faq.json / data/ops only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "agent_service" / "Dockerfile"

# Forbidden bake paths for knowledge plane content.
_FORBIDDEN = re.compile(
    r"^\s*COPY\s+(?:--\S+\s+)*"
    r"(?:data/sources|data/index|data/releases|\./data/sources|\./data/index)"
    r"(?:\s|$)",
    re.IGNORECASE | re.MULTILINE,
)
_FULL_DATA_COPY = re.compile(
    r"^\s*COPY\s+(?:--\S+\s+)*data(?:/\s|\s+\./data\s*$)",
    re.IGNORECASE | re.MULTILINE,
)


def main() -> int:
    text = DOCKERFILE.read_text(encoding="utf-8")
    findings: list[str] = []
    for match in _FORBIDDEN.finditer(text):
        findings.append(f"forbidden COPY: {match.group(0).strip()}")
    for match in _FULL_DATA_COPY.finditer(text):
        findings.append(
            f"broad data COPY reintroduced (use faq.json/ops only): "
            f"{match.group(0).strip()}"
        )
    if "knowledge releases are fetched" not in text.lower() and (
        "from GCS" not in text and "from gcs" not in text
    ):
        # Soft: require the intentional comment near the data COPY block.
        if "COPY data/faq.json" in text and "GCS" not in text:
            findings.append(
                "Dockerfile copies faq/ops but lacks GCS knowledge-release comment"
            )
    if findings:
        print("Knowledge image SoT check FAILED:", file=sys.stderr)
        for item in findings:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print(
        "Knowledge image SoT OK: Agent Dockerfile does not bake "
        "data/sources|data/index|data/releases."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
