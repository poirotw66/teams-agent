#!/usr/bin/env python3
"""Phase G quarantine gate for the emergency legacy UI shell.

Product path is React ``/console-v2``. The classic SPA under
``agent_service/src/ai_ops_backoffice/static/legacy-js/`` is quarantine only:
reachable when ``BACKOFFICE_LEGACY_SHELL_ENABLED`` is truthy. Defaults and
checked deploy/env samples must keep that kill-switch off.

Deletion criteria (do not delete the tree in this gate):
  After one full release cycle where production never sets
  ``BACKOFFICE_LEGACY_SHELL_ENABLED``, remove ``static/legacy-js/``, the
  ``/legacy`` serve path, and related frontend unit imports — keeping only
  the thin ``static/js/main.js`` redirect stub if still linked.

Usage:
  uv run python scripts/check_legacy_shell.py
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = (
    REPO_ROOT
    / "agent_service"
    / "src"
    / "ai_ops_backoffice"
    / "settings.py"
)
SETTINGS_ENV_PATH = (
    REPO_ROOT
    / "agent_service"
    / "src"
    / "ai_ops_backoffice"
    / "settings_env.py"
)
LEGACY_JS_DIR = (
    REPO_ROOT
    / "agent_service"
    / "src"
    / "ai_ops_backoffice"
    / "static"
    / "legacy-js"
)
STATIC_DIR = LEGACY_JS_DIR.parent
ENV_VAR_NAME = "BACKOFFICE_LEGACY_SHELL_ENABLED"
TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})
# Product HTML outside legacy-js/ must not import the quarantine tree.
PRODUCT_HTML_ALLOWLIST_LEGACY_REFS = frozenset()
_LEGACY_JS_REF_RE = re.compile(r"/static/legacy-js/")

# Deploy / infra / env samples that must not enable the kill-switch.
SAMPLE_GLOBS = (
    ".env.example",
    "agent_service/.env.example",
    "deploy/**/*",
    "infra/**/*",
    "docker-compose*.yml",
    "**/Dockerfile*",
    "start.sh",
)

SAMPLE_SUFFIXES = frozenset(
    {
        ".yml",
        ".yaml",
        ".tf",
        ".tfvars",
        ".env",
        ".example",
        ".sh",
        ".json",
        ".toml",
        "",
    }
)

# Matches KEY=value / KEY: value / KEY = "value" style assignments.
_ASSIGNMENT_RE = re.compile(
    rf"(?P<key>{re.escape(ENV_VAR_NAME)})"
    r"(?:\s*[:=]\s*|\s+)"
    r"""(?P<value>["']?[^\s#"']+["']?)""",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    path: Path
    message: str

    def format(self) -> str:
        try:
            rel = self.path.relative_to(REPO_ROOT)
        except ValueError:
            rel = self.path
        return f"{rel}: {self.message}"


def _normalize_env_value(raw: str) -> str:
    return raw.strip().strip("\"'").lower()


def _dataclass_field_default_is_false(source: str, field_name: str) -> bool:
    """Return True when ``field_name: bool = False`` appears on BackofficeSettings."""
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "BackofficeSettings":
            continue
        for item in node.body:
            if not isinstance(item, ast.AnnAssign) or not isinstance(
                item.target, ast.Name
            ):
                continue
            if item.target.id != field_name:
                continue
            return (
                isinstance(item.value, ast.Constant) and item.value.value is False
            )
    return False


def _from_env_default_is_false(source: str) -> bool:
    """Return True when from_env uses os.environ.get(ENV, \"false\")."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "get"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "environ"
        ):
            continue
        if len(node.args) < 2:
            continue
        key_arg, default_arg = node.args[0], node.args[1]
        if not (
            isinstance(key_arg, ast.Constant)
            and key_arg.value == ENV_VAR_NAME
            and isinstance(default_arg, ast.Constant)
            and isinstance(default_arg.value, str)
        ):
            continue
        return _normalize_env_value(default_arg.value) not in TRUTHY_VALUES
    return False


def check_settings_defaults(
    settings_path: Path = SETTINGS_PATH,
    settings_env_path: Path = SETTINGS_ENV_PATH,
) -> list[Finding]:
    findings: list[Finding] = []
    if not settings_path.is_file():
        return [Finding(settings_path, "Backoffice settings module missing")]
    source = settings_path.read_text(encoding="utf-8")
    if not _dataclass_field_default_is_false(source, "legacy_shell_enabled"):
        findings.append(
            Finding(
                settings_path,
                "BackofficeSettings.legacy_shell_enabled must default to False",
            )
        )
    # Env default may live in settings.py or the extracted settings_env helper.
    env_sources = [source]
    if settings_env_path.is_file():
        env_sources.append(settings_env_path.read_text(encoding="utf-8"))
    if not any(_from_env_default_is_false(chunk) for chunk in env_sources):
        findings.append(
            Finding(
                settings_path,
                f'from_env must default {ENV_VAR_NAME} to a non-truthy value '
                f'(expected "false")',
            )
        )
    return findings


def check_quarantine_present(legacy_js_dir: Path = LEGACY_JS_DIR) -> list[Finding]:
    """Confirm quarantine tree still exists (deletion is a later release slice)."""
    if not legacy_js_dir.is_dir():
        return [
            Finding(
                legacy_js_dir,
                "expected quarantine directory missing; if intentionally deleted, "
                "retire this check and remove leftover /legacy serve wiring",
            )
        ]
    return []


def _iter_sample_files(repo_root: Path = REPO_ROOT) -> list[Path]:
    seen: set[Path] = set()
    files: list[Path] = []
    for pattern in SAMPLE_GLOBS:
        for path in repo_root.glob(pattern):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            if path.suffix.lower() not in SAMPLE_SUFFIXES and path.name not in {
                "Dockerfile",
                "start.sh",
            }:
                # Allow unsuffixed Dockerfiles matched by **/Dockerfile*
                if not path.name.startswith("Dockerfile"):
                    continue
            seen.add(resolved)
            files.append(path)
    return sorted(files, key=lambda item: item.as_posix())


def find_enabled_assignments(text: str) -> list[str]:
    """Return raw assignment values that would enable the legacy shell."""
    enabled: list[str] = []
    for match in _ASSIGNMENT_RE.finditer(text):
        value = _normalize_env_value(match.group("value"))
        if value in TRUTHY_VALUES:
            enabled.append(match.group(0).strip())
    return enabled


def check_deploy_samples(repo_root: Path = REPO_ROOT) -> list[Finding]:
    findings: list[Finding] = []
    for path in _iter_sample_files(repo_root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for snippet in find_enabled_assignments(text):
            findings.append(
                Finding(
                    path,
                    f"deploy/env sample must not enable legacy shell "
                    f"(found {snippet!r})",
                )
            )
    return findings


def check_product_html_avoids_legacy_js(
    static_dir: Path = STATIC_DIR,
) -> list[Finding]:
    """Product HTML outside the kill-switch shell must not load legacy-js."""
    findings: list[Finding] = []
    if not static_dir.is_dir():
        return findings
    for path in sorted(static_dir.rglob("*.html")):
        try:
            relative = path.relative_to(static_dir).as_posix()
        except ValueError:
            continue
        if relative.startswith("legacy-js/"):
            continue
        if path.name in PRODUCT_HTML_ALLOWLIST_LEGACY_REFS:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if _LEGACY_JS_REF_RE.search(text):
            findings.append(
                Finding(
                    path,
                    "product HTML must not import /static/legacy-js/ "
                    "(use /static/js/session_auth.js or console-v2 instead)",
                )
            )
    return findings


def run_checks(*, repo_root: Path = REPO_ROOT) -> list[Finding]:
    settings_path = (
        repo_root
        / "agent_service"
        / "src"
        / "ai_ops_backoffice"
        / "settings.py"
    )
    legacy_js_dir = (
        repo_root
        / "agent_service"
        / "src"
        / "ai_ops_backoffice"
        / "static"
        / "legacy-js"
    )
    static_dir = legacy_js_dir.parent
    findings: list[Finding] = []
    findings.extend(check_settings_defaults(settings_path))
    findings.extend(check_quarantine_present(legacy_js_dir))
    findings.extend(check_deploy_samples(repo_root))
    findings.extend(check_product_html_avoids_legacy_js(static_dir))
    return findings


def main(argv: list[str] | None = None) -> int:
    del argv  # reserved for future flags
    findings = run_checks()
    if findings:
        print("legacy shell quarantine check FAILED:", file=sys.stderr)
        for finding in findings:
            print(f"  - {finding.format()}", file=sys.stderr)
        return 1
    print(
        "legacy shell quarantine check OK: "
        f"defaults keep {ENV_VAR_NAME} disabled; "
        "deploy/env samples do not enable it; "
        "product HTML avoids /static/legacy-js/; "
        f"{LEGACY_JS_DIR.relative_to(REPO_ROOT)} remains quarantine."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
