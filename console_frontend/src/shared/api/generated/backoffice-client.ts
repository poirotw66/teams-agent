/**
 * AUTO-GENERATED FILE. DO NOT EDIT BY HAND.
 *
 * Typed Backoffice HTTP client generated from the canonical OpenAPI document.
 * Auth headers are injected by apiClient; operation header parameters are omitted.
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

import { apiClient } from '../client';
import type {
  ActivatePolicyVersionPayload,
  ActivateTargetPayload,
  ApproveFixtureVersionPayload,
  Body_upload_workbench_document_api_console_workbench_documents_upload_post,
  BroadcastRequest,
  BudgetPolicyCreateRequest,
  BudgetPolicyStateRequest,
  BudgetPolicyUpdateRequest,
  CancelRunPayload,
  CandidateJobPayload,
  CaseCreatePayload,
  ConversationActionRequest,
  ConversationDetail,
  CreateFixtureVersionPayload,
  CreateGatePolicyPayload,
  CreatePolicyVersionPayload,
  CreateQualityCasePayload,
  CreateRunPayload,
  CreateSchedulePayload,
  CreateToolFixturePayload,
  EvaluateDecisionPayload,
  ExampleCreateRequest,
  ExampleRetireRequest,
  ExampleReviewRequest,
  ExampleUpdateRequest,
  ExportPayload,
  ExportRequest,
  FallbackBody,
  FaqCreateRequest,
  FaqEditRequest,
  FaqItem,
  FaqReasonRequest,
  FaqReviewRequest,
  FaqTestCreateRequest,
  FaqTransitionRequest,
  FlagCandidateBody,
  ImportValidatePayload,
  ItTicketItem,
  KnowledgeWorkspaceUpdateRequest,
  ManualDocumentItem,
  MaskingBody,
  ModelCandidateBody,
  OverviewApiResponse,
  PortalWorkbenchDtoCatalog,
  PreflightRunPayload,
  PromptActivateBody,
  PromptApproveBody,
  PromptCanaryBody,
  PromptCanaryEvaluateBody,
  PromptCanaryStopBody,
  PromptCandidateBody,
  PromptCandidateRequest,
  PromptRollbackBody,
  PublishSetVersionPayload,
  QualityCandidateMergeRequest,
  QualityCandidateRefreshRequest,
  QualityCaseTransitionRequest,
  QualityCaseUpdateRequest,
  QualityContentLinkRequest,
  QualityDocumentDraftRequest,
  QualityFaqDraftRequest,
  QuestionClusterCorrectionRequest,
  QuickFaqSaveRequest,
  ReasonBody,
  RequestExceptionPayload,
  RescoreRunPayload,
  RetentionBody,
  RetireCasePayload,
  ReviewExecutionPayload,
  ReviewRevisionPayload,
  RevisionCreatePayload,
  RevokeBody,
  RoleRequestBody,
  SetCreatePayload,
  SetVersionDraftPayload,
  SimulationRequest,
  SubmitRevisionPayload,
  SyncJobActionRequest,
  SyncJobCreateRequest,
  TicketCreateRequest,
  UpdateSchedulePayload,
  VerifyReleasePayload,
  WorkItemsResponse,
  WorkSummaryResponse,
  WorkflowDetailResponse,
} from './backoffice-schemas';

function buildPath(
  template: string,
  pathParams: Record<string, string | number | boolean>,
): string {
  return template.replace(/\{([^}]+)\}/g, (_match, key: string) => {
    const value = pathParams[key];
    if (value === undefined || value === null) {
      throw new Error(`Missing path parameter: ${key}`);
    }
    return encodeURIComponent(String(value));
  });
}

function buildQuery(query: Record<string, unknown> | undefined): string {
  if (!query) {
    return '';
  }
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) {
      continue;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item === undefined || item === null) {
          continue;
        }
        params.append(key, String(item));
      }
      continue;
    }
    params.set(key, String(value));
  }
  const encoded = params.toString();
  return encoded ? `?${encoded}` : '';
}

function toFormData(body: FormData | object | undefined): FormData | undefined {
  if (body === undefined) {
    return undefined;
  }
  if (typeof FormData !== 'undefined' && body instanceof FormData) {
    return body;
  }
  const form = new FormData();
  for (const [key, value] of Object.entries(body as Record<string, unknown>)) {
    if (value === undefined || value === null) {
      continue;
    }
    if (typeof Blob !== 'undefined' && value instanceof Blob) {
      form.append(key, value);
      continue;
    }
    form.append(key, String(value));
  }
  return form;
}

// Operations from ai_ops_backoffice OpenAPI (222 methods).
export const backofficeClient = {
  async acknowledge_alert_api_alerts__alert_id__acknowledge_post(args: {
    path: {
      alert_id: string;
    };
    body: FaqReasonRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/alerts/{alert_id}/acknowledge', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async activate_faq_api_faqs__faq_id__versions__version_id__activate_post(args: {
    path: {
      faq_id: string;
      version_id: string;
    };
    body: FaqReasonRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/faqs/{faq_id}/versions/{version_id}/activate', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async activate_governance_flag_api_governance_flags__flag_id__versions__version_id__activate_post(args: {
    path: {
      flag_id: string;
      version_id: string;
    };
    body: ReasonBody;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/flags/{flag_id}/versions/{version_id}/activate', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async activate_governance_model_api_governance_models__config_id__versions__version_id__activate_post(args: {
    path: {
      config_id: string;
      version_id: string;
    };
    body: ReasonBody;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/models/{config_id}/versions/{version_id}/activate', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async activate_governance_prompt_api_governance_prompts__prompt_id__versions__version_id__activate_post(args: {
    path: {
      prompt_id: string;
      version_id: string;
    };
    body: PromptActivateBody;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/prompts/{prompt_id}/versions/{version_id}/activate', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async activate_masking_api_governance_masking__version_id__activate_post(args: {
    path: {
      version_id: string;
    };
    body: ReasonBody;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/masking/{version_id}/activate', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async activate_policy_version_api_evaluations_gate_policies__policy_id__versions__version__activate_post(args: {
    path: {
      policy_id: string;
      version: number;
    };
    body: ActivatePolicyVersionPayload;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/gate-policies/{policy_id}/versions/{version}/activate', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async activate_retention_api_governance_retention__version_id__activate_post(args: {
    path: {
      version_id: string;
    };
    body: ReasonBody;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/retention/{version_id}/activate', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async activate_target_api_evaluations_activate_target_post(args: {
    body: ActivateTargetPayload;
}): Promise<Record<string, unknown>> {
    const path = '/api/evaluations/activate-target';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async add_faq_test_api_faqs__faq_id__versions__version_id__tests_post(args: {
    path: {
      faq_id: string;
      version_id: string;
    };
    body: FaqTestCreateRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/faqs/{faq_id}/versions/{version_id}/tests', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async aggregates_rebuild_api_aggregates_rebuild_post(args?: {
    query?: {
      days?: number;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/aggregates/rebuild';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'POST' });
  },
  async aggregates_summary_api_aggregates_summary_get(args?: {
    query?: {
      days?: number;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/aggregates/summary';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async approve_exception_api_evaluations_exceptions__exception_id__approve_post(args: {
    path: {
      exception_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/exceptions/{exception_id}/approve', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'POST' });
  },
  async approve_fixture_version_api_evaluations_tool_fixtures__fixture_id__versions__version__approve_post(args: {
    path: {
      fixture_id: string;
      version: number;
    };
    body: ApproveFixtureVersionPayload;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/tool-fixtures/{fixture_id}/versions/{version}/approve', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async approve_governance_flag_api_governance_flags__flag_id__versions__version_id__approve_post(args: {
    path: {
      flag_id: string;
      version_id: string;
    };
    body: ReasonBody;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/flags/{flag_id}/versions/{version_id}/approve', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async approve_governance_model_api_governance_models__config_id__versions__version_id__approve_post(args: {
    path: {
      config_id: string;
      version_id: string;
    };
    body: ReasonBody;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/models/{config_id}/versions/{version_id}/approve', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async approve_governance_prompt_api_governance_prompts__prompt_id__versions__version_id__approve_post(args: {
    path: {
      prompt_id: string;
      version_id: string;
    };
    body: PromptApproveBody;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/prompts/{prompt_id}/versions/{version_id}/approve', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async approve_masking_api_governance_masking__version_id__approve_post(args: {
    path: {
      version_id: string;
    };
    body: ReasonBody;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/masking/{version_id}/approve', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async approve_policy_version_api_evaluations_gate_policies__policy_id__versions__version__approve_post(args: {
    path: {
      policy_id: string;
      version: number;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/gate-policies/{policy_id}/versions/{version}/approve', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'POST' });
  },
  async approve_retention_api_governance_retention__version_id__approve_post(args: {
    path: {
      version_id: string;
    };
    body: ReasonBody;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/retention/{version_id}/approve', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async approve_role_change_api_governance_roles__change_id__approve_post(args: {
    path: {
      change_id: string;
    };
    body: ReasonBody;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/roles/{change_id}/approve', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async audit_events_api_audit_events_get(args?: {
    query?: {
      actor_id?: string | null;
      action?: string | null;
      target_type?: string | null;
      start_date?: string | null;
      end_date?: string | null;
      limit?: number;
      cursor?: string | null;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/audit-events';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async auth_config_api_auth_config_get(): Promise<Record<string, unknown>> {
    const path = '/api/auth/config';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async canary_governance_prompt_api_governance_prompts__prompt_id__versions__version_id__canary_post(args: {
    path: {
      prompt_id: string;
      version_id: string;
    };
    body: PromptCanaryBody;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/prompts/{prompt_id}/versions/{version_id}/canary', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async cancel_candidate_job_api_evaluations_candidate_jobs__job_id__cancel_post(args: {
    path: {
      job_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/candidate-jobs/{job_id}/cancel', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'POST' });
  },
  async cancel_run_api_evaluations_runs__run_id__cancel_post(args: {
    path: {
      run_id: string;
    };
    body: CancelRunPayload;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/runs/{run_id}/cancel', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async cancel_sync_job_api_sync_jobs__job_id__cancel_post(args: {
    path: {
      job_id: string;
    };
    body: SyncJobActionRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/sync-jobs/{job_id}/cancel', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async capabilities_api_capabilities_get(): Promise<Record<string, unknown>> {
    const path = '/api/capabilities';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async commit_import_api_evaluations_imports__staged_id__commit_post(args: {
    path: {
      staged_id: string;
    };
    query: {
      owner_unit_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/imports/{staged_id}/commit', args.path);
    const url = `${path}${buildQuery(args.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'POST' });
  },
  async compare_prompt_candidate_api_prompts_candidates__candidate_id__compare_get(args: {
    path: {
      candidate_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/prompts/candidates/{candidate_id}/compare', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async console_v2_spa_console_v2__full_path__get(args: {
    path: {
      full_path: string;
    };
}): Promise<unknown> {
    const path = buildPath('/console-v2/{full_path}', args.path);
    const url = path;
    return apiClient<unknown>(url, { method: 'GET' });
  },
  async console_v2_spa_console_v2__get(args?: {
    query?: {
      full_path?: string;
    };
}): Promise<unknown> {
    const path = '/console-v2/';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<unknown>(url, { method: 'GET' });
  },
  async console_v2_spa_console_v2_get(args?: {
    query?: {
      full_path?: string;
    };
}): Promise<unknown> {
    const path = '/console-v2';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<unknown>(url, { method: 'GET' });
  },
  async conversation_detail_api_conversations__conversation_id__get(args: {
    path: {
      conversation_id: string;
    };
    query?: {
      unmask_reason?: string | null;
      refresh?: boolean;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/conversations/{conversation_id}', args.path);
    const url = `${path}${buildQuery(args.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async conversations_api_conversations_get(args?: {
    query?: {
      days?: number;
      preset?: string | null;
      start_date?: string | null;
      end_date?: string | null;
      cursor?: string | null;
      actor_ref?: string | null;
      user_id?: string | null;
      issue_type_id?: string | null;
      route?: string | null;
      conversation_id?: string | null;
      model?: string | null;
      has_feedback?: boolean | null;
      handoff?: boolean | null;
      channel_scope?: string | null;
      query?: string | null;
      source?: string | null;
      refresh?: boolean;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/conversations';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async correct_question_clusters_api_question_clusters_correct_post(args: {
    body: QuestionClusterCorrectionRequest;
}): Promise<Record<string, unknown>> {
    const path = '/api/question-clusters/correct';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async costs_rates_api_costs_rates_get(): Promise<Record<string, unknown>> {
    const path = '/api/costs/rates';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async costs_rates_history_api_costs_rates_history_get(): Promise<Record<string, unknown>> {
    const path = '/api/costs/rates/history';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async costs_summary_api_costs_summary_get(args?: {
    query?: {
      days?: number;
      preset?: string | null;
      start_date?: string | null;
      end_date?: string | null;
      model?: string | null;
      refresh?: boolean;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/costs/summary';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async create_budget_policy_api_budget_policies_post(args: {
    body: BudgetPolicyCreateRequest;
}): Promise<Record<string, unknown>> {
    const path = '/api/budget-policies';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_case_api_evaluations_cases_post(args: {
    body: CaseCreatePayload;
}): Promise<Record<string, unknown>> {
    const path = '/api/evaluations/cases';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_conversation_example_api_conversations__conversation_id__examples_post(args: {
    path: {
      conversation_id: string;
    };
    body: ExampleCreateRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/conversations/{conversation_id}/examples', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_document_example_api_knowledge__document_id__versions__version_id__examples_post(args: {
    path: {
      document_id: string;
      version_id: string;
    };
    body: ExampleCreateRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/knowledge/{document_id}/versions/{version_id}/examples', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_export_api_exports_post(args: {
    body: ExportRequest;
}): Promise<Record<string, unknown>> {
    const path = '/api/exports';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_faq_api_faqs_post(args: {
    body: FaqCreateRequest;
}): Promise<Record<string, unknown>> {
    const path = '/api/faqs';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_faq_example_api_faqs__faq_id__versions__version_id__examples_post(args: {
    path: {
      faq_id: string;
      version_id: string;
    };
    body: ExampleCreateRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/faqs/{faq_id}/versions/{version_id}/examples', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_fixture_version_api_evaluations_tool_fixtures__fixture_id__versions_post(args: {
    path: {
      fixture_id: string;
    };
    body: CreateFixtureVersionPayload;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/tool-fixtures/{fixture_id}/versions', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_gate_policy_api_evaluations_gate_policies_post(args: {
    body: CreateGatePolicyPayload;
}): Promise<Record<string, unknown>> {
    const path = '/api/evaluations/gate-policies';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_governance_flag_api_governance_flags_candidates_post(args: {
    body: FlagCandidateBody;
}): Promise<Record<string, unknown>> {
    const path = '/api/governance/flags/candidates';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_governance_model_api_governance_models_candidates_post(args: {
    body: ModelCandidateBody;
}): Promise<Record<string, unknown>> {
    const path = '/api/governance/models/candidates';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_governance_prompt_candidate_api_governance_prompts__prompt_id__candidates_post(args: {
    path: {
      prompt_id: string;
    };
    body: PromptCandidateBody;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/prompts/{prompt_id}/candidates', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_manual_example_api_examples_manual_post(args: {
    body: ExampleCreateRequest;
}): Promise<Record<string, unknown>> {
    const path = '/api/examples/manual';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_masking_api_governance_masking_candidates_post(args: {
    body: MaskingBody;
}): Promise<Record<string, unknown>> {
    const path = '/api/governance/masking/candidates';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_policy_version_api_evaluations_gate_policies__policy_id__versions_post(args: {
    path: {
      policy_id: string;
    };
    body: CreatePolicyVersionPayload;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/gate-policies/{policy_id}/versions', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_prompt_candidate_api_prompts_candidates_post(args: {
    body: PromptCandidateRequest;
}): Promise<Record<string, unknown>> {
    const path = '/api/prompts/candidates';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_quality_case_document_draft_api_quality_cases__case_id__document_draft_post(args: {
    path: {
      case_id: string;
    };
    body: QualityDocumentDraftRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/quality-cases/{case_id}/document-draft', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_quality_case_faq_draft_api_quality_cases__case_id__faq_draft_post(args: {
    path: {
      case_id: string;
    };
    body: QualityFaqDraftRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/quality-cases/{case_id}/faq-draft', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_retention_api_governance_retention_candidates_post(args: {
    body: RetentionBody;
}): Promise<Record<string, unknown>> {
    const path = '/api/governance/retention/candidates';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_revision_api_evaluations_cases__case_id__revisions_post(args: {
    path: {
      case_id: string;
    };
    body: RevisionCreatePayload;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/cases/{case_id}/revisions', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_run_api_evaluations_runs_post(args: {
    body: CreateRunPayload;
}): Promise<Record<string, unknown>> {
    const path = '/api/evaluations/runs';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_schedule_api_evaluations_schedules_post(args: {
    body: CreateSchedulePayload;
}): Promise<Record<string, unknown>> {
    const path = '/api/evaluations/schedules';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_set_api_evaluations_sets_post(args: {
    body: SetCreatePayload;
}): Promise<Record<string, unknown>> {
    const path = '/api/evaluations/sets';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_set_version_draft_api_evaluations_sets__set_id__versions_post(args: {
    path: {
      set_id: string;
    };
    body: SetVersionDraftPayload;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/sets/{set_id}/versions', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_sync_job_api_sync_jobs_post(args: {
    body: SyncJobCreateRequest;
}): Promise<Record<string, unknown>> {
    const path = '/api/sync-jobs';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_tool_fixture_api_evaluations_tool_fixtures_post(args: {
    body: CreateToolFixturePayload;
}): Promise<Record<string, unknown>> {
    const path = '/api/evaluations/tool-fixtures';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async create_workbench_ticket_api_console_workbench_tickets_post(args: {
    body: TicketCreateRequest;
}): Promise<ItTicketItem> {
    const path = '/api/console/workbench/tickets';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<ItTicketItem>(url, { method: 'POST', body });
  },
  async delete_knowledge_workspace_api_knowledge_workspace_delete(): Promise<Record<string, unknown>> {
    const path = '/api/knowledge-workspace';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'DELETE' });
  },
  async delete_workbench_document_api_console_workbench_documents__document_id__delete(args: {
    path: {
      document_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/console/workbench/documents/{document_id}', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'DELETE' });
  },
  async delete_workbench_faq_api_console_workbench_faqs__faq_id__delete(args: {
    path: {
      faq_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/console/workbench/faqs/{faq_id}', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'DELETE' });
  },
  async disable_faq_api_faqs__faq_id__disable_post(args: {
    path: {
      faq_id: string;
    };
    body: FaqReasonRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/faqs/{faq_id}/disable', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async download_export_api_exports__job_id__download_get(args: {
    path: {
      job_id: string;
    };
}): Promise<unknown> {
    const path = buildPath('/api/exports/{job_id}/download', args.path);
    const url = path;
    return apiClient<unknown>(url, { method: 'GET' });
  },
  async edit_faq_api_faqs__faq_id__put(args: {
    path: {
      faq_id: string;
    };
    body: FaqEditRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/faqs/{faq_id}', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'PUT', body });
  },
  async effective_governance_flag_api_governance_flags__flag_id__effective_get(args: {
    path: {
      flag_id: string;
    };
    query?: {
      environment?: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/flags/{flag_id}/effective', args.path);
    const url = `${path}${buildQuery(args.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async eval_governance_model_api_governance_models__config_id__versions__version_id__eval_post(args: {
    path: {
      config_id: string;
      version_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/models/{config_id}/versions/{version_id}/eval', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'POST' });
  },
  async eval_governance_prompt_api_governance_prompts__prompt_id__versions__version_id__eval_post(args: {
    path: {
      prompt_id: string;
      version_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/prompts/{prompt_id}/versions/{version_id}/eval', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'POST' });
  },
  async evaluate_all_policies_api_budget_policies_evaluate_all_post(): Promise<Record<string, unknown>> {
    const path = '/api/budget-policies/evaluate-all';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'POST' });
  },
  async evaluate_budget_policy_api_budget_policies__policy_id__evaluate_post(args: {
    path: {
      policy_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/budget-policies/{policy_id}/evaluate', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'POST' });
  },
  async evaluate_decision_api_evaluations_gate_decisions_post(args: {
    body: EvaluateDecisionPayload;
}): Promise<Record<string, unknown>> {
    const path = '/api/evaluations/gate-decisions';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async evaluate_governance_prompt_canary_api_governance_prompts__prompt_id__canary_evaluate_post(args: {
    path: {
      prompt_id: string;
    };
    body: PromptCanaryEvaluateBody;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/prompts/{prompt_id}/canary/evaluate', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async export_cases_api_evaluations_exports_post(args: {
    body: ExportPayload;
}): Promise<Record<string, unknown>> {
    const path = '/api/evaluations/exports';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async feedback_list_api_feedback_get(args?: {
    query?: {
      days?: number;
      preset?: string | null;
      start_date?: string | null;
      end_date?: string | null;
      rating?: string | null;
      issue_type_id?: string | null;
      reason?: string | null;
      resolved?: string | null;
      handoff?: boolean | null;
      model?: string | null;
      route?: string | null;
      limit?: number;
      cursor?: string | null;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/feedback';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async gap_summary_api_gaps_summary_get(args?: {
    query?: {
      preset?: string | null;
      days?: number;
      start_date?: string | null;
      end_date?: string | null;
      issue_type_id?: string | null;
      sort_by?: string | null;
      sort_order?: string;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/gaps/summary';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async generate_question_clusters_api_question_clusters_generate_post(): Promise<Record<string, unknown>> {
    const path = '/api/question-clusters/generate';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'POST' });
  },
  async get_active_prompt_api_prompts_active_get(): Promise<Record<string, unknown>> {
    const path = '/api/prompts/active';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_alert_api_alerts__alert_id__get(args: {
    path: {
      alert_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/alerts/{alert_id}', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_budget_policy_api_budget_policies__policy_id__get(args: {
    path: {
      policy_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/budget-policies/{policy_id}', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_candidate_job_api_evaluations_candidate_jobs__job_id__get(args: {
    path: {
      job_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/candidate-jobs/{job_id}', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_case_api_evaluations_cases__case_id__get(args: {
    path: {
      case_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/cases/{case_id}', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_case_execution_api_evaluations_runs__run_id__cases__execution_id__get(args: {
    path: {
      run_id: string;
      execution_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/runs/{run_id}/cases/{execution_id}', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_case_trajectory_api_evaluations_runs__run_id__cases__execution_id__trajectory_get(args: {
    path: {
      run_id: string;
      execution_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/runs/{run_id}/cases/{execution_id}/trajectory', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_console_agent_knowledge_status(): Promise<Record<string, unknown>> {
    const path = '/api/console/agent-knowledge/status';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_decision_api_evaluations_gate_decisions__decision_id__get(args: {
    path: {
      decision_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/gate-decisions/{decision_id}', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_example_api_examples__example_id__get(args: {
    path: {
      example_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/examples/{example_id}', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_export_api_exports__job_id__get(args: {
    path: {
      job_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/exports/{job_id}', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_faq_api_faqs__faq_id__get(args: {
    path: {
      faq_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/faqs/{faq_id}', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_faq_performance_api_faqs__faq_id__performance_get(args: {
    path: {
      faq_id: string;
    };
    query?: {
      days?: number | null;
      preset?: string | null;
      start_date?: string | null;
      end_date?: string | null;
      as_of?: string | null;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/faqs/{faq_id}/performance', args.path);
    const url = `${path}${buildQuery(args.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_fixture_version_api_evaluations_tool_fixtures__fixture_id__versions__version__get(args: {
    path: {
      fixture_id: string;
      version: number;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/tool-fixtures/{fixture_id}/versions/{version}', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_gate_policy_api_evaluations_gate_policies__policy_id__get(args: {
    path: {
      policy_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/gate-policies/{policy_id}', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_knowledge_workspace_api_knowledge_workspace_get(): Promise<Record<string, unknown>> {
    const path = '/api/knowledge-workspace';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_prompt_candidate_api_prompts_candidates__candidate_id__get(args: {
    path: {
      candidate_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/prompts/candidates/{candidate_id}', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_quality_case_api_quality_cases__case_id__get(args: {
    path: {
      case_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/quality-cases/{case_id}', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_run_api_evaluations_runs__run_id__get(args: {
    path: {
      run_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/runs/{run_id}', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_set_api_evaluations_sets__set_id__get(args: {
    path: {
      set_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/sets/{set_id}', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_source_impacts_api_evaluations_source_impacts_get(args: {
    query: {
      source_type: string;
      source_id: string;
      source_version?: string | null;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/evaluations/source-impacts';
    const url = `${path}${buildQuery(args.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_sync_job_api_sync_jobs__job_id__get(args: {
    path: {
      job_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/sync-jobs/{job_id}', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_tool_fixture_api_evaluations_tool_fixtures__fixture_id__get(args: {
    path: {
      fixture_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/tool-fixtures/{fixture_id}', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async get_work_summary_api_console_work_summary_get(args?: {
    query?: {
      owner_unit_id?: string | null;
    };
}): Promise<WorkSummaryResponse> {
    const path = '/api/console/work-summary';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<WorkSummaryResponse>(url, { method: 'GET' });
  },
  async get_workbench_overview_api_console_workbench_overview_get(): Promise<OverviewApiResponse> {
    const path = '/api/console/workbench/overview';
    const url = path;
    return apiClient<OverviewApiResponse>(url, { method: 'GET' });
  },
  async get_workflow_detail_api_console_workflows__kind___item_id__get(args: {
    path: {
      kind: string;
      item_id: string;
    };
}): Promise<WorkflowDetailResponse> {
    const path = buildPath('/api/console/workflows/{kind}/{item_id}', args.path);
    const url = path;
    return apiClient<WorkflowDetailResponse>(url, { method: 'GET' });
  },
  async governance_audit_api_governance_audit_get(args?: {
    query?: {
      actor_id?: string | null;
      action?: string | null;
      target_type?: string | null;
      start_date?: string | null;
      end_date?: string | null;
      limit?: number;
      cursor?: string | null;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/governance/audit';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async governance_audit_export_api_governance_audit_export_get(args?: {
    query?: {
      actor_id?: string | null;
      action?: string | null;
      target_type?: string | null;
      start_date?: string | null;
      end_date?: string | null;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/governance/audit/export';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async governance_eval_harness_status_api_governance_eval_harness_get(): Promise<Record<string, unknown>> {
    const path = '/api/governance/eval-harness';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async governance_prompt_detail_api_governance_prompts__prompt_id__get(args: {
    path: {
      prompt_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/prompts/{prompt_id}', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async governance_prompt_diff_api_governance_prompts__prompt_id__versions__version_id__diff_get(args: {
    path: {
      prompt_id: string;
      version_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/prompts/{prompt_id}/versions/{version_id}/diff', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async governance_search_api_governance_search_get(args?: {
    query?: {
      q?: string;
      doc_type?: string | null;
      owner_unit_id?: string | null;
      status?: string | null;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/governance/search';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async handle_conversation_action_api_console_workbench_conversations__conversation_id__action_post(args: {
    path: {
      conversation_id: string;
    };
    body: ConversationActionRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/console/workbench/conversations/{conversation_id}/action', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async health_summary_api_health_summary_get(args?: {
    query?: {
      date?: string | null;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/health/summary';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async healthz_healthz_get(): Promise<Record<string, string>> {
    const path = '/healthz';
    const url = path;
    return apiClient<Record<string, string>>(url, { method: 'GET' });
  },
  async index__get(): Promise<unknown> {
    const path = '/';
    const url = path;
    return apiClient<unknown>(url, { method: 'GET' });
  },
  async issue_routes_api_issues__issue_type_id__routes_get(args: {
    path: {
      issue_type_id: string;
    };
    query?: {
      days?: number;
      preset?: string | null;
      start_date?: string | null;
      end_date?: string | null;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/issues/{issue_type_id}/routes', args.path);
    const url = `${path}${buildQuery(args.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async issues_summary_api_issues_summary_get(args?: {
    query?: {
      days?: number;
      preset?: string | null;
      start_date?: string | null;
      end_date?: string | null;
      query?: string | null;
      owner_unit_id?: string | null;
      refresh?: boolean;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/issues/summary';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async knowledge_bridge_status_api_knowledge_status_get(): Promise<Record<string, unknown>> {
    const path = '/api/knowledge/status';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async knowledge_documents_api_knowledge_get(args?: {
    query?: {
      status?: string | null;
      owner_unit_id?: string | null;
      query?: string | null;
      format_type?: string | null;
      days?: number;
      preset?: string | null;
      limit?: number;
      cursor?: string | null;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/knowledge';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async knowledge_performance_api_knowledge__document_id__performance_get(args: {
    path: {
      document_id: string;
    };
    query?: {
      days?: number;
      preset?: string | null;
      start_date?: string | null;
      end_date?: string | null;
      issue_type_id?: string | null;
      limit?: number;
      cursor?: string | null;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/knowledge/{document_id}/performance', args.path);
    const url = `${path}${buildQuery(args.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async knowledge_proxy_delete(args: {
    path: {
      full_path: string;
    };
}): Promise<unknown> {
    const path = buildPath('/api/knowledge/{full_path}', args.path);
    const url = path;
    return apiClient<unknown>(url, { method: 'DELETE' });
  },
  async knowledge_proxy_get(args: {
    path: {
      full_path: string;
    };
}): Promise<unknown> {
    const path = buildPath('/api/knowledge/{full_path}', args.path);
    const url = path;
    return apiClient<unknown>(url, { method: 'GET' });
  },
  async knowledge_proxy_post(args: {
    path: {
      full_path: string;
    };
}): Promise<unknown> {
    const path = buildPath('/api/knowledge/{full_path}', args.path);
    const url = path;
    return apiClient<unknown>(url, { method: 'POST' });
  },
  async knowledge_proxy_put(args: {
    path: {
      full_path: string;
    };
}): Promise<unknown> {
    const path = buildPath('/api/knowledge/{full_path}', args.path);
    const url = path;
    return apiClient<unknown>(url, { method: 'PUT' });
  },
  async knowledge_ui_knowledge_ui__get(args?: {
    query?: {
      path?: string;
    };
}): Promise<unknown> {
    const path = '/knowledge-ui/';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<unknown>(url, { method: 'GET' });
  },
  async knowledge_ui_knowledge_ui__path__get(args: {
    path: {
      path: string;
    };
}): Promise<unknown> {
    const path = buildPath('/knowledge-ui/{path}', args.path);
    const url = path;
    return apiClient<unknown>(url, { method: 'GET' });
  },
  async knowledge_ui_knowledge_ui_get(args?: {
    query?: {
      path?: string;
    };
}): Promise<unknown> {
    const path = '/knowledge-ui';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<unknown>(url, { method: 'GET' });
  },
  async legacy_shell_legacy__get(): Promise<unknown> {
    const path = '/legacy/';
    const url = path;
    return apiClient<unknown>(url, { method: 'GET' });
  },
  async legacy_shell_legacy_get(): Promise<unknown> {
    const path = '/legacy';
    const url = path;
    return apiClient<unknown>(url, { method: 'GET' });
  },
  async link_quality_case_api_evaluations_runs__run_id__cases__execution_id__quality_case_post(args: {
    path: {
      run_id: string;
      execution_id: string;
    };
    body: CreateQualityCasePayload;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/runs/{run_id}/cases/{execution_id}/quality-case', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async link_quality_case_content_api_quality_cases__case_id__content_post(args: {
    path: {
      case_id: string;
    };
    body: QualityContentLinkRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/quality-cases/{case_id}/content', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async list_alerts_api_alerts_get(args?: {
    query?: {
      alert_type?: string | null;
      severity?: string | null;
      status?: string | null;
      scope_type?: string | null;
      scope_id?: string | null;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/alerts';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async list_budget_policies_api_budget_policies_get(): Promise<Record<string, unknown>> {
    const path = '/api/budget-policies';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async list_case_executions_api_evaluations_runs__run_id__cases_get(args: {
    path: {
      run_id: string;
    };
    query?: {
      side?: 'BASELINE' | 'CANDIDATE' | null;
    };
}): Promise<Array<Record<string, unknown>>> {
    const path = buildPath('/api/evaluations/runs/{run_id}/cases', args.path);
    const url = `${path}${buildQuery(args.query)}`;
    return apiClient<Array<Record<string, unknown>>>(url, { method: 'GET' });
  },
  async list_cases_api_evaluations_cases_get(args?: {
    query?: {
      q?: string | null;
      owner_unit_id?: string | null;
      status?: string | null;
      behavior?: string | null;
      criticality?: string | null;
      source_health?: string | null;
      source_type?: string | null;
      source_id?: string | null;
      limit?: number;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/evaluations/cases';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async list_decisions_api_evaluations_gate_decisions_get(args?: {
    query?: {
      target_manifest_hash?: string | null;
    };
}): Promise<Array<Record<string, unknown>>> {
    const path = '/api/evaluations/gate-decisions';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Array<Record<string, unknown>>>(url, { method: 'GET' });
  },
  async list_examples_api_examples_get(args?: {
    query?: {
      source_type?: 'FAQ' | 'DOCUMENT' | 'CONVERSATION' | 'MANUAL' | null;
      source_id?: string | null;
      status?: 'DRAFT' | 'VERIFIED' | 'REJECTED' | 'RETIRED' | null;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/examples';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async list_faqs_api_faqs_get(args?: {
    query?: {
      status?: string | null;
      owner_unit_id?: string | null;
      category?: string | null;
      keyword?: string | null;
      query?: string | null;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/faqs';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async list_feature_flags_api_feature_flags_get(): Promise<Record<string, unknown>> {
    const path = '/api/feature-flags';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async list_gate_policies_api_evaluations_gate_policies_get(): Promise<Array<Record<string, unknown>>> {
    const path = '/api/evaluations/gate-policies';
    const url = path;
    return apiClient<Array<Record<string, unknown>>>(url, { method: 'GET' });
  },
  async list_governance_flags_api_governance_flags_get(): Promise<Record<string, unknown>> {
    const path = '/api/governance/flags';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async list_governance_models_api_governance_models_get(): Promise<Record<string, unknown>> {
    const path = '/api/governance/models';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async list_governance_prompts_api_governance_prompts_get(): Promise<Record<string, unknown>> {
    const path = '/api/governance/prompts';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async list_masking_api_governance_masking_get(): Promise<Record<string, unknown>> {
    const path = '/api/governance/masking';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async list_prompt_candidates_api_prompts_candidates_get(): Promise<Record<string, unknown>> {
    const path = '/api/prompts/candidates';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async list_quality_candidates_api_quality_candidates_get(args?: {
    query?: {
      status?: string | null;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/quality-candidates';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async list_quality_cases_api_quality_cases_get(args?: {
    query?: {
      status?: string | null;
      case_type?: string | null;
      owner_unit_id?: string | null;
      issue_type_id?: string | null;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/quality-cases';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async list_question_clusters_api_question_clusters_get(): Promise<Record<string, unknown>> {
    const path = '/api/question-clusters';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async list_retention_api_governance_retention_get(): Promise<Record<string, unknown>> {
    const path = '/api/governance/retention';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async list_role_changes_api_governance_roles_get(): Promise<Record<string, unknown>> {
    const path = '/api/governance/roles';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async list_runs_api_evaluations_runs_get(args?: {
    query?: {
      set_version_id?: string | null;
    };
}): Promise<Array<Record<string, unknown>>> {
    const path = '/api/evaluations/runs';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Array<Record<string, unknown>>>(url, { method: 'GET' });
  },
  async list_schedules_api_evaluations_schedules_get(): Promise<Array<Record<string, unknown>>> {
    const path = '/api/evaluations/schedules';
    const url = path;
    return apiClient<Array<Record<string, unknown>>>(url, { method: 'GET' });
  },
  async list_sets_api_evaluations_sets_get(args?: {
    query?: {
      purpose?: 'DEVELOPMENT' | 'HOLDOUT' | null;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/evaluations/sets';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async list_sync_jobs_api_sync_jobs_get(): Promise<Record<string, unknown>> {
    const path = '/api/sync-jobs';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async list_tool_fixtures_api_evaluations_tool_fixtures_get(): Promise<Array<Record<string, unknown>>> {
    const path = '/api/evaluations/tool-fixtures';
    const url = path;
    return apiClient<Array<Record<string, unknown>>>(url, { method: 'GET' });
  },
  async list_work_items_api_console_work_items_get(args?: {
    query?: {
      bucket?: string;
      workflow?: string | null;
      owner_unit_id?: string | null;
      cursor?: string | null;
      limit?: number;
    };
}): Promise<WorkItemsResponse> {
    const path = '/api/console/work-items';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<WorkItemsResponse>(url, { method: 'GET' });
  },
  async list_workbench_conversations_api_console_workbench_conversations_get(): Promise<Array<ConversationDetail>> {
    const path = '/api/console/workbench/conversations';
    const url = path;
    return apiClient<Array<ConversationDetail>>(url, { method: 'GET' });
  },
  async list_workbench_documents_api_console_workbench_documents_get(): Promise<Array<ManualDocumentItem>> {
    const path = '/api/console/workbench/documents';
    const url = path;
    return apiClient<Array<ManualDocumentItem>>(url, { method: 'GET' });
  },
  async list_workbench_faqs_api_console_workbench_faqs_get(): Promise<Array<FaqItem>> {
    const path = '/api/console/workbench/faqs';
    const url = path;
    return apiClient<Array<FaqItem>>(url, { method: 'GET' });
  },
  async list_workbench_tickets_api_console_workbench_tickets_get(): Promise<Array<ItTicketItem>> {
    const path = '/api/console/workbench/tickets';
    const url = path;
    return apiClient<Array<ItTicketItem>>(url, { method: 'GET' });
  },
  async merge_quality_candidates_api_quality_candidates_merge_post(args: {
    body: QualityCandidateMergeRequest;
}): Promise<Record<string, unknown>> {
    const path = '/api/quality-candidates/merge';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async metrics_definitions_api_metrics_definitions_get(): Promise<Record<string, unknown>> {
    const path = '/api/metrics/definitions';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async operations_summary_api_operations_summary_get(args?: {
    query?: {
      days?: number;
      preset?: string | null;
      start_date?: string | null;
      end_date?: string | null;
      model?: string | null;
      issue_type_id?: string | null;
      interval?: string;
      refresh?: boolean;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/operations/summary';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async portal_dto_catalog_api_console_workbench__well_known_portal_dto_catalog_get(): Promise<PortalWorkbenchDtoCatalog> {
    const path = '/api/console/workbench/.well-known/portal-dto-catalog';
    const url = path;
    return apiClient<PortalWorkbenchDtoCatalog>(url, { method: 'GET' });
  },
  async post_console_agent_knowledge_sync(): Promise<Record<string, unknown>> {
    const path = '/api/console/agent-knowledge/sync';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'POST' });
  },
  async preflight_run_api_evaluations_runs_preflight_post(args: {
    body: PreflightRunPayload;
}): Promise<Record<string, unknown>> {
    const path = '/api/evaluations/runs/preflight';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async publish_set_version_api_evaluations_sets__set_id__versions__version_id__publish_post(args: {
    path: {
      set_id: string;
      version_id: string;
    };
    body: PublishSetVersionPayload;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/sets/{set_id}/versions/{version_id}/publish', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async purge_retention_api_admin_retention_purge_post(): Promise<Record<string, unknown>> {
    const path = '/api/admin/retention/purge';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'POST' });
  },
  async put_knowledge_workspace_api_knowledge_workspace_put(args: {
    body: KnowledgeWorkspaceUpdateRequest;
}): Promise<Record<string, unknown>> {
    const path = '/api/knowledge-workspace';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'PUT', body });
  },
  async reconciliation_costs_summary_api_admin_reconciliation_costs_summary_get(args?: {
    query?: {
      days?: number;
      preset?: string | null;
      start_date?: string | null;
      end_date?: string | null;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/admin/reconciliation/costs-summary';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async reconciliation_issues_summary_api_admin_reconciliation_issues_summary_get(args?: {
    query?: {
      days?: number;
      preset?: string | null;
      start_date?: string | null;
      end_date?: string | null;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/admin/reconciliation/issues-summary';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async reconciliation_operations_summary_api_admin_reconciliation_operations_summary_get(args?: {
    query?: {
      days?: number;
      preset?: string | null;
      start_date?: string | null;
      end_date?: string | null;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/admin/reconciliation/operations-summary';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async refresh_quality_candidates_api_quality_candidates_refresh_post(args: {
    body: QualityCandidateRefreshRequest;
}): Promise<Record<string, unknown>> {
    const path = '/api/quality-candidates/refresh';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async refresh_quality_case_observation_api_quality_cases__case_id__observation_refresh_post(args: {
    path: {
      case_id: string;
    };
    body: FaqTransitionRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/quality-cases/{case_id}/observation/refresh', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async request_exception_api_evaluations_gate_decisions__decision_id__exceptions_post(args: {
    path: {
      decision_id: string;
    };
    body: RequestExceptionPayload;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/gate-decisions/{decision_id}/exceptions', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async request_role_change_api_governance_roles_requests_post(args: {
    body: RoleRequestBody;
}): Promise<Record<string, unknown>> {
    const path = '/api/governance/roles/requests';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async rescore_run_api_evaluations_runs__run_id__rescore_post(args: {
    path: {
      run_id: string;
    };
    body: RescoreRunPayload;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/runs/{run_id}/rescore', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async resolve_alert_api_alerts__alert_id__resolve_post(args: {
    path: {
      alert_id: string;
    };
    body: FaqReasonRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/alerts/{alert_id}/resolve', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async resolve_governance_prompt_api_governance_prompts__prompt_id__runtime_get(args: {
    path: {
      prompt_id: string;
    };
    query: {
      conversation_id: string;
      tenant?: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/prompts/{prompt_id}/runtime', args.path);
    const url = `${path}${buildQuery(args.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async resolve_sources_api_sources_get(args?: {
    query?: {
      documentId?: string | null;
      versionId?: string | null;
      releaseId?: string | null;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/sources';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async retention_status_api_admin_retention_status_get(): Promise<Record<string, unknown>> {
    const path = '/api/admin/retention/status';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async retire_case_api_evaluations_cases__case_id__retire_post(args: {
    path: {
      case_id: string;
    };
    body: RetireCasePayload;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/cases/{case_id}/retire', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async retire_example_api_examples__example_id__retire_post(args: {
    path: {
      example_id: string;
    };
    body: ExampleRetireRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/examples/{example_id}/retire', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async retry_alert_delivery_api_alerts__alert_id__deliveries__delivery_id__retry_post(args: {
    path: {
      alert_id: string;
      delivery_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/alerts/{alert_id}/deliveries/{delivery_id}/retry', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'POST' });
  },
  async retry_sync_job_api_sync_jobs__job_id__retry_post(args: {
    path: {
      job_id: string;
    };
    body: SyncJobActionRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/sync-jobs/{job_id}/retry', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async review_case_execution_api_evaluations_runs__run_id__reviews_post(args: {
    path: {
      run_id: string;
    };
    body: ReviewExecutionPayload;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/runs/{run_id}/reviews', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async review_example_api_examples__example_id__review_post(args: {
    path: {
      example_id: string;
    };
    body: ExampleReviewRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/examples/{example_id}/review', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async review_faq_api_faqs__faq_id__versions__version_id__review_post(args: {
    path: {
      faq_id: string;
      version_id: string;
    };
    body: FaqReviewRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/faqs/{faq_id}/versions/{version_id}/review', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async review_revision_api_evaluations_cases__case_id__revisions__revision_id__review_post(args: {
    path: {
      case_id: string;
      revision_id: string;
    };
    body: ReviewRevisionPayload;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/cases/{case_id}/revisions/{revision_id}/review', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async revoke_principal_api_governance_roles_revoke_post(args: {
    body: RevokeBody;
}): Promise<Record<string, unknown>> {
    const path = '/api/governance/roles/revoke';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async rollback_faq_api_faqs__faq_id__versions__version_id__rollback_post(args: {
    path: {
      faq_id: string;
      version_id: string;
    };
    body: FaqReasonRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/faqs/{faq_id}/versions/{version_id}/rollback', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async rollback_governance_model_api_governance_models__config_id__rollback_post(args: {
    path: {
      config_id: string;
    };
    body: ReasonBody;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/models/{config_id}/rollback', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async rollback_governance_prompt_api_governance_prompts__prompt_id__rollback_post(args: {
    path: {
      prompt_id: string;
    };
    body: PromptRollbackBody;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/prompts/{prompt_id}/rollback', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async routes_summary_api_routes_summary_get(args?: {
    query?: {
      days?: number;
      preset?: string | null;
      start_date?: string | null;
      end_date?: string | null;
      issue_type_id?: string | null;
      route?: string | null;
      refresh?: boolean;
    };
}): Promise<Record<string, unknown>> {
    const path = '/api/routes/summary';
    const url = `${path}${buildQuery(args?.query)}`;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async save_workbench_faq_api_console_workbench_faqs_post(args: {
    body: QuickFaqSaveRequest;
}): Promise<Record<string, unknown>> {
    const path = '/api/console/workbench/faqs';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async schedule_governance_model_api_governance_models__config_id__versions__version_id__schedule_post(args: {
    path: {
      config_id: string;
      version_id: string;
    };
    body: ReasonBody;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/models/{config_id}/versions/{version_id}/schedule', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async set_budget_policy_state_api_budget_policies__policy_id__state_post(args: {
    path: {
      policy_id: string;
    };
    body: BudgetPolicyStateRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/budget-policies/{policy_id}/state', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async set_emergency_broadcast_api_console_workbench_broadcast_post(args: {
    body: BroadcastRequest;
}): Promise<Record<string, unknown>> {
    const path = '/api/console/workbench/broadcast';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async simulate_ai_answer_api_console_workbench_simulate_post(args: {
    body: SimulationRequest;
}): Promise<Record<string, unknown>> {
    const path = '/api/console/workbench/simulate';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async simulate_model_fallback_api_governance_models__config_id__simulate_fallback_post(args: {
    path: {
      config_id: string;
    };
    body: FallbackBody;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/models/{config_id}/simulate-fallback', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async source_file_get(args: {
    path: {
      source_ref_id: string;
    };
}): Promise<unknown> {
    const path = buildPath('/api/sources/{source_ref_id}/file', args.path);
    const url = path;
    return apiClient<unknown>(url, { method: 'GET' });
  },
  async source_file_head(args: {
    path: {
      source_ref_id: string;
    };
}): Promise<unknown> {
    const path = buildPath('/api/sources/{source_ref_id}/file', args.path);
    const url = path;
    return apiClient<unknown>(url, { method: 'HEAD' });
  },
  async source_preview_api_sources__source_ref_id__get(args: {
    path: {
      source_ref_id: string;
    };
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/sources/{source_ref_id}', args.path);
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async start_candidate_job_api_evaluations_candidate_jobs_post(args: {
    body: CandidateJobPayload;
}): Promise<Record<string, unknown>> {
    const path = '/api/evaluations/candidate-jobs';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async stop_governance_prompt_canary_api_governance_prompts__prompt_id__canary_stop_post(args: {
    path: {
      prompt_id: string;
    };
    body: PromptCanaryStopBody;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/governance/prompts/{prompt_id}/canary/stop', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async submit_faq_api_faqs__faq_id__versions__version_id__submit_post(args: {
    path: {
      faq_id: string;
      version_id: string;
    };
    body: FaqTransitionRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/faqs/{faq_id}/versions/{version_id}/submit', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async submit_revision_api_evaluations_cases__case_id__revisions__revision_id__submit_post(args: {
    path: {
      case_id: string;
      revision_id: string;
    };
    body: SubmitRevisionPayload;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/cases/{case_id}/revisions/{revision_id}/submit', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async taxonomy_api_taxonomy_get(): Promise<Record<string, unknown>> {
    const path = '/api/taxonomy';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'GET' });
  },
  async transition_quality_case_api_quality_cases__case_id__transition_post(args: {
    path: {
      case_id: string;
    };
    body: QualityCaseTransitionRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/quality-cases/{case_id}/transition', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async trigger_health_check_alerts_api_health_check_alerts_post(): Promise<Record<string, unknown>> {
    const path = '/api/health/check-alerts';
    const url = path;
    return apiClient<Record<string, unknown>>(url, { method: 'POST' });
  },
  async update_budget_policy_api_budget_policies__policy_id__put(args: {
    path: {
      policy_id: string;
    };
    body: BudgetPolicyUpdateRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/budget-policies/{policy_id}', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'PUT', body });
  },
  async update_costs_rate_api_costs_rates_post(args: {
    body: Record<string, unknown>;
}): Promise<Record<string, unknown>> {
    const path = '/api/costs/rates';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async update_example_api_examples__example_id__put(args: {
    path: {
      example_id: string;
    };
    body: ExampleUpdateRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/examples/{example_id}', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'PUT', body });
  },
  async update_quality_case_api_quality_cases__case_id__put(args: {
    path: {
      case_id: string;
    };
    body: QualityCaseUpdateRequest;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/quality-cases/{case_id}', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'PUT', body });
  },
  async update_schedule_api_evaluations_schedules__schedule_id__patch(args: {
    path: {
      schedule_id: string;
    };
    body: UpdateSchedulePayload;
}): Promise<Record<string, unknown>> {
    const path = buildPath('/api/evaluations/schedules/{schedule_id}', args.path);
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'PATCH', body });
  },
  async upload_workbench_document_api_console_workbench_documents_upload_post(args: {
    body: FormData | Body_upload_workbench_document_api_console_workbench_documents_upload_post;
}): Promise<unknown> {
    const path = '/api/console/workbench/documents/upload';
    const url = path;
    const body = toFormData(args.body);
    return apiClient<unknown>(url, { method: 'POST', body });
  },
  async validate_import_api_evaluations_imports_validate_post(args: {
    body: ImportValidatePayload;
}): Promise<Record<string, unknown>> {
    const path = '/api/evaluations/imports/validate';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
  async verify_release_api_evaluations_verify_release_post(args: {
    body: VerifyReleasePayload;
}): Promise<Record<string, unknown>> {
    const path = '/api/evaluations/verify-release';
    const url = path;
    const body = args.body === undefined ? undefined : JSON.stringify(args.body);
    return apiClient<Record<string, unknown>>(url, { method: 'POST', body });
  },
} as const;

export type BackofficeClient = typeof backofficeClient;
