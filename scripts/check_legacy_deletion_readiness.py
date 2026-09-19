#!/usr/bin/env python3
"""Report readiness to delete static/legacy-js (Phase G hard exit).

Does not delete anything. Prints blockers that still prevent legacy application
LOC from reaching zero after an unused production release cycle.
"""

from __future__ import annotations

import re
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
_LEGACY_REF = re.compile(r"legacy-js|/static/legacy-js/")


def _count_loc(root: Path) -> int:
    total = 0
    if not root.is_dir():
        return 0
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in {".js", ".css", ".html"}:
            total += sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))
    return total


def main() -> int:
    blockers: list[str] = []
    notes: list[str] = []

    if LEGACY_JS.is_dir():
        loc = _count_loc(LEGACY_JS)
        files = sum(1 for p in LEGACY_JS.rglob("*") if p.is_file())
        blockers.append(
            f"legacy-js tree still present ({files} files, ~{loc} LOC); "
            "delete only after one unused production release cycle"
        )
    else:
        notes.append("legacy-js tree already absent")

    # Non-allowlisted product HTML references.
    if STATIC_DIR.is_dir():
        for path in sorted(STATIC_DIR.rglob("*.html")):
            rel = path.relative_to(STATIC_DIR).as_posix()
            if rel.startswith("legacy-js/"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if _LEGACY_REF.search(text):
                blockers.append(f"product HTML still references legacy-js: {rel}")

    # Test / script imports outside the quarantine tree.
    scan_roots = [
        REPO_ROOT / "agent_service" / "tests",
        REPO_ROOT / "tests",
        REPO_ROOT / "scripts",
    ]
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".py", ".md", ".mjs", ".ts", ".tsx", ".js"}:
                continue
            # Quarantine characterization tests are deleted with the tree.
            try:
                relative = path.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                continue
            if "/legacy_frontend/" in relative or relative.endswith(
                "check_legacy_shell.py"
            ) or relative.endswith("test_check_legacy_shell.py") or relative.endswith(
                "delete_legacy_js.py"
            ) or relative.endswith("check_legacy_deletion_readiness.py"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "static/legacy-js" in text or "/legacy-js/" in text:
                notes.append(f"reference remains (update when deleting): {relative}")

    print("Phase G legacy deletion readiness")
    print("================================")
    if blockers:
        print("BLOCKERS:")
        for item in blockers:
            print(f"  - {item}")
    else:
        print("BLOCKERS: none")
    if notes:
        print("NOTES:")
        for item in notes:
            print(f"  - {item}")
    print(
        "OPS GATE: either (1) quarantine shipped + one unused production release "
        "with BACKOFFICE_LEGACY_SHELL_ENABLED unset/false, or (2) quarantine never "
        "present on origin/main (pre-first-ship delete via "
        "--confirm-never-shipped-to-origin)."
    )
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
