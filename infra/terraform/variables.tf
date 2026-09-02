variable "project_id" {
  description = "GCP project ID."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid GCP project ID."
  }
}

variable "region" {
  description = "Primary GCP region for Cloud Run and Artifact Registry."
  type        = string
  default     = "asia-east1"
}

variable "firestore_location_id" {
  description = "Firestore location. Defaults to region when null."
  type        = string
  default     = null
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

variable "allow_latest_image_tags" {
  description = "Import-only escape hatch for existing POC environments. New projects must keep this false and pin images by commit SHA or digest."
  type        = bool
  default     = false
}

variable "agent_image" {
  description = "Immutable Agent container image (commit SHA tag or @sha256 digest)."
  type        = string
  default     = ""
}

variable "adapter_image" {
  description = "Immutable Adapter container image (commit SHA tag or @sha256 digest)."
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

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", var.bot_client_id))
    error_message = "bot_client_id must be a UUID."
  }
}

variable "bot_tenant_id" {
  description = "Entra tenant ID for the Teams bot. Not a secret."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", var.bot_tenant_id))
    error_message = "bot_tenant_id must be a UUID."
  }
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
  description = "Public HTTPS URL of the Adapter Cloud Run service for BOT_PUBLIC_BASE_URL."
  type        = string
  default     = ""
}

variable "deployment_phase" {
  description = "Greenfield bootstrap: prepare (foundation only), then activate (Cloud Run). Use full for POC import of an existing stack."
  type        = string
  default     = "full"

  validation {
    condition     = contains(["prepare", "activate", "full"], var.deployment_phase)
    error_message = "deployment_phase must be prepare, activate, or full."
  }
}

variable "knowledge_release_mode" {
  description = "How Agent Service loads the knowledge index: AUTO, PORTAL, or BUNDLED."
  type        = string
  default     = "PORTAL"

  validation {
    condition     = contains(["AUTO", "PORTAL", "BUNDLED"], var.knowledge_release_mode)
    error_message = "knowledge_release_mode must be AUTO, PORTAL, or BUNDLED."
  }
}

variable "knowledge_release_dir" {
  description = "Directory for portal release artifacts and active_release.json. Portal and Agent must share this path (or a GCS volume mount at the same mount point)."
  type        = string
  default     = "/app/data/releases"
}

variable "backoffice_auth_mode" {
  description = "Backoffice auth mode: ENTRA for production, HEADER for POC only."
  type        = string
  default     = "ENTRA"

  validation {
    condition     = contains(["ENTRA", "HEADER"], var.backoffice_auth_mode)
    error_message = "backoffice_auth_mode must be ENTRA or HEADER."
  }
}

variable "ai_ops_entra_client_id" {
  description = "Entra app registration client ID for AI Ops Backoffice. Defaults to bot_client_id when empty."
  type        = string
  default     = ""
}
