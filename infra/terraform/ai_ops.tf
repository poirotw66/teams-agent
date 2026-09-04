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

variable "ops_bigquery_deduplicated_view" {
  description = "Read-model view that selects one latest row per immutable operational event ID."
  type        = string
  default     = "operational_events_deduplicated"
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

resource "google_bigquery_dataset" "ai_ops" {
  depends_on = [google_project_service.required]

  dataset_id = var.ops_bigquery_dataset
  project    = var.project_id
  location   = var.region

  labels = {
    environment = var.environment_name
    managed_by  = "terraform"
    data_domain = "ai_ops"
  }
}

resource "google_bigquery_table" "operational_events" {
  dataset_id = google_bigquery_dataset.ai_ops.dataset_id
  project    = var.project_id
  table_id   = var.ops_bigquery_table

  require_partition_filter = true

  time_partitioning {
    type          = "DAY"
    field         = "occurred_at"
    expiration_ms = 31536000000
  }

  schema = jsonencode([
    { name = "event_id", type = "STRING", mode = "REQUIRED", description = "UUID idempotency key; retries reuse this value." },
    { name = "event_type", type = "STRING", mode = "REQUIRED" },
    { name = "schema_version", type = "INTEGER", mode = "REQUIRED" },
    { name = "occurred_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "ingested_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "environment", type = "STRING", mode = "REQUIRED" },
    { name = "tenant_id", type = "STRING", mode = "NULLABLE" },
    { name = "team_id", type = "STRING", mode = "NULLABLE" },
    { name = "channel_scope", type = "STRING", mode = "NULLABLE" },
    { name = "conversation_id", type = "STRING", mode = "NULLABLE" },
    { name = "turn_id", type = "STRING", mode = "NULLABLE" },
    { name = "request_id", type = "STRING", mode = "NULLABLE" },
    { name = "correlation_id", type = "STRING", mode = "REQUIRED" },
    { name = "issue_occurrence_id", type = "STRING", mode = "NULLABLE" },
    { name = "issue_type_id", type = "STRING", mode = "NULLABLE" },
    { name = "taxonomy_version", type = "STRING", mode = "NULLABLE" },
    { name = "actor_ref", type = "STRING", mode = "NULLABLE", description = "Pseudonymous actor reference only; never an email dashboard key." },
    { name = "data_classification", type = "STRING", mode = "REQUIRED" },
    { name = "masking_policy_version", type = "STRING", mode = "NULLABLE" },
    { name = "retention_expires_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "payload", type = "JSON", mode = "NULLABLE" },
  ])

  clustering = ["environment", "tenant_id", "event_type", "correlation_id"]
}

resource "google_bigquery_table" "operational_events_deduplicated" {
  dataset_id = google_bigquery_dataset.ai_ops.dataset_id
  project    = var.project_id
  table_id   = var.ops_bigquery_deduplicated_view

  view {
    use_legacy_sql = false
    query          = <<-SQL
      SELECT * EXCEPT (event_row_number)
      FROM (
        SELECT
          events.*,
          ROW_NUMBER() OVER (
            PARTITION BY event_id
            ORDER BY ingested_at DESC, occurred_at DESC
          ) AS event_row_number
        FROM `${var.project_id}.${var.ops_bigquery_dataset}.${var.ops_bigquery_table}` AS events
      )
      WHERE event_row_number = 1
    SQL
  }
}

resource "google_project_iam_member" "backoffice_bigquery_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.backoffice.email}"
}

resource "google_bigquery_dataset_iam_member" "backoffice_ai_ops_reader" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.ai_ops.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.backoffice.email}"
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

resource "google_firestore_index" "ops_events_by_issue_and_time" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = var.ops_events_collection

  fields {
    field_path = "issue_type_id"
    order      = "ASCENDING"
  }

  fields {
    field_path = "occurred_at"
    order      = "DESCENDING"
  }
}

resource "google_cloud_run_v2_service" "backoffice" {
  count = local.deploy_cloud_run ? 1 : 0

  depends_on = [
    google_project_service.required,
    google_bigquery_dataset.ai_ops,
    google_secret_manager_secret_iam_member.backoffice_knowledge_delegation_secret,
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

      env {
        name = "AI_OPS_KNOWLEDGE_DELEGATION_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.knowledge_delegation_secret.secret_id
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
