import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Space, Tag, Typography, message } from 'antd';
import { SyncOutlined } from '@ant-design/icons';
import { useGetIdentity } from '@refinedev/core';
import { apiClient, ApiError } from '../../../shared/api/client';
import { notifyKnowledgeMirrorUpdated } from '../lib/knowledgeMirrorEvents';
import {
  KnowledgeSyncStatus,
  syncLocalKnowledgeMirror,
  syncOutcomeToastLevel,
} from '../lib/syncLocalKnowledgeMirror';

type KnowledgeIdentity = {
  knowledgeWorkspaceMode?: string;
};

const { Text } = Typography;

type KnowledgeStatusResponse = {
  currentReleaseId?: string | null;
  sync?: KnowledgeSyncStatus;
};

function releaseLabel(value?: string | null): string {
  return value?.trim() ? value : '—';
}

/**
 * Compact honesty banner for knowledge pages that are not the full Releases
 * status card. Shows 「可能落後雲端」 whenever cloud / mirrored / loaded diverge
 * or the QA snapshot is incomplete — never claims formal parity.
 *
 * When behind / not aligned, offers 「立即同步」 (Console-connected Agent Sync Now).
 * Local workspace (default start.sh Console) always shows the button so operators
 * can pull GCS without opening Releases. Cloud formal Console keeps the button
 * hidden while already aligned — Portal reload-knowledge owns that path.
 */
export const KnowledgeSyncLagBanner: React.FC = () => {
  const { data: identity } = useGetIdentity<KnowledgeIdentity>();
  const isLocalWorkspace =
    String(identity?.knowledgeWorkspaceMode || 'LOCAL_SANDBOX').toUpperCase() !==
    'CLOUD_FORMAL';
  const [status, setStatus] = useState<KnowledgeStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const data = await apiClient<KnowledgeStatusResponse>(
        '/api/console/agent-knowledge/status',
      );
      setStatus(data);
    } catch (err) {
      setStatus(null);
      if (err instanceof ApiError && err.status === 503) {
        setError(
          '此 Console 所連 Agent 同步狀態目前無法取得；不得宣稱與雲端正式知識版本一致。',
        );
      } else {
        setError(
          err instanceof Error
            ? err.message
            : '無法取得此 Console 所連 Agent 知識同步狀態。',
        );
      }
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const onSyncNow = async () => {
    setSyncing(true);
    try {
      const outcome = await syncLocalKnowledgeMirror();
      const level = syncOutcomeToastLevel(outcome);
      if (level === 'success') {
        message.success(outcome.message);
      } else if (level === 'warning') {
        message.warning(outcome.message);
      } else {
        message.error(outcome.message);
      }
      if ('sync' in outcome) {
        setStatus((prev) => ({
          ...(prev || {}),
          sync: outcome.sync,
          currentReleaseId:
            outcome.sync.loadedReleaseId ?? prev?.currentReleaseId,
        }));
      }
      await load();
      notifyKnowledgeMirrorUpdated();
    } finally {
      setSyncing(false);
    }
  };

  const syncNowButton = (
    <Button
      size="small"
      type="primary"
      icon={<SyncOutlined spin={syncing} />}
      loading={syncing}
      onClick={() => void onSyncNow()}
    >
      立即同步
    </Button>
  );

  if (error) {
    return (
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message="此 Console 所連 Agent 可能落後雲端"
        description={
          <Space direction="vertical" size={8}>
            <Text>{error}</Text>
            <Text type="secondary">
              「立即同步」只更新 BFF 所連 Agent（地端 Playground 或雲端 Console
              所指目標），不會取代 Portal 對 Cloud Run 的 reload-knowledge。
            </Text>
            {syncNowButton}
          </Space>
        }
      />
    );
  }

  const sync = status?.sync;
  if (!sync) {
    if (!isLocalWorkspace) {
      return null;
    }
    return (
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={
          <Space wrap>
            <Tag color="blue">GCS 鏡像</Tag>
            <span>從雲端正式 release 同步到本機 Playground</span>
            {syncNowButton}
          </Space>
        }
        description={
          <Text type="secondary">
            本機問答讀的是已驗證快照，不是雲端即時庫。按「立即同步」拉取
            Firestore active + GCS QA artifacts。
          </Text>
        }
      />
    );
  }

  const aligned =
    Boolean(sync.alignedWithCloud || sync.matchesCloudProduction) &&
    Boolean(sync.qaSnapshotComplete || sync.runtimeInventoryComplete);
  const behind =
    Boolean(sync.behindCloud) ||
    Boolean(
      sync.cloudActiveReleaseId &&
        sync.cloudActiveReleaseId !==
          (sync.loadedReleaseId || status?.currentReleaseId),
    ) ||
    !Boolean(sync.qaSnapshotComplete || sync.runtimeInventoryComplete);

  if (aligned) {
    return (
      <Alert
        type="success"
        showIcon
        style={{ marginBottom: 16 }}
        message={
          <Space wrap>
            <Tag color="green">IN_SYNC</Tag>
            <span>Playground Agent 已與雲端 active 同一版</span>
            {isLocalWorkspace ? syncNowButton : null}
          </Space>
        }
        description={
          <Text type="secondary">
            雲端 {releaseLabel(sync.cloudActiveReleaseId)} ／ 鏡像{' '}
            {releaseLabel(sync.mirroredReleaseId)} ／ 此 Console 所連 Agent{' '}
            {releaseLabel(sync.loadedReleaseId || status?.currentReleaseId)}
            {isLocalWorkspace
              ? '。這只代表 GCS 鏡像／問答索引，不是「本機測試工作區」文件表。要比對雲端目錄請看「雲端正式鏡像」。'
              : ''}
          </Text>
        }
      />
    );
  }

  if (!behind && !sync.lastError && sync.syncState === 'IN_SYNC') {
    if (!isLocalWorkspace) {
      return null;
    }
  }

  return (
    <Alert
      type="warning"
      showIcon
      style={{ marginBottom: 16 }}
      message={
        <Space wrap>
          <Tag color="gold">LAG</Tag>
          <span>此 Console 所連 Agent 可能落後雲端</span>
        </Space>
      }
      description={
        <Space direction="vertical" size={8}>
          <Text type="secondary">
            雲端 {releaseLabel(sync.cloudActiveReleaseId)} ／ 鏡像{' '}
            {releaseLabel(sync.mirroredReleaseId)} ／ 此 Console 所連 Agent{' '}
            {releaseLabel(sync.loadedReleaseId || status?.currentReleaseId)}
            {sync.selectionMode ? `（${sync.selectionMode}）` : ''}
          </Text>
          <Text type="secondary">
            {sync.lastError ||
              sync.detail ||
              '不得宣稱與正式環境一致。請按「立即同步」強制同步此 Console 所連 Agent，或確認釘選／sandbox 模式。'}
          </Text>
          <Text type="secondary">
            雲端正式對話靠 Portal reload；「立即同步」不會更新未連線的地端筆電 Playground。
          </Text>
          {syncNowButton}
        </Space>
      }
    />
  );
};
