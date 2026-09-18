import React, { useEffect, useState } from 'react';
import { Alert, Card, Space, Table, Tag, Typography } from 'antd';
import { CloudServerOutlined } from '@ant-design/icons';
import { apiClient } from '../../../shared/api/client';

const { Title, Text } = Typography;

type ReleaseRow = {
  release_id?: string;
  status?: string;
  created_by?: string;
  activated_at?: string;
  failure_summary?: string;
};

export const ReleasesPage: React.FC = () => {
  const [rows, setRows] = useState<ReleaseRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await apiClient<ReleaseRow[]>('/api/knowledge/releases');
        if (!cancelled) {
          setRows(Array.isArray(data) ? data : []);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load releases.');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div>
        <Title level={3} style={{ marginBottom: 4 }}>
          <CloudServerOutlined style={{ marginRight: 8 }} />
          知識 Release
        </Title>
        <Text type="secondary">Live release manifests from `/api/knowledge/releases`.</Text>
      </div>
      {error ? <Alert type="error" showIcon message={error} /> : null}
      <Card>
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
