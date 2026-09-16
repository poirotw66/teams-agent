locals {
  knowledge_release_bucket_name = (
    var.knowledge_release_bucket_name != ""
    ? var.knowledge_release_bucket_name
    : "${var.project_id}-knowledge-releases"
  )
}

resource "google_storage_bucket" "knowledge_releases" {
  depends_on = [google_project_service.required]

  name                        = local.knowledge_release_bucket_name
  project                     = var.project_id
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }
}

resource "google_storage_bucket_iam_member" "agent_knowledge_reader" {
  bucket = google_storage_bucket.knowledge_releases.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.agent.email}"
}

resource "google_storage_bucket_iam_member" "knowledge_release_writers" {
  for_each = var.knowledge_release_writer_members

  bucket = google_storage_bucket.knowledge_releases.name
  role   = "roles/storage.objectCreator"
  member = each.value
}
