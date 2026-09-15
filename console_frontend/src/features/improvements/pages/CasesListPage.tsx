import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Space,
  Table,
  Typography,
  Empty,
  Spin,
} from 'antd';
import { ReloadOutlined, EyeOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { apiClient } from '../../../shared/api/client';
import { StatusTag } from '../../../shared/ui/StatusTag';

const { Title, Text } = Typography;

interface QualityCaseRow {
  case_id?: string;
  id?: string;
  title?: string;
  status?: string;
  priority?: string;
  owner_unit_id?: string;
  updated_at?: string;
}

interface QualityCasesResponse {
  items?: QualityCaseRow[];
  total?: number;
}

export const CasesListPage: React.FC = () => {
  const navigate = useNavigate();
  const [items, setItems] = useState<QualityCaseRow[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchCases = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient<QualityCasesResponse>('/api/quality-cases');
      setItems(response.items || []);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '載入品質案件列表失敗';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCases();
  }, [fetchCases]);

  const columns = [
    {
      title: '案件',
      dataIndex: 'title',
      key: 'title',
      render: (_: unknown, row: QualityCaseRow) => (
        <Space direction="vertical" size={0}>
          <Text strong>{row.title || row.case_id || row.id}</Text>
          <Text type="secondary">{row.case_id || row.id}</Text>
        </Space>
      ),
    },
    {
      title: '狀態',
      dataIndex: 'status',
      key: 'status',
      width: 140,
      render: (status: string | undefined) => <StatusTag status={status || 'unknown'} />,
    },
    {
      title: '優先順序',
      dataIndex: 'priority',
      key: 'priority',
      width: 120,
      render: (priority: string | undefined) => priority || '—',
    },
    {
      title: '負責單位',
      dataIndex: 'owner_unit_id',
      key: 'owner_unit_id',
      width: 160,
      render: (unit: string | undefined) => unit || '—',
    },
    {
      title: '操作',
      key: 'actions',
      width: 120,
      render: (_: unknown, row: QualityCaseRow) => {
        const caseId = row.case_id || row.id;
        return (
          <Button
            type="link"
            icon={<EyeOutlined />}
            disabled={!caseId}
            onClick={() => caseId && navigate(`/improvements/cases/${caseId}`)}
          >
            開啟
          </Button>
        );
      },
    },
  ];

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
        <div>
          <Title level={3} style={{ marginBottom: 4 }}>
            問題改善案件
          </Title>
          <Text type="secondary">品質案件列表（/console-v2/improvements/cases）</Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={fetchCases} loading={loading}>
          重新整理
        </Button>
      </Space>

      {error && <Alert type="error" showIcon message={error} />}

      {loading && items.length === 0 ? (
        <Spin />
      ) : items.length === 0 && !error ? (
        <Empty description="目前沒有品質案件" />
      ) : (
        <Table
          rowKey={(row) => String(row.case_id || row.id)}
          columns={columns}
          dataSource={items}
          loading={loading}
          pagination={{ pageSize: 20 }}
        />
      )}
    </Space>
  );
};
