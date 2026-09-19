#!/usr/bin/env python3
"""Phase G console bundle budget gate for the committed console-v2 artifact.

Budgets are monotonic upper bounds for the Backoffice-served
``static/console-v2`` tree (and any independent image that copies it).
Tighten after intentional shrinks; do not raise without review.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONSOLE_V2 = (
    REPO_ROOT
    / "agent_service"
    / "src"
    / "ai_ops_backoffice"
    / "static"
    / "console-v2"
)

# Soft ceilings derived from the 2026-09-19 artifact (~2.1 MiB total).
MAX_TOTAL_BYTES = 2_500_000
MAX_SINGLE_JS_BYTES = 2_300_000


def main() -> int:
    if not CONSOLE_V2.is_dir():
        print(f"console-v2 artifact missing: {CONSOLE_V2}", file=sys.stderr)
        return 1

    total = 0
    largest_js = 0
    largest_name = ""
    for path in CONSOLE_V2.rglob("*"):
        if not path.is_file():
            continue
        size = path.stat().st_size
        total += size
        if path.suffix == ".js" and size > largest_js:
            largest_js = size
            largest_name = str(path.relative_to(CONSOLE_V2))

    findings: list[str] = []
    if total > MAX_TOTAL_BYTES:
        findings.append(
            f"console-v2 total {total} bytes exceeds budget {MAX_TOTAL_BYTES}"
        )
    if largest_js > MAX_SINGLE_JS_BYTES:
        findings.append(
            f"largest JS {largest_name} is {largest_js} bytes "
            f"(budget {MAX_SINGLE_JS_BYTES})"
        )

    if findings:
        for item in findings:
            print(f"BUNDLE_BUDGET: {item}", file=sys.stderr)
        return 1

    print(
        f"console bundle budget OK: total={total} bytes, "
        f"largest_js={largest_name}:{largest_js} bytes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
