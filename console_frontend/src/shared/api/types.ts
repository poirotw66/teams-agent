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
  validity: 'valid' | 'stale' | 'unknown' | 'revoked';
}

export interface WorkflowStage {
  id: string;
  title: string;
  status: 'pending' | 'current' | 'completed' | 'skipped' | 'failed';
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
  status: 'ok' | 'degraded' | 'unavailable' | 'down';
  details?: Record<string, unknown>;
}

export interface SystemHealthResponse {
  status: 'healthy' | 'degraded' | 'unhealthy';
  components: Record<string, HealthComponentStatus>;
  timestamp: string;
}
