import React from 'react';
import { Alert, Button, Space, Spin } from 'antd';
import { useParams, useNavigate } from 'react-router-dom';
import { useCaseDetail } from '../hooks/useCaseDetail';
import { CaseDetailHeader } from '../components/CaseDetailHeader';
import { CaseWorkflowTimeline } from '../components/CaseWorkflowTimeline';
import { CaseDetailBody } from '../components/CaseDetailBody';
import { CaseDetailModals } from '../components/CaseDetailModals';

export const CaseDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const detail = useCaseDetail(id);

  if (detail.loading && !detail.caseData) {
    return (
      <div style={{ textAlign: 'center', padding: '100px 0' }}>
        <Spin size="large" tip="載入案件詳情中..." />
      </div>
    );
  }

  if (detail.error && !detail.caseData) {
    return (
      <Alert
        type="error"
        showIcon
        message="找不到或無法讀取品質案件"
        description={detail.error}
        action={
          <Button type="primary" onClick={() => navigate('/improvements/cases')}>
            返回案件列表
          </Button>
        }
      />
    );
  }

  const status = String(detail.caseData?.status || 'NEW').toUpperCase();
  const stages = detail.workflow?.stages || [];
  const evidenceRefs = detail.workflow?.evidence_refs || [];
  const caseId = id || '';

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <CaseDetailHeader
        caseId={caseId}
        title={detail.caseData?.title || '品質案件詳情'}
        status={status}
        etag={detail.currentEtag}
        ownerUnitId={detail.caseData?.owner_unit_id}
        submitting={detail.submitting}
        onBack={() => navigate('/improvements/cases')}
        onTransition={(nextStatus, reason) => void detail.handleTransition(nextStatus, reason)}
        onOpenDraftModal={() => detail.setIsDraftModalOpen(true)}
        onOpenResolveModal={() => detail.setIsResolveModalOpen(true)}
        onOpenCloseModal={() => detail.setIsCloseModalOpen(true)}
        onRefreshObservation={() => void detail.handleRefreshObservation()}
      />

      <CaseWorkflowTimeline stages={stages} />

      {detail.caseData ? (
        <CaseDetailBody
          caseData={detail.caseData}
          evidenceRefs={evidenceRefs}
          openingSource={detail.openingSource}
          onOpenConversation={(conversationId) => void detail.openConversation(conversationId)}
          onOpenDocument={(documentId) => void detail.openOriginalByDocument(documentId)}
        />
      ) : null}

      <CaseDetailModals
        caseTitle={detail.caseData?.title}
        submitting={detail.submitting}
        openingSource={detail.openingSource}
        isDraftModalOpen={detail.isDraftModalOpen}
        isResolveModalOpen={detail.isResolveModalOpen}
        isCloseModalOpen={detail.isCloseModalOpen}
        isConversationModalOpen={detail.isConversationModalOpen}
        conversationDetail={detail.conversationDetail}
        draftForm={detail.draftForm}
        resolveForm={detail.resolveForm}
        closeForm={detail.closeForm}
        onCloseDraft={() => detail.setIsDraftModalOpen(false)}
        onCloseResolve={() => detail.setIsResolveModalOpen(false)}
        onCloseClose={() => detail.setIsCloseModalOpen(false)}
        onCloseConversation={detail.closeConversationModal}
        onCreateDraft={(values) => void detail.handleCreateDraft(values)}
        onResolveSubmit={(values) => void detail.handleResolveSubmit(values)}
        onCloseSubmit={(values) => void detail.handleCloseSubmit(values)}
        onOpenDocument={(documentId) => void detail.openOriginalByDocument(documentId)}
        onOpenSourceRef={(sourceRefId) => void detail.openOriginalBySourceRef(sourceRefId)}
      />
    </Space>
  );
};
