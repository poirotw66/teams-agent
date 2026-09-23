"""Environment parsing helpers for BackofficeSettings.from_env."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .settings_env_common import env_path, optional_env, resolve_store_mode, truthy
from .settings_env_stores import (
    load_budget_env,
    load_evaluation_store_env,
    load_export_env,
    load_phase2_store_env,
    load_prompt_governance_env,
    load_source_artifact_env,
)


def resolve_data_dirs() -> tuple[Path, Path]:
    project_dir = Path(__file__).resolve().parents[2]
    raw_data = os.environ.get("RAG_DATA_DIR")
    if raw_data and Path(raw_data).is_absolute():
        data_dir = Path(raw_data).resolve()
    elif raw_data and (project_dir / raw_data).exists():
        data_dir = (project_dir / raw_data).resolve()
    elif raw_data and Path(raw_data).exists():
        data_dir = Path(raw_data).resolve()
    else:
        data_dir = project_dir.parent / "data"
    ops_dir = Path(os.environ.get("OPS_DATA_DIR", data_dir / "ops"))
    return data_dir, ops_dir


def resolve_primary_store_mode() -> str:
    return (
        os.environ.get("OPS_STORE_MODE")
        or os.environ.get("AI_OPS_STORE_MODE")
        or "FILE"
    ).strip().upper()


def resolve_gcp_project_id() -> str | None:
    return next(
        (
            os.environ[key]
            for key in (
                "AI_OPS_GCP_PROJECT",
                "GCP_PROJECT_ID",
                "GOOGLE_CLOUD_PROJECT",
                "GCP_PROJECT",
            )
            if os.environ.get(key)
        ),
        None,
    )


def resolve_deployment_environment() -> str:
    return next(
        (
            os.environ[key].strip().lower()
            for key in (
                "AI_OPS_DEPLOYMENT_ENV",
                "ENVIRONMENT",
                "AGENT_DEPLOYMENT_ENV",
                "ENV",
            )
            if os.environ.get(key)
        ),
        "dev",
    )


def _default_relaxed_workflow_flag() -> str:
    deployment_env = (
        os.environ.get("AGENT_DEPLOYMENT_ENV")
        or os.environ.get("ENV")
        or "dev"
    ).lower()
    if deployment_env in {"prod", "production", "staging"}:
        return "false"
    return "true"


def _relaxed_workflow_raw() -> str:
    return (
        os.environ.get("AI_OPS_RELAXED_WORKFLOW")
        or os.environ.get("KNOWLEDGE_PORTAL_RELAXED_WORKFLOW")
        or _default_relaxed_workflow_flag()
    )


def load_server_auth_env() -> dict[str, Any]:
    return {
        "host": os.environ.get("AI_OPS_BACKOFFICE_HOST", "0.0.0.0"),
        "port": int(os.environ.get("AI_OPS_BACKOFFICE_PORT", "8092")),
        "service_token": (
            os.environ.get("AI_OPS_BACKOFFICE_TOKEN")
            or os.environ.get("SERVICE_TOKEN")
            or ""
        ),
        "auth_mode": (
            os.environ.get("AI_OPS_BACKOFFICE_AUTH_MODE")
            or os.environ.get("AUTH_MODE")
            or "HEADER"
        ).strip().upper(),
        "entra_tenant_id": optional_env("AI_OPS_ENTRA_TENANT_ID", "ENTRA_TENANT_ID"),
        "entra_client_id": optional_env("AI_OPS_ENTRA_CLIENT_ID", "ENTRA_CLIENT_ID"),
        "default_owner_unit_id": os.environ.get(
            "AI_OPS_DEFAULT_OWNER_UNIT", "IT Service Desk"
        ),
        "deployment_tenant_id": os.environ.get(
            "AI_OPS_DEPLOYMENT_TENANT_ID", "local-development"
        ),
        "gcp_project_id": resolve_gcp_project_id(),
        "environment": resolve_deployment_environment(),
    }


def load_ops_store_env(ops_dir: Path, primary_store_mode: str) -> dict[str, Any]:
    return {
        "ops_store_mode": primary_store_mode,
        "ops_store_path": env_path("OPS_STORE_PATH", ops_dir / "events"),
        "ops_taxonomy_path": env_path(
            "OPS_TAXONOMY_PATH", ops_dir / "issue_taxonomy_v1.json"
        ),
        "ops_metrics_path": env_path(
            "OPS_METRICS_PATH", ops_dir / "metrics_definitions_v1.json"
        ),
        "ops_classification_rules_path": env_path(
            "OPS_CLASSIFICATION_RULES_PATH",
            ops_dir / "issue_classification_rules.json",
        ),
        "ops_audit_store_mode": resolve_store_mode(
            "OPS_AUDIT_STORE_MODE", primary_store_mode, "FILE"
        ),
    }


def _knowledge_workspace_mode_env() -> dict[str, str | None]:
    mode = (os.environ.get("AI_OPS_KNOWLEDGE_WORKSPACE_MODE") or "").strip().upper() or None
    return {
        "knowledge_workspace_mode": mode,
        "knowledge_workspace_mode_default": mode,
    }


def load_knowledge_bridge_env() -> dict[str, Any]:
    public_url = os.environ.get(
        "KNOWLEDGE_PORTAL_PUBLIC_URL", "http://127.0.0.1:8091"
    )
    return {
        "knowledge_portal_url": public_url,
        "knowledge_internal_url": os.environ.get(
            "KNOWLEDGE_PORTAL_INTERNAL_URL", public_url
        ),
        "knowledge_service_token": os.environ.get("KNOWLEDGE_PORTAL_TOKEN", ""),
        "knowledge_auth_mode": os.environ.get(
            "KNOWLEDGE_PORTAL_UPSTREAM_AUTH_MODE", "BEARER"
        ).upper(),
        "knowledge_timeout_seconds": float(
            os.environ.get("KNOWLEDGE_PORTAL_UPSTREAM_TIMEOUT_SECONDS", "180")
        ),
        "knowledge_delegation_secret": (
            os.environ.get("KNOWLEDGE_PORTAL_DELEGATION_SECRET")
            or os.environ.get("AI_OPS_KNOWLEDGE_DELEGATION_SECRET", "")
        ),
        "source_delegation_secret": os.environ.get(
            "AI_OPS_SOURCE_DELEGATION_SECRET",
            os.environ.get("RAG_ASSET_SIGNING_KEY", ""),
        ).strip(),
        "knowledge_bridge_enabled": truthy(
            os.environ.get("AI_OPS_KNOWLEDGE_BRIDGE_ENABLED", "true"),
            extras={"on"},
        ),
        "knowledge_in_process": truthy(
            os.environ.get("AI_OPS_KNOWLEDGE_IN_PROCESS", "true"),
            extras={"on"},
        ),
        "console_surface": (
            (os.environ.get("AI_OPS_CONSOLE_SURFACE") or "").strip().upper() or None
        ),
        **_knowledge_workspace_mode_env(),
        "knowledge_cloud_formal_writes_enabled": truthy(
            os.environ.get("AI_OPS_KNOWLEDGE_CLOUD_FORMAL_WRITES", "false"),
            extras={"on"},
        ),
    }


def load_upstream_urls_env() -> dict[str, Any]:
    return {
        "agent_api_url": optional_env(
            "KNOWLEDGE_PORTAL_AGENT_API_URL", "AGENT_API_URL"
        ),
        "adapter_api_url": optional_env("TEAMS_ADAPTER_URL", "ADAPTER_API_URL"),
        "ticket_service_url": os.environ.get("TICKET_SERVICE_BASE_URL"),
        "simulate_health_anomalies": truthy(
            os.environ.get("AI_OPS_SIMULATE_HEALTH_ANOMALIES", "")
        ),
    }


def load_workflow_env() -> dict[str, Any]:
    relaxed = truthy(_relaxed_workflow_raw(), extras={"on"})
    min_cases_default = "0" if relaxed else "3"
    return {
        "relaxed_workflow": relaxed,
        "min_test_cases_for_review": int(
            os.environ.get("AI_OPS_MIN_TEST_CASES_FOR_REVIEW")
            or os.environ.get("KNOWLEDGE_PORTAL_MIN_TEST_CASES_FOR_REVIEW")
            or min_cases_default
        ),
    }


def load_runtime_feature_env() -> dict[str, Any]:
    return {
        "workers_enabled": truthy(
            os.environ.get("AI_OPS_WORKERS_ENABLED", "true"),
            extras={"on"},
        ),
        "query_cache_ttl_seconds": max(
            0,
            int(os.environ.get("AI_OPS_QUERY_CACHE_TTL_SECONDS", "120")),
        ),
        "freshness_firestore_collection": (
            os.environ.get("AI_OPS_FRESHNESS_COLLECTION")
            or os.environ.get("OPS_FRESHNESS_COLLECTION")
            or "freshness_state"
        ).strip(),
        "console_v2_enabled": truthy(
            os.environ.get("BACKOFFICE_CONSOLE_V2_ENABLED", "true"),
            extras={"on"},
        ),
        "legacy_shell_enabled": truthy(
            os.environ.get("BACKOFFICE_LEGACY_SHELL_ENABLED", "false"),
            extras={"on"},
        ),
    }


def build_backoffice_settings_kwargs() -> dict[str, Any]:
    """Assemble all BackofficeSettings constructor kwargs from the environment."""
    _data_dir, ops_dir = resolve_data_dirs()
    primary_store_mode = resolve_primary_store_mode()
    return {
        **load_server_auth_env(),
        **load_ops_store_env(ops_dir, primary_store_mode),
        **load_knowledge_bridge_env(),
        **load_upstream_urls_env(),
        **load_export_env(ops_dir, primary_store_mode),
        **load_phase2_store_env(ops_dir, primary_store_mode),
        **load_budget_env(ops_dir, primary_store_mode),
        **load_prompt_governance_env(ops_dir, primary_store_mode),
        **load_workflow_env(),
        **load_evaluation_store_env(ops_dir, primary_store_mode),
        **load_source_artifact_env(ops_dir, primary_store_mode),
        **load_runtime_feature_env(),
    }
