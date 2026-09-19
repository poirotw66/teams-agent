/**
 * AUTO-GENERATED FILE. DO NOT EDIT BY HAND.
 *
 * Source: docs/architecture/baselines/openapi/ai_ops_backoffice.openapi.json
 *
 * Regenerate:
 *   PYTHONPATH=agent_service/src uv run python scripts/snapshot_openapi.py --write
 *   PYTHONPATH=agent_service/src uv run python scripts/generate_openapi_ts.py --write
 *
 * CI freshness:
 *   PYTHONPATH=agent_service/src uv run python scripts/generate_openapi_ts.py --check
 */

/* eslint-disable */
/* prettier-ignore */

// Component schemas from ai_ops_backoffice OpenAPI (115 types).
export type BackofficeSchemas = {
  ActivatePolicyVersionPayload: ActivatePolicyVersionPayload;
  ActivateTargetPayload: ActivateTargetPayload;
  ApproveFixtureVersionPayload: ApproveFixtureVersionPayload;
  Body_upload_workbench_document_api_console_workbench_documents_upload_post: Body_upload_workbench_document_api_console_workbench_documents_upload_post;
  BroadcastRequest: BroadcastRequest;
  BudgetPolicyCreateRequest: BudgetPolicyCreateRequest;
  BudgetPolicyStateRequest: BudgetPolicyStateRequest;
  BudgetPolicyUpdateRequest: BudgetPolicyUpdateRequest;
  CancelRunPayload: CancelRunPayload;
  CandidateJobPayload: CandidateJobPayload;
  CaseCreatePayload: CaseCreatePayload;
  ChatMessage: ChatMessage;
  ChunkPreviewChunk: ChunkPreviewChunk;
  ChunkPreviewImageDto: ChunkPreviewImageDto;
  ChunkPreviewResponse: ChunkPreviewResponse;
  ChunkQualityIssue: ChunkQualityIssue;
  ChunkQualitySummary: ChunkQualitySummary;
  ChunkingProfile: ChunkingProfile;
  CitationItem: CitationItem;
  ConversationActionRequest: ConversationActionRequest;
  ConversationDetail: ConversationDetail;
  CreateFixtureVersionPayload: CreateFixtureVersionPayload;
  CreateGatePolicyPayload: CreateGatePolicyPayload;
  CreatePolicyVersionPayload: CreatePolicyVersionPayload;
  CreateQualityCasePayload: CreateQualityCasePayload;
  CreateRunPayload: CreateRunPayload;
  CreateSchedulePayload: CreateSchedulePayload;
  CreateToolFixturePayload: CreateToolFixturePayload;
  DashboardKpiMetrics: DashboardKpiMetrics;
  EvaluateDecisionPayload: EvaluateDecisionPayload;
  EvidenceRef: EvidenceRef;
  ExampleCreateRequest: ExampleCreateRequest;
  ExampleRetireRequest: ExampleRetireRequest;
  ExampleReviewRequest: ExampleReviewRequest;
  ExampleUpdateRequest: ExampleUpdateRequest;
  ExportPayload: ExportPayload;
  ExportRequest: ExportRequest;
  FallbackBody: FallbackBody;
  FaqCreateRequest: FaqCreateRequest;
  FaqEditRequest: FaqEditRequest;
  FaqItem: FaqItem;
  FaqReasonRequest: FaqReasonRequest;
  FaqReviewRequest: FaqReviewRequest;
  FaqTestCreateRequest: FaqTestCreateRequest;
  FaqTransitionRequest: FaqTransitionRequest;
  FlagCandidateBody: FlagCandidateBody;
  HTTPValidationError: HTTPValidationError;
  ImportValidatePayload: ImportValidatePayload;
  IngestionStage: IngestionStage;
  ItTicketItem: ItTicketItem;
  KnowledgeBlindSpot: KnowledgeBlindSpot;
  KnowledgeGapItem: KnowledgeGapItem;
  ManualChunkImage: ManualChunkImage;
  ManualChunkItem: ManualChunkItem;
  ManualDocumentItem: ManualDocumentItem;
  MaskingBody: MaskingBody;
  ModelCandidateBody: ModelCandidateBody;
  OverviewApiResponse: OverviewApiResponse;
  PendingPortalReviewItem: PendingPortalReviewItem;
  PendingPortalReviewList: PendingPortalReviewList;
  PortalDocumentDetail: PortalDocumentDetail;
  PortalDocumentList: PortalDocumentList;
  PortalDocumentRecord: PortalDocumentRecord;
  PortalDocumentVersionSummary: PortalDocumentVersionSummary;
  PortalImportAsset: PortalImportAsset;
  PortalImportResult: PortalImportResult;
  PortalWorkbenchDtoCatalog: PortalWorkbenchDtoCatalog;
  PreflightRunPayload: PreflightRunPayload;
  PromptActivateBody: PromptActivateBody;
  PromptApproveBody: PromptApproveBody;
  PromptCanaryBody: PromptCanaryBody;
  PromptCanaryEvaluateBody: PromptCanaryEvaluateBody;
  PromptCanaryStopBody: PromptCanaryStopBody;
  PromptCandidateBody: PromptCandidateBody;
  PromptCandidateRequest: PromptCandidateRequest;
  PromptRollbackBody: PromptRollbackBody;
  PublishSetVersionPayload: PublishSetVersionPayload;
  QualityCandidateMergeRequest: QualityCandidateMergeRequest;
  QualityCandidateRefreshRequest: QualityCandidateRefreshRequest;
  QualityCaseTransitionRequest: QualityCaseTransitionRequest;
  QualityCaseUpdateRequest: QualityCaseUpdateRequest;
  QualityContentLinkRequest: QualityContentLinkRequest;
  QualityDocumentDraftRequest: QualityDocumentDraftRequest;
  QualityFaqDraftRequest: QualityFaqDraftRequest;
  QuestionClusterCorrectionRequest: QuestionClusterCorrectionRequest;
  QuickFaqSaveRequest: QuickFaqSaveRequest;
  ReasonBody: ReasonBody;
  RequestExceptionPayload: RequestExceptionPayload;
  RescoreRunPayload: RescoreRunPayload;
  RetentionBody: RetentionBody;
  RetireCasePayload: RetireCasePayload;
  ReviewExecutionPayload: ReviewExecutionPayload;
  ReviewRevisionPayload: ReviewRevisionPayload;
  RevisionCreatePayload: RevisionCreatePayload;
  RevokeBody: RevokeBody;
  RoleRequestBody: RoleRequestBody;
  SetCreatePayload: SetCreatePayload;
  SetVersionDraftPayload: SetVersionDraftPayload;
  SimulationRequest: SimulationRequest;
  SpikeAlertActiveBroadcast: SpikeAlertActiveBroadcast;
  SpikeAlertItem: SpikeAlertItem;
  SubmitRevisionPayload: SubmitRevisionPayload;
  SyncJobActionRequest: SyncJobActionRequest;
  SyncJobCreateRequest: SyncJobCreateRequest;
  TicketCreateRequest: TicketCreateRequest;
  TopFrequentTopic: TopFrequentTopic;
  UpdateSchedulePayload: UpdateSchedulePayload;
  ValidationError: ValidationError;
  VerifyReleasePayload: VerifyReleasePayload;
  WorkItem: WorkItem;
  WorkItemAction: WorkItemAction;
  WorkItemsResponse: WorkItemsResponse;
  WorkSummaryResponse: WorkSummaryResponse;
  WorkflowDetailResponse: WorkflowDetailResponse;
  WorkflowStage: WorkflowStage;
};

export interface ActivatePolicyVersionPayload {
  mode?: 'REPORT_ONLY' | 'ENFORCE' | null;
}

export interface ActivateTargetPayload {
  active_version_ref: string;
  break_glass_id?: string | null;
  candidate_manifest: Record<string, unknown>;
  environment?: string;
  expected_pointer_etag?: number | null;
  policy_id?: string;
  target_type: 'KNOWLEDGE' | 'FAQ' | 'PROMPT' | 'AGENT' | 'ROUTER';
}

export interface ApproveFixtureVersionPayload {
  reason?: string | null;
}

export interface Body_upload_workbench_document_api_console_workbench_documents_upload_post {
  category?: string;
  deprecateOlderVersion?: boolean;
  file: string;
  title: string;
  version?: string;
}

export interface BroadcastRequest {
  durationHours?: number;
  message: string;
}

export interface BudgetPolicyCreateRequest {
  critical_threshold: number;
  measure: 'TWD' | 'USD' | 'TOKEN' | 'LLM_CALL_COUNT';
  notification_target_ids: Array<string>;
  owner_unit_id: string;
  period: 'DAILY' | 'MONTHLY';
  scope_id: string;
  scope_type: 'PERSONAL' | 'SERVICE' | 'TEAM' | 'TENANT' | 'GLOBAL' | 'MODEL';
  warning_threshold: number;
}

export interface BudgetPolicyStateRequest {
  enabled: boolean;
  expected_etag: number;
  reason: string;
}

export interface BudgetPolicyUpdateRequest {
  critical_threshold: number;
  expected_etag: number;
  notification_target_ids: Array<string>;
  warning_threshold: number;
}

export interface CancelRunPayload {
  reason?: string;
}

export interface CandidateJobPayload {
  limits?: Record<string, unknown>;
  owner_unit_id: string;
  requested_count?: number;
  source_refs: Array<Record<string, unknown>>;
  target_types?: Array<string>;
}

export interface CaseCreatePayload {
  behavior?: 'ANSWER_WITH_CITATION' | 'CLARIFY' | 'REFUSE' | 'HANDOFF' | 'TOOL_TASK';
  criticality?: 'CRITICAL' | 'NORMAL';
  evidence?: Array<Record<string, unknown>>;
  forbidden_claims?: Array<string>;
  metadata?: Record<string, unknown>;
  owner_unit_id: string;
  query: string;
  reference_answer?: string | null;
  required_facts?: Array<Record<string, unknown>>;
  source_id?: string | null;
  source_type?: 'MANUAL' | 'QUALITY_CASE' | 'FAQ' | 'DOCUMENT' | 'CONVERSATION' | 'SYNTHETIC';
  source_version_id?: string | null;
  tags?: Array<string>;
  title: string;
}

export interface ChatMessage {
  citations?: Array<CitationItem> | null;
  content: string;
  feedback?: 'positive' | 'negative' | null;
  feedback_comment?: string | null;
  id: string;
  sender: 'user' | 'bot' | 'system';
  timestamp: string;
}

export interface ChunkPreviewChunk {
  chunkerVersion: string;
  content: string;
  contentHash: string;
  contentPreview: string;
  headingPath: Array<string>;
  id: string;
  images?: Array<ChunkPreviewImageDto> | null;
  neighborIds: Array<string>;
  pageEnd: number;
  pageStart: number;
  parentId: string;
  parserVersion: string;
  qualityIssues?: Array<ChunkQualityIssue> | null;
  title: string;
  tokenCount: number;
}

export interface ChunkPreviewImageDto {
  alt_text: string;
  content_type: string;
  filename: string;
  path: string;
  url: string;
}

export interface ChunkPreviewResponse {
  chunks: Array<ChunkPreviewChunk>;
  documentId: string;
  profile?: ChunkingProfile | null;
  quality: ChunkQualitySummary;
  releaseId?: string | null;
  versionId: string;
}

export type ChunkQualityIssue = 'SHORT' | 'HEADING_ONLY' | 'DUPLICATE';

export interface ChunkQualitySummary {
  acceptable: boolean;
  chunkCount: number;
  coverageRatio: number;
  coveredBlocks: number;
  duplicateChunkCount: number;
  headingOnlyCount: number;
  orphanMediaCount: number;
  shortChunkCount: number;
  sourceBlocks: number;
}

export type ChunkingProfile = 'AUTO' | 'SLIDE_DECK' | 'MANUAL' | 'POLICY';

export interface CitationItem {
  chunk_id?: string | null;
  content?: string | null;
  document_id: string;
  document_title: string;
  download_url?: string | null;
  is_policy?: boolean | null;
  is_stale?: boolean | null;
  original_url?: string | null;
  page?: number | null;
  policy_id?: string | null;
  preview_url?: string | null;
  section?: string | null;
  similarity_score: number;
  snippet: string;
  source_path?: string | null;
  source_ref_id?: string | null;
  source_type?: string | null;
  updated_at: string;
  url?: string | null;
}

export interface ConversationActionRequest {
  action: string;
  root_cause?: string | null;
}

export interface ConversationDetail {
  associated_ticket_id?: string | null;
  id: string;
  messages: Array<ChatMessage>;
  reporter_dept: string;
  reporter_ext: string;
  reporter_name: string;
  root_cause?: 'OUTDATED_DOC' | 'MISSING_KNOWLEDGE' | 'MISUNDERSTOOD' | 'HARDWARE_TICKET' | null;
  started_at: string;
  status: 'PENDING_REVIEW' | 'ESCALATED_TICKET' | 'RESOLVED';
  topic_summary: string;
}

export interface CreateFixtureVersionPayload {
  allowlist_enabled?: boolean;
  default_response?: Record<string, unknown>;
  description?: string;
  input_schema?: Record<string, unknown>;
  is_mutation?: boolean;
  is_sandbox_safe?: boolean;
  mock_responses?: Array<Record<string, unknown>>;
}

export interface CreateGatePolicyPayload {
  description?: string;
  max_regression_count?: number;
  minimum_coverage?: number;
  minimum_pass_rate?: number;
  mode?: 'REPORT_ONLY' | 'ENFORCE';
  name: string;
  policy_id: string;
  required_set_version_ids?: Array<string> | null;
}

export interface CreatePolicyVersionPayload {
  description?: string;
  max_regression_count?: number;
  minimum_coverage?: number;
  minimum_pass_rate?: number;
  mode?: 'REPORT_ONLY' | 'ENFORCE';
  name: string;
  required_set_version_ids?: Array<string> | null;
}

export interface CreateQualityCasePayload {
  root_cause: string;
}

export interface CreateRunPayload {
  baseline_target: Record<string, unknown>;
  candidate_target: Record<string, unknown>;
  execute_inline?: boolean | null;
  idempotency_key?: string | null;
  limits?: Record<string, unknown>;
  mode?: 'OFFLINE_BENCHMARK' | 'REAL_RAG';
  quality_case_id?: string | null;
  repetitions?: number;
  set_version_id: string;
}

export interface CreateSchedulePayload {
  budget_limit_usd?: number;
  frequency?: 'HOURLY' | 'DAILY' | 'WEEKLY' | 'ON_CHANGE';
  name: string;
  schedule_id: string;
  set_version_id: string;
  target_refs?: Record<string, unknown>;
}

export interface CreateToolFixturePayload {
  allowlist_enabled?: boolean;
  default_response?: Record<string, unknown>;
  description?: string;
  fixture_id: string;
  input_schema?: Record<string, unknown>;
  is_mutation?: boolean;
  is_sandbox_safe?: boolean;
  mock_responses?: Array<Record<string, unknown>>;
  tool_name: string;
}

export interface DashboardKpiMetrics {
  ai_resolution_rate: number;
  ai_resolved_count: number;
  escalated_ticket_count: number;
  inquiries_trend_percentage: number;
  negative_feedback_count: number;
  satisfaction_rate: number;
  total_inquiries_today: number;
  urgent_attention_count: number;
}

export interface EvaluateDecisionPayload {
  policy_id: string;
  policy_version?: number | null;
  run_id: string;
  target_manifest_hash: string;
}

export interface EvidenceRef {
  occurred_at?: string | null;
  relation: string;
  retrieved_at: string;
  source_id: string;
  source_type: string;
  validity: 'valid' | 'stale' | 'unknown' | 'revoked';
  version_hash?: string | null;
}

export interface ExampleCreateRequest {
  expected_issue_type_id: string;
  expected_route: 'FAQ' | 'KNOWLEDGE' | 'TICKET' | 'HANDOFF';
  label: 'POSITIVE' | 'NEGATIVE';
  reason?: string | null;
  source_correlation_id?: string | null;
  text: string;
}

export interface ExampleRetireRequest {
  expected_etag: number;
  reason: string;
}

export interface ExampleReviewRequest {
  approve: boolean;
  dataset_version?: string | null;
  expected_etag: number;
  reason: string;
}

export interface ExampleUpdateRequest {
  expected_etag: number;
  expected_issue_type_id: string;
  expected_route: 'FAQ' | 'KNOWLEDGE' | 'TICKET' | 'HANDOFF';
  label: 'POSITIVE' | 'NEGATIVE';
  reason?: string | null;
  source_correlation_id?: string | null;
  text: string;
}

export interface ExportPayload {
  file_format?: 'JSONL' | 'CSV';
  set_id?: string | null;
}

export interface ExportRequest {
  actor_ref?: string | null;
  channel_scope?: string | null;
  conversation_id?: string | null;
  days?: number;
  end_date?: string | null;
  export_format?: string;
  export_type?: string;
  feedback_reason?: string | null;
  format_type?: string | null;
  handoff?: boolean | null;
  has_feedback?: boolean | null;
  idempotency_key?: string | null;
  issue_type_id?: string | null;
  model?: string | null;
  owner_unit_id?: string | null;
  preset?: string | null;
  query?: string | null;
  rating?: string | null;
  reason: string;
  resolved_status?: string | null;
  route?: string | null;
  source?: string | null;
  start_date?: string | null;
  status?: string | null;
}

export interface FallbackBody {
  error: 'TIMEOUT' | 'RATE_LIMIT' | 'UNAVAILABLE';
}

export interface FaqCreateRequest {
  answer: string;
  audience_group_ids?: Array<string>;
  audience_type: 'ALL' | 'GROUPS';
  business_contact: string;
  category: string;
  effective_at?: string | null;
  faq_key: string;
  issue_type_ids: Array<string>;
  keywords: Array<string>;
  owner_unit_id: string;
  question: string;
  related_document_ids?: Array<string>;
  review_due_at?: string | null;
}

export interface FaqEditRequest {
  answer: string;
  audience_group_ids?: Array<string>;
  audience_type: 'ALL' | 'GROUPS';
  business_contact: string;
  category: string;
  effective_at?: string | null;
  expected_etag: number;
  faq_key: string;
  issue_type_ids: Array<string>;
  keywords: Array<string>;
  owner_unit_id: string;
  question: string;
  related_document_ids?: Array<string>;
  review_due_at?: string | null;
}

export interface FaqItem {
  answer: string;
  category: string;
  id: string;
  is_active: boolean;
  questions: Array<string>;
  updated_at: string;
  updated_by?: string | null;
}

export interface FaqReasonRequest {
  expected_etag: number;
  reason: string;
}

export interface FaqReviewRequest {
  approve: boolean;
  expected_etag: number;
  reason: string;
}

export interface FaqTestCreateRequest {
  expected_audience_group_ids?: Array<string>;
  expected_etag: number;
  kind: 'POSITIVE' | 'NEGATIVE';
  source_correlation_id?: string | null;
  source_type?: 'MANUAL' | 'CONVERSATION';
  utterance: string;
}

export interface FaqTransitionRequest {
  expected_etag: number;
}

export interface FlagCandidateBody {
  environment?: string;
  expires_at?: string | null;
  flag_id: string;
  percent?: number | null;
  reason: string;
  value: string;
}

export interface HTTPValidationError {
  detail?: Array<ValidationError>;
}

export interface ImportValidatePayload {
  content: string;
  file_format?: 'JSONL' | 'CSV';
  owner_unit_id: string;
}

export type IngestionStage = 'UPLOADED' | 'SCANNING' | 'PARSING' | 'CHUNK_REVIEW' | 'INDEXING' | 'EVALUATING' | 'READY' | 'ACTIVE' | 'FAILED' | 'CANCELLED';

export interface ItTicketItem {
  assigned_agent?: string | null;
  assigned_team: string;
  category: 'HARDWARE' | 'ACCESS' | 'NETWORK' | 'SOFTWARE';
  conversation_id?: string | null;
  created_at: string;
  id: string;
  reporter_dept: string;
  reporter_ext?: string | null;
  reporter_name: string;
  resolution_note?: string | null;
  status: 'DISPATCHED' | 'IN_PROGRESS' | 'RESOLVED' | 'CANCELLED';
  ticket_number: string;
  title: string;
  updated_at: string;
}

export interface KnowledgeBlindSpot {
  category: string;
  description: string;
  id: string;
  negative_rate: number;
  status: 'HEALTHY' | 'NEEDS_UPDATE' | 'HIGH_DEFECT';
}

export interface KnowledgeGapItem {
  category: string;
  cluster_query: string;
  detected_at: string;
  frequency: number;
  id: string;
  sample_conversations: Array<string>;
}

export interface ManualChunkImage {
  alt_text: string;
  content_type: string;
  filename: string;
  path: string;
  url: string;
}

export interface ManualChunkItem {
  character_count?: number | null;
  chunker_version?: string | null;
  content?: string | null;
  content_hash?: string | null;
  content_preview: string;
  heading_path?: Array<string> | null;
  id: string;
  images?: Array<ManualChunkImage> | null;
  neighbor_ids?: Array<string> | null;
  page_end?: number | null;
  page_number?: number | null;
  parent_id?: string | null;
  parser_version?: string | null;
  quality_issues?: Array<ChunkQualityIssue> | null;
  source_path?: string | null;
  title: string;
  token_count?: number | null;
}

export interface ManualDocumentItem {
  category: string;
  chunk_count: number;
  chunking_profile?: ChunkingProfile | null;
  chunks?: Array<ManualChunkItem> | null;
  file_name: string;
  file_size_bytes?: number;
  id: string;
  ingestion_stage?: IngestionStage | null;
  ingestion_warnings?: Array<string> | null;
  job_id?: string | null;
  quality?: ChunkQualitySummary | null;
  status: 'LIVE' | 'DRAFT' | 'PARSING' | 'CHUNK_REVIEW' | 'IN_REVIEW' | 'APPROVED' | 'CHANGES_REQUESTED' | 'PUBLISHING' | 'READY' | 'FAILED' | 'ARCHIVED';
  title: string;
  updated_at: string;
  updated_by: string;
  version: string;
  version_id?: string | null;
}

export interface MaskingBody {
  policy_version: string;
  reason: string;
}

export interface ModelCandidateBody {
  change_reason: string;
  component?: string;
  config_id?: string;
  fallback_model_id?: string | null;
  fallback_on?: Array<string>;
  max_output_tokens?: number;
  model_id: string;
  pricing_version?: string;
  provider: string;
  region?: string;
  retry?: number;
  secret_ref: string;
  temperature?: number;
  timeout_seconds?: number;
}

export interface OverviewApiResponse {
  blindSpots: Array<KnowledgeBlindSpot>;
  gaps?: Array<KnowledgeGapItem>;
  kpis: DashboardKpiMetrics;
  spikeAlert?: SpikeAlertItem | null;
  topTopics: Array<TopFrequentTopic>;
}

export interface PendingPortalReviewItem {
  document_id: string;
  review_id: string;
}

export interface PendingPortalReviewList {
  items: Array<PendingPortalReviewItem>;
}

export interface PortalDocumentDetail {
  document: PortalDocumentRecord;
  draft_version?: PortalDocumentVersionSummary | null;
  published_version?: PortalDocumentVersionSummary | null;
}

export interface PortalDocumentList {
  items: Array<PortalDocumentRecord>;
}

export interface PortalDocumentRecord {
  category: string;
  document_id: string;
  etag?: string | null;
  format?: string | null;
  status: string;
  title: string;
  updated_at: string;
  updated_by: string;
}

export interface PortalDocumentVersionSummary {
  original_asset_name?: string | null;
  original_asset_size?: number | null;
  version_id: string;
  version_number: number;
}

export interface PortalImportAsset {
  content_base64: string;
  filename: string;
}

export interface PortalImportResult {
  assets?: Array<PortalImportAsset> | null;
  audience_group_ids?: Array<string> | null;
  audience_type?: 'ALL_EMPLOYEES' | 'RESTRICTED_GROUPS' | null;
  byteSize?: number | null;
  effective_at?: string | null;
  error?: string | null;
  jobId?: string | null;
  markdown_content?: string | null;
  mode?: 'sync' | 'async' | null;
  original_asset_token?: string | null;
  owner_unit_id?: string | null;
  page_count?: number | null;
  result?: PortalImportResult | null;
  review_due_at?: string | null;
  source_type?: 'PDF' | 'DOCX' | 'MARKDOWN_UPLOAD' | null;
  stage?: IngestionStage | null;
  status?: string | null;
  title?: string | null;
  warnings?: Array<string> | null;
}

export interface PortalWorkbenchDtoCatalog {
  chunk_preview: ChunkPreviewResponse;
  document_detail: PortalDocumentDetail;
  document_list: PortalDocumentList;
  import_result: PortalImportResult;
  note?: string;
  pending_reviews: PendingPortalReviewList;
}

export interface PreflightRunPayload {
  baseline_target: Record<string, unknown>;
  candidate_target: Record<string, unknown>;
  limits?: Record<string, unknown>;
  set_version_id: string;
}

export interface PromptActivateBody {
  emergency?: boolean;
  reason: string;
}

export interface PromptApproveBody {
  approved?: boolean | null;
  policy_exception_expires_at?: string | null;
  policy_exception_reason?: string | null;
  reason: string;
}

export interface PromptCanaryBody {
  environment?: string;
  percent: number;
  reason: string;
}

export interface PromptCanaryEvaluateBody {
  error_rate: number;
  handoff_rate: number;
  negative_feedback_rate: number;
  safety_alerts?: number;
  sample_size: number;
}

export interface PromptCanaryStopBody {
  reason: string;
  rollback?: boolean;
}

export interface PromptCandidateBody {
  dataset_version: string;
  knowledge_release_id?: string | null;
  taxonomy_version: string;
}

export interface PromptCandidateRequest {
  active_prompt_version: string;
  data_range_end: string;
  data_range_start: string;
  dataset_version: string;
  masking_policy_version: string;
  taxonomy_version: string;
}

export interface PromptRollbackBody {
  reason: string;
}

export interface PublishSetVersionPayload {
  expected_etag: number;
}

export interface QualityCandidateMergeRequest {
  assignee_id?: string | null;
  candidate_ids: Array<string>;
  description?: string;
  priority?: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  target_due_at?: string | null;
  title: string;
}

export interface QualityCandidateRefreshRequest {
  days?: number;
}

export interface QualityCaseTransitionRequest {
  expected_etag: number;
  reason?: string | null;
  resolution_type?: string | null;
  status: 'TRIAGED' | 'IN_PROGRESS' | 'WAITING_REVIEW' | 'OBSERVING' | 'RESOLVED' | 'WONT_FIX' | 'DUPLICATE';
}

export interface QualityCaseUpdateRequest {
  assignee_id?: string | null;
  description?: string;
  expected_etag: number;
  priority?: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  target_due_at?: string | null;
  title: string;
}

export interface QualityContentLinkRequest {
  document_id?: string | null;
  expected_etag: number;
  faq_id?: string | null;
}

export interface QualityDocumentDraftRequest {
  business_contact?: string | null;
  category?: string | null;
  expected_case_etag: number;
  markdown_content?: string | null;
  summary?: string | null;
  title?: string | null;
}

export interface QualityFaqDraftRequest {
  answer: string;
  audience_group_ids?: Array<string>;
  audience_type: 'ALL' | 'GROUPS';
  business_contact: string;
  category: string;
  effective_at?: string | null;
  expected_case_etag: number;
  faq_key: string;
  keywords: Array<string>;
  question: string;
  related_document_ids?: Array<string>;
  review_due_at?: string | null;
}

export interface QuestionClusterCorrectionRequest {
  action: 'RENAME' | 'ACCEPT' | 'REJECT' | 'MERGE' | 'SPLIT';
  candidate_groups?: Array<Array<string>>;
  cluster_ids: Array<string>;
  name?: string | null;
}

export interface QuickFaqSaveRequest {
  answer: string;
  category?: string;
  id?: string | null;
  question: string;
  resolveConversationId?: string | null;
}

export interface ReasonBody {
  reason: string;
}

export interface RequestExceptionPayload {
  reason: string;
  validity_hours?: number;
}

export interface RescoreRunPayload {
  judge_version?: string;
  metric_version?: string;
}

export interface RetentionBody {
  migration_plan: string;
  policy_id?: string;
  reason: string;
  ttl_days: number;
}

export interface RetireCasePayload {
  reason: string;
}

export interface ReviewExecutionPayload {
  decision: 'PASS' | 'FAIL' | 'INCONCLUSIVE' | 'NOT_APPLICABLE';
  execution_id: string;
  metric_id: string;
  reason: string;
}

export interface ReviewRevisionPayload {
  approve: boolean;
  expected_etag: number;
  reason: string;
}

export interface RevisionCreatePayload {
  base_revision_id?: string | null;
  behavior?: 'ANSWER_WITH_CITATION' | 'CLARIFY' | 'REFUSE' | 'HANDOFF' | 'TOOL_TASK' | null;
  criticality?: 'CRITICAL' | 'NORMAL' | null;
  forbidden_claims?: Array<string> | null;
  query: string;
  reference_answer?: string | null;
  required_facts?: Array<Record<string, unknown>> | null;
  tags?: Array<string> | null;
}

export interface RevokeBody {
  principal: string;
  reason: string;
}

export interface RoleRequestBody {
  add_capabilities?: Array<string>;
  reason: string;
  remove_capabilities?: Array<string>;
  target_principal: string;
  target_role?: string | null;
}

export interface SetCreatePayload {
  description?: string;
  name: string;
  owner_unit_ids: Array<string>;
  purpose?: 'DEVELOPMENT' | 'HOLDOUT';
}

export interface SetVersionDraftPayload {
  case_revision_ids: Array<string>;
}

export interface SimulationRequest {
  query: string;
}

export interface SpikeAlertActiveBroadcast {
  expires_at: string;
  message: string;
}

export interface SpikeAlertItem {
  active_broadcast?: SpikeAlertActiveBroadcast | null;
  affected_count: number;
  created_at: string;
  id: string;
  is_active: boolean;
  topic: string;
  window_minutes: number;
}

export interface SubmitRevisionPayload {
  expected_etag: number;
}

export interface SyncJobActionRequest {
  expected_etag?: number | null;
  reason: string;
}

export interface SyncJobCreateRequest {
  reason: string;
  scope_ids?: Array<string>;
  scope_type: 'ALL' | 'FAQ' | 'DOCUMENT' | 'FAILED';
}

export interface TicketCreateRequest {
  assignedTeam?: string;
  category?: string;
  conversationId?: string | null;
  notes?: string | null;
  reporterDept: string;
  reporterExt?: string | null;
  reporterName: string;
  title: string;
}

export interface TopFrequentTopic {
  count: number;
  id: string;
  rank: number;
  resolution_rate: number;
  topic: string;
}

export interface UpdateSchedulePayload {
  budget_limit_usd?: number | null;
  frequency?: 'HOURLY' | 'DAILY' | 'WEEKLY' | 'ON_CHANGE' | null;
  is_enabled?: boolean | null;
  target_refs?: Record<string, unknown> | null;
}

export interface ValidationError {
  ctx?: Record<string, unknown>;
  input?: unknown;
  loc: Array<string | number>;
  msg: string;
  type: string;
}

export interface VerifyReleasePayload {
  policy_id?: string;
  target_manifest_hash: string;
}

export interface WorkItem {
  assignee_id?: string | null;
  blocked_reason?: string | null;
  due_at?: string | null;
  key: string;
  next_action: WorkItemAction;
  owner_unit_id: string;
  revision: string;
  source_id: string;
  source_status: string;
  source_type: string;
  step: string;
  title: string;
  updated_at: string;
  workflow: string;
}

export interface WorkItemAction {
  id: string;
  route: string;
}

export interface WorkItemsResponse {
  generated_at: string;
  items: Array<WorkItem>;
  next_cursor?: string | null;
  partial: boolean;
  snapshot_id: string;
  sources: Record<string, string>;
  total: number;
}

export interface WorkSummaryResponse {
  by_bucket: Record<string, number>;
  by_workflow: Record<string, number>;
  generated_at: string;
  snapshot_id: string;
  sources: Record<string, string>;
  total: number;
}

export interface WorkflowDetailResponse {
  allowed_actions: Array<string>;
  evidence_refs: Array<EvidenceRef>;
  id: string;
  kind: string;
  return_route: string;
  stages: Array<WorkflowStage>;
  status: string;
  title: string;
}

export interface WorkflowStage {
  id: string;
  status: 'pending' | 'current' | 'completed' | 'skipped' | 'failed';
  title: string;
}
