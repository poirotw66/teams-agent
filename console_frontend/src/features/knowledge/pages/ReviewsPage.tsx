import React, { useEffect, useState } from 'react';
import { Alert, Card, Space, Table, Typography } from 'antd';
import { AuditOutlined } from '@ant-design/icons';
import { apiClient } from '../../../shared/api/client';

const { Title, Text } = Typography;

type ReviewRow = {
  review_id?: string;
  document_id?: string;
  status?: string;
  submitted_by?: string;
  submitted_at?: string;
  title?: string;
};

export const ReviewsPage: React.FC = () => {
  const [rows, setRows] = useState<ReviewRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await apiClient<ReviewRow[]>('/api/knowledge/reviews/pending');
        if (!cancelled) {
          setRows(Array.isArray(data) ? data : []);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load pending reviews.');
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
          <AuditOutlined style={{ marginRight: 8 }} />
          知識審核佇列
        </Title>
        <Text type="secondary">Pending reviews from `/api/knowledge/reviews/pending`.</Text>
      </div>
      {error ? <Alert type="error" showIcon message={error} /> : null}
      <Card>
        <Table
          rowKey={(row) => String(row.review_id || Math.random())}
          loading={loading}
          dataSource={rows}
          pagination={{ pageSize: 20 }}
          columns={[
            {
              title: 'Review',
              dataIndex: 'review_id',
              render: (value?: string) => value || '—',
            },
            {
              title: 'Document',
              dataIndex: 'document_id',
              render: (_: unknown, row: ReviewRow) => row.title || row.document_id || '—',
            },
            {
              title: 'Status',
              dataIndex: 'status',
              render: (value?: string) => value || '—',
            },
            {
              title: 'Submitted by',
              dataIndex: 'submitted_by',
              render: (value?: string) => value || '—',
            },
            {
              title: 'Submitted at',
              dataIndex: 'submitted_at',
              render: (value?: string) => value || '—',
            },
          ]}
        />
      </Card>
    </Space>
  );
};
