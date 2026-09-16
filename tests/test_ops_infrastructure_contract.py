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

    def test_agent_release_defaults_match_the_verified_embedding_contract(self) -> None:
        variables = self.read("infra/terraform/variables.tf")
        locals_tf = self.read("infra/terraform/locals.tf")
        cloud_run = self.read("infra/terraform/cloud_run.tf")

        self.assertIn('default = "google_genai:gemini-3.1-flash-lite"', variables)
        self.assertIn('default = "google_genai:gemini-3.8-flash"', variables)
        self.assertIn('default = "google_genai:gemini-embedding-2"', variables)
        self.assertRegex(
            locals_tf,
            r"KNOWLEDGE_RELEASE_TENANT_ID\s+=\s+\"default\"",
        )
        self.assertRegex(
            locals_tf,
            r"OPS_FIRESTORE_PROJECT\s+=\s+var\.project_id",
        )
        self.assertRegex(
            locals_tf,
            r"TICKET_SERVICE_MODE\s+=\s+var\.ticket_service_mode",
        )
        self.assertRegex(
            locals_tf,
            r"OPS_BIGQUERY_ENABLED\s+=\s+tostring\(var\.agent_ops_bigquery_enabled\)",
        )
        self.assertIn('name = "TICKET_SERVICE_TOKEN"', cloud_run)

    def test_one_year_retention_is_the_default(self) -> None:
        variables = self.read("infra/terraform/variables.tf")
        locals_tf = self.read("infra/terraform/locals.tf")
        ai_ops = self.read("infra/terraform/ai_ops.tf")

        self.assertIn('variable "conversation_retention_days"', variables)
        self.assertIn('variable "handoff_retention_days"', variables)
        self.assertGreaterEqual(variables.count("default     = 365"), 2)
        self.assertRegex(
            locals_tf,
            r"CONVERSATION_RETENTION_DAYS\s+=\s+tostring\(var\.conversation_retention_days\)",
        )
        self.assertRegex(
            locals_tf,
            r"HANDOFF_RETENTION_DAYS\s+=\s+tostring\(var\.handoff_retention_days\)",
        )
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
        portal = self.read("infra/terraform/knowledge_portal.tf")

        self.assertRegex(locals_tf, r"KNOWLEDGE_PORTAL_PUBLIC_URL\s+=\s+var\.knowledge_portal_public_url")
        self.assertRegex(
            locals_tf,
            r'KNOWLEDGE_PORTAL_URL_CONFIGURED\s+=\s+tostring\(local\.deploy_cloud_run \|\| var\.knowledge_portal_public_url != ""\)',
        )
        self.assertNotRegex(locals_tf, r"KNOWLEDGE_PORTAL_PUBLIC_URL\s+=\s+var\.adapter_public_base_url")
        self.assertNotIn("      template,", cloud_run)
        self.assertNotIn("      scaling,", cloud_run)
        self.assertNotIn("      template,", backoffice)
        self.assertNotIn("      scaling,", backoffice)
        self.assertRegex(
            portal,
            r'AGENT_DEPLOYMENT_ENV"\s+value\s+=\s+var\.environment_name',
        )
        self.assertRegex(
            portal,
            r'KNOWLEDGE_PORTAL_RELEASE_PURPOSE"\s+value\s+=\s+"PRODUCTION"',
        )

    def test_environment_templates_and_inventory_do_not_claim_current_verification(self) -> None:
        for environment in ("dev", "test", "poc", "prod"):
            self.assertTrue((ROOT / "infra" / "environments" / environment / "backend.hcl").is_file())
            self.assertTrue((ROOT / "infra" / "environments" / environment / "terraform.tfvars.example").is_file())
        inventory = self.read("infra/ai-ops-environment-inventory.json")
        self.assertIn('"verificationStatus": "historical-record-only"', inventory)
        self.assertIn('"historicalPlanEvidence"', inventory)

    def test_release_pipeline_pins_rollback_images_and_waits_for_parallel_updates(self) -> None:
        release_script = self.read("deploy/release-gcp.sh")

        self.assertIn("pin_image_reference()", release_script)
        self.assertGreaterEqual(
            release_script.count('pin_image_reference "$(current_service_image'),
            4,
        )
        self.assertIn('if ! wait "${pid}"; then', release_script)
        self.assertIn('[[ "${DEPLOY_FAILED}" == "0" ]]', release_script)

    def test_pdf_converter_release_and_cloud_run_are_private_and_pinned(self) -> None:
        dockerfile = self.read("services/pdf_converter/Dockerfile.upstream")
        cloudbuild = self.read("deploy/cloudbuild-release.yaml")
        release_script = self.read("deploy/release-gcp.sh")
        gcloudignore = self.read(".gcloudignore")
        converter = self.read("infra/terraform/cloud_run_pdf_converter.tf")
        portal = self.read("infra/terraform/knowledge_portal.tf")

        self.assertRegex(dockerfile, r"ARG UPSTREAM_REF=[0-9a-f]{40}")
        self.assertIn("id: converter", cloudbuild)
        self.assertIn("_CONVERTER_CACHE_IMAGE", cloudbuild)
        self.assertRegex(cloudbuild, r'_PDF_CONVERTER_UPSTREAM_REF: "[0-9a-f]{40}"')
        self.assertIn("services/pdf_converter/Dockerfile.upstream", cloudbuild)
        self.assertIn("!services/pdf_converter/Dockerfile.upstream", gcloudignore)
        self.assertIn('*",converter,"*', release_script)
        self.assertIn('ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY"', converter)
        self.assertIn('value = "gemini"', converter)
        self.assertIn("pdf_converter_google_api_key", converter)
        self.assertIn("google_service_account.pdf_converter[0].email", converter)
        self.assertIn("google_service_account.portal.email", converter)
        self.assertNotIn("google_service_account.agent.email", converter)
        self.assertRegex(
            portal,
            r'KNOWLEDGE_PORTAL_PDF_CONVERTER_ENGINE"\s+'
            r'value = local\.deploy_pdf_converter \? "gemini_vision" : "legacy_text"',
        )
        self.assertRegex(
            portal,
            r'KNOWLEDGE_PORTAL_PDF_CONVERTER_AUTH_MODE"\s+'
            r'value = local\.deploy_pdf_converter \? "GOOGLE_ID_TOKEN" : "BEARER"',
        )


if __name__ == "__main__":
    unittest.main()
