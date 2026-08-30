locals {
  agent_service_account_email   = "${var.agent_service_account_id}@${var.project_id}.iam.gserviceaccount.com"
  adapter_service_account_email = "${var.adapter_service_account_id}@${var.project_id}.iam.gserviceaccount.com"
  artifact_registry_path        = "${var.region}-docker.pkg.dev/${var.project_id}/${var.artifact_repository_id}"

  agent_image   = var.agent_image != "" ? var.agent_image : "${local.artifact_registry_path}/${var.agent_service_name}:latest"
  adapter_image = var.adapter_image != "" ? var.adapter_image : "${local.artifact_registry_path}/${var.adapter_service_name}:latest"

  required_apis = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com",
    "iamcredentials.googleapis.com",
    "firestore.googleapis.com",
  ])

  agent_env = {
    LOG_LEVEL                          = "INFO"
    RAG_DATA_DIR                       = "/app/data"
    RAG_INDEX_PATH                     = "/app/data/index/chunks.json"
    RAG_AUTO_BUILD_INDEX               = "false"
    RAG_MODEL                          = var.rag_model
    AGENT_MODEL                        = var.agent_model
    RAG_EMBEDDING_MODEL                = var.rag_embedding_model
    RAG_ALLOWED_TENANTS                = var.rag_allowed_tenants
    RAG_MAX_IMAGES                     = "2"
    KNOWLEDGE_SERVICE_MODE             = "HYBRID"
    GEMINI_FILE_SEARCH_STORE           = var.gemini_file_search_store
    GEMINI_FILE_SEARCH_MODEL           = var.gemini_file_search_model
    GEMINI_FILE_SEARCH_ENFORCE_ACL     = tostring(var.gemini_file_search_enforce_acl)
    RAG_REQUIRE_FILE_SEARCH_ACL        = tostring(var.rag_require_file_search_acl)
    KNOWLEDGE_BACKEND_STATE_MODE       = "FIRESTORE"
    KNOWLEDGE_BACKEND_STATE_COLLECTION = var.knowledge_backend_state_collection
    KNOWLEDGE_BACKEND_ADMIN_ENABLED    = tostring(var.knowledge_backend_admin_enabled)
    TICKET_REQUEST_DEDUPE_MODE         = var.ticket_request_dedupe_mode
    TICKET_REQUEST_DEDUPE_COLLECTION   = var.ticket_request_dedupe_collection
    TICKET_SERVICE_MODE                = "DISABLED"
    CONVERSATION_REPOSITORY_MODE       = "FIRESTORE"
    CONVERSATION_FIRESTORE_COLLECTION  = var.firestore_conversations_collection
    CONVERSATION_RETENTION_DAYS        = "730"
    HANDOFF_REPOSITORY_MODE            = "FIRESTORE"
    HANDOFF_FIRESTORE_COLLECTION       = var.firestore_handoffs_collection
    HANDOFF_DEMO_TIMEOUT_HOURS         = "24"
    HANDOFF_RETENTION_DAYS             = "730"
    FEEDBACK_ENABLED                   = "true"
  }

  adapter_env = {
    LOG_LEVEL                 = "INFO"
    AGENT_MODE                = "api"
    AGENT_API_AUTH_MODE       = "google_id_token"
    AGENT_API_TIMEOUT_SECONDS = "30"
    CLIENT_ID                 = var.bot_client_id
    TENANT_ID                 = var.bot_tenant_id
    TEAMS_INBOUND_AUTH_MODE   = "both"
    RAG_ASSET_DIR             = "/app/data/assets"
    RAG_ASSET_URL_TTL_SECONDS = "3600"
    RAG_ASSET_MAX_DIMENSION   = "1024"
    RAG_ASSET_MAX_BYTES       = "1000000"
  }
}
