resource "google_cloud_run_v2_service" "agent" {
  count = local.deploy_cloud_run ? 1 : 0

  depends_on = [
    google_project_service.required,
    google_secret_manager_secret_iam_member.agent_google_api_key,
    terraform_data.image_policy,
  ]

  name     = var.agent_service_name
  location = var.region
  project  = var.project_id
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account                  = google_service_account.agent.email
    timeout                          = "90s"
    max_instance_request_concurrency = 8

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      image = local.agent_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "2Gi"
        }
      }

      dynamic "env" {
        for_each = local.agent_env
        content {
          name  = env.key
          value = env.value
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
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      template,
      scaling,
      client,
      client_version,
    ]
  }
}

resource "google_cloud_run_v2_service" "adapter" {
  count = local.deploy_cloud_run ? 1 : 0

  depends_on = [
    google_project_service.required,
    google_cloud_run_v2_service.agent,
    google_secret_manager_secret_iam_member.adapter_bot_client_secret,
    google_secret_manager_secret_iam_member.adapter_asset_signing_key,
    terraform_data.image_policy,
  ]

  name     = var.adapter_service_name
  location = var.region
  project  = var.project_id
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account                  = google_service_account.adapter.email
    timeout                          = "90s"
    max_instance_request_concurrency = 40

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      image = local.adapter_image

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
        for_each = merge(
          local.adapter_env,
          {
            AGENT_API_URL      = "${google_cloud_run_v2_service.agent[0].uri}/agent/chat"
            AGENT_API_AUDIENCE = google_cloud_run_v2_service.agent[0].uri
          },
          var.adapter_public_base_url != "" ? {
            BOT_PUBLIC_BASE_URL = var.adapter_public_base_url
          } : {}
        )
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name = "CLIENT_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.bot_client_secret.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "RAG_ASSET_SIGNING_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.asset_signing_key.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      template,
      scaling,
      client,
      client_version,
    ]
  }
}
