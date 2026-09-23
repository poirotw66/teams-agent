import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Space, Tag, Typography, message } from 'antd';
import { SyncOutlined } from '@ant-design/icons';
import { useGetIdentity } from '@refinedev/core';
import { apiClient, ApiError } from '../../../shared/api/client';
import { isCloudConsoleSurface } from '../lib/consoleSurface';
import { notifyKnowledgeMirrorUpdated } from '../lib/knowledgeMirrorEvents';
import {
  KnowledgeSyncStatus,
  syncLocalKnowledgeMirror,
  syncOutcomeToastLevel,
} from '../lib/syncLocalKnowledgeMirror';
import { resolveKnowledgeSyncBannerState } from './knowledgeSyncBannerState';

type KnowledgeIdentity = {
  knowledgeWorkspaceMode?: string;
  knowledgeInProcess?: boolean;
  consoleSurface?: string;
};

const { Text } = Typography;

type KnowledgeStatusResponse = {
  currentReleaseId?: string | null;
  sync?: KnowledgeSyncStatus;
};

/**
 * Compact honesty banner for knowledge pages that are not the full Releases
 * status card. Matching cloud / mirrored / loaded IDs with a complete QA
 * snapshot are not 「落後雲端」, even when the Agent is PINNED.
 *
 * When behind, offers 「立即同步」 (Console-connected Agent Sync Now).
 * Local workspace always shows the button. Cloud Console keeps the button
 * hidden while already aligned — Portal reload-knowledge owns that path.
 */
export const KnowledgeSyncLagBanner: React.FC = () => {
  const { data: identity } = useGetIdentity<KnowledgeIdentity>();
  const isCloudConsole = isCloudConsoleSurface(identity);
  const isLocalWorkspace = !isCloudConsole;
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

  const decision = resolveKnowledgeSyncBannerState({
    sync: status?.sync,
    currentReleaseId: status?.currentReleaseId,
    error,
    isCloudConsole,
  });

  if (decision.kind === 'unreachable') {
    return (
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message={decision.copy.headline}
        description={
          <Space direction="vertical" size={8}>
            <Text>{decision.copy.description}</Text>
            {decision.copy.footnote ? (
              <Text type="secondary">{decision.copy.footnote}</Text>
            ) : null}
            {syncNowButton}
          </Space>
        }
      />
    );
  }

  if (decision.kind === 'loading') {
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
            <span>{decision.copy.headline}</span>
            {syncNowButton}
          </Space>
        }
        description={<Text type="secondary">{decision.copy.description}</Text>}
      />
    );
  }

  if (decision.kind === 'in_sync' || decision.kind === 'pinned_same_release') {
    const tagLabel = decision.kind === 'pinned_same_release' ? 'PINNED' : 'IN_SYNC';
    const tagColor = decision.kind === 'pinned_same_release' ? 'blue' : 'green';
    return (
      <Alert
        type={decision.tone === 'success' ? 'success' : 'info'}
        showIcon
        style={{ marginBottom: 16 }}
        message={
          <Space wrap>
            <Tag color={tagColor}>{tagLabel}</Tag>
            <span>{decision.copy.headline}</span>
            {isLocalWorkspace ? syncNowButton : null}
          </Space>
        }
        description={<Text type="secondary">{decision.copy.description}</Text>}
      />
    );
  }

  return (
    <Alert
      type="warning"
      showIcon
      style={{ marginBottom: 16 }}
      message={
        <Space wrap>
          <Tag color="gold">LAG</Tag>
          <span>{decision.copy.headline}</span>
        </Space>
      }
      description={
        <Space direction="vertical" size={8}>
          <Text type="secondary">{decision.copy.description}</Text>
          {decision.copy.footnote ? (
            <Text type="secondary">{decision.copy.footnote}</Text>
          ) : null}
          {syncNowButton}
        </Space>
      }
    />
  );
};
