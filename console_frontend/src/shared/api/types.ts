/** Type definitions for Console V2 APIs and entities */

export interface WorkItemAction {
  id: string;
  route: string;
}

export interface WorkItem {
  key: string;
  workflow: string;
  source_type: string;
  source_id: string;
  title: string;
  owner_unit_id: string;
  assignee_id: string | null;
  source_status: string;
  step: string;
  next_action: WorkItemAction;
  blocked_reason: string | null;
  due_at: string | null;
  updated_at: string;
  revision: string;
}

export interface WorkItemsResponse {
  items: WorkItem[];
  next_cursor: string | null;
  total: number;
  snapshot_id: string;
  generated_at: string;
  partial: boolean;
  sources: Record<string, string>;
}

export interface WorkSummaryResponse {
  total: number;
  by_bucket: {
    pending_action: number;
    pending_review: number;
    tracking: number;
    completed: number;
  };
  by_workflow: Record<string, number>;
  sources: Record<string, string>;
  snapshot_id: string;
  generated_at: string;
}

export interface EvidenceRef {
  source_type: string;
  source_id: string;
  version_hash: string | null;
  relation: string;
  occurred_at: string | null;
  retrieved_at: string;
  validity: "valid" | "stale" | "unknown" | "revoked";
}

export interface WorkflowStage {
  id: string;
  title: string;
  status: "pending" | "current" | "completed" | "skipped" | "failed";
}

export interface WorkflowDetailResponse {
  kind: string;
  id: string;
  title: string;
  status: string;
  stages: WorkflowStage[];
  evidence_refs: EvidenceRef[];
  allowed_actions: string[];
  return_route: string;
}

export interface UserCapabilities {
  user_id: string;
  user_name: string;
  role: string;
  owner_units: string[];
  capabilities: string[];
}

export interface HealthComponentStatus {
  status: "ok" | "degraded" | "unavailable" | "down";
  details?: Record<string, unknown>;
}

export interface SystemHealthResponse {
  status: "healthy" | "degraded" | "unhealthy";
  components: Record<string, HealthComponentStatus>;
  timestamp: string;
}

export interface ItTicketItem {
  id: string;
  ticket_number: string;
  title: string;
  reporter_name: string;
  reporter_dept: string;
  reporter_ext?: string;
  category: "HARDWARE" | "ACCESS" | "NETWORK" | "SOFTWARE";
  assigned_team: string;
  assigned_agent?: string;
  status: "DISPATCHED" | "IN_PROGRESS" | "RESOLVED" | "CANCELLED";
  conversation_id?: string;
  created_at: string;
  updated_at: string;
  resolution_note?: string;
}

export interface FaqItem {
  id: string;
  questions: string[];
  answer: string;
  category: string;
  is_active: boolean;
  updated_at: string;
  updated_by?: string;
}

export type ChunkQualityIssue = "SHORT" | "HEADING_ONLY" | "DUPLICATE";

export interface ManualChunkImage {
  path: string;
  filename: string;
  alt_text: string;
  content_type: string;
  url: string;
}

export interface ManualChunkItem {
  id: string;
  title: string;
  content_preview: string;
  content?: string;
  character_count?: number;
  page_number?: number;
  page_end?: number;
  token_count?: number;
  parent_id?: string;
  neighbor_ids?: string[];
  heading_path?: string[];
  content_hash?: string;
  parser_version?: string;
  chunker_version?: string;
  quality_issues?: ChunkQualityIssue[];
  images?: ManualChunkImage[];
  source_path?: string;
}

export type IngestionStage =
  | "UPLOADED"
  | "SCANNING"
  | "PARSING"
  | "CHUNK_REVIEW"
  | "INDEXING"
  | "EVALUATING"
  | "READY"
  | "ACTIVE"
  | "FAILED"
  | "CANCELLED";

export interface ChunkQualitySummary {
  acceptable: boolean;
  coverageRatio: number;
  sourceBlocks: number;
  coveredBlocks: number;
  chunkCount: number;
  shortChunkCount: number;
  headingOnlyCount: number;
  orphanMediaCount: number;
  duplicateChunkCount: number;
}

export interface ManualDocumentItem {
  id: string;
  title: string;
  file_name: string;
  file_size_bytes: number;
  version: string;
  version_id?: string;
  category: string;
  status:
    | "LIVE"
    | "DRAFT"
    | "PARSING"
    | "CHUNK_REVIEW"
    | "IN_REVIEW"
    | "APPROVED"
    | "CHANGES_REQUESTED"
    | "PUBLISHING"
    | "READY"
    | "FAILED"
    | "ARCHIVED";
  chunk_count: number;
  updated_at: string;
  updated_by: string;
  chunks?: ManualChunkItem[];
  chunking_profile?: "AUTO" | "SLIDE_DECK" | "MANUAL" | "POLICY";
  quality?: ChunkQualitySummary;
  ingestion_stage?: IngestionStage;
  job_id?: string;
  ingestion_warnings?: string[];
}

export interface KnowledgeGapItem {
  id: string;
  cluster_query: string;
  frequency: number;
  category: string;
  sample_conversations: string[];
  detected_at: string;
}

export interface CitationItem {
  document_id: string;
  document_title: string;
  similarity_score: number;
  snippet: string;
  updated_at: string;
  is_stale?: boolean;
}

export interface ChatMessage {
  id: string;
  sender: "user" | "bot" | "system";
  content: string;
  timestamp: string;
  feedback?: "positive" | "negative";
  feedback_comment?: string;
  citations?: CitationItem[];
}

export interface ConversationDetail {
  id: string;
  reporter_name: string;
  reporter_dept: string;
  reporter_ext: string;
  started_at: string;
  topic_summary: string;
  status: "PENDING_REVIEW" | "ESCALATED_TICKET" | "RESOLVED";
  root_cause?:
    "OUTDATED_DOC" | "MISSING_KNOWLEDGE" | "MISUNDERSTOOD" | "HARDWARE_TICKET";
  messages: ChatMessage[];
  associated_ticket_id?: string;
}

export interface DashboardKpiMetrics {
  total_inquiries_today: number;
  inquiries_trend_percentage: number;
  ai_resolution_rate: number;
  ai_resolved_count: number;
  escalated_ticket_count: number;
  satisfaction_rate: number;
  negative_feedback_count: number;
  urgent_attention_count: number;
}

export interface SpikeAlertItem {
  id: string;
  topic: string;
  affected_count: number;
  window_minutes: number;
  created_at: string;
  is_active: boolean;
  active_broadcast?: {
    message: string;
    expires_at: string;
  };
}

export interface TopFrequentTopic {
  id: string;
  rank: number;
  topic: string;
  count: number;
  resolution_rate: number;
}

export interface KnowledgeBlindSpot {
  id: string;
  category: string;
  status: "HEALTHY" | "NEEDS_UPDATE" | "HIGH_DEFECT";
  description: string;
  negative_rate: number;
}
