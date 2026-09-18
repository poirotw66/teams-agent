import React from 'react';
import { Tag } from 'antd';
import { SyncOutlined } from '@ant-design/icons';
import { LiveTablePage } from '../../../shared/ui/LiveTablePage';

type SyncJobRow = {
  job_id?: string;
  id?: string;
  status?: string;
  scope_type?: string;
  created_at?: string;
};

export const SyncJobsPage: React.FC = () => (
  <LiveTablePage<SyncJobRow>
    title="知識 Sync Jobs"
    subtitle="Live connector sync jobs from `/api/sync-jobs`."
    endpoint="/api/sync-jobs"
    icon={<SyncOutlined style={{ marginRight: 8 }} />}
    rowKey={(row) => String(row.job_id || row.id || Math.random())}
    columns={[
      {
        title: 'Job',
        render: (_: unknown, row) => row.job_id || row.id || '—',
      },
      {
        title: 'Status',
        dataIndex: 'status',
        render: (status?: string) => (status ? <Tag>{status}</Tag> : '—'),
      },
      { title: 'Scope', dataIndex: 'scope_type', render: (v?: string) => v || '—' },
      { title: 'Created', dataIndex: 'created_at', render: (v?: string) => v || '—' },
    ]}
  />
);
