"""Shared service-catalog payload validation (release artifact contract).

Lives in ``knowledge_core`` so both Portal packaging and Agent runtime loaders
can validate the same schema without a reverse ``agent_service → knowledge_portal``
dependency.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "SERVICE_CATALOG_SCHEMA_VERSION",
    "validate_service_catalog_payload",
]

SERVICE_CATALOG_SCHEMA_VERSION = 1


def validate_service_catalog_payload(payload: object) -> dict[str, Any]:
    """Validate a service-catalog JSON object; raise on invalid shape or fields."""
    if not isinstance(payload, dict):
        raise TypeError("Service catalog payload must be an object.")
    schema_version = payload.get("schemaVersion")
    if not isinstance(schema_version, int) or schema_version < 1:
        raise ValueError("Service catalog schemaVersion must be a positive integer.")
    release_id = payload.get("releaseId")
    if not isinstance(release_id, str) or not release_id.strip():
        raise ValueError("Service catalog releaseId is required.")
    tenant_id = payload.get("tenantId")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("Service catalog tenantId is required.")
    services = payload.get("services")
    if not isinstance(services, list):
        raise TypeError("Service catalog services must be a list.")
    for index, item in enumerate(services):
        if not isinstance(item, dict):
            raise TypeError(f"Service catalog services[{index}] must be an object.")
        service_id = item.get("serviceId")
        if not isinstance(service_id, str) or not service_id.strip():
            raise ValueError(f"Service catalog services[{index}].serviceId is required.")
    return payload
