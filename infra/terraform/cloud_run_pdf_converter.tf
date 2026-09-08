locals {
  deploy_pdf_converter = local.deploy_cloud_run && var.enable_pdf_converter
  pdf_converter_image = var.pdf_converter_image != "" ? var.pdf_converter_image : (
    "${local.artifact_registry_path}/${var.pdf_converter_service_name}:latest"
  )
}

resource "google_cloud_run_v2_service" "pdf_converter" {
  count = local.deploy_pdf_converter ? 1 : 0

  depends_on = [
    google_project_service.required,
    google_secret_manager_secret_iam_member.agent_google_api_key,
    terraform_data.image_policy,
  ]

  name     = var.pdf_converter_service_name
  location = var.region
  project  = var.project_id
  ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    service_account                  = google_service_account.agent.email
    timeout                          = "300s"
    max_instance_request_concurrency = 4

    scaling {
      min_instance_count = 0
      max_instance_count = var.pdf_converter_max_instances
    }

    containers {
      image = local.pdf_converter_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
      }

      env {
        name  = "PDF_CONVERTER_MODE"
        value = "legacy"
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

resource "google_cloud_run_v2_service_iam_member" "portal_invokes_pdf_converter" {
  count = local.deploy_pdf_converter ? 1 : 0

  depends_on = [google_cloud_run_v2_service.pdf_converter]
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.pdf_converter[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.agent.email}"
}
