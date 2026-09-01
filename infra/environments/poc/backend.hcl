# Remote state backend for the existing POC environment (import workflow).
#
# WARNING: Do not use this backend for new test projects. Use
# ../test/backend.hcl with a separate bucket or prefix instead.
#
# Bootstrap once (outside Terraform):
#   gsutil mb -p itr-aimasteryhub-lab -l asia-east1 gs://itr-aimasteryhub-lab-terraform-state
#   gsutil versioning set on gs://itr-aimasteryhub-lab-terraform-state
#
# Then init from infra/terraform:
#   cp ../environments/poc/terraform.tfvars.example terraform.tfvars
#   terraform init -backend-config=../environments/poc/backend.hcl

bucket = "itr-aimasteryhub-lab-terraform-state"
prefix = "poc/teams-agent"
