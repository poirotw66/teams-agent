#!/usr/bin/env python3
"""Generate TypeScript schema types from the canonical Backoffice OpenAPI doc.

Usage (from repo root):
  PYTHONPATH=agent_service/src uv run python scripts/generate_openapi_ts.py --write
  PYTHONPATH=agent_service/src uv run python scripts/generate_openapi_ts.py --check

The generator reads:
  docs/architecture/baselines/openapi/ai_ops_backoffice.openapi.json

and writes:
  console_frontend/src/shared/api/generated/backoffice-schemas.ts

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
    GENERATED_TS_DIR,
    GENERATED_TS_FILE,
    canonical_openapi_path,
    load_json,
    rel_path,
    schema_ref_name,
)

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


def _quote_prop(name: str) -> str:
    if name.isidentifier():
        return name
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _ts_from_schema(schema: Any, schemas: dict[str, Any], depth: int = 0) -> str:
    if depth > 12:
        return "unknown"
    if not isinstance(schema, dict):
        return "unknown"

    ref = schema_ref_name(schema)
    if ref:
        return ref

    if "enum" in schema and isinstance(schema["enum"], list):
        literals = []
        for value in schema["enum"]:
            if isinstance(value, str):
                literals.append(json_string_literal(value))
            elif isinstance(value, bool):
                literals.append("true" if value else "false")
            elif value is None:
                literals.append("null")
            else:
                literals.append(str(value))
        return " | ".join(literals) if literals else "unknown"

    if "anyOf" in schema or "oneOf" in schema:
        key = "anyOf" if "anyOf" in schema else "oneOf"
        parts = [
            _ts_from_schema(part, schemas, depth + 1)
            for part in schema[key]
            if isinstance(part, dict)
        ]
        # Collapse `T | null` style unions.
        unique: list[str] = []
        for part in parts:
            if part not in unique:
                unique.append(part)
        return " | ".join(unique) if unique else "unknown"

    if "allOf" in schema:
        parts = [
            _ts_from_schema(part, schemas, depth + 1)
            for part in schema["allOf"]
            if isinstance(part, dict)
        ]
        return " & ".join(parts) if parts else "unknown"

    schema_type = schema.get("type")
    if schema_type == "string":
        return "string"
    if schema_type == "integer" or schema_type == "number":
        return "number"
    if schema_type == "boolean":
        return "boolean"
    if schema_type == "null":
        return "null"
    if schema_type == "array":
        item_type = _ts_from_schema(schema.get("items"), schemas, depth + 1)
        return f"Array<{item_type}>"

    if schema_type == "object" or "properties" in schema:
        properties = schema.get("properties") or {}
        if not isinstance(properties, dict) or not properties:
            additional = schema.get("additionalProperties")
            if additional is True:
                return "Record<string, unknown>"
            if isinstance(additional, dict):
                value_type = _ts_from_schema(additional, schemas, depth + 1)
                return f"Record<string, {value_type}>"
            return "Record<string, unknown>"

        required = set(schema.get("required") or [])
        lines = ["{"]
        for prop_name, prop_schema in properties.items():
            optional = "" if prop_name in required else "?"
            prop_type = _ts_from_schema(prop_schema, schemas, depth + 1)
            lines.append(
                f"  {_quote_prop(str(prop_name))}{optional}: {prop_type};"
            )
        lines.append("}")
        return "\n".join(lines)

    if schema.get("additionalProperties") is True:
        return "Record<string, unknown>"

    return "unknown"


def json_string_literal(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return f"'{escaped}'"


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
        body = _ts_from_schema(definition, schemas)
        if body.startswith(("{", "{\n")):
            chunks.append(f"export interface {name} {body}\n\n")
        else:
            chunks.append(f"export type {name} = {body};\n\n")

    return "".join(chunks).rstrip() + "\n"


def write_generated() -> None:
    canonical = canonical_openapi_path(CANONICAL_SERVICE)
    if not canonical.exists():
        raise FileNotFoundError(
            f"Missing canonical OpenAPI at {rel_path(canonical)}. "
            "Run scripts/snapshot_openapi.py --write first."
        )
    document = load_json(canonical)
    text = render_typescript(document)
    GENERATED_TS_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_TS_FILE.write_text(text, encoding="utf-8", newline="\n")
    readme = GENERATED_TS_DIR / "README.md"
    readme.write_text(
        "# Generated API types\n\n"
        "TypeScript schema types generated from the canonical Backoffice "
        "OpenAPI document.\n\n"
        "**Do not edit files in this directory by hand.**\n\n"
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
        "import type { WorkItemsResponse } from './generated/backoffice-schemas';\n"
        "```\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Wrote {rel_path(GENERATED_TS_FILE)}")
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
    if not GENERATED_TS_FILE.exists():
        return [
            (
                f"missing generated TypeScript {rel_path(GENERATED_TS_FILE)}; "
                "run generate_openapi_ts.py --write first"
            )
        ]
    expected = render_typescript(load_json(canonical))
    actual = GENERATED_TS_FILE.read_text(encoding="utf-8")
    if actual != expected:
        return [
            (
                f"{rel_path(GENERATED_TS_FILE)} is out of date. "
                "Run: PYTHONPATH=agent_service/src uv run python "
                "scripts/generate_openapi_ts.py --write"
            )
        ]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate or verify TypeScript types from canonical OpenAPI."
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
        print(f"Generated OpenAPI TypeScript is up to date ({rel_path(GENERATED_TS_FILE)}).")
        return 0
    print("Generated OpenAPI TypeScript check failed:")
    for error in errors:
        print(f"  {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
