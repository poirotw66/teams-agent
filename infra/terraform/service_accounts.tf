resource "google_service_account" "agent" {
  account_id   = var.agent_service_account_id
  display_name = "Teams LangGraph RAG Agent"
  project      = var.project_id
}

resource "google_service_account" "adapter" {
  account_id   = var.adapter_service_account_id
  display_name = "Teams Bot Adapter"
  project      = var.project_id
}
