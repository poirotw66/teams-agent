import React, { useEffect, useState } from 'react';
import { Alert, Card, Descriptions, Space, Typography } from 'antd';
import { apiClient } from '../api/client';

const { Title, Text } = Typography;

type SummaryPageProps = {
  title: string;
  subtitle: string;
  endpoint: string;
  icon?: React.ReactNode;
};

export const SummaryPage: React.FC<SummaryPageProps> = ({
  title,
  subtitle,
  endpoint,
  icon,
}) => {
  const [payload, setPayload] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await apiClient<Record<string, unknown>>(endpoint);
        if (!cancelled) {
          setPayload(data && typeof data === 'object' ? data : {});
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

  const entries = Object.entries(payload || {}).slice(0, 40);

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
      <Card loading={loading}>
        <Descriptions bordered size="small" column={1}>
          {entries.map(([key, value]) => (
            <Descriptions.Item key={key} label={key}>
              {typeof value === 'string' || typeof value === 'number'
                ? String(value)
                : JSON.stringify(value)}
            </Descriptions.Item>
          ))}
        </Descriptions>
      </Card>
    </Space>
  );
};
