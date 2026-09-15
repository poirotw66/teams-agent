import React, { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Row,
  Col,
  Statistic,
  Tabs,
  Table,
  Button,
  Space,
  Typography,
  Alert,
  Empty,
  Spin,
} from 'antd';
import {
  ClockCircleOutlined,
  AuditOutlined,
  EyeOutlined,
  CheckCircleOutlined,
  ReloadOutlined,
  ArrowRightOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { apiClient } from '../../../shared/api/client';
import { WorkItem, WorkItemsResponse, WorkSummaryResponse } from '../../../shared/api/types';
import { StatusTag } from '../../../shared/ui/StatusTag';

const { Title, Text } = Typography;

export const WorkPage: React.FC = () => {
  const navigate = useNavigate();
  const [activeBucket, setActiveBucket] = useState<string>('all');
  const [items, setItems] = useState<WorkItem[]>([]);
  const [summary, setSummary] = useState<WorkSummaryResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [partial, setPartial] = useState<boolean>(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [summaryRes, itemsRes] = await Promise.all([
        apiClient<WorkSummaryResponse>('/api/console/work-summary'),
        apiClient<WorkItemsResponse>(`/api/console/work-items?bucket=${activeBucket}&limit=50`),
      ]);

      setSummary(summaryRes);
      setItems(itemsRes.items || []);
      setPartial(itemsRes.partial || false);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '載入工作項目時發生錯誤';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [activeBucket]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleActionClick = (route: string) => {
    navigate(route);
  };

  const getSourceTypeName = (sourceType: string) => {
    switch (sourceType) {
      case 'quality_case':
        return '品質案件';
      case 'knowledge_doc':
        return '知識文件';
      case 'eval_gate':
        return '評測門禁';
      default:
        return sourceType;
    }
  };

  const columns = [
    {
      title: '工作標題',
      dataIndex: 'title',
      key: 'title',
      render: (text: string, record: WorkItem) => (
        <Space direction="vertical" size={2}>
          <Text strong style={{ cursor: 'pointer' }} onClick={() => handleActionClick(record.next_action.route)}>
            {text}
          </Text>
          <Text type="secondary" style={{ fontSize: '12px' }}>
            ID: {record.source_id}
          </Text>
        </Space>
      ),
    },
    {
      title: '來源類型',
      dataIndex: 'source_type',
      key: 'source_type',
      width: 120,
      render: (type: string) => <Text>{getSourceTypeName(type)}</Text>,
    },
    {
      title: '負責人',
      dataIndex: 'assignee_id',
      key: 'assignee_id',
      width: 130,
      render: (assignee: string | null) => (
        <Text type={assignee ? undefined : 'secondary'}>{assignee || '未指派'}</Text>
      ),
    },
    {
      title: '目前階段',
      dataIndex: 'source_status',
      key: 'source_status',
      width: 140,
      render: (status: string, record: WorkItem) => (
        <Space direction="vertical" size={2}>
          <StatusTag status={status} />
          <Text type="secondary" style={{ fontSize: '12px' }}>{record.step}</Text>
        </Space>
      ),
    },
    {
      title: '資料更新時間',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 180,
      render: (time: string) => (
        <Text style={{ fontSize: '12px' }}>
          {new Date(time).toLocaleString('zh-TW', { hour12: false })}
        </Text>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 130,
      render: (_: unknown, record: WorkItem) => (
        <Button
          type="primary"
          size="small"
          icon={<ArrowRightOutlined />}
          onClick={() => handleActionClick(record.next_action.route)}
        >
          處理案件
        </Button>
      ),
    },
  ];

  const tabItems = [
    { key: 'all', label: `全部 (${summary?.total ?? 0})` },
    { key: 'pending_action', label: `待我處理 (${summary?.by_bucket.pending_action ?? 0})` },
    { key: 'pending_review', label: `待我審核 (${summary?.by_bucket.pending_review ?? 0})` },
    { key: 'tracking', label: `追蹤中 (${summary?.by_bucket.tracking ?? 0})` },
    { key: 'completed', label: `已完成 (${summary?.by_bucket.completed ?? 0})` },
  ];

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <Title level={3} style={{ marginBottom: 4 }}>
            今天要處理什麼
          </Title>
          <Text type="secondary">
            跨流程工作佇列彙整。僅呈現您被指派或具備檢視權限的真實案件。
          </Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>
          重新整理
        </Button>
      </div>

      {/* Workflow Summary Cards */}
      <Row gutter={[16, 16]}>
        <Col xs={12} sm={6}>
          <Card
            hoverable
            onClick={() => setActiveBucket('pending_action')}
            style={{
              borderColor: activeBucket === 'pending_action' ? '#1890ff' : undefined,
              borderRadius: 8,
            }}
          >
            <Statistic
              title="待我處理"
              value={summary?.by_bucket.pending_action ?? 0}
              valueStyle={{ color: '#1890ff' }}
              prefix={<ClockCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card
            hoverable
            onClick={() => setActiveBucket('pending_review')}
            style={{
              borderColor: activeBucket === 'pending_review' ? '#faad14' : undefined,
              borderRadius: 8,
            }}
          >
            <Statistic
              title="待我審核"
              value={summary?.by_bucket.pending_review ?? 0}
              valueStyle={{ color: '#faad14' }}
              prefix={<AuditOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card
            hoverable
            onClick={() => setActiveBucket('tracking')}
            style={{
              borderColor: activeBucket === 'tracking' ? '#722ed1' : undefined,
              borderRadius: 8,
            }}
          >
            <Statistic
              title="追蹤中"
              value={summary?.by_bucket.tracking ?? 0}
              valueStyle={{ color: '#722ed1' }}
              prefix={<EyeOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card
            hoverable
            onClick={() => setActiveBucket('completed')}
            style={{
              borderColor: activeBucket === 'completed' ? '#52c41a' : undefined,
              borderRadius: 8,
            }}
          >
            <Statistic
              title="已完成"
              value={summary?.by_bucket.completed ?? 0}
              valueStyle={{ color: '#52c41a' }}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* Partial failure notice */}
      {partial && (
        <Alert
          type="warning"
          showIcon
          message="部分資料來源暫時無法取得"
          description="已有部分外部工作佇列服務回應超時或無法連線，目前畫面僅顯示可成功存取的項目。"
        />
      )}

      {/* Error state */}
      {error && (
        <Alert
          type="error"
          showIcon
          message="載入工作清單失敗"
          description={error}
          action={
            <Button size="small" type="primary" onClick={fetchData}>
              重試
            </Button>
          }
        />
      )}

      {/* Items table card */}
      <Card style={{ borderRadius: 8 }}>
        <Tabs
          activeKey={activeBucket}
          items={tabItems}
          onChange={(key) => setActiveBucket(key)}
          style={{ marginBottom: 16 }}
        />

        {loading ? (
          <div style={{ textAlign: 'center', padding: '60px 0' }}>
            <Spin size="large" tip="載入工作項目中..." />
          </div>
        ) : items.length === 0 ? (
          <Empty
            description={
              activeBucket === 'all'
                ? '目前沒有任何待辦工作'
                : '此分類下目前沒有工作項目'
            }
            style={{ padding: '40px 0' }}
          />
        ) : (
          <Table
            dataSource={items}
            columns={columns}
            rowKey="key"
            pagination={{ pageSize: 20, showSizeChanger: true }}
          />
        )}
      </Card>
    </Space>
  );
};
