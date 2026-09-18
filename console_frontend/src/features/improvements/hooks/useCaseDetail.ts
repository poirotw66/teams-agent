import { useState, useEffect, useCallback } from 'react';
import { Form, message } from 'antd';
import { apiClient } from '../../../shared/api/client';
import { authRequestHeaders } from '../../../shared/auth/session';
import { WorkflowDetailResponse } from '../../../shared/api/types';

export type SourcePreview = {
  sourceRefId?: string;
  documentId?: string;
  downloadUrl?: string;
  title?: string;
};

export type CaseRecord = {
  etag?: number;
  status?: string;
  title?: string;
  description?: string;
  owner_unit_id?: string;
  issue_type_id?: string;
  priority?: string;
  assignee_id?: string;
  target_due_at?: string;
  resolution_type?: string;
  resolution_reason?: string;
  observation_started_at?: string;
  observation_updated_at?: string;
  observation_latest?: { verdict?: string };
  conversation_refs?: string[];
  document_ids?: string[];
};

async function openAuthenticatedFile(downloadUrl: string): Promise<void> {
  const headers = new Headers();
  for (const [name, value] of Object.entries(authRequestHeaders())) {
    headers.set(name, value);
  }
  const response = await fetch(downloadUrl, {
    headers,
    credentials: 'same-origin',
  });
  if (!response.ok) {
    throw new Error(`開啟原檔失敗（HTTP ${response.status}）`);
  }
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  window.open(objectUrl, '_blank', 'noopener,noreferrer');
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
}

/** Loads quality-case detail and exposes status / source / draft actions. */
export function useCaseDetail(caseId: string | undefined) {
  const [workflow, setWorkflow] = useState<WorkflowDetailResponse | null>(null);
  const [caseData, setCaseData] = useState<CaseRecord | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const [isDraftModalOpen, setIsDraftModalOpen] = useState<boolean>(false);
  const [isResolveModalOpen, setIsResolveModalOpen] = useState<boolean>(false);
  const [isCloseModalOpen, setIsCloseModalOpen] = useState<boolean>(false);
  const [isConversationModalOpen, setIsConversationModalOpen] = useState<boolean>(false);
  const [conversationDetail, setConversationDetail] = useState<Record<string, unknown> | null>(
    null
  );
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [openingSource, setOpeningSource] = useState<boolean>(false);

  const [draftForm] = Form.useForm();
  const [resolveForm] = Form.useForm();
  const [closeForm] = Form.useForm();

  const loadCaseDetail = useCallback(async () => {
    if (!caseId) return;
    setLoading(true);
    setError(null);
    try {
      const [wfRes, caseRes] = await Promise.all([
        apiClient<WorkflowDetailResponse>(`/api/console/workflows/quality_case/${caseId}`),
        apiClient<{ case?: CaseRecord } & CaseRecord>(`/api/quality-cases/${caseId}`),
      ]);
      setWorkflow(wfRes);
      setCaseData(caseRes.case || caseRes);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '載入品質案件詳情失敗';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [caseId]);

  useEffect(() => {
    void loadCaseDetail();
  }, [loadCaseDetail]);

  const currentEtag = caseData?.etag ?? 1;

  const openOriginalByDocument = async (documentId: string) => {
    setOpeningSource(true);
    try {
      const preview = await apiClient<SourcePreview>(
        `/api/sources?documentId=${encodeURIComponent(documentId)}`
      );
      if (!preview.downloadUrl) {
        throw new Error('此文件尚無可開啟的原檔');
      }
      await openAuthenticatedFile(preview.downloadUrl);
      message.success(`已開啟原檔 ${preview.sourceRefId || documentId}`);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '開啟原檔失敗');
    } finally {
      setOpeningSource(false);
    }
  };

  const openOriginalBySourceRef = async (sourceRefId: string) => {
    setOpeningSource(true);
    try {
      const preview = await apiClient<SourcePreview>(
        `/api/sources/${encodeURIComponent(sourceRefId)}`
      );
      if (!preview.downloadUrl) {
        throw new Error('此來源尚無可開啟的原檔');
      }
      await openAuthenticatedFile(preview.downloadUrl);
      message.success(`已開啟原檔 ${sourceRefId}`);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '開啟原檔失敗');
    } finally {
      setOpeningSource(false);
    }
  };

  const openConversation = async (conversationId: string) => {
    try {
      const detail = await apiClient<Record<string, unknown>>(
        `/api/conversations/${encodeURIComponent(conversationId)}`
      );
      setConversationDetail(detail);
      setIsConversationModalOpen(true);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '載入對話失敗');
    }
  };

  const handleTransition = async (
    status: string,
    reason: string | null = null,
    resolutionType: string | null = null
  ) => {
    if (!caseId) return;
    setSubmitting(true);
    try {
      await apiClient(`/api/quality-cases/${caseId}/transition`, {
        method: 'POST',
        body: JSON.stringify({
          status,
          reason,
          resolution_type: resolutionType,
          expected_etag: currentEtag,
        }),
      });
      message.success(`狀態已成功更新至：${status}`);
      await loadCaseDetail();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '狀態切換失敗';
      message.error(msg);
      if (
        err &&
        typeof err === 'object' &&
        'status' in err &&
        (err as { status: number }).status === 409
      ) {
        await loadCaseDetail();
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleCreateDraft = async (values: {
    title: string;
    content: string;
    notes?: string;
  }) => {
    if (!caseId) return;
    setSubmitting(true);
    try {
      await apiClient(`/api/quality-cases/${caseId}/document-draft`, {
        method: 'POST',
        body: JSON.stringify({
          title: values.title,
          content: values.content,
          notes: values.notes || null,
          expected_case_etag: currentEtag,
        }),
      });
      message.success('已成功建立修正文件草稿並關聯至本案件');
      setIsDraftModalOpen(false);
      draftForm.resetFields();
      await loadCaseDetail();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '建立文件草稿失敗';
      message.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleResolveSubmit = async (values: {
    resolution_type: string;
    reason: string;
  }) => {
    await handleTransition('RESOLVED', values.reason, values.resolution_type);
    setIsResolveModalOpen(false);
    resolveForm.resetFields();
  };

  const handleCloseSubmit = async (values: { status: string; reason: string }) => {
    await handleTransition(values.status, values.reason, null);
    setIsCloseModalOpen(false);
    closeForm.resetFields();
  };

  const handleRefreshObservation = async () => {
    if (!caseId) return;
    setSubmitting(true);
    try {
      await apiClient(`/api/quality-cases/${caseId}/observation/refresh`, {
        method: 'POST',
        body: JSON.stringify({
          expected_etag: currentEtag,
        }),
      });
      message.success('已重新計算最新上線觀察指標');
      await loadCaseDetail();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '更新觀察指標失敗';
      message.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const closeConversationModal = () => {
    setIsConversationModalOpen(false);
    setConversationDetail(null);
  };

  return {
    workflow,
    caseData,
    loading,
    error,
    currentEtag,
    submitting,
    openingSource,
    isDraftModalOpen,
    setIsDraftModalOpen,
    isResolveModalOpen,
    setIsResolveModalOpen,
    isCloseModalOpen,
    setIsCloseModalOpen,
    isConversationModalOpen,
    conversationDetail,
    closeConversationModal,
    draftForm,
    resolveForm,
    closeForm,
    openOriginalByDocument,
    openOriginalBySourceRef,
    openConversation,
    handleTransition,
    handleCreateDraft,
    handleResolveSubmit,
    handleCloseSubmit,
    handleRefreshObservation,
  };
}
