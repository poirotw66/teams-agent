locals {
  deploy_cloud_run              = contains(["activate", "full"], var.deployment_phase)
  firestore_location_id         = coalesce(var.firestore_location_id, var.region)
  agent_service_account_email   = "${var.agent_service_account_id}@${var.project_id}.iam.gserviceaccount.com"
  adapter_service_account_email = "${var.adapter_service_account_id}@${var.project_id}.iam.gserviceaccount.com"
  artifact_registry_path        = "${var.region}-docker.pkg.dev/${var.project_id}/${var.artifact_repository_id}"

  agent_image = var.agent_image != "" ? var.agent_image : (
    var.allow_latest_image_tags
    ? "${local.artifact_registry_path}/${var.agent_service_name}:latest"
    : null
  )
  adapter_image = var.adapter_image != "" ? var.adapter_image : (
    var.allow_latest_image_tags
    ? "${local.artifact_registry_path}/${var.adapter_service_name}:latest"
    : null
  )
  backoffice_image = var.backoffice_image != "" ? var.backoffice_image : (
    var.allow_latest_image_tags
    ? "${local.artifact_registry_path}/${var.backoffice_service_name}:latest"
    : null
  )

  required_apis = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com",
    "iamcredentials.googleapis.com",
    "firestore.googleapis.com",
    "bigquery.googleapis.com",
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
    KNOWLEDGE_RELEASE_MODE             = var.knowledge_release_mode
    KNOWLEDGE_RELEASE_DIR              = var.knowledge_release_dir
    FEEDBACK_ENABLED                   = "true"
    OPS_EVENTS_ENABLED                 = "true"
    OPS_STORE_MODE                     = "FIRESTORE"
    OPS_AUDIT_STORE_MODE               = "FIRESTORE"
    OPS_FIRESTORE_COLLECTION           = var.ops_events_collection
    OPS_AUDIT_FIRESTORE_COLLECTION     = var.ops_audit_collection
    OPS_BIGQUERY_ENABLED               = "true"
    OPS_BIGQUERY_DATASET               = var.ops_bigquery_dataset
    OPS_BIGQUERY_TABLE                 = var.ops_bigquery_table
  }

  backoffice_env = {
    AI_OPS_BACKOFFICE_PORT             = "8080"
    AI_OPS_BACKOFFICE_AUTH_MODE        = "HEADER"
    OPS_STORE_MODE                     = "FIRESTORE"
    OPS_AUDIT_STORE_MODE               = "FIRESTORE"
    OPS_FIRESTORE_COLLECTION           = var.ops_events_collection
    OPS_AUDIT_FIRESTORE_COLLECTION     = var.ops_audit_collection
    KNOWLEDGE_PORTAL_PUBLIC_URL        = var.adapter_public_base_url != "" ? var.adapter_public_base_url : ""
    KNOWLEDGE_PORTAL_AGENT_API_URL     = local.deploy_cloud_run ? google_cloud_run_v2_service.agent[0].uri : ""
    TEAMS_ADAPTER_URL                  = local.deploy_cloud_run ? google_cloud_run_v2_service.adapter[0].uri : ""
    RAG_DATA_DIR                       = "/app/data"
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

resource "terraform_data" "image_policy" {
  count = local.deploy_cloud_run ? 1 : 0

  lifecycle {
    precondition {
      condition     = local.agent_image != null && local.adapter_image != null && local.backoffice_image != null
      error_message = "Set agent_image, adapter_image, and backoffice_image to immutable tags or digests. allow_latest_image_tags=true is import-only for existing POC."
    }

    precondition {
      condition     = var.adapter_public_base_url == "" || can(regex("^https://", var.adapter_public_base_url))
      error_message = "adapter_public_base_url must be an https URL when set."
    }

    precondition {
      condition = !var.allow_latest_image_tags || (
        (var.agent_image == "" || endswith(var.agent_image, ":latest")) &&
        (var.adapter_image == "" || endswith(var.adapter_image, ":latest")) &&
        (var.backoffice_image == "" || endswith(var.backoffice_image, ":latest"))
      )
      error_message = "When allow_latest_image_tags=true, omit images or use :latest explicitly for import workflows only."
    }
  }
}
