"""Configuration validator for AI Ops Backoffice deployments.

Provides pre-flight checks before deploying to GCP Cloud Run or staging
environments, ensuring that environment variables are aligned, production
mode uses FIRESTORE rather than local file defaults, and required secrets
are populated.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .settings import BackofficeSettings


def validate_backoffice_settings(
    settings: BackofficeSettings,
    *,
    require_production: bool = False,
) -> list[str]:
    """Validate BackofficeSettings for production readiness."""
    errors: list[str] = []
    is_prod = require_production or settings.environment in ("prod", "production", "staging")

    if is_prod:
        if settings.ops_store_mode != "FIRESTORE":
            errors.append(
                f"Production deployment requires ops_store_mode='FIRESTORE', found '{settings.ops_store_mode}'. "
                "Ensure OPS_STORE_MODE=FIRESTORE is set."
            )

        if not settings.gcp_project_id:
            errors.append(
                "Production deployment requires a non-empty GCP project ID. "
                "Ensure GCP_PROJECT_ID or GOOGLE_CLOUD_PROJECT is set."
            )

        domain_modes = {
            "ops_audit_store_mode": settings.ops_audit_store_mode,
            "export_job_store_mode": settings.export_job_store_mode,
            "faq_store_mode": settings.faq_store_mode,
            "example_store_mode": settings.example_store_mode,
            "quality_store_mode": settings.quality_store_mode,
            "sync_store_mode": settings.sync_store_mode,
            "budget_store_mode": settings.budget_store_mode,
            "prompt_poc_store_mode": settings.prompt_poc_store_mode,
            "governance_store_mode": settings.governance_store_mode,
            "eval_store_mode": settings.eval_store_mode,
            "gate_store_mode": settings.gate_store_mode,
            "fixture_store_mode": settings.fixture_store_mode,
            "job_store_mode": settings.job_store_mode,
            "source_store_mode": settings.source_store_mode,
        }

        for name, mode in domain_modes.items():
            if mode in ("FILE", "MEMORY"):
                errors.append(
                    f"Production domain store '{name}' cannot use '{mode}'. "
                    "Must be configured to 'FIRESTORE' to avoid unshared instance state."
                )

        if settings.auth_mode == "HEADER" and not settings.service_token:
            errors.append(
                "HEADER authentication mode in production requires a non-empty AI_OPS_BACKOFFICE_TOKEN."
            )
        elif settings.auth_mode == "ENTRA":
            if not settings.entra_tenant_id or not settings.entra_client_id:
                errors.append(
                    "ENTRA authentication mode in production requires both ENTRA_TENANT_ID and ENTRA_CLIENT_ID."
                )

    return errors


validate_production_config = validate_backoffice_settings


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entrypoint for pre-flight deployment configuration validation."""
    parser = argparse.ArgumentParser(
        description="Validate AI Ops Backoffice environment configuration."
    )
    parser.add_argument(
        "--production",
        action="store_true",
        help="Enforce production checks regardless of ENVIRONMENT variable.",
    )
    args = parser.parse_args(argv)

    settings = BackofficeSettings.from_env()
    errors = validate_backoffice_settings(settings, require_production=args.production)

    if errors:
        sys.stderr.write("[ERROR] AI Ops Backoffice deployment configuration validation failed:\n")
        for err in errors:
            sys.stderr.write(f"  - {err}\n")
        sys.exit(1)

    print(
        f"[OK] AI Ops Backoffice configuration is valid for environment: '{settings.environment}' "
        f"(store_mode={settings.ops_store_mode}, project={settings.gcp_project_id or 'none'})"
    )


if __name__ == "__main__":
    main()
