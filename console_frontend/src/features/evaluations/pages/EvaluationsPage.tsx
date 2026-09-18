import React, { useEffect, useState } from 'react';
import { Alert, Card, Space, Table, Tag, Typography } from 'antd';
import { ExperimentOutlined } from '@ant-design/icons';
import { apiClient } from '../../../shared/api/client';

const { Title, Text } = Typography;

type EvaluationRunRow = {
  run_id?: string;
  id?: string;
  status?: string;
  mode?: string;
  set_version_id?: string;
  created_at?: string;
};

export const EvaluationsPage: React.FC = () => {
  const [runs, setRuns] = useState<EvaluationRunRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await apiClient<EvaluationRunRow[]>('/api/evaluations/runs');
        if (!cancelled) {
          setRuns(Array.isArray(data) ? data : []);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load evaluation runs.');
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
          <ExperimentOutlined style={{ marginRight: 8 }} />
          評測與 Golden 執行
        </Title>
        <Text type="secondary">Live evaluation runs from `/api/evaluations/runs`.</Text>
      </div>
      {error ? <Alert type="error" showIcon message={error} /> : null}
      <Card>
        <Table
          rowKey={(row) => String(row.run_id || row.id || Math.random())}
          loading={loading}
          dataSource={runs}
          pagination={{ pageSize: 20 }}
          columns={[
            {
              title: 'Run',
              dataIndex: 'run_id',
              render: (_: unknown, row: EvaluationRunRow) => row.run_id || row.id || '—',
            },
            {
              title: 'Status',
              dataIndex: 'status',
              render: (status?: string) =>
                status ? <Tag>{status}</Tag> : <Text type="secondary">—</Text>,
            },
            {
              title: 'Mode',
              dataIndex: 'mode',
              render: (mode?: string) => mode || '—',
            },
            {
              title: 'Set version',
              dataIndex: 'set_version_id',
              render: (value?: string) => value || '—',
            },
            {
              title: 'Created',
              dataIndex: 'created_at',
              render: (value?: string) => value || '—',
            },
          ]}
        />
      </Card>
    </Space>
  );
};
