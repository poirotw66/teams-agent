"""Static Phase 0 infrastructure contracts; these tests do not contact GCP."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TERRAFORM = ROOT / "infra" / "terraform"


class OpsInfrastructureContractTests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_runtime_environment_is_not_deployment_phase(self) -> None:
        variables = self.read("infra/terraform/variables.tf")
        locals_tf = self.read("infra/terraform/locals.tf")

        self.assertIn('variable "environment_name"', variables)
        self.assertIn('["dev", "test", "poc", "prod"]', variables)
        self.assertRegex(locals_tf, r"AGENT_DEPLOYMENT_ENV\s+=\s+var\.environment_name")
        self.assertNotRegex(locals_tf, r"AGENT_DEPLOYMENT_ENV\s+=\s+var\.deployment_phase")

    def test_one_year_retention_is_the_default(self) -> None:
        variables = self.read("infra/terraform/variables.tf")
        locals_tf = self.read("infra/terraform/locals.tf")
        ai_ops = self.read("infra/terraform/ai_ops.tf")

        self.assertIn('variable "conversation_retention_days"', variables)
        self.assertIn('variable "handoff_retention_days"', variables)
        self.assertGreaterEqual(variables.count("default     = 365"), 2)
        self.assertIn("CONVERSATION_RETENTION_DAYS        = tostring(var.conversation_retention_days)", locals_tf)
        self.assertIn("HANDOFF_RETENTION_DAYS             = tostring(var.handoff_retention_days)", locals_tf)
        self.assertIn("expiration_ms = 31536000000", ai_ops)

    def test_event_table_has_full_scope_and_deduplication_contract(self) -> None:
        ai_ops = self.read("infra/terraform/ai_ops.tf")
        required_fields = (
            "event_id",
            "event_type",
            "schema_version",
            "occurred_at",
            "ingested_at",
            "environment",
            "tenant_id",
            "team_id",
            "channel_scope",
            "conversation_id",
            "turn_id",
            "request_id",
            "correlation_id",
            "issue_occurrence_id",
            "issue_type_id",
            "taxonomy_version",
            "actor_ref",
            "data_classification",
            "retention_expires_at",
            "payload",
        )

        for field in required_fields:
            self.assertIn(f'name = "{field}"', ai_ops)
        self.assertIn("require_partition_filter = true", ai_ops)
        self.assertIn('clustering = ["environment", "tenant_id", "event_type", "correlation_id"]', ai_ops)
        self.assertIn('PARTITION BY event_id', ai_ops)
        self.assertIn('ORDER BY ingested_at DESC, occurred_at DESC', ai_ops)

    def test_bigquery_access_is_scoped_and_backoffice_is_read_only(self) -> None:
        iam = self.read("infra/terraform/iam.tf")
        ai_ops = self.read("infra/terraform/ai_ops.tf")

        self.assertIn('resource "google_bigquery_table_iam_member" "agent_operational_events_writer"', iam)
        self.assertIn('resource "google_project_iam_member" "agent_bigquery_job_user"', iam)
        self.assertNotIn('resource "google_project_iam_member" "agent_bigquery"', iam)
        self.assertIn('resource "google_bigquery_dataset_iam_member" "backoffice_ai_ops_reader"', ai_ops)
        self.assertIn('role       = "roles/bigquery.dataViewer"', ai_ops)
        self.assertNotIn('resource "google_project_iam_member" "backoffice_bigquery"', ai_ops)

    def test_portal_is_not_derived_from_adapter_and_template_drift_is_managed(self) -> None:
        locals_tf = self.read("infra/terraform/locals.tf")
        cloud_run = self.read("infra/terraform/cloud_run.tf")
        backoffice = self.read("infra/terraform/ai_ops.tf")

        self.assertRegex(locals_tf, r"KNOWLEDGE_PORTAL_PUBLIC_URL\s+=\s+var\.knowledge_portal_public_url")
        self.assertRegex(locals_tf, r'KNOWLEDGE_PORTAL_URL_CONFIGURED\s+=\s+tostring\(var\.knowledge_portal_public_url != ""\)')
        self.assertNotRegex(locals_tf, r"KNOWLEDGE_PORTAL_PUBLIC_URL\s+=\s+var\.adapter_public_base_url")
        self.assertNotIn("      template,", cloud_run)
        self.assertNotIn("      scaling,", cloud_run)
        self.assertNotIn("      template,", backoffice)
        self.assertNotIn("      scaling,", backoffice)

    def test_environment_templates_and_inventory_do_not_claim_current_verification(self) -> None:
        for environment in ("dev", "test", "poc", "prod"):
            self.assertTrue((ROOT / "infra" / "environments" / environment / "backend.hcl").is_file())
            self.assertTrue((ROOT / "infra" / "environments" / environment / "terraform.tfvars.example").is_file())
        inventory = self.read("infra/ai-ops-environment-inventory.json")
        self.assertIn('"verificationStatus": "historical-record-only"', inventory)
        self.assertIn('"historicalPlanEvidence"', inventory)


if __name__ == "__main__":
    unittest.main()
