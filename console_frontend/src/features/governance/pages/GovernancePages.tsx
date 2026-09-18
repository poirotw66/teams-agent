import React from 'react';
import { Tag } from 'antd';
import {
  AuditOutlined,
  FlagOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { LiveTablePage } from '../../../shared/ui/LiveTablePage';

type NamedRow = Record<string, unknown> & {
  id?: string;
  flag_id?: string;
  config_id?: string;
  change_id?: string;
  version_id?: string;
  status?: string;
  name?: string;
};

function idOf(row: NamedRow, ...keys: string[]): string {
  for (const key of keys) {
    const value = row[key];
    if (typeof value === 'string' && value) {
      return value;
    }
  }
  return String(Math.random());
}

export const ModelsPage: React.FC = () => (
  <LiveTablePage<NamedRow>
    title="模型設定"
    subtitle="Live model configs from `/api/governance/models`."
    endpoint="/api/governance/models"
    icon={<ThunderboltOutlined style={{ marginRight: 8 }} />}
    rowKey={(row) => idOf(row, 'config_id', 'id', 'name')}
    columns={[
      { title: 'Config', render: (_: unknown, row) => idOf(row, 'config_id', 'id', 'name') },
      {
        title: 'Status',
        dataIndex: 'status',
        render: (status?: string) => (status ? <Tag>{status}</Tag> : '—'),
      },
      { title: 'Name', dataIndex: 'name', render: (v?: string) => v || '—' },
    ]}
  />
);

export const FlagsPage: React.FC = () => (
  <LiveTablePage<NamedRow>
    title="Feature Flags"
    subtitle="Live flags from `/api/governance/flags`."
    endpoint="/api/governance/flags"
    icon={<FlagOutlined style={{ marginRight: 8 }} />}
    rowKey={(row) => idOf(row, 'flag_id', 'id', 'name')}
    columns={[
      { title: 'Flag', render: (_: unknown, row) => idOf(row, 'flag_id', 'id', 'name') },
      {
        title: 'Status',
        dataIndex: 'status',
        render: (status?: string) => (status ? <Tag>{status}</Tag> : '—'),
      },
      { title: 'Name', dataIndex: 'name', render: (v?: string) => v || '—' },
    ]}
  />
);

export const RolesPage: React.FC = () => (
  <LiveTablePage<NamedRow>
    title="角色與權限"
    subtitle="Live role matrix from `/api/governance/roles`."
    endpoint="/api/governance/roles"
    icon={<TeamOutlined style={{ marginRight: 8 }} />}
    rowKey={(row) => idOf(row, 'change_id', 'id', 'name')}
    columns={[
      { title: 'Entry', render: (_: unknown, row) => idOf(row, 'change_id', 'id', 'name') },
      {
        title: 'Status',
        dataIndex: 'status',
        render: (status?: string) => (status ? <Tag>{status}</Tag> : '—'),
      },
    ]}
  />
);

export const RetentionPage: React.FC = () => (
  <LiveTablePage<NamedRow>
    title="保存政策"
    subtitle="Live retention policies from `/api/governance/retention`."
    endpoint="/api/governance/retention"
    icon={<SafetyCertificateOutlined style={{ marginRight: 8 }} />}
    rowKey={(row) => idOf(row, 'version_id', 'id')}
    columns={[
      { title: 'Version', render: (_: unknown, row) => idOf(row, 'version_id', 'id') },
      {
        title: 'Status',
        dataIndex: 'status',
        render: (status?: string) => (status ? <Tag>{status}</Tag> : '—'),
      },
    ]}
  />
);

export const MaskingPage: React.FC = () => (
  <LiveTablePage<NamedRow>
    title="脫敏遮罩"
    subtitle="Live masking rules from `/api/governance/masking`."
    endpoint="/api/governance/masking"
    icon={<SafetyCertificateOutlined style={{ marginRight: 8 }} />}
    rowKey={(row) => idOf(row, 'version_id', 'id')}
    columns={[
      { title: 'Version', render: (_: unknown, row) => idOf(row, 'version_id', 'id') },
      {
        title: 'Status',
        dataIndex: 'status',
        render: (status?: string) => (status ? <Tag>{status}</Tag> : '—'),
      },
    ]}
  />
);

export const AuditPage: React.FC = () => (
  <LiveTablePage<NamedRow>
    title="治理稽核"
    subtitle="Live audit stream from `/api/governance/audit`."
    endpoint="/api/governance/audit"
    icon={<AuditOutlined style={{ marginRight: 8 }} />}
    rowKey={(row) => idOf(row, 'event_id', 'id', 'timestamp')}
    columns={[
      { title: 'Event', render: (_: unknown, row) => idOf(row, 'event_id', 'id', 'action') },
      { title: 'Action', dataIndex: 'action', render: (v?: string) => v || '—' },
      { title: 'Actor', dataIndex: 'actor_id', render: (v?: string) => v || '—' },
      { title: 'When', dataIndex: 'timestamp', render: (v?: string) => v || '—' },
    ]}
  />
);
