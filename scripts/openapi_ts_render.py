"""Shared OpenAPI → TypeScript schema rendering helpers."""

from __future__ import annotations

from typing import Any

from openapi_contract import schema_ref_name


def quote_prop(name: str) -> str:
    if name.isidentifier():
        return name
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def json_string_literal(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return f"'{escaped}'"


def ts_from_schema(schema: Any, schemas: dict[str, Any], depth: int = 0) -> str:
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
            ts_from_schema(part, schemas, depth + 1)
            for part in schema[key]
            if isinstance(part, dict)
        ]
        unique: list[str] = []
        for part in parts:
            if part not in unique:
                unique.append(part)
        return " | ".join(unique) if unique else "unknown"

    if "allOf" in schema:
        parts = [
            ts_from_schema(part, schemas, depth + 1)
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
        item_type = ts_from_schema(schema.get("items"), schemas, depth + 1)
        return f"Array<{item_type}>"

    if schema_type == "object" or "properties" in schema:
        properties = schema.get("properties") or {}
        if not isinstance(properties, dict) or not properties:
            additional = schema.get("additionalProperties")
            if additional is True:
                return "Record<string, unknown>"
            if isinstance(additional, dict):
                value_type = ts_from_schema(additional, schemas, depth + 1)
                return f"Record<string, {value_type}>"
            return "Record<string, unknown>"

        required = set(schema.get("required") or [])
        lines = ["{"]
        for prop_name, prop_schema in properties.items():
            optional = "" if prop_name in required else "?"
            prop_type = ts_from_schema(prop_schema, schemas, depth + 1)
            lines.append(f"  {quote_prop(str(prop_name))}{optional}: {prop_type};")
        lines.append("}")
        return "\n".join(lines)

    if schema.get("additionalProperties") is True:
        return "Record<string, unknown>"

    return "unknown"


def collect_schema_refs(schema: Any, out: set[str]) -> None:
    """Collect component schema names referenced via $ref."""
    if not isinstance(schema, dict):
        return
    ref = schema_ref_name(schema)
    if ref:
        out.add(ref)
        return
    for key in ("anyOf", "oneOf", "allOf"):
        for part in schema.get(key) or []:
            collect_schema_refs(part, out)
    if "items" in schema:
        collect_schema_refs(schema.get("items"), out)
    additional = schema.get("additionalProperties")
    if isinstance(additional, dict):
        collect_schema_refs(additional, out)
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for prop_schema in properties.values():
            collect_schema_refs(prop_schema, out)
