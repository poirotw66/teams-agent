#!/usr/bin/env python3
"""Generate TypeScript schemas + client from the canonical Backoffice OpenAPI doc.

Usage (from repo root):
  PYTHONPATH=agent_service/src uv run python scripts/generate_openapi_ts.py --write
  PYTHONPATH=agent_service/src uv run python scripts/generate_openapi_ts.py --check

The generator reads:
  docs/architecture/baselines/openapi/ai_ops_backoffice.openapi.json

and writes:
  console_frontend/src/shared/api/generated/backoffice-schemas.ts
  console_frontend/src/shared/api/generated/backoffice-client.ts

Regenerate the OpenAPI document first with:
  PYTHONPATH=agent_service/src uv run python scripts/snapshot_openapi.py --write
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = str(REPO_ROOT / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from openapi_contract import (
    GENERATED_TS_CLIENT_FILE,
    GENERATED_TS_DIR,
    GENERATED_TS_FILE,
    canonical_openapi_path,
    load_json,
    rel_path,
)
from openapi_ts_client import render_client
from openapi_ts_render import ts_from_schema

CANONICAL_SERVICE = "ai_ops_backoffice"
HEADER = """\
/**
 * AUTO-GENERATED FILE. DO NOT EDIT BY HAND.
 *
 * Source: docs/architecture/baselines/openapi/ai_ops_backoffice.openapi.json
 *
 * Regenerate:
 *   PYTHONPATH=agent_service/src uv run python scripts/snapshot_openapi.py --write
 *   PYTHONPATH=agent_service/src uv run python scripts/generate_openapi_ts.py --write
 *
 * CI freshness:
 *   PYTHONPATH=agent_service/src uv run python scripts/generate_openapi_ts.py --check
 */

/* eslint-disable */
/* prettier-ignore */

"""


def render_typescript(document: dict[str, Any]) -> str:
    components = document.get("components") or {}
    schemas = components.get("schemas") if isinstance(components, dict) else {}
    if not isinstance(schemas, dict):
        schemas = {}

    chunks: list[str] = [HEADER]
    chunks.append(
        "// Component schemas from ai_ops_backoffice OpenAPI "
        f"({len(schemas)} types).\n"
    )
    chunks.append("export type BackofficeSchemas = {\n")
    for name in sorted(schemas):
        chunks.append(f"  {name}: {name};\n")
    chunks.append("};\n\n")

    for name in sorted(schemas):
        definition = schemas[name]
        body = ts_from_schema(definition, schemas)
        if body.startswith(("{", "{\n")):
            chunks.append(f"export interface {name} {body}\n\n")
        else:
            chunks.append(f"export type {name} = {body};\n\n")

    return "".join(chunks).rstrip() + "\n"


def _generated_readme() -> str:
    return (
        "# Generated API types and client\n\n"
        "TypeScript schema types and a typed HTTP client generated from the "
        "canonical Backoffice OpenAPI document.\n\n"
        "**Do not edit files in this directory by hand.**\n\n"
        "## Artifacts\n\n"
        "- `backoffice-schemas.ts` — component schema types\n"
        "- `backoffice-client.ts` — `backofficeClient` path/operation wrappers "
        "over `apiClient`\n\n"
        "## Regenerate\n\n"
        "```bash\n"
        "PYTHONPATH=agent_service/src uv run python scripts/snapshot_openapi.py --write\n"
        "PYTHONPATH=agent_service/src uv run python scripts/generate_openapi_ts.py --write\n"
        "```\n\n"
        "## CI freshness check\n\n"
        "```bash\n"
        "PYTHONPATH=agent_service/src uv run python scripts/generate_openapi_ts.py --check\n"
        "```\n\n"
        "Import example:\n\n"
        "```ts\n"
        "import { backofficeClient } from './generated/backoffice-client';\n"
        "import type { WorkItemsResponse } from './generated/backoffice-schemas';\n"
        "\n"
        "const res: WorkItemsResponse =\n"
        "  await backofficeClient.list_work_items_api_console_work_items_get({\n"
        "    query: { bucket: 'all', limit: 25 },\n"
        "  });\n"
        "```\n"
    )


def write_generated() -> None:
    canonical = canonical_openapi_path(CANONICAL_SERVICE)
    if not canonical.exists():
        raise FileNotFoundError(
            f"Missing canonical OpenAPI at {rel_path(canonical)}. "
            "Run scripts/snapshot_openapi.py --write first."
        )
    document = load_json(canonical)
    schemas_text = render_typescript(document)
    client_text = render_client(document)
    GENERATED_TS_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_TS_FILE.write_text(schemas_text, encoding="utf-8", newline="\n")
    GENERATED_TS_CLIENT_FILE.write_text(client_text, encoding="utf-8", newline="\n")
    readme = GENERATED_TS_DIR / "README.md"
    readme.write_text(_generated_readme(), encoding="utf-8", newline="\n")
    print(f"Wrote {rel_path(GENERATED_TS_FILE)}")
    print(f"Wrote {rel_path(GENERATED_TS_CLIENT_FILE)}")
    print(f"Wrote {rel_path(readme)}")


def check_generated() -> list[str]:
    canonical = canonical_openapi_path(CANONICAL_SERVICE)
    if not canonical.exists():
        return [
            (
                f"missing canonical OpenAPI {rel_path(canonical)}; "
                "run snapshot_openapi.py --write first"
            )
        ]
    errors: list[str] = []
    document = load_json(canonical)
    expected_pairs = (
        (GENERATED_TS_FILE, render_typescript(document), "generate_openapi_ts.py --write"),
        (
            GENERATED_TS_CLIENT_FILE,
            render_client(document),
            "generate_openapi_ts.py --write",
        ),
    )
    for path, expected, regenerate in expected_pairs:
        if not path.exists():
            errors.append(
                f"missing generated TypeScript {rel_path(path)}; run {regenerate} first"
            )
            continue
        actual = path.read_text(encoding="utf-8")
        if actual != expected:
            errors.append(
                f"{rel_path(path)} is out of date. "
                f"Run: PYTHONPATH=agent_service/src uv run python "
                f"scripts/{regenerate}"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate or verify TypeScript schemas and client from canonical OpenAPI."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="Write generated types.")
    mode.add_argument("--check", action="store_true", help="Verify generated types.")
    args = parser.parse_args()

    if args.write:
        write_generated()
        return 0

    errors = check_generated()
    if not errors:
        print(
            "Generated OpenAPI TypeScript is up to date "
            f"({rel_path(GENERATED_TS_FILE)}, {rel_path(GENERATED_TS_CLIENT_FILE)})."
        )
        return 0
    print("Generated OpenAPI TypeScript check failed:")
    for error in errors:
        print(f"  {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
