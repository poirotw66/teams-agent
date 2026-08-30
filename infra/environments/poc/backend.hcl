# Remote state backend for the POC environment.
#
# Bootstrap once (outside Terraform):
#   gsutil mb -p <project-id> -l asia-east1 gs://<project-id>-terraform-state
#   gsutil versioning set on gs://<project-id>-terraform-state
#
# Then init from infra/terraform:
#   terraform init -backend-config=../environments/poc/backend.hcl

bucket = "itr-aimasteryhub-lab-terraform-state"
prefix = "poc/teams-agent"
