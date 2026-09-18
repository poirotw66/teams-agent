import React from 'react';
import { Tag } from 'antd';
import { BookOutlined } from '@ant-design/icons';
import { LiveTablePage } from '../../../shared/ui/LiveTablePage';

type ExampleRow = {
  example_id?: string;
  id?: string;
  status?: string;
  issue_type_id?: string;
  text?: string;
};

export const ExamplesPage: React.FC = () => (
  <LiveTablePage<ExampleRow>
    title="分類 Examples"
    subtitle="Live few-shot examples from `/api/examples`."
    endpoint="/api/examples"
    icon={<BookOutlined style={{ marginRight: 8 }} />}
    rowKey={(row) => String(row.example_id || row.id || Math.random())}
    columns={[
      {
        title: 'Example',
        render: (_: unknown, row) => row.example_id || row.id || '—',
      },
      {
        title: 'Status',
        dataIndex: 'status',
        render: (status?: string) => (status ? <Tag>{status}</Tag> : '—'),
      },
      { title: 'Issue type', dataIndex: 'issue_type_id', render: (v?: string) => v || '—' },
      {
        title: 'Text',
        dataIndex: 'text',
        ellipsis: true,
        render: (v?: string) => v || '—',
      },
    ]}
  />
);
