import React from 'react';
import { Tag } from 'antd';
import { FormOutlined } from '@ant-design/icons';
import { LiveTablePage } from '../../../shared/ui/LiveTablePage';

type PromptRow = {
  candidate_id?: string;
  id?: string;
  status?: string;
  name?: string;
  created_at?: string;
};

export const PromptsPage: React.FC = () => (
  <LiveTablePage<PromptRow>
    title="Prompt Candidates"
    subtitle="Live prompt candidates from `/api/prompts/candidates`."
    endpoint="/api/prompts/candidates"
    icon={<FormOutlined style={{ marginRight: 8 }} />}
    rowKey={(row) => String(row.candidate_id || row.id || Math.random())}
    columns={[
      {
        title: 'Candidate',
        render: (_: unknown, row) => row.candidate_id || row.id || row.name || '—',
      },
      {
        title: 'Status',
        dataIndex: 'status',
        render: (status?: string) => (status ? <Tag>{status}</Tag> : '—'),
      },
      { title: 'Name', dataIndex: 'name', render: (v?: string) => v || '—' },
      { title: 'Created', dataIndex: 'created_at', render: (v?: string) => v || '—' },
    ]}
  />
);
