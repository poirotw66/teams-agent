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

    def test_release_console_v2_static_artifact_is_ui_only(self) -> None:
        """Synced console-v2 assets must not force a Backoffice Python rebuild."""
        release_script = self.read("deploy/release-gcp.sh")
        console_v2_case = (
            "agent_service/src/ai_ops_backoffice/static/console-v2/*)"
        )
        backoffice_case = (
            "agent_service/src/ai_ops_backoffice/*|agent_service/Dockerfile.backoffice)"
        )
        self.assertIn(console_v2_case, release_script)
        self.assertIn(backoffice_case, release_script)
        self.assertLess(
            release_script.index(console_v2_case),
            release_script.index(backoffice_case),
        )
        console_block_start = release_script.index(console_v2_case)
        console_block_end = release_script.index(backoffice_case)
        console_block = release_script[console_block_start:console_block_end]
        self.assertIn("BUILD_CONSOLE=1", console_block)
        self.assertNotIn("BUILD_BACKOFFICE=1", console_block)

    def test_backoffice_dockerfile_is_python_only(self) -> None:
        """Phase G: Backoffice image must not rebuild the React console."""
        dockerfile = self.read("agent_service/Dockerfile.backoffice")
        self.assertNotIn("FROM node:", dockerfile)
        self.assertNotIn("npm ci", dockerfile)
        self.assertNotIn("npm run build", dockerfile)
        self.assertIn("COPY agent_service/src", dockerfile)

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
        self.assertIn('name  = "GEMINI_MODEL"', converter)
        self.assertIn('value = "gemini-3.8-flash"', converter)
        self.assertIn("pdf_converter_aiplatform_user", converter)
        self.assertIn("GEMINI_API_BACKEND", converter)
        self.assertNotIn("GOOGLE_API_KEY", converter)
        self.assertIn("google_service_account.pdf_converter[0].email", converter)
        self.assertIn("google_service_account.portal.email", converter)
        self.assertNotIn("google_service_account.agent.email", converter)
        self.assertIn("template[0].containers[0].image", converter)
        self.assertIn("      scaling,", converter)
        self.assertNotIn("      template,", converter)
        self.assertIn("pdf_converter_existing_url", converter)
        self.assertIn("portal_pdf_converter_engine", converter)
        self.assertIn('? "gemini_vision" : "legacy_text"', converter)
        self.assertRegex(
            portal,
            r'KNOWLEDGE_PORTAL_PDF_CONVERTER_URL"\s+'
            r"value = local\.portal_pdf_converter_url",
        )
        self.assertRegex(
            portal,
            r'KNOWLEDGE_PORTAL_PDF_CONVERTER_ENGINE"\s+'
            r"value = local\.portal_pdf_converter_engine",
        )
        self.assertRegex(
            portal,
            r'KNOWLEDGE_PORTAL_PDF_CONVERTER_AUTH_MODE"\s+'
            r"value = local\.portal_pdf_converter_auth_mode",
        )
        self.assertNotRegex(
            portal,
            r'KNOWLEDGE_PORTAL_PDF_CONVERTER_ENGINE"\s+'
            r'value = local\.deploy_pdf_converter \? "gemini_vision" : "legacy_text"',
        )
        variables = self.read("infra/terraform/variables.tf")
        poc_tfvars = self.read("infra/environments/poc/terraform.tfvars.example")
        self.assertIn('variable "pdf_converter_existing_url"', variables)
        self.assertIn('variable "portal_pdf_converter_engine"', variables)
        self.assertIn("enable_pdf_converter       = true", poc_tfvars)
        self.assertIn("pdf_converter_existing_url", poc_tfvars)
        self.assertIn(
            "@sha256:6c00f9f11a93f9f8a756c9ed9fadcb9f9b1dbd6ce28282d82a6fb005ace683a3",
            poc_tfvars,
        )
        self.assertNotIn(
            "@sha256:f05fe09d2f95317e5aaf6111be92b4f491793ce52a3aacf78962a1ef81f14326",
            poc_tfvars,
        )

    def test_bu_vertex_revisions_have_no_google_api_key_mount(self) -> None:
        locals_tf = self.read("infra/terraform/locals.tf")
        agent = self.read("infra/terraform/cloud_run.tf")
        portal = self.read("infra/terraform/knowledge_portal.tf")
        converter = self.read("infra/terraform/cloud_run_pdf_converter.tf")
        iam = self.read("infra/terraform/iam.tf")
        secrets = self.read("infra/terraform/secrets.tf")
        deploy_agent = self.read("deploy/deploy-gcp.sh")
        deploy_portal = self.read("deploy/deploy-portal.sh")

        self.assertIn('GEMINI_API_BACKEND                   = "VERTEX_AI"', locals_tf)
        self.assertNotIn("GOOGLE_API_KEY", locals_tf)
        self.assertNotIn("GOOGLE_API_KEY", agent)
        self.assertNotIn("GOOGLE_API_KEY", portal)
        self.assertNotIn("GOOGLE_API_KEY", converter)
        self.assertIn("agent_aiplatform_user", iam)
        self.assertIn("backoffice_aiplatform_user", iam)
        self.assertIn("aiplatform.googleapis.com", locals_tf)
        self.assertIn('resource "google_secret_manager_secret" "google_api_key"', secrets)
        self.assertNotIn("GOOGLE_API_KEY=", deploy_agent)
        self.assertNotIn("GOOGLE_API_KEY=", deploy_portal.split("--set-env-vars", 1)[-1])
        self.assertIn("deploy/lib/vertex-revision-contract.sh", deploy_agent)
        self.assertIn("unmount_developer_api_key_secrets", deploy_agent)
        self.assertIn("assert_bu_vertex_revision", deploy_agent)
        self.assertIn("assert_bu_agent_knowledge_runtime", deploy_agent)
        self.assertIn("preserve_live_agent_knowledge_env", deploy_agent)
        self.assertIn("deploy_cloud_run_preserving_runtime", deploy_agent)
        self.assertIn("VERTEX_AI_PDF_LOCATION", portal)
        self.assertIn("unapproved_vertex_location_placeholder", locals_tf)
        self.assertIn(
            'unapproved_vertex_location_placeholder = "global"', locals_tf
        )
        self.assertNotIn(
            "var.vertex_ai_project != \"\" ? var.vertex_ai_project : var.project_id",
            locals_tf,
        )
        self.assertIn("vertex_ai_project_is_explicit", locals_tf)
        self.assertIn("Do not infer it from project_id", locals_tf)
        self.assertIn("vertex_pdf_in_play", locals_tf)
        self.assertIn('P0 placeholder \\"global\\" is rejected', locals_tf)
        image_policy = locals_tf.split('resource "terraform_data" "image_policy"', 1)[1]
        self.assertIn("vertex_pdf_in_play", image_policy)
        self.assertNotIn("portal_pdf_converter_engine", image_policy)
        variables = self.read("infra/terraform/variables.tf")
        self.assertIn(
            'lower(trimspace(var.vertex_ai_chat_location)) != "global"',
            variables,
        )
        self.assertIn(
            'lower(trimspace(var.vertex_ai_embedding_location)) != "global"',
            variables,
        )
        self.assertIn(
            'lower(trimspace(var.vertex_ai_pdf_location)) != "global"',
            variables,
        )
        self.assertNotRegex(
            variables,
            r'variable "vertex_ai_chat_location"[\s\S]*?default\s+=\s+"global"',
        )
        self.assertIn("deploy/lib/vertex-revision-contract.sh", deploy_portal)
        self.assertIn("unmount_developer_api_key_secrets", deploy_portal)
        self.assertIn("assert_bu_vertex_revision", deploy_portal)
        self.assertIn("deploy_remove_developer_api_key_secrets_args", deploy_portal)
        self.assertIn(
            'KNOWLEDGE_PORTAL_GEMINI_FILE_SEARCH_SYNC_ENABLED=false',
            deploy_portal,
        )
        self.assertIn(
            "KNOWLEDGE_PORTAL_REQUIRE_FILE_SEARCH_PARITY=false",
            deploy_portal,
        )
        deploy_backoffice = self.read("deploy/deploy-backoffice.sh")
        self.assertIn('GEMINI_API_BACKEND="VERTEX_AI"', deploy_backoffice)
        self.assertIn("unmount_developer_api_key_secrets", deploy_backoffice)
        self.assertIn("assert_bu_vertex_revision", deploy_backoffice)
        self.assertGreaterEqual(deploy_backoffice.count("assert_bu_vertex_revision"), 4)
        source_wiring = self.read("deploy/lib/source-api-wiring.sh")
        self.assertIn("deploy_remove_developer_api_key_secrets_args", source_wiring)


if __name__ == "__main__":
    unittest.main()
