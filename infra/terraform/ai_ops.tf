variable "backoffice_service_name" {
  description = "Cloud Run service name for AI Ops Backoffice."
  type        = string
  default     = "teams-ai-ops-backoffice"
}

variable "backoffice_service_account_id" {
  description = "Service account ID for AI Ops Backoffice."
  type        = string
  default     = "teams-ai-ops-backoffice"
}

variable "ops_events_collection" {
  type    = string
  default = "operational_events"
}

variable "ops_audit_collection" {
  type    = string
  default = "audit_events"
}

variable "ops_bigquery_dataset" {
  type    = string
  default = "ai_ops_analytics"
}

variable "ops_bigquery_table" {
  type    = string
  default = "operational_events"
}

variable "backoffice_image" {
  description = "Immutable Backoffice container image."
  type        = string
  default     = ""
}

resource "google_service_account" "backoffice" {
  account_id   = var.backoffice_service_account_id
  display_name = "AI Ops Backoffice"
  project      = var.project_id
}

resource "google_project_iam_member" "backoffice_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.backoffice.email}"
}

resource "google_project_iam_member" "backoffice_bigquery" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.backoffice.email}"
}

resource "google_bigquery_dataset" "ai_ops" {
  depends_on = [google_project_service.required]

  dataset_id = var.ops_bigquery_dataset
  project    = var.project_id
  location   = var.region
}

resource "google_bigquery_table" "operational_events" {
  dataset_id = google_bigquery_dataset.ai_ops.dataset_id
  project    = var.project_id
  table_id   = var.ops_bigquery_table

  schema = jsonencode([
    { name = "event_id", type = "STRING", mode = "REQUIRED" },
    { name = "event_type", type = "STRING", mode = "REQUIRED" },
    { name = "occurred_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "conversation_id", type = "STRING", mode = "NULLABLE" },
    { name = "correlation_id", type = "STRING", mode = "NULLABLE" },
    { name = "issue_type_id", type = "STRING", mode = "NULLABLE" },
    { name = "payload", type = "JSON", mode = "NULLABLE" },
  ])
}

resource "google_firestore_field" "ops_events_retention_ttl" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = var.ops_events_collection
  field      = "retention_expires_at"

  ttl_config {}
}

resource "google_firestore_field" "ops_audit_retention_ttl" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = var.ops_audit_collection
  field      = "retention_expires_at"

  ttl_config {}
}

resource "google_cloud_run_v2_service" "backoffice" {
  count = local.deploy_cloud_run ? 1 : 0

  depends_on = [
    google_project_service.required,
    google_bigquery_dataset.ai_ops,
    terraform_data.image_policy,
  ]

  name     = var.backoffice_service_name
  location = var.region
  project  = var.project_id
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account                  = google_service_account.backoffice.email
    timeout                          = "60s"
    max_instance_request_concurrency = 20

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = local.backoffice_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      dynamic "env" {
        for_each = local.backoffice_env
        content {
          name  = env.key
          value = env.value
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
