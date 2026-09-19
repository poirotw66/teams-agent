#!/usr/bin/env python3
"""Phase G console bundle budget gate for the committed console-v2 artifact.

Budgets follow the architecture review gzip targets:
- entry (assets/index-*.js): gzip < 350 KiB
- lazy feature chunks (non-vendor): gzip < 200 KiB
- shared vendor-* chunks: gzip < 400 KiB

Tighten after intentional shrinks; do not raise without review.
"""

from __future__ import annotations

import gzip
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

MAX_ENTRY_GZIP_BYTES = 350_000
MAX_FEATURE_GZIP_BYTES = 200_000
MAX_VENDOR_GZIP_BYTES = 400_000
MAX_TOTAL_BYTES = 2_500_000


def gzip_size(path: Path) -> int:
    return len(gzip.compress(path.read_bytes(), compresslevel=9))


def classify_js(relative: str) -> str:
    name = Path(relative).name
    if name.startswith("index-") and name.endswith(".js"):
        return "entry"
    if name.startswith("vendor-") or name.startswith("vendor.") or name.startswith(
        "rolldown-runtime-"
    ):
        return "vendor"
    return "feature"


def main() -> int:
    if not CONSOLE_V2.is_dir():
        print(f"console-v2 artifact missing: {CONSOLE_V2}", file=sys.stderr)
        return 1

    total = 0
    findings: list[str] = []
    summary: list[str] = []

    for path in sorted(CONSOLE_V2.rglob("*")):
        if not path.is_file():
            continue
        size = path.stat().st_size
        total += size
        if path.suffix != ".js":
            continue

        relative = path.relative_to(CONSOLE_V2).as_posix()
        kind = classify_js(relative)
        gz = gzip_size(path)
        summary.append(f"{kind}:{relative}={gz}")

        if kind == "entry" and gz > MAX_ENTRY_GZIP_BYTES:
            findings.append(
                f"entry {relative} gzip {gz} exceeds {MAX_ENTRY_GZIP_BYTES}"
            )
        elif kind == "feature" and gz > MAX_FEATURE_GZIP_BYTES:
            findings.append(
                f"feature chunk {relative} gzip {gz} exceeds {MAX_FEATURE_GZIP_BYTES}"
            )
        elif kind == "vendor" and gz > MAX_VENDOR_GZIP_BYTES:
            findings.append(
                f"vendor chunk {relative} gzip {gz} exceeds {MAX_VENDOR_GZIP_BYTES}"
            )

    if total > MAX_TOTAL_BYTES:
        findings.append(f"console-v2 total {total} bytes exceeds budget {MAX_TOTAL_BYTES}")

    if findings:
        for item in findings:
            print(f"BUNDLE_BUDGET: {item}", file=sys.stderr)
        return 1

    print(
        f"console bundle budget OK: total={total} bytes; "
        + "; ".join(summary)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
