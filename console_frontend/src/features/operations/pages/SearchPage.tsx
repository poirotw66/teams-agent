import React, { useState } from 'react';
import { Alert, Button, Card, Input, Space, Table, Typography } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { apiClient } from '../../../shared/api/client';

const { Title, Text } = Typography;

type SearchHit = Record<string, unknown> & {
  id?: string;
  title?: string;
  type?: string;
};

export const SearchPage: React.FC = () => {
  const [query, setQuery] = useState('');
  const [rows, setRows] = useState<SearchHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runSearch = async () => {
    const trimmed = query.trim();
    if (!trimmed) {
      setRows([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient<SearchHit[] | { items?: SearchHit[] }>(
        `/api/governance/search?q=${encodeURIComponent(trimmed)}`
      );
      setRows(Array.isArray(data) ? data : Array.isArray(data?.items) ? data.items : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Search failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div>
        <Title level={3} style={{ marginBottom: 4 }}>
          <SearchOutlined style={{ marginRight: 8 }} />
          跨實體搜尋
        </Title>
        <Text type="secondary">Live search via `/api/governance/search`.</Text>
      </div>
      <Space.Compact style={{ width: '100%', maxWidth: 560 }}>
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onPressEnter={() => void runSearch()}
          placeholder="輸入關鍵字"
        />
        <Button type="primary" onClick={() => void runSearch()} loading={loading}>
          搜尋
        </Button>
      </Space.Compact>
      {error ? <Alert type="error" showIcon message={error} /> : null}
      <Card>
        <Table
          rowKey={(row) => String(row.id || row.title || Math.random())}
          loading={loading}
          dataSource={rows}
          pagination={{ pageSize: 20 }}
          columns={[
            {
              title: 'Title',
              dataIndex: 'title',
              render: (v?: string) => v || '—',
            },
            {
              title: 'Type',
              dataIndex: 'type',
              render: (v?: string) => v || '—',
            },
            {
              title: 'Id',
              dataIndex: 'id',
              render: (v?: string) => v || '—',
            },
          ]}
        />
      </Card>
    </Space>
  );
};
