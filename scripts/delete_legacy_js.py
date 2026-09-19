#!/usr/bin/env python3
"""Delete static/legacy-js only after an unused production release cycle.

Fail-closed by default. Does not run unless both:
  1. Soft readiness blockers are clear (product HTML / non-allowlisted refs), and
  2. ``--confirm-unused-release-completed`` is passed to acknowledge the ops gate.

Usage (from repo root, after quarantine has shipped and one unused release ran):
  uv run python scripts/delete_legacy_js.py --confirm-unused-release-completed --write
"""

from __future__ import annotations

import argparse
import re
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
STATIC_DIR = LEGACY_JS.parent
WAIVERS = REPO_ROOT / "docs" / "architecture" / "oversized-waivers.md"
PROGRESS = REPO_ROOT / "docs" / "project-architecture-followup-progress-20260918.md"
_LEGACY_REF = re.compile(r"legacy-js|/static/legacy-js/")
_ALLOWLISTED_REF_SUFFIXES = (
    "check_legacy_shell.py",
    "test_check_legacy_shell.py",
    "delete_legacy_js.py",
    "check_legacy_deletion_readiness.py",
)


def soft_blockers(*, legacy_js_dir: Path = LEGACY_JS) -> list[str]:
    """Return non-ops blockers that must be clear before deleting the tree.

    The tree itself is the hard ops gate, not a soft blocker.
    """
    blockers: list[str] = []
    static_dir = legacy_js_dir.parent
    if static_dir.is_dir():
        for path in sorted(static_dir.rglob("*.html")):
            rel = path.relative_to(static_dir).as_posix()
            if rel.startswith("legacy-js/"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if _LEGACY_REF.search(text):
                blockers.append(f"product HTML still references legacy-js: {rel}")

    scan_roots = [
        REPO_ROOT / "agent_service" / "tests",
        REPO_ROOT / "tests",
        REPO_ROOT / "scripts",
    ]
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {
                ".py",
                ".md",
                ".mjs",
                ".ts",
                ".tsx",
                ".js",
            }:
                continue
            try:
                relative = path.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                continue
            if "/legacy_frontend/" in relative:
                continue
            if relative.endswith(_ALLOWLISTED_REF_SUFFIXES):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "static/legacy-js" in text or "/legacy-js/" in text:
                blockers.append(f"non-allowlisted reference: {relative}")
    return blockers


def _update_waivers_after_delete(waivers_path: Path = WAIVERS) -> None:
    if not waivers_path.is_file():
        return
    text = waivers_path.read_text(encoding="utf-8")
    old = (
        "| Legacy quarantine (non-product) | `static/legacy-js/**` | "
        "Emergency kill-switch only; not on default product path | "
        "Delete after **one full release cycle** where production never sets "
        "`BACKOFFICE_LEGACY_SHELL_ENABLED`; gate: `scripts/check_legacy_shell.py` "
        "(defaults + deploy/env samples must stay off). Do not delete the tree "
        "until that cycle completes |"
    )
    new = (
        "| Legacy quarantine (non-product) | ~~`static/legacy-js/**`~~ (deleted) | "
        "Emergency kill-switch retired after unused release | "
        "Tree removed; dual-mode `check_legacy_shell.py` accepts absence |"
    )
    if old in text:
        waivers_path.write_text(text.replace(old, new), encoding="utf-8")


def _update_progress_after_delete(progress_path: Path = PROGRESS) -> None:
    if not progress_path.is_file():
        return
    text = progress_path.read_text(encoding="utf-8")
    updated = text.replace(
        "| G Independent frontend + legacy removal | Partial — soft deliverables + "
        "fail-closed `delete_legacy_js.py`; **tree delete still waits unused release** |",
        "| G Independent frontend + legacy removal | **Done** — soft deliverables + "
        "`static/legacy-js` removed after unused release |",
    )
    if "## Goal blockers (not closed)" in updated:
        updated = re.sub(
            r"## Goal blockers \(not closed\).*",
            "## Goal blockers (not closed)\n\n- None — Phase G hard exit complete "
            "(`static/legacy-js` absent).\n",
            updated,
            count=1,
            flags=re.DOTALL,
        )
    if updated != text:
        progress_path.write_text(updated, encoding="utf-8")


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

    blockers = soft_blockers()
    if blockers:
        print("REFUSED: soft readiness blockers remain:", file=sys.stderr)
        for item in blockers:
            print(f"  - {item}", file=sys.stderr)
        return 1

    if not LEGACY_JS.is_dir():
        print(f"legacy-js already absent: {LEGACY_JS.relative_to(REPO_ROOT)}")
        return 0

    files = sum(1 for path in LEGACY_JS.rglob("*") if path.is_file())
    print(
        f"{'DELETE' if args.write else 'DRY-RUN'}: "
        f"{LEGACY_JS.relative_to(REPO_ROOT)} ({files} files)"
    )
    if not args.write:
        print(
            "Re-run with --write to delete. Dual-mode check_legacy_shell accepts "
            "absence; waivers/progress update on write."
        )
        return 0

    shutil.rmtree(LEGACY_JS)
    _update_waivers_after_delete()
    _update_progress_after_delete()
    print(
        "Deleted. Dual-mode check_legacy_shell accepts absence; "
        "product path remains React /console-v2."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
