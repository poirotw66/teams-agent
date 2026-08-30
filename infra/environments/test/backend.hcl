# Remote state backend for a clean-room test / handoff drill project.
#
# IMPORTANT: Do not reuse the POC bucket or prefix. Each environment needs
# isolated state so a test apply cannot touch POC resources.
#
# Bootstrap once (outside Terraform, in the test project):
#   gsutil mb -p <test-project-id> -l asia-east1 gs://<test-project-id>-terraform-state
#   gsutil versioning set on gs://<test-project-id>-terraform-state
#
# Then init from infra/terraform:
#   cp ../environments/test/terraform.tfvars.example terraform.tfvars
#   terraform init -backend-config=../environments/test/backend.hcl

bucket = "<test-project-id>-terraform-state"
prefix = "test/teams-agent"
