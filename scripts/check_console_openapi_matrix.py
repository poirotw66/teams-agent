#!/usr/bin/env python3
"""Fail when console_frontend calls Backoffice paths missing from OpenAPI.

Phase F cross-version matrix: the generated contract and live console call sites
must stay aligned. Literal ``/api/...`` paths in console TypeScript must resolve
to an operation in the canonical Backoffice OpenAPI document (path-params
normalized to ``{name}`` templates).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONSOLE_SRC = REPO_ROOT / "console_frontend" / "src"
OPENAPI = (
    REPO_ROOT
    / "docs"
    / "architecture"
    / "baselines"
    / "openapi"
    / "ai_ops_backoffice.openapi.json"
)

# Capture string literals that look like Backoffice HTTP paths.
_API_PATH_RE = re.compile(r"""['"`](/api/[^'"`?#]+)['"`]""")
_TEMPLATE_EXPR_RE = re.compile(r"\$\{[^}]+\}")
_SKIP_DIR_NAMES = frozenset({"generated", "node_modules", "dist"})


def _normalize_template(path: str) -> str:
    """Turn runtime template segments into OpenAPI `{param}` placeholders."""
    cleaned = path.split("?")[0]
    cleaned = _TEMPLATE_EXPR_RE.sub("{id}", cleaned)
    # Collapse accidental double braces from adjacent templates.
    while "{{" in cleaned:
        cleaned = cleaned.replace("{{", "{").replace("}}", "}")
    return cleaned


def _openapi_path_templates(document: dict) -> set[str]:
    paths = document.get("paths") or {}
    return set(paths) if isinstance(paths, dict) else set()


def _path_matches(template: str, openapi_paths: set[str]) -> bool:
    if template in openapi_paths:
        return True
    template_parts = template.strip("/").split("/")
    for candidate in openapi_paths:
        candidate_parts = candidate.strip("/").split("/")
        # Catch-all final param (e.g. /api/knowledge/{full_path}) covers nested paths.
        if (
            len(candidate_parts) <= len(template_parts)
            and candidate_parts
            and candidate_parts[-1].startswith("{")
            and candidate_parts[-1].endswith("}")
            and (
                "full_path" in candidate_parts[-1]
                or "path" in candidate_parts[-1].lower()
            )
        ):
            prefix = candidate_parts[:-1]
            if template_parts[: len(prefix)] == prefix or all(
                left == right
                or (left.startswith("{") and left.endswith("}"))
                or (right.startswith("{") and right.endswith("}"))
                for left, right in zip(
                    template_parts[: len(prefix)], prefix, strict=True
                )
            ):
                if len(template_parts) >= len(candidate_parts):
                    return True
        if len(candidate_parts) != len(template_parts):
            continue
        matched = True
        for left, right in zip(template_parts, candidate_parts, strict=True):
            left_param = left.startswith("{") and left.endswith("}")
            right_param = right.startswith("{") and right.endswith("}")
            if left_param or right_param:
                continue
            if left != right:
                matched = False
                break
        if matched:
            return True
    return False


def _collect_console_api_paths(root: Path) -> set[str]:
    found: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in {".ts", ".tsx"}:
            continue
        if any(part in _SKIP_DIR_NAMES for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        for match in _API_PATH_RE.findall(text):
            if "${" in match or match.startswith("/api/"):
                found.add(_normalize_template(match))
    return found


def main() -> int:
    if not OPENAPI.is_file():
        print(f"missing OpenAPI document: {OPENAPI}", file=sys.stderr)
        return 1
    if not CONSOLE_SRC.is_dir():
        print(f"missing console source: {CONSOLE_SRC}", file=sys.stderr)
        return 1

    import json

    document = json.loads(OPENAPI.read_text(encoding="utf-8"))
    openapi_paths = _openapi_path_templates(document)
    console_paths = _collect_console_api_paths(CONSOLE_SRC)
    missing = sorted(
        path for path in console_paths if not _path_matches(path, openapi_paths)
    )
    if missing:
        print(
            "CONSOLE_OPENAPI_MATRIX: console call sites missing from "
            "canonical Backoffice OpenAPI:",
            file=sys.stderr,
        )
        for path in missing:
            print(f"  - {path}", file=sys.stderr)
        return 1

    print(
        f"console OpenAPI matrix OK: checked={len(console_paths)} "
        f"openapi_paths={len(openapi_paths)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
