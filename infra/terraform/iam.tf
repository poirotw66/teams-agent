resource "google_project_iam_member" "agent_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.agent.email}"
}

resource "google_cloud_run_v2_service_iam_member" "adapter_invokes_agent" {
  count = local.deploy_cloud_run ? 1 : 0

  depends_on = [google_cloud_run_v2_service.agent]

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.agent[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.adapter.email}"
}

resource "google_cloud_run_v2_service_iam_member" "adapter_public" {
  count = local.deploy_cloud_run ? 1 : 0

  depends_on = [google_cloud_run_v2_service.adapter]

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.adapter[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
