import React, { useEffect, useState } from 'react';
import { Alert, Card, Space, Table, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { apiClient } from '../api/client';

const { Title, Text } = Typography;

type LiveTablePageProps<T extends object> = {
  title: string;
  subtitle: string;
  endpoint: string;
  columns: ColumnsType<T>;
  rowKey: (row: T) => string;
  icon?: React.ReactNode;
};

export function LiveTablePage<T extends object>({
  title,
  subtitle,
  endpoint,
  columns,
  rowKey,
  icon,
}: LiveTablePageProps<T>) {
  const [rows, setRows] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await apiClient<T[] | { items?: T[] }>(endpoint);
        const list = Array.isArray(data) ? data : Array.isArray(data?.items) ? data.items : [];
        if (!cancelled) {
          setRows(list);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : `Failed to load ${endpoint}.`);
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
  }, [endpoint]);

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div>
        <Title level={3} style={{ marginBottom: 4 }}>
          {icon}
          {title}
        </Title>
        <Text type="secondary">{subtitle}</Text>
      </div>
      {error ? <Alert type="error" showIcon message={error} /> : null}
      <Card>
        <Table
          rowKey={rowKey}
          loading={loading}
          dataSource={rows}
          pagination={{ pageSize: 20 }}
          columns={columns}
        />
      </Card>
    </Space>
  );
}
