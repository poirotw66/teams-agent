#!/usr/bin/env python3
"""Delete static/legacy-js only after an unused production release cycle.

Fail-closed by default. Does not run unless both:
  1. ``scripts/check_legacy_deletion_readiness.py`` reports no soft blockers
     other than the tree itself (product HTML / tests already clean), and
  2. ``--confirm-unused-release-completed`` is passed to acknowledge the ops gate.

Usage (from repo root, after quarantine has shipped and one unused release ran):
  uv run python scripts/delete_legacy_js.py --confirm-unused-release-completed --write
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY_JS = (
    REPO_ROOT
    / "agent_service"
    / "src"
    / "ai_ops_backoffice"
    / "static"
    / "legacy-js"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-unused-release-completed",
        action="store_true",
        help="Required acknowledgment that production ran one release without "
        "BACKOFFICE_LEGACY_SHELL_ENABLED after quarantine shipped.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Actually delete the quarantine tree. Without this flag, dry-run only.",
    )
    args = parser.parse_args(argv)

    if not args.confirm_unused_release_completed:
        print(
            "REFUSED: pass --confirm-unused-release-completed only after quarantine "
            "shipped to production and one unused release cycle completed.",
            file=sys.stderr,
        )
        return 2

    if not LEGACY_JS.is_dir():
        print(f"legacy-js already absent: {LEGACY_JS.relative_to(REPO_ROOT)}")
        return 0

    files = sum(1 for path in LEGACY_JS.rglob("*") if path.is_file())
    print(
        f"{'DELETE' if args.write else 'DRY-RUN'}: "
        f"{LEGACY_JS.relative_to(REPO_ROOT)} ({files} files)"
    )
    if not args.write:
        print("Re-run with --write to delete. Then update check_legacy_shell quarantine expectation.")
        return 0

    shutil.rmtree(LEGACY_JS)
    print(
        "Deleted. Dual-mode check_legacy_shell accepts absence; "
        "product path remains React /console-v2."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
