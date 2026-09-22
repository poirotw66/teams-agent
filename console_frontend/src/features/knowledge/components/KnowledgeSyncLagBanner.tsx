import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Space, Tag, Typography } from 'antd';
import { apiClient, ApiError } from '../../../shared/api/client';

const { Text } = Typography;

type KnowledgeSyncStatus = {
  cloudActiveReleaseId?: string | null;
  mirroredReleaseId?: string | null;
  loadedReleaseId?: string | null;
  selectionMode?: string;
  syncState?: string;
  behindCloud?: boolean;
  alignedWithCloud?: boolean;
  matchesCloudProduction?: boolean;
  qaSnapshotComplete?: boolean;
  runtimeInventoryComplete?: boolean;
  detail?: string | null;
  lastError?: string | null;
};

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
 */
export const KnowledgeSyncLagBanner: React.FC = () => {
  const [status, setStatus] = useState<KnowledgeStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const data = await apiClient<KnowledgeStatusResponse>('/api/agent/knowledge-status');
      setStatus(data);
    } catch (err) {
      setStatus(null);
      if (err instanceof ApiError && err.status === 503) {
        setError(
          '地端 Agent 同步狀態目前無法取得；不得宣稱與雲端正式知識版本一致。',
        );
      } else {
        setError(
          err instanceof Error
            ? err.message
            : '無法取得地端 Agent 知識同步狀態。',
        );
      }
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) {
    return (
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message="本機可能落後雲端"
        description={error}
      />
    );
  }

  const sync = status?.sync;
  if (!sync) {
    return null;
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
            <span>目前與雲端正式知識版本一致</span>
          </Space>
        }
        description={
          <Text type="secondary">
            雲端 {releaseLabel(sync.cloudActiveReleaseId)} ／ 本機鏡像{' '}
            {releaseLabel(sync.mirroredReleaseId)} ／ Playground{' '}
            {releaseLabel(sync.loadedReleaseId || status?.currentReleaseId)}
          </Text>
        }
      />
    );
  }

  if (!behind && !sync.lastError && sync.syncState === 'IN_SYNC') {
    return null;
  }

  return (
    <Alert
      type="warning"
      showIcon
      style={{ marginBottom: 16 }}
      message={
        <Space wrap>
          <Tag color="gold">LAG</Tag>
          <span>本機可能落後雲端</span>
        </Space>
      }
      description={
        <Space direction="vertical" size={2}>
          <Text type="secondary">
            雲端 {releaseLabel(sync.cloudActiveReleaseId)} ／ 本機鏡像{' '}
            {releaseLabel(sync.mirroredReleaseId)} ／ Playground{' '}
            {releaseLabel(sync.loadedReleaseId || status?.currentReleaseId)}
            {sync.selectionMode ? `（${sync.selectionMode}）` : ''}
          </Text>
          <Text type="secondary">
            {sync.lastError ||
              sync.detail ||
              '不得宣稱與正式環境一致。請至知識 Release 頁同步或確認釘選／sandbox 模式。'}
          </Text>
        </Space>
      }
    />
  );
};
