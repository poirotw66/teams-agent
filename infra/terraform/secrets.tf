resource "google_secret_manager_secret" "google_api_key" {
  depends_on = [google_project_service.required]

  project   = var.project_id
  secret_id = var.google_api_secret_id

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "bot_client_secret" {
  depends_on = [google_project_service.required]

  project   = var.project_id
  secret_id = var.bot_client_secret_id

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "asset_signing_key" {
  depends_on = [google_project_service.required]

  project   = var.project_id
  secret_id = var.asset_signing_secret_id

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "agent_google_api_key" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.google_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.agent.email}"
}

resource "google_secret_manager_secret_iam_member" "adapter_bot_client_secret" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.bot_client_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.adapter.email}"
}

resource "google_secret_manager_secret_iam_member" "adapter_asset_signing_key" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.asset_signing_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.adapter.email}"
}

resource "google_secret_manager_secret" "knowledge_delegation_secret" {
  depends_on = [google_project_service.required]

  project   = var.project_id
  secret_id = var.knowledge_delegation_secret_id

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "backoffice_knowledge_delegation_secret" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.knowledge_delegation_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backoffice.email}"
}

