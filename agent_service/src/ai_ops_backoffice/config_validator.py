"""Configuration validator for AI Ops Backoffice deployments.

Provides unified pre-flight checks before deploying to GCP Cloud Run or staging
environments and runtime validation on startup, ensuring that environment variables
are aligned, production mode uses FIRESTORE rather than local file defaults, and
production authentication uses ENTRA.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING

from .config_validator_stores import collect_production_store_errors

if TYPE_CHECKING:
    from .settings import BackofficeSettings


def validate_backoffice_settings(
    settings: BackofficeSettings,
    *,
    require_production: bool = False,
    require_gcp_project: bool = True,
) -> list[str]:
    """Validate BackofficeSettings for production readiness.

    Single source of truth for both pre-flight deployment verification
    and application startup validation.
    """
    errors: list[str] = []
    is_prod = require_production or settings.environment in (
        "prod",
        "production",
        "staging",
    )

    if is_prod:
        if settings.auth_mode != "ENTRA":
            errors.append(
                f"auth_mode must be ENTRA in production; configure ENTRA (found '{settings.auth_mode}')."
            )
        elif not settings.entra_tenant_id or not settings.entra_client_id:
            errors.append(
                "ENTRA authentication mode in production requires both ENTRA_TENANT_ID and ENTRA_CLIENT_ID."
            )

        if settings.ops_store_mode in ("FILE", "MEMORY"):
            errors.append(
                f"ops_store_mode must not be {settings.ops_store_mode} in production; configure FIRESTORE."
            )

        if require_gcp_project and not settings.gcp_project_id:
            errors.append(
                "Production deployment requires a non-empty GCP project ID. "
                "Ensure GCP_PROJECT_ID or GOOGLE_CLOUD_PROJECT is set."
            )

        errors.extend(collect_production_store_errors(settings))

    return errors


validate_production_config = validate_backoffice_settings


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entrypoint for pre-flight deployment configuration validation."""
    from .settings import BackofficeSettings

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
    errors = validate_backoffice_settings(
        settings,
        require_production=args.production,
        require_gcp_project=True,
    )

    if errors:
        sys.stderr.write(
            "[ERROR] AI Ops Backoffice deployment configuration validation failed:\n"
        )
        for err in errors:
            sys.stderr.write(f"  - {err}\n")
        sys.exit(1)

    print(
        f"[OK] AI Ops Backoffice configuration is valid for environment: '{settings.environment}' "
        f"(store_mode={settings.ops_store_mode}, project={settings.gcp_project_id or 'none'})"
    )


if __name__ == "__main__":
    main()
