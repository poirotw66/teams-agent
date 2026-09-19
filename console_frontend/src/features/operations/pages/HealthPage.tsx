import React, { useState, useEffect, useCallback } from 'react';
import { Card, Table, Typography, Space, Button, Alert, Tag, Descriptions } from 'antd';
import { ReloadOutlined, CheckCircleOutlined, WarningOutlined, CloseCircleOutlined } from '@ant-design/icons';
import { apiClient } from '../../../shared/api/client';
import { StatusTag } from '../../../shared/ui/StatusTag';

const { Title, Text } = Typography;

interface ComponentRow {
  key: string;
  name: string;
  status: string;
  note?: string;
}

export const HealthPage: React.FC = () => {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchHealth = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient<any>('/api/health/summary');
      setData(res);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '無法取得系統健康檢查資訊';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
  }, [fetchHealth]);

  const componentsList: ComponentRow[] = (() => {
    if (!data) return [];
    const raw = data.components || data.probes;
    if (Array.isArray(raw)) {
      return raw.map((item: Record<string, unknown>, index: number) => {
        const id = String(item.id || item.name || index);
        return {
          key: id,
          name: id,
          status: String(item.status || item.health || 'UNKNOWN'),
          note: typeof item.note === 'string' ? item.note : undefined,
        };
      });
    }
    if (raw && typeof raw === 'object') {
      return Object.entries(raw).map(([key, val]: [string, any]) => {
        const status = typeof val === 'object' && val ? val.status || 'UNKNOWN' : String(val);
        const note = typeof val === 'object' && val ? val.note || '' : '';
        return { key, name: key, status, note };
      });
    }
    return [];
  })();

  const overallStatus = data?.overallStatus || data?.status || (error ? 'DOWN' : 'READY');

  const getStatusIcon = (status: string) => {
    switch (status.toUpperCase()) {
      case 'READY':
      case 'OK':
      case 'HEALTHY':
        return <CheckCircleOutlined style={{ color: '#52c41a', fontSize: '24px' }} />;
      case 'DEGRADED':
        return <WarningOutlined style={{ color: '#faad14', fontSize: '24px' }} />;
      default:
        return <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: '24px' }} />;
    }
  };

  const columns = [
    {
      title: '子系統／組件',
      dataIndex: 'name',
      key: 'name',
      render: (text: string) => <Text strong>{text}</Text>,
    },
    {
      title: '健康狀態',
      dataIndex: 'status',
      key: 'status',
      width: 160,
      render: (status: string) => <StatusTag status={status} type="health" />,
    },
    {
      title: '備註與診斷資訊',
      dataIndex: 'note',
      key: 'note',
      render: (note: string) => (
        <Text type="secondary" style={{ fontSize: '13px' }}>
          {note || '運作正常，無異常日誌'}
        </Text>
      ),
    },
  ];

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <Title level={3} style={{ marginBottom: 4 }}>
            平台健康與探針狀態
          </Title>
          <Text type="secondary">
            即時檢測後台、AI 代理、知識庫同步與核心儲存節點連線狀態。
          </Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={fetchHealth} loading={loading}>
          重新檢測
        </Button>
      </div>

      {error && (
        <Alert
          type="error"
          showIcon
          message="健康檢查端點連線失敗"
          description={error}
          action={
            <Button size="small" type="primary" onClick={fetchHealth}>
              重試
            </Button>
          }
        />
      )}

      {/* Overall Health Card */}
      <Card style={{ borderRadius: 8 }}>
        <Space size="large" align="center">
          {getStatusIcon(overallStatus)}
          <div>
            <Space align="center" size="small">
              <Text strong style={{ fontSize: '18px' }}>
                整體系統狀態：
              </Text>
              <Tag
                color={
                  overallStatus === 'READY' || overallStatus === 'OK'
                    ? 'success'
                    : overallStatus === 'DEGRADED'
                    ? 'warning'
                    : 'error'
                }
                style={{ fontSize: '14px', padding: '2px 8px' }}
              >
                {overallStatus === 'READY' || overallStatus === 'OK'
                  ? '所有服務正常運行'
                  : overallStatus === 'DEGRADED'
                  ? '部分服務降級運行'
                  : '系統連線異常'}
              </Tag>
            </Space>
            <div style={{ marginTop: 4 }}>
              <Text type="secondary" style={{ fontSize: '12px' }}>
                最後檢測時間：{new Date().toLocaleString('zh-TW', { hour12: false })}
              </Text>
            </div>
          </div>
        </Space>

        {data?.metrics && (
          <Descriptions size="small" column={{ xs: 1, sm: 2, md: 4 }} style={{ marginTop: 20 }}>
            {Object.entries(data.metrics).map(([k, v]) => (
              <Descriptions.Item key={k} label={k}>
                {String(v)}
              </Descriptions.Item>
            ))}
          </Descriptions>
        )}
      </Card>

      {/* Components Table Card */}
      <Card title="各組件探針監控清單" style={{ borderRadius: 8 }}>
        <Table
          dataSource={componentsList}
          columns={columns}
          loading={loading}
          pagination={false}
        />
      </Card>
    </Space>
  );
};
