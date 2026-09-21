import React, { useState } from 'react';
import { Card, Input, Segmented, List, Tag, Typography, Badge, Space, Empty, Spin } from 'antd';
import {
  SearchOutlined,
  DislikeOutlined,
  QuestionCircleOutlined,
  FileDoneOutlined,
} from '@ant-design/icons';
import { ConversationDetail } from '../../../shared/api/types';

const { Text } = Typography;

interface TriageQueueProps {
  conversations: ConversationDetail[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  filterTopic?: string | null;
  emptyMessage?: string;
  isLoading?: boolean;
}

export const TriageQueue: React.FC<TriageQueueProps> = ({
  conversations,
  selectedId,
  onSelect,
  filterTopic,
  emptyMessage,
  isLoading = false,
}) => {
  const [filterType, setFilterType] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>(filterTopic || '');

  const filteredList = conversations.filter((c) => {
    // Tab filter
    if (filterType === 'negative') {
      const hasNegative = c.messages.some((m) => m.feedback === 'negative');
      if (!hasNegative) return false;
    } else if (filterType === 'missing') {
      if (c.root_cause !== 'MISSING_KNOWLEDGE') return false;
    } else if (filterType === 'ticket') {
      if (c.status !== 'ESCALATED_TICKET') return false;
    }

    // Search filter
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchName = c.reporter_name.toLowerCase().includes(q);
      const matchDept = c.reporter_dept.toLowerCase().includes(q);
      const matchTopic = c.topic_summary.toLowerCase().includes(q);
      const matchContent = c.messages.some((m) => m.content.toLowerCase().includes(q));
      if (!matchName && !matchDept && !matchTopic && !matchContent) return false;
    }

    return true;
  });

  const negativeCount = conversations.filter((c) =>
    c.messages.some((m) => m.feedback === 'negative')
  ).length;

  const missingCount = conversations.filter(
    (c) => c.root_cause === 'MISSING_KNOWLEDGE'
  ).length;

  const ticketCount = conversations.filter(
    (c) => c.status === 'ESCALATED_TICKET'
  ).length;

  return (
    <Card
      size="small"
      title={
        <Space direction="vertical" size={8} style={{ width: '100%', padding: '4px 0' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Text strong style={{ fontSize: '15px' }}>
              待處理分診佇列 ({filteredList.length})
            </Text>
          </div>
          <Input
            placeholder="搜尋同仁 / 部門 / 問題關鍵字..."
            prefix={<SearchOutlined style={{ color: '#bfbfbf' }} />}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            allowClear
            size="small"
          />
          <Segmented
            value={filterType}
            onChange={(val) => setFilterType(String(val))}
            size="small"
            block
            options={[
              { label: '全部', value: 'all' },
              {
                label: (
                  <Space size={4}>
                    <DislikeOutlined style={{ color: '#c4314b' }} />
                    <span>負評</span>
                    <Badge count={negativeCount} size="small" style={{ backgroundColor: '#c4314b' }} />
                  </Space>
                ),
                value: 'negative',
              },
              {
                label: (
                  <Space size={4}>
                    <QuestionCircleOutlined style={{ color: '#b78800' }} />
                    <span>查無</span>
                    <Badge count={missingCount} size="small" style={{ backgroundColor: '#b78800' }} />
                  </Space>
                ),
                value: 'missing',
              },
              {
                label: (
                  <Space size={4}>
                    <FileDoneOutlined style={{ color: '#5b5fc7' }} />
                    <span>工單</span>
                    <Badge count={ticketCount} size="small" style={{ backgroundColor: '#5b5fc7' }} />
                  </Space>
                ),
                value: 'ticket',
              },
            ]}
          />
        </Space>
      }
      style={{ borderRadius: 10, height: '100%', minHeight: 320, display: 'flex', flexDirection: 'column' }}
      styles={{
        body: { padding: '8px', flex: 1, overflowY: 'auto' },
      }}
    >
      {isLoading ? (
        <div style={{ display: 'grid', placeItems: 'center', minHeight: 180 }}>
          <Spin tip="載入對話佇列中…" />
        </div>
      ) : (
        <List
          dataSource={filteredList}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={emptyMessage || '目前沒有符合條件的對話'}
              />
            ),
          }}
          renderItem={(item) => {
          const isSelected = item.id === selectedId;
          const hasNegative = item.messages.some((m) => m.feedback === 'negative');
          const isTicket = item.status === 'ESCALATED_TICKET';

          return (
            <div
              key={item.id}
              onClick={() => onSelect(item.id)}
              className="teams-card-hover"
              style={{
                padding: '10px 12px',
                borderRadius: 8,
                marginBottom: 6,
                cursor: 'pointer',
                border: isSelected ? '1px solid #5b5fc7' : '1px solid #ebebf2',
                backgroundColor: isSelected ? '#f0f1fa' : '#ffffff',
                transition: 'all 0.2s cubic-bezier(0.32, 0.72, 0, 1)',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Space size={4}>
                  {hasNegative && (
                    <Tag style={{ backgroundColor: '#fdf3f4', color: '#c4314b', borderColor: '#f6ccd2', fontSize: '11px' }}>
                      負評
                    </Tag>
                  )}
                  {isTicket && (
                    <Tag style={{ backgroundColor: '#f0f1fa', color: '#5b5fc7', borderColor: '#d2d3ec', fontSize: '11px' }}>
                      已開單
                    </Tag>
                  )}
                  {!hasNegative && !isTicket && (
                    <Tag style={{ backgroundColor: '#fff9e6', color: '#8a6605', borderColor: '#ffe699', fontSize: '11px' }}>
                      查無
                    </Tag>
                  )}
                  <Text strong style={{ fontSize: '13px', color: isSelected ? '#33357b' : '#242424' }}>
                    {item.reporter_dept} - {item.reporter_name}
                  </Text>
                </Space>
                <Text type="secondary" style={{ fontSize: '11px' }}>
                  {item.started_at}
                </Text>
              </div>

              <div style={{ marginTop: 6 }}>
                <Text
                  style={{
                    fontSize: '13px',
                    color: isSelected ? '#0050b3' : '#262626',
                    display: '-webkit-box',
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: 'vertical',
                    overflow: 'hidden',
                  }}
                >
                  {item.topic_summary}
                </Text>
              </div>
            </div>
          );
        }}
        />
      )}
    </Card>
  );
};
