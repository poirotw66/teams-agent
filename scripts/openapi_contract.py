"""Shared OpenAPI contract helpers for snapshots, breaking checks, and TS gen.

Canonical artifact (Phase F first slice):
  docs/architecture/baselines/openapi/ai_ops_backoffice.openapi.json

Inventory snapshots (routes/schemas) remain the lightweight CI ratchet for all
three FastAPI services. The canonical document preserves full schemas and real
operationIds for TypeScript generation and breaking-change analysis.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = REPO_ROOT / "docs" / "architecture" / "baselines" / "openapi"

# First Phase F seam: Backoffice is the Console frontend's primary HTTP surface.
CANONICAL_OPENAPI_SERVICES: tuple[str, ...] = ("ai_ops_backoffice",)

GENERATED_TS_DIR = (
    REPO_ROOT / "console_frontend" / "src" / "shared" / "api" / "generated"
)
GENERATED_TS_FILE = GENERATED_TS_DIR / "backoffice-schemas.ts"


def rel_path(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def canonical_openapi_path(service: str) -> Path:
    return SNAPSHOT_DIR / f"{service}.openapi.json"


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_openapi(document: dict[str, Any]) -> dict[str, Any]:
    """Return a stable, comparable OpenAPI document (round-trip via JSON)."""
    return json.loads(json.dumps(document, sort_keys=True, ensure_ascii=False))


def schema_ref_name(value: Any) -> str | None:
    if isinstance(value, dict) and isinstance(value.get("$ref"), str):
        ref = value["$ref"]
        if ref.startswith("#/components/schemas/"):
            return ref.rsplit("/", 1)[-1]
    return None


def _operation_map(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    operations: dict[str, dict[str, Any]] = {}
    for path, methods in (document.get("paths") or {}).items():
        if not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            if method.startswith("x-") or not isinstance(operation, dict):
                continue
            operations[f"{method.upper()} {path}"] = operation
    return operations


def _component_schemas(document: dict[str, Any]) -> dict[str, Any]:
    components = document.get("components") or {}
    schemas = components.get("schemas") if isinstance(components, dict) else {}
    return schemas if isinstance(schemas, dict) else {}


def _property_type_signature(schema: Any) -> str:
    if not isinstance(schema, dict):
        return type(schema).__name__
    ref = schema_ref_name(schema)
    if ref:
        return f"$ref:{ref}"
    if "anyOf" in schema:
        parts = [_property_type_signature(part) for part in schema["anyOf"]]
        return "anyOf[" + "|".join(parts) + "]"
    if "oneOf" in schema:
        parts = [_property_type_signature(part) for part in schema["oneOf"]]
        return "oneOf[" + "|".join(parts) + "]"
    if "allOf" in schema:
        parts = [_property_type_signature(part) for part in schema["allOf"]]
        return "allOf[" + "+".join(parts) + "]"
    if schema.get("type") == "array":
        return f"array<{_property_type_signature(schema.get('items'))}>"
    enum_values = schema.get("enum")
    if isinstance(enum_values, list):
        return f"enum:{'|'.join(str(value) for value in enum_values)}"
    type_name = schema.get("type")
    format_name = schema.get("format")
    if type_name and format_name:
        return f"{type_name}:{format_name}"
    if type_name:
        return str(type_name)
    return "object"


def find_breaking_changes(
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> list[str]:
    """Detect backward-incompatible OpenAPI deltas.

    Additive changes (new paths, new optional properties, new schemas) are not
    reported. Focus is on removals and incompatible tightenings that would break
    existing clients.
    """
    findings: list[str] = []
    baseline_ops = _operation_map(baseline)
    current_ops = _operation_map(current)

    for key in sorted(set(baseline_ops) - set(current_ops)):
        findings.append(f"removed operation {key}")

    for key in sorted(set(baseline_ops) & set(current_ops)):
        before = baseline_ops[key]
        after = current_ops[key]
        before_codes = {str(code) for code in (before.get("responses") or {})}
        after_codes = {str(code) for code in (after.get("responses") or {})}
        for code in sorted(before_codes - after_codes):
            findings.append(f"removed status {code} from {key}")

        before_id = before.get("operationId")
        after_id = after.get("operationId")
        if before_id and after_id and before_id != after_id:
            findings.append(
                f"changed operationId on {key}: {before_id!r} -> {after_id!r}"
            )

    baseline_schemas = _component_schemas(baseline)
    current_schemas = _component_schemas(current)
    for name in sorted(set(baseline_schemas) - set(current_schemas)):
        findings.append(f"removed schema {name}")

    for name in sorted(set(baseline_schemas) & set(current_schemas)):
        before = baseline_schemas[name]
        after = current_schemas[name]
        if not isinstance(before, dict) or not isinstance(after, dict):
            continue
        before_required = set(before.get("required") or [])
        after_required = set(after.get("required") or [])
        for field in sorted(after_required - before_required):
            findings.append(f"added required property {name}.{field}")

        before_props = before.get("properties") or {}
        after_props = after.get("properties") or {}
        if not isinstance(before_props, dict) or not isinstance(after_props, dict):
            continue
        for field in sorted(set(before_props) - set(after_props)):
            findings.append(f"removed property {name}.{field}")
        for field in sorted(set(before_props) & set(after_props)):
            before_sig = _property_type_signature(before_props[field])
            after_sig = _property_type_signature(after_props[field])
            if before_sig != after_sig:
                findings.append(
                    f"changed property type {name}.{field}: "
                    f"{before_sig} -> {after_sig}"
                )

    return findings
