variable "ops_alert_email" {
  description = "Optional email address for AI Ops monitoring alerts."
  type        = string
  default     = ""
}

resource "google_monitoring_notification_channel" "ops_alerts" {
  count = local.deploy_cloud_run && var.ops_alert_email != "" ? 1 : 0

  depends_on = [google_project_service.required]

  display_name = "AI Ops Backoffice Alerts"
  type         = "email"
  project      = var.project_id

  labels = {
    email_address = var.ops_alert_email
  }
}

resource "google_monitoring_alert_policy" "backoffice_5xx" {
  count = local.deploy_cloud_run ? 1 : 0

  depends_on = [google_project_service.required]

  display_name = "AI Ops Backoffice 5xx errors"
  project      = var.project_id
  combiner     = "OR"

  conditions {
    display_name = "Cloud Run 5xx request rate"

    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.backoffice_service_name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 5

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }

  notification_channels = var.ops_alert_email != "" ? [
    google_monitoring_notification_channel.ops_alerts[0].name,
  ] : []

  alert_strategy {
    auto_close = "1800s"
  }
}

resource "google_monitoring_dashboard" "ai_ops" {
  count = local.deploy_cloud_run ? 1 : 0

  depends_on = [google_project_service.required]

  dashboard_json = jsonencode({
    displayName = "AI Ops Backoffice"
    mosaicLayout = {
      columns = 12
      tiles = [
        {
          width  = 6
          height = 4
          widget = {
            title = "Backoffice request rate"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.backoffice_service_name}\" AND metric.type=\"run.googleapis.com/request_count\""
                    aggregation = {
                      alignmentPeriod    = "60s"
                      perSeriesAligner   = "ALIGN_RATE"
                      crossSeriesReducer = "REDUCE_SUM"
                    }
                  }
                }
              }]
            }
          }
        },
        {
          xPos   = 6
          width  = 6
          height = 4
          widget = {
            title = "Backoffice 5xx errors"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.backoffice_service_name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\""
                    aggregation = {
                      alignmentPeriod    = "60s"
                      perSeriesAligner   = "ALIGN_RATE"
                      crossSeriesReducer = "REDUCE_SUM"
                    }
                  }
                }
              }]
            }
          }
        },
        {
          yPos   = 4
          width  = 6
          height = 4
          widget = {
            title = "Backoffice latency P95"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.backoffice_service_name}\" AND metric.type=\"run.googleapis.com/request_latencies\""
                    aggregation = {
                      alignmentPeriod    = "60s"
                      perSeriesAligner   = "ALIGN_DELTA"
                      crossSeriesReducer = "REDUCE_PERCENTILE_95"
                    }
                  }
                }
              }]
            }
          }
        },
      ]
    }
  })
}
