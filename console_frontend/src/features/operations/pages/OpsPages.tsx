import React from 'react';
import { Tag } from 'antd';
import {
  ApartmentOutlined,
  BarChartOutlined,
  DollarOutlined,
  FundOutlined,
  NodeIndexOutlined,
} from '@ant-design/icons';
import { LiveTablePage } from '../../../shared/ui/LiveTablePage';
import { SummaryPage } from '../../../shared/ui/SummaryPage';

type BudgetRow = {
  policy_id?: string;
  id?: string;
  status?: string;
  name?: string;
};

export const BudgetsPage: React.FC = () => (
  <LiveTablePage<BudgetRow>
    title="預算政策"
    subtitle="Live budget policies from `/api/budget-policies`."
    endpoint="/api/budget-policies"
    icon={<FundOutlined style={{ marginRight: 8 }} />}
    rowKey={(row) => String(row.policy_id || row.id || Math.random())}
    columns={[
      {
        title: 'Policy',
        render: (_: unknown, row) => row.policy_id || row.id || row.name || '—',
      },
      {
        title: 'Status',
        dataIndex: 'status',
        render: (status?: string) => (status ? <Tag>{status}</Tag> : '—'),
      },
      { title: 'Name', dataIndex: 'name', render: (v?: string) => v || '—' },
    ]}
  />
);

export const CostsPage: React.FC = () => (
  <SummaryPage
    title="成本摘要"
    subtitle="Live cost summary from `/api/costs/summary`."
    endpoint="/api/costs/summary"
    icon={<DollarOutlined style={{ marginRight: 8 }} />}
  />
);

export const IssuesPage: React.FC = () => (
  <SummaryPage
    title="議題摘要"
    subtitle="Live issue taxonomy summary from `/api/issues/summary`."
    endpoint="/api/issues/summary"
    icon={<ApartmentOutlined style={{ marginRight: 8 }} />}
  />
);

export const RoutesPage: React.FC = () => (
  <SummaryPage
    title="路由摘要"
    subtitle="Live grounding route summary from `/api/routes/summary`."
    endpoint="/api/routes/summary"
    icon={<NodeIndexOutlined style={{ marginRight: 8 }} />}
  />
);

export const KnowledgeAnalyticsPage: React.FC = () => (
  <SummaryPage
    title="知識成效"
    subtitle="Live knowledge analytics from `/api/knowledge/dashboard`."
    endpoint="/api/knowledge/dashboard"
    icon={<BarChartOutlined style={{ marginRight: 8 }} />}
  />
);

export const KnowledgeAuditPage: React.FC = () => (
  <LiveTablePage<Record<string, unknown>>
    title="知識稽核"
    subtitle="Live knowledge audit events from `/api/knowledge/audit-events`."
    endpoint="/api/knowledge/audit-events"
    icon={<BarChartOutlined style={{ marginRight: 8 }} />}
    rowKey={(row) => String(row.event_id || row.id || Math.random())}
    columns={[
      {
        title: 'Event',
        render: (_: unknown, row) => String(row.event_id || row.id || row.action || '—'),
      },
      {
        title: 'Action',
        dataIndex: 'action',
        render: (v?: unknown) => (typeof v === 'string' ? v : '—'),
      },
      {
        title: 'When',
        dataIndex: 'timestamp',
        render: (v?: unknown) => (typeof v === 'string' ? v : '—'),
      },
    ]}
  />
);
