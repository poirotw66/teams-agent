resource "google_firestore_database" "default" {
  depends_on = [google_project_service.required]

  project     = var.project_id
  name        = var.firestore_database_id
  location_id = local.firestore_location_id
  type        = "FIRESTORE_NATIVE"
}

resource "google_firestore_field" "conversations_expires_at_ttl" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = var.firestore_conversations_collection
  field      = "expiresAt"

  ttl_config {}
}

resource "google_firestore_field" "conversation_keys_expires_at_ttl" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = "${var.firestore_conversations_collection}_keys"
  field      = "expiresAt"

  ttl_config {}
}

resource "google_firestore_field" "messages_expires_at_ttl" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = "messages"
  field      = "expiresAt"

  ttl_config {}
}

resource "google_firestore_field" "handoffs_retention_ttl" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = var.firestore_handoffs_collection
  field      = "retentionExpiresAt"

  ttl_config {}
}

resource "google_firestore_field" "handoff_events_retention_ttl" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = "${var.firestore_handoffs_collection}_events"
  field      = "retentionExpiresAt"

  ttl_config {}
}
