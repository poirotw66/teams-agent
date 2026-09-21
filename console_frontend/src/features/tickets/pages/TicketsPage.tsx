import React, { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Card,
  Table,
  Tag,
  Button,
  Space,
  Typography,
  Input,
  Select,
  Segmented,
  Modal,
  Descriptions,
} from 'antd';
import {
  FileDoneOutlined,
  SearchOutlined,
  EyeOutlined,
  ExportOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';
import { ItTicketItem } from '../../../shared/api/types';
import { workbenchStore } from '../../../shared/api/workbenchStore';
import { WorkbenchLoadErrorBanner } from '../../../shared/ui/WorkbenchLoadErrorBanner';

const { Title, Text } = Typography;

export const TicketsPage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const paramTicketId = searchParams.get('ticketId');

  const [tickets, setTickets] = useState<ItTicketItem[]>(workbenchStore.getTickets());
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');

  const [detailModalOpen, setDetailModalOpen] = useState<boolean>(false);
  const [activeTicket, setActiveTicket] = useState<ItTicketItem | null>(null);

  useEffect(() => {
    void workbenchStore.ensureDomains(['tickets']);
    const unsubscribe = workbenchStore.subscribe(() => {
      setTickets(workbenchStore.getTickets());
    });
    return unsubscribe;
  }, []);

  useEffect(() => {
    if (paramTicketId) {
      const match = tickets.find((t) => t.id === paramTicketId || t.ticket_number === paramTicketId);
      if (match) {
        setActiveTicket(match);
        setDetailModalOpen(true);
      }
    }
  }, [paramTicketId, tickets]);

  const filteredTickets = tickets.filter((t) => {
    if (statusFilter === 'in_progress' && t.status !== 'IN_PROGRESS') return false;
    if (statusFilter === 'resolved' && t.status !== 'RESOLVED') return false;

    if (categoryFilter !== 'all' && t.category !== categoryFilter) return false;

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchNum = t.ticket_number.toLowerCase().includes(q);
      const matchTitle = t.title.toLowerCase().includes(q);
      const matchReporter = t.reporter_name.toLowerCase().includes(q);
      const matchDept = t.reporter_dept.toLowerCase().includes(q);
      if (!matchNum && !matchTitle && !matchReporter && !matchDept) return false;
    }

    return true;
  });

  const handleViewConversation = (conversationId: string) => {
    navigate(`/triage?conversationId=${conversationId}`);
  };

  const handleOpenDetail = (ticket: ItTicketItem) => {
    setActiveTicket(ticket);
    setDetailModalOpen(true);
  };

  const columns = [
    {
      title: '工單編號',
      dataIndex: 'ticket_number',
      key: 'ticket_number',
      width: 140,
      render: (num: string, record: ItTicketItem) => (
        <Space direction="vertical" size={2}>
          <Text strong style={{ color: '#5B5FC7', cursor: 'pointer' }} onClick={() => handleOpenDetail(record)}>
            {num}
          </Text>
          <Tag style={{ fontSize: '10px', backgroundColor: '#F0F1FA', color: '#5B5FC7', borderColor: '#D1D3E0' }}>
            Jira 已同步
          </Tag>
        </Space>
      ),
    },
    {
      title: '報修同仁資訊',
      key: 'reporter',
      width: 170,
      render: (_: any, record: ItTicketItem) => (
        <Space direction="vertical" size={2}>
          <Text strong>
            {record.reporter_dept} - {record.reporter_name}
          </Text>
          <Text type="secondary" style={{ fontSize: '12px' }}>
            分機：{record.reporter_ext || '未提供'}
          </Text>
        </Space>
      ),
    },
    {
      title: '問題主旨與派工組別',
      key: 'title',
      render: (_: any, record: ItTicketItem) => (
        <Space direction="vertical" size={2}>
          <Text strong style={{ fontSize: '14px' }}>
            {record.title}
          </Text>
          <Space size="small">
            <Tag style={{ backgroundColor: '#F0F1FA', color: '#6264A7', borderColor: '#D1D3E0' }}>
              {record.assigned_team}
            </Tag>
            {record.assigned_agent && (
              <Text type="secondary" style={{ fontSize: '12px' }}>
                接單工程師：{record.assigned_agent}
              </Text>
            )}
          </Space>
        </Space>
      ),
    },
    {
      title: '目前進度狀態',
      key: 'status',
      width: 140,
      render: (_: any, record: ItTicketItem) => (
        <Space direction="vertical" size={2}>
          <Tag
            style={{
              backgroundColor: record.status === 'RESOLVED' ? '#EBF6EC' : '#FFF8E6',
              color: record.status === 'RESOLVED' ? '#107C41' : '#B78800',
              borderColor: record.status === 'RESOLVED' ? '#BDE3C4' : '#F5D38A',
            }}
            icon={record.status === 'RESOLVED' ? <CheckCircleOutlined /> : <ClockCircleOutlined />}
          >
            {record.status === 'RESOLVED' ? '已結案' : '處理中'}
          </Tag>
          <Text type="secondary" style={{ fontSize: '11px' }}>
            {record.updated_at}
          </Text>
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 200,
      render: (_: any, record: ItTicketItem) => (
        <Space size="small">
          {record.conversation_id ? (
            <Button
              size="small"
              icon={<EyeOutlined />}
              onClick={() => handleViewConversation(record.conversation_id!)}
            >
              原始對話
            </Button>
          ) : (
            <Text type="secondary" style={{ fontSize: '12px' }}>
              手動進件
            </Text>
          )}
          <Button
            size="small"
            type="primary"
            ghost
            onClick={() => handleOpenDetail(record)}
          >
            詳情
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <WorkbenchLoadErrorBanner domains={['tickets']} />
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          IT 實體工單追蹤中心
        </Title>
        <Text type="secondary" style={{ fontSize: '13px' }}>
          Jira / ServiceNow / 內部工單連動 · 硬體與權限派工進度 · 一鍵穿梭回溯 Teams 對話上下文
        </Text>
      </div>

      <Card
        size="small"
        title={
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
            <Space>
              <Segmented
                value={statusFilter}
                onChange={(val) => setStatusFilter(String(val))}
                size="small"
                options={[
                  { label: `全部工單 (${tickets.length})`, value: 'all' },
                  {
                    label: `處理中 (${tickets.filter((t) => t.status === 'IN_PROGRESS').length})`,
                    value: 'in_progress',
                  },
                  {
                    label: `已結案 (${tickets.filter((t) => t.status === 'RESOLVED').length})`,
                    value: 'resolved',
                  },
                ]}
              />
              <Select
                value={categoryFilter}
                onChange={setCategoryFilter}
                size="small"
                style={{ width: 140 }}
                options={[
                  { label: '全部類別', value: 'all' },
                  { label: '硬體維護', value: 'HARDWARE' },
                  { label: '系統權限', value: 'ACCESS' },
                  { label: '網路實體', value: 'NETWORK' },
                ]}
              />
            </Space>

            <Input
              placeholder="搜尋工單號碼 / 同仁 / 主旨..."
              prefix={<SearchOutlined style={{ color: '#bfbfbf' }} />}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{ width: 240 }}
              size="small"
              allowClear
            />
          </div>
        }
        style={{ borderRadius: 8 }}
      >
        <Table
          columns={columns}
          dataSource={filteredTickets}
          rowKey="id"
          pagination={{ pageSize: 8 }}
          size="middle"
        />
      </Card>

      {/* Ticket Detail Modal */}
      <Modal
        title={
          <Space>
            <FileDoneOutlined style={{ color: '#5B5FC7' }} />
            <span>工單詳情 — {activeTicket?.ticket_number}</span>
          </Space>
        }
        open={detailModalOpen}
        onCancel={() => setDetailModalOpen(false)}
        footer={[
          activeTicket?.conversation_id && (
            <Button
              key="conv"
              icon={<EyeOutlined />}
              onClick={() => {
                setDetailModalOpen(false);
                handleViewConversation(activeTicket.conversation_id!);
              }}
            >
              檢視 Teams 原始對話
            </Button>
          ),
          <Button
            key="jira"
            type="primary"
            icon={<ExportOutlined />}
            href={`https://jira.corp.internal/browse/${activeTicket?.ticket_number}`}
            target="_blank"
            style={{ backgroundColor: '#5B5FC7', borderColor: '#5B5FC7' }}
          >
            在 Jira 中開啟
          </Button>,
          <Button key="close" onClick={() => setDetailModalOpen(false)}>
            關閉
          </Button>,
        ]}
        width={650}
      >
        {activeTicket && (
          <Descriptions bordered column={2} size="small" style={{ marginTop: 12 }}>
            <Descriptions.Item label="工單編號">
              <Tag style={{ backgroundColor: '#F0F1FA', color: '#5B5FC7', borderColor: '#D1D3E0' }}>
                {activeTicket.ticket_number}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="目前狀態">
              <Tag
                style={{
                  backgroundColor: activeTicket.status === 'RESOLVED' ? '#EBF6EC' : '#FFF8E6',
                  color: activeTicket.status === 'RESOLVED' ? '#107C41' : '#B78800',
                  borderColor: activeTicket.status === 'RESOLVED' ? '#BDE3C4' : '#F5D38A',
                }}
                icon={activeTicket.status === 'RESOLVED' ? <CheckCircleOutlined /> : <ClockCircleOutlined />}
              >
                {activeTicket.status === 'RESOLVED' ? '已結案' : '處理中'}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="報修同仁">
              {activeTicket.reporter_dept} - {activeTicket.reporter_name}
            </Descriptions.Item>
            <Descriptions.Item label="分機電話">
              {activeTicket.reporter_ext || '未提供'}
            </Descriptions.Item>
            <Descriptions.Item label="指派組別" span={2}>
              {activeTicket.assigned_team}（處理工程師：{activeTicket.assigned_agent || '待指派'}）
            </Descriptions.Item>
            <Descriptions.Item label="問題主旨" span={2}>
              <Text strong>{activeTicket.title}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="最新處置進度" span={2}>
              <div style={{ color: '#107C41', fontWeight: 600 }}>
                {activeTicket.resolution_note || '工程師現場處理中'}
              </div>
            </Descriptions.Item>
            <Descriptions.Item label="建立時間">
              {activeTicket.created_at}
            </Descriptions.Item>
            <Descriptions.Item label="最後更新">
              {activeTicket.updated_at}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </div>
  );
};
