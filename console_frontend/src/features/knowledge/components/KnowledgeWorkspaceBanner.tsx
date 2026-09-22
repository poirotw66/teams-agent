import React, { useState } from 'react';
import { Alert, Button, Space, Tag, Typography, message } from 'antd';
import { useGetIdentity } from '@refinedev/core';
import { ApiError } from '../../../shared/api/client';
import { refreshCachedSession } from '../../../app/providers/authProvider';
import {
  KnowledgeWorkspacePayload,
  resetKnowledgeWorkspaceMode,
} from '../../../shared/api/workbench/knowledgeWorkspaceApi';

type KnowledgeIdentity = {
  knowledgeWorkspaceMode?: string;
  cloudFormalWritesAllowed?: boolean;
  cloudFormalWriteBlockReasons?: string[];
  cloudFormalWriteBlockReasonLabels?: string[];
  knowledgeWorkspaceSwitchAllowed?: boolean;
  knowledgeWorkspaceOverrideActive?: boolean;
  knowledgeWorkspaceModeSource?: string;
  authMode?: string;
  relaxedWorkflow?: boolean;
};

const { Text } = Typography;

/**
 * Knowledge admin workspace status.
 *
 * CLOUD formal-path switching is intentionally not offered in console UX yet;
 * operators use the normal knowledge workspace (server mode LOCAL_SANDBOX).
 * If a stale CLOUD override remains, offer reset only.
 */
export const KnowledgeWorkspaceBanner: React.FC = () => {
  const { data: identity, refetch } = useGetIdentity<KnowledgeIdentity>();
  const [saving, setSaving] = useState(false);
  const [localGate, setLocalGate] = useState<KnowledgeWorkspacePayload | null>(null);

  const workspaceMode = String(
    localGate?.knowledgeWorkspaceMode
      || identity?.knowledgeWorkspaceMode
      || 'LOCAL_SANDBOX',
  ).toUpperCase();
  const isCloud = workspaceMode === 'CLOUD_FORMAL';
  const formalAllowed = Boolean(
    localGate?.cloudFormalWritesAllowed ?? identity?.cloudFormalWritesAllowed,
  );
  const blockReasons =
    localGate?.cloudFormalWriteBlockReasons
    || identity?.cloudFormalWriteBlockReasons
    || [];
  const blockLabels =
    localGate?.cloudFormalWriteBlockReasonLabels
    || identity?.cloudFormalWriteBlockReasonLabels
    || blockReasons;
  const canReset = Boolean(
    localGate?.knowledgeWorkspaceSwitchAllowed
    ?? identity?.knowledgeWorkspaceSwitchAllowed,
  );

  const onReset = async () => {
    setSaving(true);
    try {
      const payload = await resetKnowledgeWorkspaceMode();
      setLocalGate(payload);
      await refreshCachedSession();
      await refetch?.();
      message.success('已回到環境預設的知識庫工作區。');
    } catch (err) {
      const detail =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : '重設工作區失敗';
      message.error(detail);
    } finally {
      setSaving(false);
    }
  };

  const resetButton = canReset ? (
    <Button size="small" type="link" disabled={saving} onClick={() => void onReset()}>
      回到知識庫
    </Button>
  ) : null;

  if (isCloud && formalAllowed) {
    return (
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={
          <Space wrap>
            <Tag color="geekblue">正式路徑</Tag>
            <span>目前位於雲端正式寫入路徑（ENTRA 已就緒）。一般知識管理請回到知識庫工作區。</span>
            {resetButton}
          </Space>
        }
      />
    );
  }

  if (isCloud) {
    return (
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message={
          <Space wrap>
            <Tag color="orange">正式路徑（鎖定）</Tag>
            <span>正式雲端寫入尚未開放；管理者上傳／發布請使用一般知識庫工作區。</span>
            {resetButton}
          </Space>
        }
        description={
          <Text type="secondary">
            封鎖原因：{blockLabels.join('；') || '正式身分門檻未就緒'}。
          </Text>
        }
      />
    );
  }

  return (
    <Alert
      type="success"
      showIcon
      style={{ marginBottom: 16 }}
      message={
        <Space wrap>
          <Tag color="blue">知識庫</Tag>
          <span>一般知識管理：草稿、審核與發布由此操作（無需 Entra）。</span>
        </Space>
      }
    />
  );
};
