#!/usr/bin/env python3
"""Delete static/legacy-js under a fail-closed ops gate.

Does not run unless soft readiness blockers are clear and one of:

1. ``--confirm-unused-release-completed`` — quarantine already shipped and one
   production release ran with ``BACKOFFICE_LEGACY_SHELL_ENABLED`` unset/false; or
2. ``--confirm-never-shipped-to-origin`` — ``origin/<ref>`` has no quarantine
   tree / kill-switch env (pre-first-ship delete; avoids shipping ~18k LOC of
   unused classic SPA solely to retire it later).

Usage:
  uv run python scripts/delete_legacy_js.py --confirm-never-shipped-to-origin --write
  uv run python scripts/delete_legacy_js.py --confirm-unused-release-completed --write
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
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
WAIVERS = REPO_ROOT / "docs" / "architecture" / "oversized-waivers.md"
PROGRESS = REPO_ROOT / "docs" / "project-architecture-followup-progress-20260918.md"
_LEGACY_REF = re.compile(r"legacy-js|/static/legacy-js/")
_ALLOWLISTED_REF_SUFFIXES = (
    "check_legacy_shell.py",
    "test_check_legacy_shell.py",
    "delete_legacy_js.py",
    "check_legacy_deletion_readiness.py",
)
_ORIGIN_QUARANTINE_MARKERS = (
    "legacy-js",
    "BACKOFFICE_LEGACY_SHELL",
)


def soft_blockers(*, legacy_js_dir: Path = LEGACY_JS) -> list[str]:
    """Return non-ops blockers that must be clear before deleting the tree."""
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


def origin_quarantine_hits(
    *,
    origin_ref: str = "origin/main",
) -> list[str]:
    """Return paths on origin_ref that prove quarantine already shipped."""
    completed = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", origin_ref],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"unable to inspect {origin_ref}: {completed.stderr.strip() or completed.stdout.strip()}"
        )
    hits: list[str] = []
    for line in completed.stdout.splitlines():
        if any(marker in line for marker in _ORIGIN_QUARANTINE_MARKERS):
            hits.append(line)
    return hits


def _update_waivers_after_delete(
    waivers_path: Path = WAIVERS,
    *,
    reason: str,
) -> None:
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
        f"| Legacy quarantine (non-product) | ~~`static/legacy-js/**`~~ (deleted) | "
        f"{reason} | "
        "Tree removed; dual-mode `check_legacy_shell.py` accepts absence |"
    )
    if old in text:
        waivers_path.write_text(text.replace(old, new), encoding="utf-8")


def _update_progress_after_delete(
    progress_path: Path = PROGRESS,
    *,
    how: str,
) -> None:
    if not progress_path.is_file():
        return
    text = progress_path.read_text(encoding="utf-8")
    updated = re.sub(
        r"\| G Independent frontend \+ legacy removal \| Partial —.*?\|",
        f"| G Independent frontend + legacy removal | **Done** — soft deliverables + "
        f"`static/legacy-js` removed ({how}) |",
        text,
        count=1,
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
        help="Acknowledge production ran one unused release after quarantine shipped.",
    )
    parser.add_argument(
        "--confirm-never-shipped-to-origin",
        action="store_true",
        help="Acknowledge quarantine is absent on origin (pre-first-ship delete).",
    )
    parser.add_argument(
        "--origin-ref",
        default="origin/main",
        help="Git ref inspected for --confirm-never-shipped-to-origin (default origin/main).",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Actually delete the quarantine tree. Without this flag, dry-run only.",
    )
    args = parser.parse_args(argv)

    if not (
        args.confirm_unused_release_completed or args.confirm_never_shipped_to_origin
    ):
        print(
            "REFUSED: pass --confirm-unused-release-completed or "
            "--confirm-never-shipped-to-origin.",
            file=sys.stderr,
        )
        return 2

    if args.confirm_never_shipped_to_origin:
        try:
            hits = origin_quarantine_hits(origin_ref=args.origin_ref)
        except RuntimeError as error:
            print(f"REFUSED: {error}", file=sys.stderr)
            return 1
        if hits:
            print(
                f"REFUSED: {args.origin_ref} already contains quarantine markers; "
                "use --confirm-unused-release-completed after an unused production release.",
                file=sys.stderr,
            )
            for hit in hits[:20]:
                print(f"  - {hit}", file=sys.stderr)
            return 1

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
    if args.confirm_never_shipped_to_origin:
        reason = (
            "Pre-first-ship delete — quarantine never present on origin/main"
        )
        how = "pre-first-ship; never on origin/main"
    else:
        reason = "Emergency kill-switch retired after unused release"
        how = "after unused production release"
    _update_waivers_after_delete(reason=reason)
    _update_progress_after_delete(how=how)
    print(
        "Deleted. Dual-mode check_legacy_shell accepts absence; "
        "product path remains React /console-v2."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
