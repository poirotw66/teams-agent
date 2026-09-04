output "deployment_phase" {
  description = "Current Terraform deployment phase."
  value       = var.deployment_phase
}

output "environment_name" {
  description = "Runtime/data-governance environment, independent from Terraform bootstrap phase."
  value       = var.environment_name
}

output "knowledge_portal_public_url" {
  description = "Configured Knowledge Portal URL, or null when the Portal has not been deployed/configured."
  value       = var.knowledge_portal_public_url != "" ? var.knowledge_portal_public_url : null
}

output "agent_url" {
  description = "HTTPS URL of the private LangGraph Agent Cloud Run service."
  value       = try(google_cloud_run_v2_service.agent[0].uri, null)
}

output "adapter_url" {
  description = "HTTPS URL of the public Teams Adapter Cloud Run service."
  value       = try(google_cloud_run_v2_service.adapter[0].uri, null)
}

output "teams_bot_endpoint" {
  description = "Teams Developer Portal bot messaging endpoint."
  value       = local.deploy_cloud_run ? "${google_cloud_run_v2_service.adapter[0].uri}/api/messages" : null
}

output "teams_developer_portal_runbook" {
  description = "Links for configuring the bot in Teams Developer Portal."
  value = local.deploy_cloud_run ? {
    messaging_endpoint = "${google_cloud_run_v2_service.adapter[0].uri}/api/messages"
    runbook_doc        = "docs/teams-app-setup.md"
    smoke_check        = "${google_cloud_run_v2_service.adapter[0].uri}/readyz"
  } : null
}

output "agent_service_account_email" {
  value = google_service_account.agent.email
}

output "adapter_service_account_email" {
  value = google_service_account.adapter.email
}

output "artifact_registry_repository" {
  value = google_artifact_registry_repository.teams_agent.name
}

output "secret_names" {
  value = {
    google_api_key              = google_secret_manager_secret.google_api_key.secret_id
    bot_client_secret           = google_secret_manager_secret.bot_client_secret.secret_id
    asset_signing_key           = google_secret_manager_secret.asset_signing_key.secret_id
    knowledge_delegation_secret = google_secret_manager_secret.knowledge_delegation_secret.secret_id
  }
}

output "knowledge_portal_internal_url" {
  description = "Internal URL of the Knowledge Portal service for Backoffice BFF."
  value       = var.knowledge_portal_internal_url != "" ? var.knowledge_portal_internal_url : null
}

output "firestore_database_id" {
  value = google_firestore_database.default.name
}
