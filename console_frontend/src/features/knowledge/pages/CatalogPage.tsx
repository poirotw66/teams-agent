import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  CheckOutlined,
  CloseOutlined,
  PlusOutlined,
  SaveOutlined,
  SendOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons';
import { useCan } from '@refinedev/core';
import { ApiError } from '../../../shared/api/client';
import {
  approveCatalog,
  CatalogServiceRow,
  fetchCatalogDraft,
  rejectCatalog,
  saveCatalogDraft,
  submitCatalogReview,
} from '../../../shared/api/workbench/catalogApi';
import { CloudFormalMirrorDocs } from '../components/CloudFormalMirrorDocs';
import { KnowledgeWorkspaceBanner } from '../components/KnowledgeWorkspaceBanner';
import { KnowledgeSyncLagBanner } from '../components/KnowledgeSyncLagBanner';

const { Title, Text } = Typography;

type EditableRow = CatalogServiceRow & { key: string };

function statusColor(status?: string): string {
  switch ((status || '').toUpperCase()) {
    case 'APPROVED':
      return 'success';
    case 'IN_REVIEW':
      return 'processing';
    case 'REJECTED':
      return 'error';
    case 'DRAFT':
      return 'default';
    default:
      return 'default';
  }
}

function toEditableRows(services: CatalogServiceRow[] | undefined): EditableRow[] {
  if (!services?.length) {
    return [
      {
        key: 'row-0',
        serviceId: '',
        officialName: '',
        aliases: [],
        documentId: '',
      },
    ];
  }
  return services.map((row, index) => ({
    ...row,
    key: `row-${index}-${row.serviceId || index}`,
    aliases: Array.isArray(row.aliases) ? row.aliases : [],
  }));
}

function normalizeRows(rows: EditableRow[]): CatalogServiceRow[] {
  return rows
    .map((row) => ({
      serviceId: String(row.serviceId || '').trim(),
      officialName: String(row.officialName || '').trim() || undefined,
      aliases: (row.aliases || [])
        .map((alias) => String(alias).trim())
        .filter(Boolean),
      documentId: String(row.documentId || '').trim(),
      versionId: row.versionId ? String(row.versionId).trim() : undefined,
      ownerUnitId: row.ownerUnitId ? String(row.ownerUnitId).trim() : undefined,
      aclGroups: row.aclGroups || [],
    }))
    .filter((row) => row.serviceId || row.documentId);
}

export const CatalogPage: React.FC = () => {
  const [rows, setRows] = useState<EditableRow[]>(toEditableRows(undefined));
  const [status, setStatus] = useState<string>('DRAFT');
  const [updatedBy, setUpdatedBy] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [remainingGaps, setRemainingGaps] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState('');

  const { data: canEdit } = useCan({ resource: 'knowledge-catalog', action: 'edit' });
  const { data: canSubmit } = useCan({ resource: 'knowledge-catalog', action: 'submit' });
  const { data: canReview } = useCan({ resource: 'knowledge-catalog', action: 'review' });
  const { data: canPublish } = useCan({ resource: 'knowledge-catalog', action: 'publish' });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchCatalogDraft();
      const draft = data.draft;
      setRows(toEditableRows(draft?.services));
      setStatus(String(draft?.status || 'DRAFT').toUpperCase());
      setUpdatedBy(draft?.updatedBy || null);
      setUpdatedAt(draft?.updatedAt || null);
      setRemainingGaps(Array.isArray(data.remainingGaps) ? data.remainingGaps : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '無法載入服務目錄草稿。');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const editable = Boolean(canEdit?.can) && (status === 'DRAFT' || status === 'REJECTED');

  const columns = useMemo(
    () => [
      {
        title: '服務 ID',
        dataIndex: 'serviceId',
        width: 160,
        render: (_: unknown, row: EditableRow, index: number) => (
          <Input
            value={row.serviceId}
            disabled={!editable}
            onChange={(event) => {
              const next = [...rows];
              next[index] = { ...row, serviceId: event.target.value };
              setRows(next);
            }}
          />
        ),
      },
      {
        title: '正式名稱',
        dataIndex: 'officialName',
        render: (_: unknown, row: EditableRow, index: number) => (
          <Input
            value={row.officialName || ''}
            disabled={!editable}
            onChange={(event) => {
              const next = [...rows];
              next[index] = { ...row, officialName: event.target.value };
              setRows(next);
            }}
          />
        ),
      },
      {
        title: '別名（逗號分隔）',
        dataIndex: 'aliases',
        render: (_: unknown, row: EditableRow, index: number) => (
          <Input
            value={(row.aliases || []).join(', ')}
            disabled={!editable}
            onChange={(event) => {
              const next = [...rows];
              next[index] = {
                ...row,
                aliases: event.target.value
                  .split(',')
                  .map((part) => part.trim())
                  .filter(Boolean),
              };
              setRows(next);
            }}
          />
        ),
      },
      {
        title: '連結文件 ID',
        dataIndex: 'documentId',
        width: 180,
        render: (_: unknown, row: EditableRow, index: number) => (
          <Input
            value={row.documentId}
            disabled={!editable}
            onChange={(event) => {
              const next = [...rows];
              next[index] = { ...row, documentId: event.target.value };
              setRows(next);
            }}
          />
        ),
      },
    ],
    [editable, rows],
  );

  const runMutation = async (
    action: () => Promise<unknown>,
    successMessage: string,
  ) => {
    setSaving(true);
    setError(null);
    try {
      await action();
      message.success(successMessage);
      await load();
    } catch (err) {
      const detail =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : '操作失敗。';
      setError(detail);
      message.error(detail);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <KnowledgeWorkspaceBanner />
      <KnowledgeSyncLagBanner />
      <div>
        <Title level={3} style={{ marginBottom: 4 }}>
          <UnorderedListOutlined style={{ marginRight: 8 }} />
          企業服務目錄
        </Title>
        <Text type="secondary">
          下方草稿是本機 FILE Portal 的目錄工作區，不會因為 IN_SYNC 自動變成雲端
          catalog。要比對雲端已發布目錄，請看「雲端正式鏡像」。
        </Text>
      </div>
      <CloudFormalMirrorDocs />
      <div>
        <Text type="secondary">
          企業服務目錄與文件發布分開治理：編輯 → 送審 →「核准目錄」（不可自審；
          不等於文件／Release 發布）後，下一次知識 Release finalize 會寫入不可變的
          catalog/service_catalog.json。
        </Text>
      </div>

      {error ? <Alert type="error" showIcon message={error} /> : null}

      <Card
        title={
          <Space>
            <span>本機目錄草稿</span>
            <Tag color={statusColor(status)}>{status}</Tag>
            {updatedBy ? <Text type="secondary">更新者：{updatedBy}</Text> : null}
            {updatedAt ? <Text type="secondary">{updatedAt}</Text> : null}
          </Space>
        }
        extra={
          <Space wrap>
            {editable ? (
              <Button
                icon={<PlusOutlined />}
                onClick={() =>
                  setRows((current) => [
                    ...current,
                    {
                      key: `row-${current.length}-${Date.now()}`,
                      serviceId: '',
                      officialName: '',
                      aliases: [],
                      documentId: '',
                    },
                  ])
                }
              >
                新增列
              </Button>
            ) : null}
            {editable && canEdit?.can ? (
              <Button
                type="primary"
                icon={<SaveOutlined />}
                loading={saving}
                onClick={() =>
                  void runMutation(async () => {
                    const services = normalizeRows(rows);
                    if (!services.length) {
                      throw new Error('至少需要一筆含服務 ID 與文件 ID 的目錄列。');
                    }
                    for (const service of services) {
                      if (!service.serviceId || !service.documentId) {
                        throw new Error('每一列都需要服務 ID 與連結文件 ID。');
                      }
                    }
                    await saveCatalogDraft(services);
                  }, '已儲存目錄草稿')
                }
              >
                儲存草稿
              </Button>
            ) : null}
            {status === 'DRAFT' && canSubmit?.can ? (
              <Button
                icon={<SendOutlined />}
                loading={saving}
                onClick={() =>
                  void runMutation(
                    () => submitCatalogReview(reason || undefined),
                    '已送審',
                  )
                }
              >
                送審
              </Button>
            ) : null}
            {status === 'IN_REVIEW' && canPublish?.can ? (
              <Button
                type="primary"
                icon={<CheckOutlined />}
                loading={saving}
                onClick={() =>
                  void runMutation(
                    () => approveCatalog(reason || undefined),
                    '目錄已核准',
                  )
                }
              >
                核准目錄
              </Button>
            ) : null}
            {status === 'IN_REVIEW' && canReview?.can ? (
              <Button
                danger
                icon={<CloseOutlined />}
                loading={saving}
                onClick={() =>
                  void runMutation(
                    () => rejectCatalog(reason || undefined),
                    '已退回目錄草稿',
                  )
                }
              >
                退回
              </Button>
            ) : null}
          </Space>
        }
      >
        <Form layout="vertical" style={{ marginBottom: 12 }}>
          <Form.Item label="審核／退回理由（選填）" style={{ marginBottom: 8 }}>
            <Input.TextArea
              rows={2}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="送審、核准或退回時可填寫理由"
            />
          </Form.Item>
        </Form>
        <Table
          rowKey="key"
          loading={loading}
          dataSource={rows}
          columns={columns}
          pagination={false}
          size="middle"
        />
      </Card>

      {remainingGaps.length ? (
        <Alert
          type="info"
          showIcon
          message="尚待完成的目錄治理能力"
          description={
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {remainingGaps.map((gap) => (
                <li key={gap}>{gap}</li>
              ))}
            </ul>
          }
        />
      ) : null}
    </Space>
  );
};
