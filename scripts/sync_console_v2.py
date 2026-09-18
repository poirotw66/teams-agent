#!/usr/bin/env python3
"""Build or verify the production console-v2 static bundle.

The React app lives in ``console_frontend/``. Vite writes the production
bundle to:

  agent_service/src/ai_ops_backoffice/static/console-v2/

That directory is the artifact served by the Backoffice ASGI app and baked
into ``Dockerfile.backoffice``. Do not edit it by hand.

Usage (from repo root):

  python3 scripts/sync_console_v2.py --write
  python3 scripts/sync_console_v2.py --check

``--write`` runs ``npm run build`` so hashed assets land in the canonical
static directory. ``--check`` builds into a temporary directory and compares
file paths plus SHA-256 digests against the committed bundle (no mutation).

CI runs ``--check`` after ``npm ci`` in the console-frontend job.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONSOLE_FRONTEND = REPO_ROOT / "console_frontend"
STATIC_CONSOLE_V2 = (
    REPO_ROOT
    / "agent_service"
    / "src"
    / "ai_ops_backoffice"
    / "static"
    / "console-v2"
)

NPM_TIMEOUT_SECONDS = 600


def rel_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory_files(root: Path) -> dict[str, str]:
    """Return relative POSIX paths mapped to SHA-256 digests."""
    if not root.is_dir():
        raise FileNotFoundError(f"missing directory: {rel_path(root)}")
    inventory: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        inventory[relative] = file_digest(path)
    return inventory


def compare_inventories(
    *,
    expected: dict[str, str],
    actual: dict[str, str],
    expected_label: str,
    actual_label: str,
) -> list[str]:
    """Return human-readable drift messages; empty means match."""
    errors: list[str] = []
    expected_keys = set(expected)
    actual_keys = set(actual)

    missing = sorted(expected_keys - actual_keys)
    extra = sorted(actual_keys - expected_keys)
    for relative in missing:
        errors.append(f"missing in {actual_label}: {relative}")
    for relative in extra:
        errors.append(f"extra in {actual_label} (not in {expected_label}): {relative}")

    for relative in sorted(expected_keys & actual_keys):
        if expected[relative] != actual[relative]:
            errors.append(
                f"content mismatch: {relative} "
                f"({expected_label}={expected[relative][:12]}… "
                f"{actual_label}={actual[relative][:12]}…)"
            )
    return errors


def _npm_env() -> dict[str, str]:
    env = os.environ.copy()
    # Keep CI/local builds deterministic for content-hashed assets.
    env.setdefault("NODE_ENV", "production")
    return env


def ensure_dependencies(*, force_install: bool) -> None:
    lockfile = CONSOLE_FRONTEND / "package-lock.json"
    if not lockfile.is_file():
        raise FileNotFoundError(
            f"missing {rel_path(lockfile)}; cannot install console_frontend deps"
        )
    node_modules = CONSOLE_FRONTEND / "node_modules"
    if force_install or not node_modules.is_dir():
        print(f"Running npm ci in {rel_path(CONSOLE_FRONTEND)}…", flush=True)
        subprocess.run(
            ["npm", "ci"],
            cwd=CONSOLE_FRONTEND,
            check=True,
            env=_npm_env(),
            timeout=NPM_TIMEOUT_SECONDS,
        )


def build_bundle(*, out_dir: Path | None = None) -> None:
    """Typecheck and Vite-build; default outDir comes from vite.config.ts."""
    if not CONSOLE_FRONTEND.is_dir():
        raise FileNotFoundError(f"missing {rel_path(CONSOLE_FRONTEND)}")

    if out_dir is None:
        print(f"Building console_frontend → {rel_path(STATIC_CONSOLE_V2)}…", flush=True)
        command = ["npm", "run", "build"]
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"Building console_frontend → {out_dir}…", flush=True)
        # Append Vite flags after `--` so `tsc && vite build` receives them.
        command = [
            "npm",
            "run",
            "build",
            "--",
            "--outDir",
            str(out_dir),
            "--emptyOutDir",
        ]

    subprocess.run(
        command,
        cwd=CONSOLE_FRONTEND,
        check=True,
        env=_npm_env(),
        timeout=NPM_TIMEOUT_SECONDS,
    )


def write_bundle(*, force_install: bool) -> None:
    ensure_dependencies(force_install=force_install)
    build_bundle(out_dir=None)
    if not STATIC_CONSOLE_V2.is_dir():
        raise RuntimeError(
            f"build finished but {rel_path(STATIC_CONSOLE_V2)} is missing"
        )
    inventory = inventory_files(STATIC_CONSOLE_V2)
    print(
        f"Wrote {len(inventory)} file(s) under {rel_path(STATIC_CONSOLE_V2)}. "
        "Commit the updated static assets when sources change."
    )


def check_bundle(*, force_install: bool) -> list[str]:
    if not STATIC_CONSOLE_V2.is_dir():
        return [
            (
                f"missing committed bundle {rel_path(STATIC_CONSOLE_V2)}; "
                "run: python3 scripts/sync_console_v2.py --write"
            )
        ]

    ensure_dependencies(force_install=force_install)
    with tempfile.TemporaryDirectory(prefix="console-v2-check-") as tmp:
        rebuild_dir = Path(tmp) / "console-v2"
        build_bundle(out_dir=rebuild_dir)
        committed = inventory_files(STATIC_CONSOLE_V2)
        rebuilt = inventory_files(rebuild_dir)
        return compare_inventories(
            expected=rebuilt,
            actual=committed,
            expected_label="rebuild",
            actual_label="committed",
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build or verify the console-v2 production bundle under "
            "ai_ops_backoffice/static/console-v2."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--write",
        action="store_true",
        help="Build into the committed static/console-v2 directory.",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="Rebuild to a temp dir and compare with the committed bundle.",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Force npm ci before build (default: install only if node_modules missing).",
    )
    args = parser.parse_args()

    try:
        if args.write:
            write_bundle(force_install=args.install)
            return 0

        errors = check_bundle(force_install=args.install)
    except (OSError, subprocess.CalledProcessError, RuntimeError) as error:
        print(f"console-v2 sync failed: {error}", file=sys.stderr)
        return 1

    if not errors:
        print(
            f"Committed console-v2 bundle matches rebuild "
            f"({rel_path(STATIC_CONSOLE_V2)})."
        )
        return 0

    print("console-v2 bundle freshness check failed:")
    for error in errors:
        print(f"  {error}")
    print(
        "Regenerate with: python3 scripts/sync_console_v2.py --write\n"
        "Then commit agent_service/src/ai_ops_backoffice/static/console-v2/."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
