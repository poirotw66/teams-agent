import React, { useMemo, useState } from 'react';
import { Alert, Button, Input, Modal, Space, Tooltip, Typography, message } from 'antd';
import {
  CheckCircleOutlined,
  EditOutlined,
  RocketOutlined,
  SendOutlined,
} from '@ant-design/icons';
import { ManualDocumentItem } from '../../../shared/api/types';
import { workbenchStore } from '../../../shared/api/workbenchStore';

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

export const DocumentGovernanceActions: React.FC<DocumentGovernanceActionsProps> = ({
  document,
  onComplete,
}) => {
  const [action, setAction] = useState<GovernanceAction | null>(null);
  const [reason, setReason] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const content = action ? ACTION_CONTENT[action] : null;
  const qualityIsReady = document.quality?.acceptable === true;

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

  const openAction = (nextAction: GovernanceAction) => {
    setAction(nextAction);
    setReason(ACTION_CONTENT[nextAction].defaultReason);
  };

  const completeAction = async () => {
    if (!action || !reason.trim()) return;
    setIsSubmitting(true);
    try {
      if (action === 'SUBMIT') {
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
      setIsSubmitting(false);
    }
  };

  if (availableActions.length === 0) return null;

  return (
    <>
      <Space size={6}>
        {availableActions.map((item) => {
          const isSubmitBlocked = item === 'SUBMIT' && !qualityIsReady;
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
              disabled={isSubmitBlocked}
              icon={icon}
              onClick={() => openAction(item)}
            >
              {ACTION_CONTENT[item].label}
            </Button>
          );
          return isSubmitBlocked ? (
            <Tooltip key={item} title="請先開啟段落預覽並通過品質檢查">
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
          disabled: !reason.trim(),
        }}
        onOk={completeAction}
        onCancel={() => setAction(null)}
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
              isSubmitting
                ? '系統完成 Hybrid、Gemini File Search 與 Agent reload 後會自動切換正式版本。'
                : '只有 Hybrid 與 Gemini File Search 都完成同步後，正式版本才會切換。失敗時會保留目前版本。'
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
