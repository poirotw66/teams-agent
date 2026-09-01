#!/usr/bin/env bash
# Prepare Environment: APIs, Artifact Registry, service accounts, secret
# containers, Firestore, and base IAM. Does not create Cloud Run services.
#
# Usage (from repo root):
#   ./infra/scripts/terraform-prepare.sh [backend-config]
#
# Example:
#   ./infra/scripts/terraform-prepare.sh infra/environments/test/backend.hcl

set -Eeuo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TERRAFORM_DIR="${REPO_ROOT}/infra/terraform"
BACKEND_CONFIG="${REPO_ROOT}/infra/environments/test/backend.hcl"
if [[ $# -gt 0 ]]; then
  BACKEND_CONFIG="$1"
  shift
fi

cd "${TERRAFORM_DIR}"

command -v terraform >/dev/null 2>&1 || { echo "terraform not found" >&2; exit 1; }

terraform init -backend-config="${BACKEND_CONFIG}" -input=false
terraform apply -input=false -var="deployment_phase=prepare" "$@"

printf '\nPrepare complete. Next:\n'
printf '  1. Inject secret values (see infra/terraform/README.md)\n'
printf '  2. BUILD_ONLY=1 ./deploy/release-gcp.sh  (or pinned gcloud builds submit)\n'
printf '  3. ./infra/scripts/terraform-activate.sh %s\n' "${BACKEND_CONFIG}"
