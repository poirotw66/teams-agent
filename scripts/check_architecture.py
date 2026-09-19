#!/usr/bin/env python3
"""Architecture ratchet for domain imports, file size, and function size.

Wave 0 stop-the-bleeding gate from docs/project-architecture-refactor-plan-20260918.md.
Phase C adds monotonic shrink (auto-tighten baselines) and ownership importer-count
ratchets.

Usage:
  uv run python scripts/check_architecture.py
  uv run python scripts/check_architecture.py --write-baselines

Shrinks auto-tighten baselines during a normal check (no --write-baselines needed).
Commit the rewritten JSON when BASELINE_TIGHTENED / IMPORTER_COUNT_TIGHTENED appears.
--write-baselines still regenerates all baselines from the current tree.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_DIR = REPO_ROOT / "docs" / "architecture" / "baselines"
OVERSIZED_FILES_BASELINE = BASELINE_DIR / "oversized_files.json"
OVERSIZED_FUNCTIONS_BASELINE = BASELINE_DIR / "oversized_functions.json"
REVERSE_IMPORTS_BASELINE = BASELINE_DIR / "reverse_imports.json"
IMPORTER_COUNTS_BASELINE = BASELINE_DIR / "importer_counts.json"
PRIVATE_ACCESS_BASELINE = BASELINE_DIR / "private_access.json"

# HTTP routers must not open files directly; I/O belongs in adapters/services.
ROUTER_FS_IO_RE = re.compile(
    r"(?:\.open|\.read_text|\.write_text|\.read_bytes|\.write_bytes)\s*\("
)
ROUTER_DIR_NAMES = frozenset({"routers", "routes"})

PACKAGE_ROOTS: dict[str, Path] = {
    "agent_service": REPO_ROOT / "agent_service" / "src" / "agent_service",
    "ai_ops_backoffice": REPO_ROOT / "agent_service" / "src" / "ai_ops_backoffice",
    "knowledge_portal": REPO_ROOT / "agent_service" / "src" / "knowledge_portal",
    "platform_kernel": REPO_ROOT / "agent_service" / "src" / "platform_kernel",
    "operations_core": REPO_ROOT / "agent_service" / "src" / "operations_core",
    "knowledge_core": REPO_ROOT / "agent_service" / "src" / "knowledge_core",
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
        "operations_core",
        "knowledge_core",
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
        ("platform_kernel", "operations_core"),
        ("platform_kernel", "knowledge_core"),
        ("operations_core", "agent_service"),
        ("operations_core", "ai_ops_backoffice"),
        ("operations_core", "knowledge_portal"),
        ("operations_core", "composition"),
        ("operations_core", "teams_agent"),
        ("operations_core", "platform_kernel"),
        ("operations_core", "knowledge_core"),
        ("knowledge_core", "agent_service"),
        ("knowledge_core", "ai_ops_backoffice"),
        ("knowledge_core", "knowledge_portal"),
        ("knowledge_core", "composition"),
        ("knowledge_core", "teams_agent"),
        ("teams_agent", "agent_service"),
        ("teams_agent", "ai_ops_backoffice"),
        ("teams_agent", "knowledge_portal"),
        ("teams_agent", "platform_kernel"),
        ("teams_agent", "composition"),
        ("teams_agent", "operations_core"),
        ("teams_agent", "knowledge_core"),
    }
)

# Allowed ownership edges that must not grow (importer-file count ratchet).
OWNERSHIP_IMPORT_EDGES = frozenset(
    {
        ("ai_ops_backoffice", "agent_service"),
        ("knowledge_portal", "agent_service"),
    }
)

MAX_NEW_FILE_LINES = 500
MAX_NEW_FUNCTION_LINES = 80
SOURCE_SUFFIXES = frozenset({".py", ".ts", ".tsx"})
EXCLUDED_DIR_NAMES = frozenset(
    {
        "__pycache__",
        "static",
        "node_modules",
        "dist",
        "build",
        ".vite",
        # OpenAPI/codegen output (freshness gated by generate_openapi_ts.py).
        "generated",
    }
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


def collect_importer_counts() -> dict[str, int]:
    """Count distinct importer files per ownership edge."""
    grouped: dict[str, set[str]] = {
        f"{src}->{dst}": set() for src, dst in sorted(OWNERSHIP_IMPORT_EDGES)
    }
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
            if edge not in OWNERSHIP_IMPORT_EDGES:
                continue
            key = f"{src_pkg}->{dst_pkg}"
            grouped[key].add(rel_path(path))
    return {key: len(paths) for key, paths in sorted(grouped.items())}


def tighten_size_baseline(
    baseline: dict[str, int],
    current: dict[str, int],
    *,
    max_lines: int,
) -> dict[str, int]:
    """Return baseline capped by current sizes; drop entries that fell to <= max_lines or disappeared."""
    tightened: dict[str, int] = {}
    for path, baseline_lines in sorted(baseline.items()):
        if path not in current:
            continue
        current_lines = current[path]
        if current_lines <= max_lines:
            continue
        tightened[path] = min(baseline_lines, current_lines)
    return tightened


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


def check_importer_counts(
    current: dict[str, int],
    baseline: dict[str, int],
) -> list[Finding]:
    findings: list[Finding] = []
    for edge, count in sorted(current.items()):
        baseline_count = baseline.get(edge, 0)
        if count > baseline_count:
            findings.append(
                Finding(
                    "IMPORTER_COUNT_GREW",
                    f"ownership importer count grew for {edge}: "
                    f"{baseline_count} -> {count}",
                )
            )
    return findings


def tighten_importer_counts(
    baseline: dict[str, int],
    current: dict[str, int],
) -> dict[str, int]:
    """Return ownership-edge counts capped by current; initialize missing edges."""
    tightened: dict[str, int] = {}
    for src, dst in sorted(OWNERSHIP_IMPORT_EDGES):
        key = f"{src}->{dst}"
        current_count = current.get(key, 0)
        if key in baseline:
            tightened[key] = min(baseline[key], current_count)
        else:
            tightened[key] = current_count
    return tightened


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


_PRIVATE_ACCESS_ROOTS: tuple[Path, ...] = (
    REPO_ROOT / "agent_service" / "src" / "ai_ops_backoffice" / "routers",
    REPO_ROOT / "agent_service" / "src" / "ai_ops_backoffice" / "bootstrap",
    REPO_ROOT / "agent_service" / "src" / "ai_ops_backoffice" / "services",
    REPO_ROOT / "agent_service" / "src" / "ai_ops_backoffice" / "application",
    REPO_ROOT / "agent_service" / "src" / "ai_ops_backoffice" / "governance_domain",
)
_ALLOWED_PRIVATE_BASES = frozenset({"self", "cls"})


def is_private_access_path_excluded(path: Path) -> bool:
    """Exclude generated dirs and governance eval harness (intentional private digs)."""
    if is_excluded(path):
        return True
    return "governance_domain" in path.parts and path.name.startswith("eval_")


def _attribute_expr(node: ast.AST) -> str | None:
    """Reconstruct a dotted attribute expression from Name/Attribute nodes."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _attribute_expr(node.value)
        if parent is None:
            return None
        return f"{parent}.{node.attr}"
    return None


def is_cross_module_private_attr(node: ast.Attribute) -> bool:
    """True when node loads a single-underscore private attr on a non-self/cls base."""
    if not node.attr.startswith("_") or node.attr.startswith("__"):
        return False
    return not (
        isinstance(node.value, ast.Name) and node.value.id in _ALLOWED_PRIVATE_BASES
    )


def collect_cross_module_private_access(
    source: str,
    *,
    filename: str = "<memory>",
) -> list[tuple[int, str]]:
    """Return (lineno, expr) for cross-module private attribute loads in source."""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return []
    findings: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if not is_cross_module_private_attr(node):
            continue
        expr = _attribute_expr(node)
        if expr is None:
            continue
        findings.append((node.lineno, expr))
    return findings


def private_access_finding_key(path: Path, lineno: int, expr: str) -> str:
    return f"{rel_path(path)}:{lineno}: {expr}"


def collect_private_access_keys() -> list[str]:
    """Return sorted finding keys for current private-access violations."""
    keys: list[str] = []
    for root in _PRIVATE_ACCESS_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if is_private_access_path_excluded(path):
                continue
            text = path.read_text(encoding="utf-8")
            for lineno, expr in collect_cross_module_private_access(
                text, filename=str(path)
            ):
                keys.append(private_access_finding_key(path, lineno, expr))
    return sorted(keys)


def tighten_private_access_allowlist(
    baseline: list[str],
    current: list[str],
) -> list[str]:
    """Return allowlist capped to entries still present in current findings."""
    current_set = set(current)
    return sorted(entry for entry in baseline if entry in current_set)


def check_cross_module_private_access(
    allowlist: list[str] | None = None,
) -> list[Finding]:
    """Fail on non-allowlisted cross-module private attribute access."""
    allowed = set(allowlist or [])
    findings: list[Finding] = []
    for key in collect_private_access_keys():
        if key in allowed:
            continue
        findings.append(Finding("CROSS_MODULE_PRIVATE_ACCESS", key))
    return findings


def _is_router_module(path: Path) -> bool:
    return any(part in ROUTER_DIR_NAMES for part in path.parts)


def check_router_filesystem_io() -> list[Finding]:
    """Fail when HTTP router modules open files directly."""
    findings: list[Finding] = []
    for path in iter_source_files():
        if path.suffix != ".py" or not _is_router_module(path):
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if ROUTER_FS_IO_RE.search(line):
                findings.append(
                    Finding(
                        "ROUTER_FILESYSTEM_IO",
                        f"{rel_path(path)}:{lineno}: router must not open files "
                        f"directly ({stripped.strip()})",
                    )
                )
    return findings


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
        "importer_counts": {
            "edges": collect_importer_counts(),
        },
        "private_access": {
            "allowlist": collect_private_access_keys(),
        },
    }


def write_baselines() -> None:
    baselines = build_baselines()
    write_json(OVERSIZED_FILES_BASELINE, baselines["oversized_files"])
    write_json(OVERSIZED_FUNCTIONS_BASELINE, baselines["oversized_functions"])
    write_json(REVERSE_IMPORTS_BASELINE, baselines["reverse_imports"])
    write_json(IMPORTER_COUNTS_BASELINE, baselines["importer_counts"])
    write_json(PRIVATE_ACCESS_BASELINE, baselines["private_access"])
    print(f"Wrote {rel_path(OVERSIZED_FILES_BASELINE)}")
    print(f"Wrote {rel_path(OVERSIZED_FUNCTIONS_BASELINE)}")
    print(f"Wrote {rel_path(REVERSE_IMPORTS_BASELINE)}")
    print(f"Wrote {rel_path(IMPORTER_COUNTS_BASELINE)}")
    print(f"Wrote {rel_path(PRIVATE_ACCESS_BASELINE)}")


def _count_reduced_caps(
    stored: dict[str, int],
    tightened: dict[str, int],
) -> int:
    reduced = 0
    for key, stored_value in stored.items():
        if key not in tightened:
            reduced += 1
            continue
        if tightened[key] < stored_value:
            reduced += 1
    return reduced


def _apply_size_baseline_tighten(
    *,
    baseline_path: Path,
    envelope_key: str,
    size_key: str,
    stored: dict[str, int],
    current: dict[str, int],
    max_lines: int,
) -> Finding | None:
    tightened = tighten_size_baseline(stored, current, max_lines=max_lines)
    if tightened == stored:
        return None
    payload = load_json(baseline_path)
    payload[size_key] = tightened
    if envelope_key not in payload:
        payload[envelope_key] = max_lines
    write_json(baseline_path, payload)
    reduced = _count_reduced_caps(stored, tightened)
    return Finding(
        "BASELINE_TIGHTENED",
        f"tightened {rel_path(baseline_path)}: {reduced} cap(s) reduced or removed; "
        "commit the updated JSON",
    )


def _apply_importer_count_tighten(
    stored: dict[str, int],
    current: dict[str, int],
) -> Finding | None:
    tightened = tighten_importer_counts(stored, current)
    if tightened == stored:
        return None
    write_json(IMPORTER_COUNTS_BASELINE, {"edges": tightened})
    reduced = _count_reduced_caps(stored, tightened)
    initialized = sorted(set(tightened) - set(stored))
    detail = (
        f"initialized edges {initialized}"
        if initialized and not stored
        else f"{reduced} edge cap(s) reduced"
    )
    return Finding(
        "IMPORTER_COUNT_TIGHTENED",
        f"tightened {rel_path(IMPORTER_COUNTS_BASELINE)}: {detail}; "
        "commit the updated JSON",
    )


def _apply_private_access_tighten(
    stored: list[str],
    current: list[str],
) -> Finding | None:
    tightened = tighten_private_access_allowlist(stored, current)
    if tightened == stored:
        return None
    write_json(PRIVATE_ACCESS_BASELINE, {"allowlist": tightened})
    removed = len(stored) - len(tightened)
    return Finding(
        "PRIVATE_ACCESS_TIGHTENED",
        f"tightened {rel_path(PRIVATE_ACCESS_BASELINE)}: "
        f"{removed} allowlist entr{'y' if removed == 1 else 'ies'} removed; "
        "commit the updated JSON",
    )


def run_checks() -> list[Finding]:
    missing = [
        path
        for path in (
            OVERSIZED_FILES_BASELINE,
            OVERSIZED_FUNCTIONS_BASELINE,
            REVERSE_IMPORTS_BASELINE,
            PRIVATE_ACCESS_BASELINE,
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

    file_payload = load_json(OVERSIZED_FILES_BASELINE)
    function_payload = load_json(OVERSIZED_FUNCTIONS_BASELINE)
    file_baseline = file_payload["files"]
    function_baseline = function_payload["functions"]
    import_baseline = load_json(REVERSE_IMPORTS_BASELINE)["allowlist"]
    private_access_baseline = list(
        load_json(PRIVATE_ACCESS_BASELINE).get("allowlist", [])
    )

    all_file_sizes = collect_file_sizes()
    current_files = {
        path: lines
        for path, lines in all_file_sizes.items()
        if lines > MAX_NEW_FILE_LINES or path in file_baseline
    }
    current_functions = collect_oversized_functions()
    current_importer_counts = collect_importer_counts()
    current_private_access = collect_private_access_keys()

    findings: list[Finding] = []
    findings.extend(check_file_sizes(current_files, file_baseline))
    findings.extend(check_functions(current_functions, function_baseline))
    findings.extend(
        check_reverse_imports(collect_reverse_imports(), import_baseline)
    )
    findings.extend(check_package_cycles(collect_package_dependency_graph()))
    findings.extend(check_cross_module_private_access(private_access_baseline))
    findings.extend(check_router_filesystem_io())

    if IMPORTER_COUNTS_BASELINE.exists():
        importer_baseline = load_json(IMPORTER_COUNTS_BASELINE).get("edges", {})
        findings.extend(
            check_importer_counts(current_importer_counts, importer_baseline)
        )
    else:
        importer_baseline = {}

    file_finding = _apply_size_baseline_tighten(
        baseline_path=OVERSIZED_FILES_BASELINE,
        envelope_key="max_new_file_lines",
        size_key="files",
        stored=file_baseline,
        current=all_file_sizes,
        max_lines=MAX_NEW_FILE_LINES,
    )
    if file_finding is not None:
        findings.append(file_finding)

    function_finding = _apply_size_baseline_tighten(
        baseline_path=OVERSIZED_FUNCTIONS_BASELINE,
        envelope_key="max_new_function_lines",
        size_key="functions",
        stored=function_baseline,
        current=current_functions,
        max_lines=MAX_NEW_FUNCTION_LINES,
    )
    if function_finding is not None:
        findings.append(function_finding)

    importer_finding = _apply_importer_count_tighten(
        importer_baseline,
        current_importer_counts,
    )
    if importer_finding is not None:
        findings.append(importer_finding)

    private_finding = _apply_private_access_tighten(
        private_access_baseline,
        current_private_access,
    )
    if private_finding is not None:
        findings.append(private_finding)

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check architecture ratchets for imports and size growth."
    )
    parser.add_argument(
        "--write-baselines",
        action="store_true",
        help=(
            "Regenerate docs/architecture/baselines from the current tree. "
            "Shrinks also auto-tighten during a normal check."
        ),
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
