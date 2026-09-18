#!/usr/bin/env python3
"""Architecture ratchet for domain imports, file size, and function size.

Wave 0 stop-the-bleeding gate from docs/project-architecture-refactor-plan-20260918.md.

Usage:
  uv run python scripts/check_architecture.py
  uv run python scripts/check_architecture.py --write-baselines
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_DIR = REPO_ROOT / "docs" / "architecture" / "baselines"
OVERSIZED_FILES_BASELINE = BASELINE_DIR / "oversized_files.json"
OVERSIZED_FUNCTIONS_BASELINE = BASELINE_DIR / "oversized_functions.json"
REVERSE_IMPORTS_BASELINE = BASELINE_DIR / "reverse_imports.json"

PACKAGE_ROOTS: dict[str, Path] = {
    "agent_service": REPO_ROOT / "agent_service" / "src" / "agent_service",
    "ai_ops_backoffice": REPO_ROOT / "agent_service" / "src" / "ai_ops_backoffice",
    "knowledge_portal": REPO_ROOT / "agent_service" / "src" / "knowledge_portal",
    "platform_kernel": REPO_ROOT / "agent_service" / "src" / "platform_kernel",
    "composition": REPO_ROOT / "agent_service" / "src" / "composition",
    "teams_agent": REPO_ROOT / "src" / "teams_agent",
    "console_frontend": REPO_ROOT / "console_frontend" / "src",
}

DOMAIN_PACKAGES = frozenset(
    {
        "agent_service",
        "ai_ops_backoffice",
        "knowledge_portal",
        "platform_kernel",
        "composition",
        "teams_agent",
    }
)

# Target dependency direction. Edges listed here are forbidden and may only
# shrink via the reverse-import ratchet allowlist.
# composition is the wiring root and may import any domain; domains must not
# import each other except via platform_kernel ports / allowed one-way edges.
FORBIDDEN_EDGES = frozenset(
    {
        ("agent_service", "ai_ops_backoffice"),
        ("agent_service", "knowledge_portal"),
        ("agent_service", "composition"),
        ("ai_ops_backoffice", "composition"),
        ("knowledge_portal", "ai_ops_backoffice"),
        ("knowledge_portal", "composition"),
        ("platform_kernel", "agent_service"),
        ("platform_kernel", "ai_ops_backoffice"),
        ("platform_kernel", "knowledge_portal"),
        ("platform_kernel", "teams_agent"),
        ("platform_kernel", "composition"),
        ("teams_agent", "agent_service"),
        ("teams_agent", "ai_ops_backoffice"),
        ("teams_agent", "knowledge_portal"),
        ("teams_agent", "platform_kernel"),
        ("teams_agent", "composition"),
    }
)

MAX_NEW_FILE_LINES = 500
MAX_NEW_FUNCTION_LINES = 80
SOURCE_SUFFIXES = frozenset({".py", ".ts", ".tsx"})
EXCLUDED_DIR_NAMES = frozenset(
    {"__pycache__", "static", "node_modules", "dist", "build", ".vite"}
)


@dataclass(frozen=True)
class Finding:
    code: str
    message: str


def rel_path(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIR_NAMES for part in path.parts)


def package_of(path: Path) -> str | None:
    resolved = path.resolve()
    for name, root in PACKAGE_ROOTS.items():
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            continue
        else:
            return name
    return None


def iter_source_files() -> Iterable[Path]:
    for root in PACKAGE_ROOTS.values():
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            if is_excluded(path):
                continue
            yield path


def count_lines(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def collect_file_sizes() -> dict[str, int]:
    return {rel_path(path): count_lines(path) for path in iter_source_files()}


def collect_oversized_functions() -> dict[str, int]:
    """Map 'relative/path.py::qualname' -> logical line count."""
    results: dict[str, int] = {}
    for path in iter_source_files():
        if path.suffix != ".py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            end_lineno = getattr(node, "end_lineno", None) or node.lineno
            line_count = end_lineno - node.lineno + 1
            if line_count <= MAX_NEW_FUNCTION_LINES:
                continue
            key = f"{rel_path(path)}::{node.name}"
            # Keep the largest overload / nested collision if names collide.
            results[key] = max(results.get(key, 0), line_count)
    return results


def imported_domain_packages(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in DOMAIN_PACKAGES:
                    found.add(root)
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".", 1)[0]
            if root in DOMAIN_PACKAGES:
                found.add(root)
    return found


def collect_reverse_imports() -> dict[str, list[str]]:
    """Map 'src_pkg->dst_pkg' -> sorted importer relative paths."""
    grouped: dict[str, set[str]] = {}
    for path in iter_source_files():
        if path.suffix != ".py":
            continue
        src_pkg = package_of(path)
        if src_pkg is None or src_pkg not in DOMAIN_PACKAGES:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for dst_pkg in imported_domain_packages(tree):
            if src_pkg == dst_pkg:
                continue
            edge = (src_pkg, dst_pkg)
            if edge not in FORBIDDEN_EDGES:
                continue
            key = f"{src_pkg}->{dst_pkg}"
            grouped.setdefault(key, set()).add(rel_path(path))
    return {key: sorted(paths) for key, paths in sorted(grouped.items())}


def check_file_sizes(
    current: dict[str, int],
    baseline: dict[str, int],
) -> list[Finding]:
    findings: list[Finding] = []
    for path, lines in sorted(current.items()):
        baseline_lines = baseline.get(path)
        if baseline_lines is None:
            if lines > MAX_NEW_FILE_LINES:
                findings.append(
                    Finding(
                        "FILE_NEW_OVERSIZED",
                        f"new file exceeds {MAX_NEW_FILE_LINES} lines: "
                        f"{path} ({lines} lines)",
                    )
                )
            continue
        if lines > baseline_lines:
            findings.append(
                Finding(
                    "FILE_GREW",
                    f"oversized file grew: {path} "
                    f"{baseline_lines} -> {lines} lines",
                )
            )
    return findings


def check_functions(
    current: dict[str, int],
    baseline: dict[str, int],
) -> list[Finding]:
    findings: list[Finding] = []
    for key, lines in sorted(current.items()):
        baseline_lines = baseline.get(key)
        if baseline_lines is None:
            findings.append(
                Finding(
                    "FUNC_NEW_OVERSIZED",
                    f"new function exceeds {MAX_NEW_FUNCTION_LINES} lines: "
                    f"{key} ({lines} lines)",
                )
            )
            continue
        if lines > baseline_lines:
            findings.append(
                Finding(
                    "FUNC_GREW",
                    f"oversized function grew: {key} "
                    f"{baseline_lines} -> {lines} lines",
                )
            )
    return findings


def check_reverse_imports(
    current: dict[str, list[str]],
    baseline: dict[str, list[str]],
) -> list[Finding]:
    findings: list[Finding] = []
    for edge, paths in sorted(current.items()):
        allowed = set(baseline.get(edge, []))
        extras = sorted(set(paths) - allowed)
        for path in extras:
            findings.append(
                Finding(
                    "IMPORT_REVERSE_NEW",
                    f"new forbidden reverse import {edge} in {path}",
                )
            )
    return findings


def collect_package_dependency_graph() -> dict[str, set[str]]:
    """Map src_pkg -> set of imported dst_pkgs."""
    graph: dict[str, set[str]] = {pkg: set() for pkg in DOMAIN_PACKAGES}
    for path in iter_source_files():
        if path.suffix != ".py":
            continue
        src_pkg = package_of(path)
        if src_pkg is None or src_pkg not in DOMAIN_PACKAGES:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for dst_pkg in imported_domain_packages(tree):
            if src_pkg != dst_pkg and dst_pkg in DOMAIN_PACKAGES:
                graph[src_pkg].add(dst_pkg)
    return graph


def find_package_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Find all strongly connected components with >1 node using Tarjan's algorithm."""
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    sccs: list[list[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for neighbor in sorted(graph.get(node, set())):
            if neighbor not in indices:
                strongconnect(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[neighbor])

        if lowlinks[node] == indices[node]:
            component: list[str] = []
            while True:
                w = stack.pop()
                on_stack.remove(w)
                component.append(w)
                if w == node:
                    break
            if len(component) > 1:
                sccs.append(sorted(component))

    for node in sorted(graph):
        if node not in indices:
            strongconnect(node)

    return sccs


def check_package_cycles(graph: dict[str, set[str]]) -> list[Finding]:
    findings: list[Finding] = []
    for scc in find_package_cycles(graph):
        findings.append(
            Finding(
                "PACKAGE_CYCLE",
                f"strongly connected package cycle detected: {' <-> '.join(scc)}",
            )
        )
    return findings


def build_baselines() -> dict[str, object]:
    file_sizes = collect_file_sizes()
    oversized_files = {
        path: lines
        for path, lines in sorted(file_sizes.items())
        if lines > MAX_NEW_FILE_LINES
    }
    return {
        "oversized_files": {
            "max_new_file_lines": MAX_NEW_FILE_LINES,
            "files": oversized_files,
        },
        "oversized_functions": {
            "max_new_function_lines": MAX_NEW_FUNCTION_LINES,
            "functions": collect_oversized_functions(),
        },
        "reverse_imports": {
            "forbidden_edges": sorted(
                f"{src}->{dst}" for src, dst in sorted(FORBIDDEN_EDGES)
            ),
            "allowlist": collect_reverse_imports(),
        },
    }


def write_baselines() -> None:
    baselines = build_baselines()
    write_json(OVERSIZED_FILES_BASELINE, baselines["oversized_files"])
    write_json(OVERSIZED_FUNCTIONS_BASELINE, baselines["oversized_functions"])
    write_json(REVERSE_IMPORTS_BASELINE, baselines["reverse_imports"])
    print(f"Wrote {rel_path(OVERSIZED_FILES_BASELINE)}")
    print(f"Wrote {rel_path(OVERSIZED_FUNCTIONS_BASELINE)}")
    print(f"Wrote {rel_path(REVERSE_IMPORTS_BASELINE)}")


def run_checks() -> list[Finding]:
    missing = [
        path
        for path in (
            OVERSIZED_FILES_BASELINE,
            OVERSIZED_FUNCTIONS_BASELINE,
            REVERSE_IMPORTS_BASELINE,
        )
        if not path.exists()
    ]
    if missing:
        return [
            Finding(
                "BASELINE_MISSING",
                "missing baseline "
                f"{rel_path(path)}; run with --write-baselines first",
            )
            for path in missing
        ]

    file_baseline = load_json(OVERSIZED_FILES_BASELINE)["files"]
    function_baseline = load_json(OVERSIZED_FUNCTIONS_BASELINE)["functions"]
    import_baseline = load_json(REVERSE_IMPORTS_BASELINE)["allowlist"]

    current_files = {
        path: lines
        for path, lines in collect_file_sizes().items()
        if lines > MAX_NEW_FILE_LINES or path in file_baseline
    }
    findings: list[Finding] = []
    findings.extend(check_file_sizes(current_files, file_baseline))
    findings.extend(
        check_functions(collect_oversized_functions(), function_baseline)
    )
    findings.extend(
        check_reverse_imports(collect_reverse_imports(), import_baseline)
    )
    findings.extend(
        check_package_cycles(collect_package_dependency_graph())
    )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check architecture ratchets for imports and size growth."
    )
    parser.add_argument(
        "--write-baselines",
        action="store_true",
        help="Regenerate docs/architecture/baselines from the current tree.",
    )
    args = parser.parse_args()

    if args.write_baselines:
        write_baselines()
        return 0

    findings = run_checks()
    if not findings:
        print("Architecture checks passed.")
        return 0

    print(f"Architecture checks failed ({len(findings)} finding(s)):")
    for finding in findings:
        print(f"  [{finding.code}] {finding.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
