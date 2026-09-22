import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Row,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import { CloudServerOutlined, SyncOutlined } from '@ant-design/icons';
import { apiClient, ApiError } from '../../../shared/api/client';
import { KnowledgeWorkspaceBanner } from '../components/KnowledgeWorkspaceBanner';

const { Title, Text } = Typography;

type ReleaseRow = {
  release_id?: string;
  status?: string;
  created_by?: string;
  activated_at?: string;
  failure_summary?: string;
};

type KnowledgeSyncStatus = {
  cloudActiveReleaseId?: string | null;
  mirroredReleaseId?: string | null;
  loadedReleaseId?: string | null;
  selectionMode?: string;
  syncState?: string;
  lastSuccessfulSyncAt?: string | null;
  artifactCount?: number;
  verificationHash?: string | null;
  qaSnapshotComplete?: boolean;
  runtimeInventoryComplete?: boolean;
  indexOnlyMirror?: boolean;
  behindCloud?: boolean;
  alignedWithCloud?: boolean;
  matchesCloudProduction?: boolean;
  detail?: string | null;
  lastError?: string | null;
};

type KnowledgeStatusResponse = {
  currentReleaseId?: string | null;
  targetReleaseId?: string | null;
  inSync?: boolean;
  chunks?: number;
  source?: string;
  sync?: KnowledgeSyncStatus;
};

function releaseLabel(value?: string | null): string {
  return value?.trim() ? value : '—';
}

function syncStateColor(state?: string): string {
  switch (state) {
    case 'IN_SYNC':
      return 'success';
    case 'DOWNLOADING':
    case 'VALIDATING':
      return 'processing';
    case 'FAILED':
      return 'error';
    case 'CONTROL_UNAVAILABLE':
      return 'warning';
    default:
      return 'default';
  }
}

export const ReleasesPage: React.FC = () => {
  const [rows, setRows] = useState<ReleaseRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [agentStatus, setAgentStatus] = useState<KnowledgeStatusResponse | null>(null);
  const [agentStatusError, setAgentStatusError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const loadReleases = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient<ReleaseRow[]>('/api/knowledge/releases');
      setRows(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load releases.');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadAgentStatus = useCallback(async () => {
    setAgentStatusError(null);
    try {
      const data = await apiClient<KnowledgeStatusResponse>('/api/agent/knowledge-status');
      setAgentStatus(data);
    } catch (err) {
      setAgentStatus(null);
      if (err instanceof ApiError && err.status === 503) {
        setAgentStatusError(
          '地端 Agent 同步狀態目前無法取得（可能尚未設定 AGENT_API_URL 或 Agent 未以 GCS 模式啟動）。',
        );
      } else {
        setAgentStatusError(
          err instanceof Error ? err.message : 'Failed to load Agent knowledge status.',
        );
      }
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await Promise.all([loadReleases(), loadAgentStatus()]);
      if (cancelled) {
        return;
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadReleases, loadAgentStatus]);

  const onSyncNow = async () => {
    setSyncing(true);
    try {
      const sync = await apiClient<KnowledgeSyncStatus>('/api/agent/knowledge-sync', {
        method: 'POST',
      });
      setAgentStatus((prev) => ({
        ...(prev || {}),
        sync,
        currentReleaseId: sync.loadedReleaseId ?? prev?.currentReleaseId,
        targetReleaseId: sync.cloudActiveReleaseId ?? prev?.targetReleaseId,
      }));
      if (sync.alignedWithCloud || sync.matchesCloudProduction) {
        message.success('已與雲端正式知識版本一致。');
      } else if (sync.behindCloud) {
        message.warning('本機鏡像已更新，但 Playground 載入版本可能仍落後雲端。');
      } else {
        message.success('同步完成。');
      }
      await loadAgentStatus();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '立即同步失敗。');
    } finally {
      setSyncing(false);
    }
  };

  const sync = agentStatus?.sync;
  const aligned =
    Boolean(sync?.alignedWithCloud || sync?.matchesCloudProduction) &&
    Boolean(sync?.qaSnapshotComplete || sync?.runtimeInventoryComplete);
  const indexOnly =
    Boolean(sync?.indexOnlyMirror) ||
    Boolean(
      sync?.mirroredReleaseId &&
        !(sync?.qaSnapshotComplete || sync?.runtimeInventoryComplete),
    );
  const behind =
    Boolean(sync?.behindCloud) ||
    indexOnly ||
    Boolean(
      sync?.cloudActiveReleaseId &&
        sync.cloudActiveReleaseId !== sync.loadedReleaseId,
    );

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <KnowledgeWorkspaceBanner />
      <div>
        <Title level={3} style={{ marginBottom: 4 }}>
          <CloudServerOutlined style={{ marginRight: 8 }} />
          知識 Release
        </Title>
        <Text type="secondary">
          Portal release 清單與地端 Agent 鏡像狀態（雲端最新／本機已同步／Playground 使用中）。
        </Text>
      </div>

      <Card
        title="地端 Agent 同步狀態"
        extra={
          <Button
            type="primary"
            icon={<SyncOutlined spin={syncing} />}
            loading={syncing}
            onClick={() => void onSyncNow()}
          >
            立即同步
          </Button>
        }
      >
        {agentStatusError ? (
          <Alert type="warning" showIcon message={agentStatusError} />
        ) : null}
        {aligned ? (
          <Alert
            type="success"
            showIcon
            style={{ marginBottom: 16 }}
            message="目前與雲端正式知識版本一致"
            description="雲端最新、本機已同步與 Playground 正在使用的 release 相同，且 QA 快照驗證成功。"
          />
        ) : null}
        {!aligned && indexOnly ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="本機可能落後雲端（僅索引鏡像）"
            description="雲端 active release 缺少 runtimeArtifacts 完整 QA inventory（來源／資產／目錄／ACL）。不得宣稱與正式環境一致；需重新發布含 inventory 的 release 後再同步。"
          />
        ) : null}
        {!aligned && behind && !indexOnly ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="本機可能落後雲端"
            description="不得宣稱與正式環境一致。請確認同步狀態與 Playground 載入的 release。"
          />
        ) : null}
        <Row gutter={[16, 16]}>
          <Col xs={24} md={8}>
            <Card size="small" type="inner" title="雲端最新">
              <Text code>{releaseLabel(sync?.cloudActiveReleaseId)}</Text>
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card size="small" type="inner" title="本機已同步">
              <Text code>{releaseLabel(sync?.mirroredReleaseId)}</Text>
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card size="small" type="inner" title="Playground 正在使用">
              <Text code>
                {releaseLabel(sync?.loadedReleaseId ?? agentStatus?.currentReleaseId)}
              </Text>
            </Card>
          </Col>
        </Row>
        <Descriptions
          size="small"
          column={{ xs: 1, sm: 2, md: 3 }}
          style={{ marginTop: 16 }}
          items={[
            {
              key: 'selection',
              label: '選擇模式',
              children: sync?.selectionMode || '—',
            },
            {
              key: 'state',
              label: '同步狀態',
              children: sync?.syncState ? (
                <Tag color={syncStateColor(sync.syncState)}>{sync.syncState}</Tag>
              ) : (
                '—'
              ),
            },
            {
              key: 'verified',
              label: 'QA 快照完整',
              children:
                sync?.qaSnapshotComplete || sync?.runtimeInventoryComplete ? '是' : '否',
            },
            {
              key: 'lastSync',
              label: '上次成功同步',
              children: sync?.lastSuccessfulSyncAt || '—',
            },
            {
              key: 'artifacts',
              label: 'Artifact 數',
              children: sync?.artifactCount ?? '—',
            },
            {
              key: 'hash',
              label: '驗證 Hash',
              children: sync?.verificationHash ? (
                <Text code copyable>
                  {sync.verificationHash.slice(0, 16)}…
                </Text>
              ) : (
                '—'
              ),
            },
          ]}
        />
        {sync?.detail || sync?.lastError ? (
          <Alert
            style={{ marginTop: 16 }}
            type={sync?.lastError ? 'error' : 'info'}
            showIcon
            message={sync?.lastError || sync?.detail}
          />
        ) : null}
      </Card>

      {error ? <Alert type="error" showIcon message={error} /> : null}
      <Card title="Portal Release 清單">
        <Table
          rowKey={(row) => String(row.release_id || Math.random())}
          loading={loading}
          dataSource={rows}
          pagination={{ pageSize: 20 }}
          columns={[
            {
              title: 'Release',
              dataIndex: 'release_id',
              render: (value?: string) => value || '—',
            },
            {
              title: 'Status',
              dataIndex: 'status',
              render: (status?: string) =>
                status ? <Tag>{status}</Tag> : <Text type="secondary">—</Text>,
            },
            {
              title: 'Created by',
              dataIndex: 'created_by',
              render: (value?: string) => value || '—',
            },
            {
              title: 'Activated',
              dataIndex: 'activated_at',
              render: (value?: string) => value || '—',
            },
            {
              title: 'Failure',
              dataIndex: 'failure_summary',
              render: (value?: string) => value || '—',
            },
          ]}
        />
      </Card>
    </Space>
  );
};
