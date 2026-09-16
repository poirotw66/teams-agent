variable "portal_service_name" {
  description = "Cloud Run service name for the Knowledge Portal."
  type        = string
  default     = "teams-knowledge-portal"
}

variable "portal_service_account_id" {
  description = "Service account ID for the Knowledge Portal."
  type        = string
  default     = "teams-knowledge-portal"
}

variable "portal_image" {
  description = "Immutable Knowledge Portal container image."
  type        = string
  default     = ""
}

variable "knowledge_portal_token_secret_id" {
  description = "Secret Manager secret ID for Portal service authentication."
  type        = string
  default     = "teams-knowledge-portal-token"
}

resource "google_service_account" "portal" {
  account_id   = var.portal_service_account_id
  display_name = "Knowledge Portal"
  project      = var.project_id
}

resource "google_project_iam_member" "portal_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.portal.email}"
}

resource "google_storage_bucket_iam_member" "portal_knowledge_writer" {
  bucket = google_storage_bucket.knowledge_releases.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.portal.email}"
}

resource "google_secret_manager_secret" "knowledge_portal_token" {
  depends_on = [google_project_service.required]

  project   = var.project_id
  secret_id = var.knowledge_portal_token_secret_id

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "portal_service_token" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.knowledge_portal_token.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.portal.email}"
}

resource "google_secret_manager_secret_iam_member" "portal_google_api_key" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.google_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.portal.email}"
}

resource "google_secret_manager_secret_iam_member" "portal_delegation_secret" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.knowledge_delegation_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.portal.email}"
}

resource "google_cloud_run_v2_service" "portal" {
  count = local.deploy_cloud_run ? 1 : 0

  depends_on = [
    google_project_service.required,
    google_secret_manager_secret_iam_member.portal_service_token,
    google_secret_manager_secret_iam_member.portal_google_api_key,
    google_secret_manager_secret_iam_member.portal_delegation_secret,
    google_storage_bucket_iam_member.portal_knowledge_writer,
    terraform_data.image_policy,
  ]

  name     = var.portal_service_name
  location = var.region
  project  = var.project_id
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account                  = google_service_account.portal.email
    timeout                          = "600s"
    max_instance_request_concurrency = 8

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      image = local.portal_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "2Gi"
        }
      }

      env {
        name  = "KNOWLEDGE_PORTAL_REPOSITORY_MODE"
        value = "FIRESTORE"
      }

      env {
        name  = "KNOWLEDGE_PORTAL_AUTH_MODE"
        value = "HEADER"
      }

      env {
        name  = "KNOWLEDGE_PORTAL_REQUIRE_SERVICE_TOKEN_WITH_DELEGATION"
        value = "false"
      }

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }

      env {
        name  = "AGENT_DEPLOYMENT_ENV"
        value = var.environment_name
      }

      env {
        name  = "KNOWLEDGE_PORTAL_RELEASE_PURPOSE"
        value = "PRODUCTION"
      }

      env {
        name  = "RAG_EMBEDDING_MODEL"
        value = var.rag_embedding_model
      }

      env {
        name  = "KNOWLEDGE_PORTAL_RELEASE_GCS_BUCKET"
        value = google_storage_bucket.knowledge_releases.name
      }

      env {
        name  = "KNOWLEDGE_PORTAL_RELEASE_GCS_PREFIX"
        value = var.knowledge_release_object_prefix
      }

      env {
        name  = "KNOWLEDGE_PORTAL_AGENT_API_URL"
        value = google_cloud_run_v2_service.agent[0].uri
      }

      env {
        name  = "KNOWLEDGE_PORTAL_AGENT_API_AUTH_MODE"
        value = "GOOGLE_ID_TOKEN"
      }

      env {
        name  = "KNOWLEDGE_PORTAL_PDF_CONVERTER_URL"
        value = local.deploy_pdf_converter ? google_cloud_run_v2_service.pdf_converter[0].uri : ""
      }

      env {
        name  = "KNOWLEDGE_PORTAL_PDF_CONVERTER_ENGINE"
        value = local.deploy_pdf_converter ? "gemini_vision" : "legacy_text"
      }

      env {
        name  = "KNOWLEDGE_PORTAL_PDF_CONVERTER_AUTH_MODE"
        value = local.deploy_pdf_converter ? "GOOGLE_ID_TOKEN" : "BEARER"
      }

      env {
        name  = "KNOWLEDGE_PORTAL_SOURCE_STORE_MODE"
        value = "FIRESTORE"
      }

      env {
        name = "KNOWLEDGE_PORTAL_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.knowledge_portal_token.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "GOOGLE_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.google_api_key.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "KNOWLEDGE_PORTAL_DELEGATION_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.knowledge_delegation_secret.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }
}

resource "google_cloud_run_v2_service_iam_member" "backoffice_invokes_portal" {
  count = local.deploy_cloud_run ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.portal[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.backoffice.email}"
}

resource "google_cloud_run_v2_service_iam_member" "portal_invokes_agent" {
  count = local.deploy_cloud_run ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.agent[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.portal.email}"
}
