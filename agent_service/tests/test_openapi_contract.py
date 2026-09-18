"""Unit tests for OpenAPI contract helpers (Phase F seam)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"


def _load_openapi_contract():
    scripts_dir = str(SCRIPTS)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location(
        "openapi_contract_under_test",
        SCRIPTS / "openapi_contract.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["openapi_contract_under_test"] = module
    spec.loader.exec_module(module)
    return module


def test_breaking_change_detects_removed_operation() -> None:
    contract = _load_openapi_contract()
    baseline = {
        "paths": {
            "/api/items": {
                "get": {"operationId": "list_items", "responses": {"200": {}}},
            }
        },
        "components": {"schemas": {}},
    }
    current = {"paths": {}, "components": {"schemas": {}}}
    findings = contract.find_breaking_changes(baseline, current)
    assert "removed operation GET /api/items" in findings


def test_breaking_change_detects_added_required_property() -> None:
    contract = _load_openapi_contract()
    baseline = {
        "paths": {},
        "components": {
            "schemas": {
                "Item": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                    },
                }
            }
        },
    }
    current = {
        "paths": {},
        "components": {
            "schemas": {
                "Item": {
                    "type": "object",
                    "required": ["id", "name"],
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                    },
                }
            }
        },
    }
    findings = contract.find_breaking_changes(baseline, current)
    assert "added required property Item.name" in findings


def test_additive_optional_property_is_not_breaking() -> None:
    contract = _load_openapi_contract()
    baseline = {
        "paths": {
            "/api/items": {
                "get": {"operationId": "list_items", "responses": {"200": {}}},
            }
        },
        "components": {
            "schemas": {
                "Item": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {"id": {"type": "string"}},
                }
            }
        },
    }
    current = {
        "paths": {
            "/api/items": {
                "get": {"operationId": "list_items", "responses": {"200": {}}},
            },
            "/api/items/{id}": {
                "get": {"operationId": "get_item", "responses": {"200": {}}},
            },
        },
        "components": {
            "schemas": {
                "Item": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {
                        "id": {"type": "string"},
                        "label": {"type": "string"},
                    },
                }
            }
        },
    }
    assert contract.find_breaking_changes(baseline, current) == []


def test_breaking_change_detects_property_type_change() -> None:
    contract = _load_openapi_contract()
    baseline = {
        "paths": {},
        "components": {
            "schemas": {
                "Item": {
                    "type": "object",
                    "properties": {"count": {"type": "integer"}},
                }
            }
        },
    }
    current = {
        "paths": {},
        "components": {
            "schemas": {
                "Item": {
                    "type": "object",
                    "properties": {"count": {"type": "string"}},
                }
            }
        },
    }
    findings = contract.find_breaking_changes(baseline, current)
    assert any(
        item.startswith("changed property type Item.count:") for item in findings
    )
