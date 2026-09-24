locals {
  deploy_pdf_converter = local.deploy_cloud_run && var.enable_pdf_converter
  pdf_converter_image = var.pdf_converter_image != "" ? var.pdf_converter_image : (
    var.allow_latest_image_tags
    ? "${local.artifact_registry_path}/${var.pdf_converter_service_name}:latest"
    : null
  )

  # Vertex mode must not park Vision. Keep gemini_vision when a converter URL
  # exists (managed service or already-running import target).
  portal_pdf_converter_url = (
    var.pdf_converter_existing_url != ""
    ? var.pdf_converter_existing_url
    : (local.deploy_pdf_converter ? google_cloud_run_v2_service.pdf_converter[0].uri : "")
  )
  portal_uses_pdf_vision = local.portal_pdf_converter_url != ""
  portal_pdf_converter_engine = (
    var.portal_pdf_converter_engine != ""
    ? var.portal_pdf_converter_engine
    : (local.portal_uses_pdf_vision ? "gemini_vision" : "legacy_text")
  )
  portal_pdf_converter_auth_mode = (
    local.portal_pdf_converter_engine == "gemini_vision"
    ? "GOOGLE_ID_TOKEN"
    : "BEARER"
  )
}

resource "google_service_account" "pdf_converter" {
  count = local.deploy_pdf_converter ? 1 : 0

  account_id   = var.pdf_converter_service_account_id
  display_name = "PDF Converter"
  project      = var.project_id
}

resource "google_project_iam_member" "pdf_converter_aiplatform_user" {
  count = local.deploy_pdf_converter && local.vertex_ai_project_is_explicit ? 1 : 0

  project = local.vertex_ai_project
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.pdf_converter[0].email}"
}

resource "google_cloud_run_v2_service" "pdf_converter" {
  count = local.deploy_pdf_converter ? 1 : 0

  depends_on = [
    google_project_service.required,
    terraform_data.image_policy,
    google_project_iam_member.pdf_converter_aiplatform_user,
  ]

  name     = var.pdf_converter_service_name
  location = var.region
  project  = var.project_id
  ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    service_account                  = google_service_account.pdf_converter[0].email
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
        value = "gemini"
      }

      env {
        name  = "GEMINI_MODEL"
        value = "gemini-3.8-flash"
      }

      env {
        name  = "GEMINI_API_BACKEND"
        value = "VERTEX_AI"
      }

      env {
        name  = "VERTEX_AI_PROJECT"
        value = local.vertex_ai_project
      }

      env {
        name  = "VERTEX_AI_PDF_LOCATION"
        value = local.vertex_ai_pdf_location
      }

      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "true"
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = local.vertex_ai_project
      }

      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = local.vertex_ai_pdf_location
      }
    }
  }

  lifecycle {
    precondition {
      condition = (
        local.pdf_converter_image != null && (
          can(regex("@sha256:[0-9a-f]{64}$", local.pdf_converter_image)) ||
          can(regex(":[0-9a-f]{7,40}$", local.pdf_converter_image)) ||
          (var.allow_latest_image_tags && endswith(local.pdf_converter_image, ":latest"))
        )
      )
      error_message = "enable_pdf_converter requires pdf_converter_image pinned to the live digest or commit SHA. allow_latest_image_tags=true is import-only."
    }

    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
      # Live gcloud revisions leave a service-level scaling block
      # (manual_instance_count / min_instance_count). That is operational
      # capacity, not the Vertex env contract. Reconciling it would mint a
      # dummy converter revision. Template-level min/max stays owned.
      scaling,
    ]
  }
}

resource "google_cloud_run_v2_service_iam_member" "portal_invokes_pdf_converter" {
  count = local.deploy_pdf_converter ? 1 : 0

  depends_on = [google_cloud_run_v2_service.pdf_converter]
  project    = var.project_id
  location   = var.region
  name       = google_cloud_run_v2_service.pdf_converter[0].name
  role       = "roles/run.invoker"
  member     = "serviceAccount:${google_service_account.portal.email}"
}
