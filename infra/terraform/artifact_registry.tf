resource "google_artifact_registry_repository" "teams_agent" {
  depends_on = [google_project_service.required]

  project       = var.project_id
  location      = var.region
  repository_id = var.artifact_repository_id
  format        = "DOCKER"
  description   = "Teams AI Agent container images"
}
