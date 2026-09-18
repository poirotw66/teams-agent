"""Render a typed TypeScript fetch client from Backoffice OpenAPI."""

from __future__ import annotations

from typing import Any

from openapi_ts_render import collect_schema_refs, quote_prop, ts_from_schema

HTTP_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options"}
)
SUCCESS_STATUS_CODES = ("200", "201", "202", "204")

CLIENT_HEADER = """\
/**
 * AUTO-GENERATED FILE. DO NOT EDIT BY HAND.
 *
 * Typed Backoffice HTTP client generated from the canonical OpenAPI document.
 * Auth headers are injected by apiClient; operation header parameters are omitted.
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

import { apiClient } from '../client';
"""


def _component_schemas(document: dict[str, Any]) -> dict[str, Any]:
    components = document.get("components") or {}
    schemas = components.get("schemas") if isinstance(components, dict) else {}
    return schemas if isinstance(schemas, dict) else {}


def _iter_operations(
    document: dict[str, Any],
) -> list[tuple[str, str, dict[str, Any]]]:
    operations: list[tuple[str, str, dict[str, Any]]] = []
    for path, methods in (document.get("paths") or {}).items():
        if not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            operations.append((path, method.upper(), operation))
    operations.sort(key=lambda item: (item[2].get("operationId") or "", item[0], item[1]))
    return operations


def _media_schema(content: Any) -> tuple[str | None, Any]:
    if not isinstance(content, dict) or not content:
        return None, None
    for media_type in ("application/json", "multipart/form-data", "application/octet-stream"):
        if media_type in content:
            media = content[media_type]
            schema = media.get("schema") if isinstance(media, dict) else None
            return media_type, schema
    media_type, media = next(iter(content.items()))
    schema = media.get("schema") if isinstance(media, dict) else None
    return str(media_type), schema


def _success_response(operation: dict[str, Any]) -> tuple[str | None, Any]:
    responses = operation.get("responses") or {}
    if not isinstance(responses, dict):
        return None, None
    for code in SUCCESS_STATUS_CODES:
        if code not in responses:
            continue
        response = responses[code]
        if not isinstance(response, dict):
            return code, None
        content = response.get("content")
        if not content:
            return code, None
        _media_type, schema = _media_schema(content)
        return code, schema
    return None, None


def _request_body(operation: dict[str, Any]) -> tuple[bool, str | None, Any]:
    body = operation.get("requestBody")
    if not isinstance(body, dict):
        return False, None, None
    required = bool(body.get("required"))
    media_type, schema = _media_schema(body.get("content"))
    return required, media_type, schema


def _split_parameters(
    operation: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    path_params: list[dict[str, Any]] = []
    query_params: list[dict[str, Any]] = []
    for parameter in operation.get("parameters") or []:
        if not isinstance(parameter, dict):
            continue
        location = parameter.get("in")
        if location == "path":
            path_params.append(parameter)
        elif location == "query":
            query_params.append(parameter)
        # Header/cookie params are intentionally omitted (apiClient injects auth).
    return path_params, query_params


def _params_object_type(
    parameters: list[dict[str, Any]],
    schemas: dict[str, Any],
) -> str | None:
    if not parameters:
        return None
    lines = ["{"]
    for parameter in parameters:
        name = str(parameter.get("name") or "param")
        required = bool(parameter.get("required"))
        optional = "" if required else "?"
        schema = parameter.get("schema") or {"type": "string"}
        prop_type = ts_from_schema(schema, schemas)
        lines.append(f"  {quote_prop(name)}{optional}: {prop_type};")
    lines.append("}")
    return "\n".join(lines)


def _operation_method_name(operation: dict[str, Any], method: str, path: str) -> str:
    operation_id = operation.get("operationId")
    if isinstance(operation_id, str) and operation_id.isidentifier():
        return operation_id
    if isinstance(operation_id, str):
        cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in operation_id)
        if cleaned and cleaned[0].isdigit():
            cleaned = f"op_{cleaned}"
        if cleaned.isidentifier():
            return cleaned
    slug = "".join(ch if ch.isalnum() else "_" for ch in f"{method}_{path}")
    return f"op_{slug}"


def _return_type(schema: Any, schemas: dict[str, Any], status: str | None) -> str:
    if status == "204" or schema is None:
        return "void"
    return ts_from_schema(schema, schemas)


def _inline_type_for_args(type_expr: str, *, indent: int = 2) -> str:
    """Indent a multi-line object type used inside an args interface."""
    if "\n" not in type_expr:
        return type_expr
    pad = " " * indent
    return "\n".join(
        line if index == 0 else f"{pad}{line}"
        for index, line in enumerate(type_expr.splitlines())
    )


def render_client(document: dict[str, Any]) -> str:
    schemas = _component_schemas(document)
    operations = _iter_operations(document)
    referenced: set[str] = set()

    method_chunks: list[str] = []
    for path, method, operation in operations:
        path_params, query_params = _split_parameters(operation)
        body_required, media_type, body_schema = _request_body(operation)
        status, response_schema = _success_response(operation)

        for parameter in path_params + query_params:
            collect_schema_refs(parameter.get("schema"), referenced)
        collect_schema_refs(body_schema, referenced)
        collect_schema_refs(response_schema, referenced)

        method_name = _operation_method_name(operation, method, path)
        return_type = _return_type(response_schema, schemas, status)

        path_type = _params_object_type(path_params, schemas)
        query_type = _params_object_type(query_params, schemas)

        args_fields: list[str] = []
        path_required = any(bool(item.get("required")) for item in path_params) or bool(
            path_params
        )
        query_required = any(bool(item.get("required")) for item in query_params)

        if path_type:
            optional = "" if path_required else "?"
            args_fields.append(
                f"    path{optional}: {_inline_type_for_args(path_type, indent=4)};"
            )
        if query_type:
            optional = "" if query_required else "?"
            args_fields.append(
                f"    query{optional}: {_inline_type_for_args(query_type, indent=4)};"
            )
        if body_schema is not None:
            optional = "" if body_required else "?"
            body_type = ts_from_schema(body_schema, schemas)
            if media_type == "multipart/form-data":
                body_type = f"FormData | {body_type}"
            args_fields.append(
                f"    body{optional}: {_inline_type_for_args(body_type, indent=4)};"
            )

        args_required = (
            (path_type is not None and path_required)
            or (query_type is not None and query_required)
            or (body_schema is not None and body_required)
        )

        if args_fields:
            args_type = "{\n" + "\n".join(args_fields) + "\n}"
            args_sig = f"args: {args_type}" if args_required else f"args?: {args_type}"
        else:
            args_sig = ""

        # Build method body.
        lines: list[str] = []
        if args_sig:
            lines.append(f"  async {method_name}({args_sig}): Promise<{return_type}> {{")
        else:
            lines.append(f"  async {method_name}(): Promise<{return_type}> {{")

        args_root = "args" if args_required else "args?"

        if path_params:
            lines.append(f"    const path = buildPath('{path}', args.path);")
        else:
            lines.append(f"    const path = '{path}';")

        if query_params:
            lines.append(
                f"    const url = `${{path}}${{buildQuery({args_root}.query)}}`;"
            )
        else:
            lines.append("    const url = path;")

        fetch_options: list[str] = [f"method: '{method}'"]
        if body_schema is not None:
            body_access = f"{args_root}.body"
            if media_type == "multipart/form-data":
                lines.append(f"    const body = toFormData({body_access});")
                fetch_options.append("body")
            else:
                lines.append(
                    f"    const body = {body_access} === undefined "
                    f"? undefined : JSON.stringify({body_access});"
                )
                fetch_options.append("body")

        options_literal = "{ " + ", ".join(fetch_options) + " }"
        if return_type == "void":
            lines.append(f"    await apiClient<void>(url, {options_literal});")
        else:
            lines.append(
                f"    return apiClient<{return_type}>(url, {options_literal});"
            )
        lines.append("  },")
        method_chunks.append("\n".join(lines))

    chunks: list[str] = [CLIENT_HEADER]
    if referenced:
        sorted_refs = sorted(referenced)
        # Keep imports readable: one type per line.
        import_lines = ",\n  ".join(sorted_refs)
        chunks.append(f"import type {{\n  {import_lines},\n}} from './backoffice-schemas';\n\n")
    else:
        chunks.append("\n")

    chunks.append(
        """\
function buildPath(
  template: string,
  pathParams: Record<string, string | number | boolean>,
): string {
  return template.replace(/\\{([^}]+)\\}/g, (_match, key: string) => {
    const value = pathParams[key];
    if (value === undefined || value === null) {
      throw new Error(`Missing path parameter: ${key}`);
    }
    return encodeURIComponent(String(value));
  });
}

function buildQuery(query: Record<string, unknown> | undefined): string {
  if (!query) {
    return '';
  }
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) {
      continue;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item === undefined || item === null) {
          continue;
        }
        params.append(key, String(item));
      }
      continue;
    }
    params.set(key, String(value));
  }
  const encoded = params.toString();
  return encoded ? `?${encoded}` : '';
}

function toFormData(body: FormData | object | undefined): FormData | undefined {
  if (body === undefined) {
    return undefined;
  }
  if (typeof FormData !== 'undefined' && body instanceof FormData) {
    return body;
  }
  const form = new FormData();
  for (const [key, value] of Object.entries(body as Record<string, unknown>)) {
    if (value === undefined || value === null) {
      continue;
    }
    if (typeof Blob !== 'undefined' && value instanceof Blob) {
      form.append(key, value);
      continue;
    }
    form.append(key, String(value));
  }
  return form;
}

"""
    )
    chunks.append(
        f"// Operations from ai_ops_backoffice OpenAPI ({len(operations)} methods).\n"
    )
    chunks.append("export const backofficeClient = {\n")
    chunks.append("\n".join(method_chunks))
    if method_chunks:
        chunks.append("\n")
    chunks.append("} as const;\n\n")
    chunks.append("export type BackofficeClient = typeof backofficeClient;\n")
    return "".join(chunks).rstrip() + "\n"
