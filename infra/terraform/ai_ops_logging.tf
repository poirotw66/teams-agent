variable "ops_logs_dataset" {
  description = "BigQuery dataset for Cloud Run structured log exports."
  type        = string
  default     = "ai_ops_logs"
}

resource "google_bigquery_dataset" "ai_ops_logs" {
  count = local.deploy_cloud_run ? 1 : 0

  depends_on = [google_project_service.required]

  dataset_id = var.ops_logs_dataset
  project    = var.project_id
  location   = var.region
}

resource "google_logging_project_sink" "backoffice_logs" {
  count = local.deploy_cloud_run ? 1 : 0

  depends_on = [google_project_service.required]

  name        = "ai-ops-backoffice-logs"
  project     = var.project_id
  destination = "bigquery.googleapis.com/projects/${var.project_id}/datasets/${var.ops_logs_dataset}"
  filter      = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.backoffice_service_name}\""

  unique_writer_identity = true

  bigquery_options {
    use_partitioned_tables = true
  }
}

resource "google_logging_project_sink" "agent_logs" {
  count = local.deploy_cloud_run ? 1 : 0

  depends_on = [google_project_service.required]

  name        = "ai-ops-agent-logs"
  project     = var.project_id
  destination = "bigquery.googleapis.com/projects/${var.project_id}/datasets/${var.ops_logs_dataset}"
  filter      = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.agent_service_name}\""

  unique_writer_identity = true

  bigquery_options {
    use_partitioned_tables = true
  }
}

resource "google_bigquery_dataset_iam_member" "backoffice_log_sink_writer" {
  count = local.deploy_cloud_run ? 1 : 0

  dataset_id = google_bigquery_dataset.ai_ops_logs[0].dataset_id
  project    = var.project_id
  role       = "roles/bigquery.dataEditor"
  member     = google_logging_project_sink.backoffice_logs[0].writer_identity
}

resource "google_bigquery_dataset_iam_member" "agent_log_sink_writer" {
  count = local.deploy_cloud_run ? 1 : 0

  dataset_id = google_bigquery_dataset.ai_ops_logs[0].dataset_id
  project    = var.project_id
  role       = "roles/bigquery.dataEditor"
  member     = google_logging_project_sink.agent_logs[0].writer_identity
}
