#!/usr/bin/env python3
"""Capture and verify OpenAPI route/schema snapshots for FastAPI services.

Usage (from repo root):
  PYTHONPATH=agent_service/src uv run python scripts/snapshot_openapi.py --write
  PYTHONPATH=agent_service/src uv run python scripts/snapshot_openapi.py --check
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = REPO_ROOT / "docs" / "architecture" / "baselines" / "openapi"
DATA_DIR = REPO_ROOT / "data"


def rel_path(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def stable_operation_id(method: str, path: str) -> str:
    cleaned = path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
    cleaned = cleaned.replace("-", "_")
    return f"{method.lower()}_{cleaned or 'root'}"


def schema_ref_name(value: Any) -> str | None:
    if isinstance(value, dict) and isinstance(value.get("$ref"), str):
        ref = value["$ref"]
        if ref.startswith("#/components/schemas/"):
            return ref.rsplit("/", 1)[-1]
    return None


def response_schema_names(operation: dict[str, Any]) -> list[str]:
    names: set[str] = set()
    for response in (operation.get("responses") or {}).values():
        if not isinstance(response, dict):
            continue
        content = response.get("content") or {}
        for media in content.values():
            if not isinstance(media, dict):
                continue
            name = schema_ref_name(media.get("schema"))
            if name:
                names.add(name)
    return sorted(names)


def request_schema_name(operation: dict[str, Any]) -> str | None:
    request_body = operation.get("requestBody")
    if not isinstance(request_body, dict):
        return None
    content = request_body.get("content") or {}
    for media in content.values():
        if not isinstance(media, dict):
            continue
        name = schema_ref_name(media.get("schema"))
        if name:
            return name
    return None


def route_inventory(schema: dict[str, Any]) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    for path, methods in sorted((schema.get("paths") or {}).items()):
        for method, operation in sorted(methods.items()):
            if method.startswith("x-") or not isinstance(operation, dict):
                continue
            responses = operation.get("responses") or {}
            routes.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "operationId": stable_operation_id(method, path),
                    "statusCodes": sorted(str(code) for code in responses),
                    "tags": sorted(operation.get("tags") or []),
                    "requestSchema": request_schema_name(operation),
                    "responseSchemas": response_schema_names(operation),
                }
            )
    return routes


def component_schema_inventory(schema: dict[str, Any]) -> list[dict[str, Any]]:
    components = ((schema.get("components") or {}).get("schemas")) or {}
    inventory: list[dict[str, Any]] = []
    for name, definition in sorted(components.items()):
        if not isinstance(definition, dict):
            inventory.append({"name": name, "type": None, "required": [], "properties": []})
            continue
        properties = definition.get("properties") or {}
        inventory.append(
            {
                "name": name,
                "type": definition.get("type"),
                "required": sorted(definition.get("required") or []),
                "properties": sorted(properties.keys()) if isinstance(properties, dict) else [],
            }
        )
    return inventory


def build_agent_schema() -> dict[str, Any]:
    from agent_service.api import create_app
    from agent_service.settings import RagSettings

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = RagSettings(
            data_dir=tmp_path,
            index_path=tmp_path / "index" / "chunks.json",
            auto_build_index=False,
            service_token="",
        )
        return create_app(settings).openapi()


def build_portal_schema() -> dict[str, Any]:
    from knowledge_portal.api import create_app
    from knowledge_portal.settings import PortalSettings

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        base = PortalSettings.from_env()
        settings = PortalSettings(
            **{
                **base.__dict__,
                "service_token": "",
                "repository_mode": "MEMORY",
                "data_dir": tmp_path,
                "state_path": tmp_path / "portal-state.json",
                "drafts_dir": tmp_path / "drafts",
                "original_assets_dir": tmp_path / "originals",
                "deployment_environment": "test",
                "gemini_file_search_sync_enabled": False,
                "require_file_search_parity": False,
            }
        )
        return create_app(settings).openapi()


def build_backoffice_schema() -> dict[str, Any]:
    from ai_ops_backoffice.api import create_app
    from ai_ops_backoffice.settings import BackofficeSettings

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = BackofficeSettings(
            host="127.0.0.1",
            port=8092,
            service_token="",
            auth_mode="HEADER",
            ops_store_mode="MEMORY",
            ops_store_path=tmp_path / "events",
            ops_taxonomy_path=DATA_DIR / "ops" / "issue_taxonomy_v1.json",
            ops_metrics_path=DATA_DIR / "ops" / "metrics_definitions_v1.json",
            ops_classification_rules_path=(
                DATA_DIR / "ops" / "issue_classification_rules.json"
            ),
            ops_audit_store_mode="MEMORY",
            knowledge_portal_url="http://127.0.0.1:8091",
            agent_api_url="http://127.0.0.1:8000",
            adapter_api_url="http://127.0.0.1:3978",
            ticket_service_url=None,
            default_owner_unit_id="IT Service Desk",
            entra_tenant_id=None,
            entra_client_id=None,
            governance_store_path=tmp_path / "governance.json",
            quality_store_mode="FILE",
            quality_store_path=tmp_path / "quality.json",
            eval_store_mode="MEMORY",
            eval_store_path=tmp_path / "golden_evals.json",
            knowledge_bridge_enabled=False,
            console_v2_enabled=True,
        )
        return create_app(settings).openapi()


SERVICE_BUILDERS: dict[str, Callable[[], dict[str, Any]]] = {
    "agent_service": build_agent_schema,
    "knowledge_portal": build_portal_schema,
    "ai_ops_backoffice": build_backoffice_schema,
}


def snapshot_paths(service: str) -> tuple[Path, Path]:
    return (
        SNAPSHOT_DIR / f"{service}.routes.json",
        SNAPSHOT_DIR / f"{service}.schemas.json",
    )


def build_snapshot(service: str, schema: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    routes = route_inventory(schema)
    schemas = component_schema_inventory(schema)
    return (
        {
            "service": service,
            "routeCount": len(routes),
            "routes": routes,
        },
        {
            "service": service,
            "schemaCount": len(schemas),
            "schemas": schemas,
        },
    )


def write_snapshots() -> None:
    for service, builder in SERVICE_BUILDERS.items():
        schema = builder()
        routes_payload, schemas_payload = build_snapshot(service, schema)
        routes_path, schemas_path = snapshot_paths(service)
        write_json(routes_path, routes_payload)
        write_json(schemas_path, schemas_payload)
        # Remove legacy full OpenAPI dumps if present from earlier Wave 0 drafts.
        legacy = SNAPSHOT_DIR / f"{service}.openapi.json"
        if legacy.exists():
            legacy.unlink()
        print(
            f"Wrote {rel_path(routes_path)} ({routes_payload['routeCount']} routes) "
            f"and {rel_path(schemas_path)} ({schemas_payload['schemaCount']} schemas)"
        )


def check_snapshots() -> list[str]:
    errors: list[str] = []
    for service, builder in SERVICE_BUILDERS.items():
        routes_path, schemas_path = snapshot_paths(service)
        if not routes_path.exists() or not schemas_path.exists():
            errors.append(
                f"missing snapshot for {service}; run with --write first"
            )
            continue
        schema = builder()
        current_routes, current_schemas = build_snapshot(service, schema)
        expected_routes = json.loads(routes_path.read_text(encoding="utf-8"))
        expected_schemas = json.loads(schemas_path.read_text(encoding="utf-8"))
        if current_routes != expected_routes:
            errors.append(
                f"{service} route inventory drifted "
                f"(expected {expected_routes.get('routeCount')} routes, "
                f"got {current_routes['routeCount']}). "
                "Re-run with --write after intentional API changes."
            )
            errors.extend(
                f"  {line}"
                for line in describe_route_diff(
                    expected_routes.get("routes") or [],
                    current_routes["routes"],
                )[:20]
            )
        if current_schemas != expected_schemas:
            errors.append(
                f"{service} component schema inventory drifted "
                f"(expected {expected_schemas.get('schemaCount')} schemas, "
                f"got {current_schemas['schemaCount']}). "
                "Re-run with --write after intentional API changes."
            )
    return errors


def route_key(route: dict[str, Any]) -> str:
    return f"{route['method']} {route['path']}"


def describe_route_diff(
    expected: list[dict[str, Any]],
    current: list[dict[str, Any]],
) -> list[str]:
    expected_map = {route_key(route): route for route in expected}
    current_map = {route_key(route): route for route in current}
    lines: list[str] = []
    for key in sorted(set(expected_map) - set(current_map)):
        lines.append(f"- removed {key}")
    for key in sorted(set(current_map) - set(expected_map)):
        lines.append(f"+ added {key}")
    for key in sorted(set(expected_map) & set(current_map)):
        if expected_map[key] != current_map[key]:
            lines.append(f"~ changed {key}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write or verify FastAPI OpenAPI route/schema snapshots."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="Write snapshots.")
    mode.add_argument("--check", action="store_true", help="Verify snapshots.")
    args = parser.parse_args()

    if str(REPO_ROOT / "agent_service" / "src") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "agent_service" / "src"))

    if args.write:
        write_snapshots()
        return 0

    errors = check_snapshots()
    if not errors:
        print("OpenAPI snapshots match.")
        return 0
    print("OpenAPI snapshot check failed:")
    for error in errors:
        print(f"  {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
