variable "project_id" {
  description = "GCP project ID for the POC environment."
  type        = string
}

variable "region" {
  description = "Primary GCP region for Cloud Run, Artifact Registry, and Firestore."
  type        = string
  default     = "asia-east1"
}

variable "artifact_repository_id" {
  description = "Artifact Registry repository ID for container images."
  type        = string
  default     = "teams-agent"
}

variable "agent_service_name" {
  description = "Cloud Run service name for the LangGraph Agent."
  type        = string
  default     = "teams-rag-agent"
}

variable "adapter_service_name" {
  description = "Cloud Run service name for the Teams Adapter."
  type        = string
  default     = "teams-agent-adapter"
}

variable "agent_service_account_id" {
  description = "Service account ID (short name) for the Agent service."
  type        = string
  default     = "teams-rag-agent"
}

variable "adapter_service_account_id" {
  description = "Service account ID (short name) for the Adapter service."
  type        = string
  default     = "teams-agent-adapter"
}

variable "firestore_database_id" {
  description = "Firestore database ID. Use (default) for the primary database."
  type        = string
  default     = "(default)"
}

variable "firestore_location_id" {
  description = "Firestore multi-region or region location."
  type        = string
  default     = "asia-east1"
}

variable "firestore_conversations_collection" {
  type    = string
  default = "conversations"
}

variable "firestore_handoffs_collection" {
  type    = string
  default = "handoffs"
}

variable "knowledge_backend_state_collection" {
  type    = string
  default = "runtime_config"
}

variable "ticket_request_dedupe_collection" {
  type    = string
  default = "ticket_request_ledger"
}

variable "google_api_secret_id" {
  type    = string
  default = "teams-agent-google-api-key"
}

variable "bot_client_secret_id" {
  type    = string
  default = "teams-agent-bot-client-secret"
}

variable "asset_signing_secret_id" {
  type    = string
  default = "teams-agent-asset-signing-key"
}

variable "agent_image" {
  description = "Container image for the Agent service. Release pipeline owns updates; Terraform ignores image drift after initial import."
  type        = string
  default     = ""
}

variable "adapter_image" {
  description = "Container image for the Adapter service. Release pipeline owns updates; Terraform ignores image drift after initial import."
  type        = string
  default     = ""
}

variable "rag_model" {
  type    = string
  default = "gemini-2.5-flash"
}

variable "agent_model" {
  type    = string
  default = ""
}

variable "rag_embedding_model" {
  type    = string
  default = "text-embedding-004"
}

variable "rag_allowed_tenants" {
  type    = string
  default = ""
}

variable "bot_client_id" {
  description = "Entra application (client) ID for the Teams bot. Not a secret."
  type        = string
}

variable "bot_tenant_id" {
  description = "Entra tenant ID for the Teams bot. Not a secret."
  type        = string
}

variable "gemini_file_search_store" {
  type    = string
  default = "fileSearchStores/helpdeskstore-1p3gu83qot1s"
}

variable "gemini_file_search_model" {
  type    = string
  default = "gemini-2.5-flash"
}

variable "gemini_file_search_enforce_acl" {
  type    = bool
  default = true
}

variable "rag_require_file_search_acl" {
  type    = bool
  default = true
}

variable "knowledge_backend_admin_enabled" {
  type    = bool
  default = false
}

variable "ticket_request_dedupe_mode" {
  type    = string
  default = "FIRESTORE"
}

variable "adapter_public_base_url" {
  description = "Public HTTPS URL of the Adapter Cloud Run service for BOT_PUBLIC_BASE_URL. Set after first deploy/import for zero-diff plans."
  type        = string
  default     = ""
}
