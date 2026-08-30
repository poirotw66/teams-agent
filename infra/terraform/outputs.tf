output "agent_url" {
  description = "HTTPS URL of the private LangGraph Agent Cloud Run service."
  value       = google_cloud_run_v2_service.agent.uri
}

output "adapter_url" {
  description = "HTTPS URL of the public Teams Adapter Cloud Run service."
  value       = google_cloud_run_v2_service.adapter.uri
}

output "teams_bot_endpoint" {
  description = "Teams Developer Portal bot messaging endpoint."
  value       = "${google_cloud_run_v2_service.adapter.uri}/api/messages"
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
    google_api_key    = google_secret_manager_secret.google_api_key.secret_id
    bot_client_secret = google_secret_manager_secret.bot_client_secret.secret_id
    asset_signing_key = google_secret_manager_secret.asset_signing_key.secret_id
  }
}

output "firestore_database_id" {
  value = google_firestore_database.default.name
}
