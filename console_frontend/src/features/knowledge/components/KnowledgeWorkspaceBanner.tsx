import React, { useState } from 'react';
import { Alert, Button, Segmented, Space, Tag, Typography, message } from 'antd';
import { useGetIdentity } from '@refinedev/core';
import { ApiError } from '../../../shared/api/client';
import { refreshCachedSession } from '../../../app/providers/authProvider';
import {
  KnowledgeWorkspacePayload,
  resetKnowledgeWorkspaceMode,
  setKnowledgeWorkspaceMode,
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
 * Explicit LOCAL vs CLOUD workspace labeling + operator switch.
 * Switching to CLOUD does not unlock formal writes; the server gate still applies.
 * Operator overrides persist across Backoffice restarts until reset.
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
  const canSwitch = Boolean(
    localGate?.knowledgeWorkspaceSwitchAllowed
    ?? identity?.knowledgeWorkspaceSwitchAllowed,
  );
  const overrideActive = Boolean(
    localGate?.knowledgeWorkspaceOverrideActive
    ?? identity?.knowledgeWorkspaceOverrideActive,
  );

  const onSwitch = async (next: string) => {
    const mode = next === 'CLOUD_FORMAL' ? 'CLOUD_FORMAL' : 'LOCAL_SANDBOX';
    if (mode === workspaceMode) {
      return;
    }
    setSaving(true);
    try {
      const payload = await setKnowledgeWorkspaceMode(mode, 'console-v2 workspace switch');
      setLocalGate(payload);
      await refreshCachedSession();
      await refetch?.();
      if (mode === 'CLOUD_FORMAL' && !payload.cloudFormalWritesAllowed) {
        message.warning('已切換至雲端工作區，但正式寫入仍鎖定（身分門檻未就緒）。');
      } else if (mode === 'CLOUD_FORMAL') {
        message.success('已切換至雲端正式工作區。');
      } else {
        message.success('已切回本機測試工作區。');
      }
    } catch (err) {
      const detail =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : '切換工作區失敗';
      message.error(detail);
    } finally {
      setSaving(false);
    }
  };

  const onReset = async () => {
    setSaving(true);
    try {
      const payload = await resetKnowledgeWorkspaceMode();
      setLocalGate(payload);
      await refreshCachedSession();
      await refetch?.();
      message.success('已重設為環境預設工作區（覆寫已清除）。');
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

  const switchControl = canSwitch ? (
    <Space size="small" wrap>
      <Segmented
        size="small"
        disabled={saving}
        value={isCloud ? 'CLOUD_FORMAL' : 'LOCAL_SANDBOX'}
        options={[
          { label: 'LOCAL', value: 'LOCAL_SANDBOX' },
          { label: 'CLOUD', value: 'CLOUD_FORMAL' },
        ]}
        onChange={(value) => {
          void onSwitch(String(value));
        }}
      />
      {overrideActive ? (
        <Button size="small" type="link" disabled={saving} onClick={() => void onReset()}>
          重設為環境預設
        </Button>
      ) : null}
    </Space>
  ) : null;

  const overrideNote = overrideActive
    ? '運算子覆寫已持久化，Backoffice 重啟後仍會套用，直到重設。'
    : null;

  if (isCloud && formalAllowed) {
    return (
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={
          <Space wrap>
            <Tag color="geekblue">CLOUD</Tag>
            {overrideActive ? <Tag color="purple">覆寫</Tag> : null}
            <span>目前為雲端正式知識工作區（ENTRA 正式身分已就緒）。</span>
            {switchControl}
          </Space>
        }
        description={overrideNote}
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
            <Tag color="geekblue">CLOUD</Tag>
            {overrideActive ? <Tag color="purple">覆寫</Tag> : null}
            <span>雲端工作區已選取，但正式發布／回滾仍鎖定，直到正式身分路徑設定完成。</span>
            {switchControl}
          </Space>
        }
        description={
          <Space direction="vertical" size={4}>
            <Text type="secondary">
              封鎖原因：{blockLabels.join('；') || '正式身分門檻未就緒'}。
              請使用 ENTRA、關閉 relaxed／demo，並啟用 AI_OPS_KNOWLEDGE_CLOUD_FORMAL_WRITES。
            </Text>
            <Text type="secondary">
              切換工作區不會自動開放正式寫入；地端測試請切回 LOCAL。
              {overrideNote ? ` ${overrideNote}` : ''}
            </Text>
          </Space>
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
          <Tag color="gold">LOCAL</Tag>
          {overrideActive ? <Tag color="purple">覆寫</Tag> : null}
          <span>本機測試工作區：草稿與發布只寫入本機 sandbox，不會自動成為雲端正式知識。</span>
          {switchControl}
        </Space>
      }
      description={
        canSwitch
          ? `可切換至 CLOUD 檢視雲端連線狀態；正式寫入仍受伺服器門檻鎖定，直到 ENTRA 與 AI_OPS_KNOWLEDGE_CLOUD_FORMAL_WRITES 就緒。${
              overrideNote ? ` ${overrideNote}` : ''
            }`
          : '需要 SYSTEM_ADMIN 或 KNOWLEDGE_ADMIN 才能切換工作區。'
      }
    />
  );
};
