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

variable "environment_name" {
  description = "Runtime and data-governance environment. This is independent from deployment_phase and must be one of dev, test, poc, or prod."
  type        = string
  default     = "poc"

  validation {
    condition     = contains(["dev", "test", "poc", "prod"], var.environment_name)
    error_message = "environment_name must be dev, test, poc, or prod; deployment workflow values such as prepare, activate, and full are not environments."
  }
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

variable "conversation_retention_days" {
  description = "Default retention for raw conversation detail. Production policy is one year; test environments may use a shorter value to exercise TTL deletion."
  type        = number
  default     = 365

  validation {
    condition     = var.conversation_retention_days > 0 && var.conversation_retention_days <= 365
    error_message = "conversation_retention_days must be between 1 and 365 days; the policy maximum is one year."
  }
}

variable "handoff_retention_days" {
  description = "Default retention for handoff detail. Production policy is one year; test environments may use a shorter value to exercise TTL deletion."
  type        = number
  default     = 365

  validation {
    condition     = var.handoff_retention_days > 0 && var.handoff_retention_days <= 365
    error_message = "handoff_retention_days must be between 1 and 365 days; the policy maximum is one year."
  }
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

variable "vertex_ai_project" {
  description = "Explicit Vertex Gemini billing/IAM project. Required before Cloud Run activate/full. Never inferred from project_id."
  type        = string
  default     = ""
}

variable "vertex_ai_chat_location" {
  description = "Vertex chat endpoint location. Required before Cloud Run activate/full. The unapproved P0 placeholder global is rejected."
  type        = string
  default     = ""

  validation {
    condition     = lower(trimspace(var.vertex_ai_chat_location)) != "global"
    error_message = "vertex_ai_chat_location cannot be the unapproved P0 placeholder \"global\". Set a BU-approved Vertex location or leave empty until Cloud Run is activated."
  }
}

variable "vertex_ai_embedding_location" {
  description = "Vertex embedding endpoint location. Required before Cloud Run activate/full. The unapproved P0 placeholder global is rejected."
  type        = string
  default     = ""

  validation {
    condition     = lower(trimspace(var.vertex_ai_embedding_location)) != "global"
    error_message = "vertex_ai_embedding_location cannot be the unapproved P0 placeholder \"global\". Set a BU-approved Vertex location or leave empty until Cloud Run is activated."
  }
}

variable "vertex_ai_pdf_location" {
  description = "Vertex PDF Vision endpoint location. Required when the converter or gemini_vision is in play. The unapproved P0 placeholder global is rejected."
  type        = string
  default     = ""

  validation {
    condition     = lower(trimspace(var.vertex_ai_pdf_location)) != "global"
    error_message = "vertex_ai_pdf_location cannot be the unapproved P0 placeholder \"global\". Set a BU-approved Vertex location or leave empty until Vision is activated."
  }
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
  default = "google_genai:gemini-3.1-flash-lite"
}

variable "agent_model" {
  type    = string
  default = "google_genai:gemini-3.8-flash"
}

variable "rag_embedding_model" {
  type    = string
  default = "google_genai:gemini-embedding-2"
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

variable "ticket_service_mode" {
  description = "Agent ticket integration mode."
  type        = string
  default     = "DISABLED"

  validation {
    condition     = contains(["DISABLED", "HTTP"], var.ticket_service_mode)
    error_message = "ticket_service_mode must be DISABLED or HTTP."
  }
}

variable "ticket_service_base_url" {
  description = "Ticket service base URL when ticket_service_mode is HTTP."
  type        = string
  default     = ""
}

variable "ticket_service_token_secret_id" {
  description = "Existing Secret Manager secret ID for the ticket service token."
  type        = string
  default     = ""
}

variable "agent_ops_bigquery_enabled" {
  description = "Whether the Agent writes operational events to BigQuery."
  type        = bool
  default     = true
}

variable "agent_ops_delivery_inline_sinks" {
  description = "Whether Agent request handling writes operational sinks inline."
  type        = bool
  default     = true
}

variable "adapter_public_base_url" {
  description = "Public HTTPS URL of the Adapter Cloud Run service for BOT_PUBLIC_BASE_URL."
  type        = string
  default     = ""
}

variable "knowledge_portal_public_url" {
  description = "Optional approved external Portal URL override. The internal Terraform-managed Portal URL is never inferred from the Teams Adapter URL."
  type        = string
  default     = ""

  validation {
    condition     = var.knowledge_portal_public_url == "" || can(regex("^https://", var.knowledge_portal_public_url))
    error_message = "knowledge_portal_public_url must be an https URL when set."
  }
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

variable "knowledge_release_bucket_name" {
  description = "GCS bucket for immutable tenant knowledge releases. Defaults to <project>-knowledge-releases."
  type        = string
  default     = ""
}

variable "knowledge_release_object_prefix" {
  description = "Object prefix containing tenants/<tenant>/releases/<release>."
  type        = string
  default     = "knowledge-releases"
}

variable "knowledge_release_writer_members" {
  description = "Additional IAM members allowed to create immutable knowledge release objects, normally the Portal service account."
  type        = set(string)
  default     = []
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

variable "knowledge_delegation_secret_id" {
  description = "Secret Manager secret ID for Knowledge Portal delegation secret."
  type        = string
  default     = "teams-agent-knowledge-delegation-secret"
}

variable "knowledge_bridge_enabled" {
  description = "Whether to enable the AI Ops Backoffice Knowledge Bridge (BFF)."
  type        = bool
  default     = true
}

variable "knowledge_portal_internal_url" {
  description = "Internal URL of the Knowledge Portal service for Backoffice BFF."
  type        = string
  default     = ""
}

variable "enable_pdf_converter" {
  description = "Manage the standalone PDF converter Cloud Run service. For a live unmanaged converter, pin pdf_converter_image to the running digest and import before apply; do not create a second service."
  type        = bool
  default     = false
}

variable "pdf_converter_service_name" {
  description = "Cloud Run service name for the PDF converter."
  type        = string
  default     = "teams-pdf-converter"
}

variable "pdf_converter_service_account_id" {
  description = "Dedicated service account ID for the PDF converter."
  type        = string
  default     = "teams-pdf-converter"
}

variable "pdf_converter_image" {
  description = "Immutable PDF converter image pinned by commit SHA tag or sha256 digest. When importing a live service, use that revision's digest; do not invent a new pin."
  type        = string
  default     = ""
}

variable "pdf_converter_existing_url" {
  description = "Already-running PDF converter URL. Preferred for Portal Vision so a Vertex apply cannot clear the converter before import."
  type        = string
  default     = ""
}

variable "portal_pdf_converter_engine" {
  description = "Portal PDF engine override. Empty keeps gemini_vision whenever a converter URL exists. Set legacy_text only to explicitly park Vision."
  type        = string
  default     = ""

  validation {
    condition     = contains(["", "gemini_vision", "legacy_text"], var.portal_pdf_converter_engine)
    error_message = "portal_pdf_converter_engine must be empty, gemini_vision, or legacy_text."
  }
}

variable "pdf_converter_max_instances" {
  type    = number
  default = 2
}
