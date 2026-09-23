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
import { CloudServerOutlined, ReloadOutlined, SyncOutlined } from '@ant-design/icons';
import { apiClient, ApiError } from '../../../shared/api/client';
import { KnowledgeWorkspaceBanner } from '../components/KnowledgeWorkspaceBanner';
import {
  KnowledgeSyncStatus,
  syncLocalKnowledgeMirror,
  syncOutcomeToastLevel,
} from '../lib/syncLocalKnowledgeMirror';
import {
  isKnowledgeReleaseBehind,
  knowledgeInventoryComplete,
  knowledgeReleaseIdsMatch,
  resolveKnowledgeSyncBannerState,
} from '../components/knowledgeSyncBannerState';

const { Title, Text } = Typography;

type ReleaseRow = {
  release_id?: string;
  status?: string;
  created_by?: string;
  activated_at?: string;
  failure_summary?: string;
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
  const [retryingReleaseId, setRetryingReleaseId] = useState<string | null>(null);

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
      const data = await apiClient<KnowledgeStatusResponse>(
        '/api/console/agent-knowledge/status',
      );
      setAgentStatus(data);
    } catch (err) {
      setAgentStatus(null);
      if (err instanceof ApiError && err.status === 503) {
        setAgentStatusError(
          '此 Console 所連 Agent 同步狀態目前無法取得（可能尚未設定 AGENT_API_URL 或 Agent 未以 GCS 模式啟動）。',
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
        setAgentStatus((prev) => ({
          ...(prev || {}),
          sync: outcome.sync,
          currentReleaseId:
            outcome.sync.loadedReleaseId ?? prev?.currentReleaseId,
          targetReleaseId:
            outcome.sync.cloudActiveReleaseId ?? prev?.targetReleaseId,
        }));
      }
      await loadAgentStatus();
    } finally {
      setSyncing(false);
    }
  };

  const onRetryActivate = async (releaseId: string) => {
    setRetryingReleaseId(releaseId);
    try {
      await apiClient(`/api/knowledge/releases/${encodeURIComponent(releaseId)}/sync-agent`, {
        method: 'POST',
      });
      message.success(
        `已重試啟用 release ${releaseId}（Portal → 雲端 Agent reload）。若本機 Playground 仍落後，請再按「立即同步」。`,
      );
      await Promise.all([loadReleases(), loadAgentStatus()]);
    } catch (err) {
      message.error(
        err instanceof Error ? err.message : `重試啟用 ${releaseId} 失敗。`,
      );
    } finally {
      setRetryingReleaseId(null);
    }
  };

  const sync = agentStatus?.sync;
  const releaseIdsMatch = knowledgeReleaseIdsMatch(
    sync,
    agentStatus?.currentReleaseId,
  );
  const inventoryComplete = knowledgeInventoryComplete(sync);
  // Matching IDs + complete inventory are not behind, even when PINNED
  // keeps alignedWithCloud false for answer-audit honesty.
  const aligned = releaseIdsMatch && inventoryComplete;
  const bannerDecision = resolveKnowledgeSyncBannerState({
    sync,
    currentReleaseId: agentStatus?.currentReleaseId,
    error: agentStatusError,
  });
  const indexOnly =
    Boolean(sync?.indexOnlyMirror) ||
    Boolean(sync?.mirroredReleaseId && !inventoryComplete);
  const behind =
    isKnowledgeReleaseBehind(sync, agentStatus?.currentReleaseId) || indexOnly;
  // Aligned with cloud-active is honest, but a stuck RELOAD_FAILED candidate
  // may still hold published docs that never became live. Surface that gap.
  const activeReleaseId = sync?.cloudActiveReleaseId || null;
  const reloadFailedGap = rows.find(
    (row) =>
      row.status === 'RELOAD_FAILED' &&
      Boolean(row.release_id) &&
      row.release_id !== activeReleaseId,
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
          Portal release 清單與 Console 所連 Agent 鏡像狀態（雲端最新／已同步鏡像／Agent
          載入中）。雲端正式對話靠 Portal reload；「立即同步」只強制同步此 Console 所連
          Agent（地端 Playground 或 BFF 所指目標）。
        </Text>
      </div>

      <Card
        title="此 Console 所連 Agent 同步狀態"
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
        {aligned && bannerDecision.kind === 'pinned_same_release' ? (
          <Alert
            type="success"
            showIcon
            style={{ marginBottom: 16 }}
            message="已釘選此版，與目前正式 release 相同"
            description="雲端最新、鏡像與此 Console 所連 Agent 載入的 release 相同，且 QA 快照驗證成功。選擇模式為 PINNED，並非落後雲端。"
          />
        ) : null}
        {aligned && bannerDecision.kind !== 'pinned_same_release' ? (
          <Alert
            type="success"
            showIcon
            style={{ marginBottom: 16 }}
            message="目前與雲端正式知識版本一致"
            description="雲端最新、鏡像與此 Console 所連 Agent 載入的 release 相同，且 QA 快照驗證成功。"
          />
        ) : null}
        {reloadFailedGap ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="有已發布內容尚未生效"
            description={
              <Space direction="vertical" size={8}>
                <Text>
                  「與雲端一致」僅對齊目前 active release。另有 release{' '}
                  <Text code>{reloadFailedGap.release_id}</Text> 狀態為 RELOAD_FAILED（雲端
                  Agent 生效失敗），其中已發布文件可能尚未進入正式對話。請在下方清單按「重試啟用」，不要只按「立即同步」。
                </Text>
                <Button
                  size="small"
                  type="primary"
                  danger
                  icon={<ReloadOutlined />}
                  loading={retryingReleaseId === reloadFailedGap.release_id}
                  onClick={() =>
                    void onRetryActivate(String(reloadFailedGap.release_id))
                  }
                >
                  重試啟用 {reloadFailedGap.release_id}
                </Button>
              </Space>
            }
          />
        ) : null}
        {!aligned && indexOnly ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="此 Console 所連 Agent 可能落後雲端（僅索引鏡像）"
            description="雲端 active release 缺少 runtimeArtifacts 完整 QA inventory（來源／資產／目錄／ACL）。不得宣稱與正式環境一致；需重新發布含 inventory 的 release 後再同步。"
          />
        ) : null}
        {!aligned && behind && !indexOnly ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="此 Console 所連 Agent 可能落後雲端"
            description="不得宣稱與正式環境一致。請按「立即同步」強制同步此 Console 所連 Agent，或確認載入的 release。"
          />
        ) : null}
        <Row gutter={[16, 16]}>
          <Col xs={24} md={8}>
            <Card size="small" type="inner" title="雲端最新">
              <Text code>{releaseLabel(sync?.cloudActiveReleaseId)}</Text>
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card size="small" type="inner" title="已同步鏡像">
              <Text code>{releaseLabel(sync?.mirroredReleaseId)}</Text>
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card size="small" type="inner" title="此 Console 所連 Agent 載入中">
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
            {
              title: 'Actions',
              key: 'actions',
              render: (_: unknown, row: ReleaseRow) => {
                if (row.status !== 'RELOAD_FAILED' || !row.release_id) {
                  return <Text type="secondary">—</Text>;
                }
                return (
                  <Button
                    size="small"
                    type="primary"
                    danger
                    icon={<ReloadOutlined />}
                    loading={retryingReleaseId === row.release_id}
                    onClick={() => void onRetryActivate(row.release_id!)}
                  >
                    重試啟用
                  </Button>
                );
              },
            },
          ]}
        />
      </Card>
    </Space>
  );
};
