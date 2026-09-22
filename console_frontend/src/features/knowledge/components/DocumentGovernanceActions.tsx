import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Input, Modal, Space, Tooltip, Typography, message } from 'antd';
import {
  CheckCircleOutlined,
  EditOutlined,
  RocketOutlined,
  SendOutlined,
} from '@ant-design/icons';
import { ManualDocumentItem } from '../../../shared/api/types';
import { workbenchStore } from '../../../shared/api/workbenchStore';
import { PublishElapsedLabel } from './PublishElapsedLabel';
import {
  clearFormalPublishInFlight,
  startFormalPublishInFlight,
} from '../lib/formalPublishSession';

const { Text } = Typography;

type GovernanceAction = 'SUBMIT' | 'APPROVE' | 'REQUEST_CHANGES' | 'PUBLISH';

interface DocumentGovernanceActionsProps {
  document: ManualDocumentItem;
  onComplete: () => void;
}

const ACTION_CONTENT: Record<
  GovernanceAction,
  { title: string; label: string; defaultReason: string; success: string }
> = {
  SUBMIT: {
    title: '送出品質審查',
    label: '送出審查',
    defaultReason: '段落品質檢查已通過，送交內容與權限審查。',
    success: '文件已送出審查。',
  },
  APPROVE: {
    title: '核准文件版本',
    label: '核准',
    defaultReason: '內容、來源定位與存取權限均符合發布要求。',
    success: '文件版本已核准。',
  },
  REQUEST_CHANGES: {
    title: '要求修改',
    label: '要求修改',
    defaultReason: '',
    success: '文件已退回修改。',
  },
  PUBLISH: {
    title: '發布至正式知識庫',
    label: '正式發布',
    defaultReason: '核准版本發布至 Hybrid 與 Gemini File Search。',
    success: '文件已發布並同步至雙後端。',
  },
};

function blockingQualityMessage(document: ManualDocumentItem): string | null {
  const quality = document.quality;
  if (!quality) {
    return '尚無法取得段落品質結果，請稍後再試。';
  }
  if (quality.acceptable) {
    return null;
  }
  const parts: string[] = [];
  if (quality.coverageRatio < 0.995) {
    parts.push(`原文覆蓋 ${(quality.coverageRatio * 100).toFixed(1)}%`);
  }
  if (quality.headingOnlyCount > 0) {
    parts.push(`純標題 ${quality.headingOnlyCount}`);
  }
  if (quality.orphanMediaCount > 0) {
    parts.push(`孤立媒體 ${quality.orphanMediaCount}`);
  }
  if (quality.duplicateChunkCount > 0) {
    parts.push(`重複 ${quality.duplicateChunkCount}`);
  }
  return parts.length > 0
    ? `仍有阻擋送審的品質問題：${parts.join('、')}。過短段落僅為警告，不阻擋送審。`
    : '仍有阻擋送審的品質問題，請開啟段落預覽確認。';
}

export const DocumentGovernanceActions: React.FC<DocumentGovernanceActionsProps> = ({
  document,
  onComplete,
}) => {
  const [action, setAction] = useState<GovernanceAction | null>(null);
  const [reason, setReason] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRefreshingQuality, setIsRefreshingQuality] = useState(false);
  const [publishStartedAtMs, setPublishStartedAtMs] = useState<number | null>(null);
  const qualityRefreshAttempted = useRef<string | null>(null);
  const content = action ? ACTION_CONTENT[action] : null;

  const availableActions = useMemo<GovernanceAction[]>(() => {
    if (document.status === 'IN_REVIEW') return ['APPROVE', 'REQUEST_CHANGES'];
    if (document.status === 'APPROVED') return ['PUBLISH'];
    if (
      document.status === 'DRAFT' ||
      document.status === 'CHUNK_REVIEW' ||
      document.status === 'CHANGES_REQUESTED'
    ) {
      return ['SUBMIT'];
    }
    return [];
  }, [document.status]);

  useEffect(() => {
    if (!isSubmitting || action !== 'PUBLISH') {
      setPublishStartedAtMs(null);
    }
  }, [action, isSubmitting]);

  useEffect(() => {
    const needsSubmit = availableActions.includes('SUBMIT');
    if (
      !needsSubmit ||
      document.quality != null ||
      isRefreshingQuality ||
      qualityRefreshAttempted.current === document.id
    ) {
      return;
    }
    qualityRefreshAttempted.current = document.id;
    setIsRefreshingQuality(true);
    void workbenchStore
      .previewDocument(document, document.chunking_profile || 'AUTO')
      .catch((error: unknown) => {
        const detail = error instanceof Error ? error.message : '伺服器連線異常';
        message.warning(`無法自動檢查段落品質：${detail}`);
      })
      .finally(() => {
        setIsRefreshingQuality(false);
      });
  }, [availableActions, document, isRefreshingQuality]);

  const openAction = (nextAction: GovernanceAction) => {
    setAction(nextAction);
    setReason(ACTION_CONTENT[nextAction].defaultReason);
  };

  const completeAction = async () => {
    if (!action || !reason.trim()) return;
    setIsSubmitting(true);
    if (action === 'PUBLISH') {
      const startedAt = Date.now();
      setPublishStartedAtMs(startedAt);
      startFormalPublishInFlight(document.id, document.title);
    }
    try {
      if (action === 'SUBMIT') {
        const reviewed = await workbenchStore.previewDocument(
          document,
          document.chunking_profile || 'AUTO',
        );
        const blocked = blockingQualityMessage(reviewed);
        if (blocked) {
          message.error(blocked);
          return;
        }
        await workbenchStore.submitDocumentReview(document.id, reason.trim());
      } else if (action === 'PUBLISH') {
        await workbenchStore.publishDocument(document.id, reason.trim());
      } else {
        await workbenchStore.decideDocumentReview(
          document.id,
          action === 'APPROVE' ? 'APPROVED' : 'CHANGES_REQUESTED',
          reason.trim()
        );
      }
      message.success(ACTION_CONTENT[action].success);
      setAction(null);
      onComplete();
    } catch (error) {
      const detail = error instanceof Error ? error.message : '伺服器連線異常';
      message.error(`操作失敗：${detail}`);
    } finally {
      if (action === 'PUBLISH') {
        clearFormalPublishInFlight(document.id);
      }
      setIsSubmitting(false);
      setPublishStartedAtMs(null);
    }
  };

  if (availableActions.length === 0) return null;

  return (
    <>
      <Space size={6}>
        {availableActions.map((item) => {
          const icon =
            item === 'SUBMIT' ? (
              <SendOutlined />
            ) : item === 'APPROVE' ? (
              <CheckCircleOutlined />
            ) : item === 'PUBLISH' ? (
              <RocketOutlined />
            ) : (
              <EditOutlined />
            );
          const button = (
            <Button
              key={item}
              size="small"
              type={item === 'PUBLISH' || item === 'APPROVE' ? 'primary' : 'default'}
              danger={item === 'REQUEST_CHANGES'}
              loading={item === 'SUBMIT' && isRefreshingQuality}
              icon={icon}
              onClick={() => openAction(item)}
            >
              {ACTION_CONTENT[item].label}
            </Button>
          );
          return item === 'SUBMIT' && document.quality && !document.quality.acceptable ? (
            <Tooltip
              key={item}
              title="點擊後會再檢查品質；僅純標題、孤立媒體、重複或覆蓋不足會擋送審。"
            >
              <span>{button}</span>
            </Tooltip>
          ) : (
            button
          );
        })}
      </Space>

      <Modal
        open={action !== null}
        title={content?.title}
        okText={content?.label}
        cancelText="取消"
        confirmLoading={isSubmitting}
        okButtonProps={{
          danger: action === 'REQUEST_CHANGES',
          disabled: !reason.trim() || isSubmitting,
        }}
        cancelButtonProps={{ disabled: isSubmitting && action === 'PUBLISH' }}
        closable={!(isSubmitting && action === 'PUBLISH')}
        maskClosable={!(isSubmitting && action === 'PUBLISH')}
        onOk={completeAction}
        onCancel={() => {
          if (isSubmitting && action === 'PUBLISH') return;
          setAction(null);
        }}
        destroyOnHidden
      >
        {action === 'PUBLISH' && (
          <Alert
            type={isSubmitting ? 'info' : 'warning'}
            showIcon
            message={
              isSubmitting
                ? '正在建立 release 並同步雙後端'
                : '發布會建立新的不可變更 release'
            }
            description={
              isSubmitting ? (
                <Space direction="vertical" size={4}>
                  <Text>
                    系統完成 Hybrid、Gemini File Search 與 Agent reload 後會自動切換正式版本。
                  </Text>
                  <Text type="secondary">
                    <PublishElapsedLabel startedAtMs={publishStartedAtMs} />
                  </Text>
                  <Text type="secondary">
                    請保持此視窗開啟；通常需 1–3 分鐘，大型文件可能更久。
                  </Text>
                </Space>
              ) : (
                '只有 Hybrid 與 Gemini File Search 都完成同步後，正式版本才會切換。失敗時會保留目前版本。'
              )
            }
            style={{ marginBottom: 16 }}
          />
        )}
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Text strong>{action === 'REQUEST_CHANGES' ? '修改要求' : '操作原因'}</Text>
          <Input.TextArea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            rows={4}
            maxLength={2000}
            showCount
            disabled={isSubmitting}
            placeholder={
              action === 'REQUEST_CHANGES'
                ? '請具體說明需修改的內容、頁碼或權限設定'
                : '請填寫本次操作原因'
            }
          />
        </Space>
      </Modal>
    </>
  );
};
