import React from 'react';
import { Card, Table, Tag, Button, Space, Typography } from 'antd';
import { ThunderboltOutlined, QuestionCircleOutlined } from '@ant-design/icons';
import { KnowledgeGapItem } from '../../../shared/api/types';
import { QuickFaqInitialData } from '../../dashboard/components/QuickFaqDrawer';

const { Text } = Typography;

interface KnowledgeGapsManagerProps {
  gaps: KnowledgeGapItem[];
  onOpenQuickFaq: (data: QuickFaqInitialData) => void;
  onTestQuery: (query: string) => void;
}

export const KnowledgeGapsManager: React.FC<KnowledgeGapsManagerProps> = ({
  gaps,
  onOpenQuickFaq,
  onTestQuery,
}) => {
  const columns = [
    {
      title: '高頻未解答問題聚類',
      key: 'cluster',
      render: (_: any, gap: KnowledgeGapItem) => (
        <Space direction="vertical" size={2}>
          <Space>
            <Tag
              style={{
                backgroundColor: '#FFF8E6',
                color: '#B78800',
                borderColor: '#F5D38A',
              }}
              icon={<QuestionCircleOutlined />}
            >
              被問 {gap.frequency} 次
            </Tag>
            <Text strong style={{ fontSize: '14px' }}>
              {gap.cluster_query}
            </Text>
          </Space>
          <Text type="secondary" style={{ fontSize: '12px' }}>
            真實口語範例：{gap.sample_conversations.join(' / ')}
          </Text>
        </Space>
      ),
    },
    {
      title: '建議所屬分類',
      dataIndex: 'category',
      key: 'category',
      width: 140,
      render: (cat: string) => (
        <Tag style={{ backgroundColor: '#F0F1FA', color: '#5B5FC7', borderColor: '#D1D3E0' }}>
          {cat}
        </Tag>
      ),
    },
    {
      title: '偵測區間',
      dataIndex: 'detected_at',
      key: 'detected_at',
      width: 120,
      render: (time: string) => <Text type="secondary">{time}</Text>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 180,
      render: (_: any, gap: KnowledgeGapItem) => (
        <Space size="small">
          <Button
            type="primary"
            size="small"
            icon={<ThunderboltOutlined />}
            style={{ backgroundColor: '#5B5FC7', borderColor: '#5B5FC7' }}
            onClick={() =>
              onOpenQuickFaq({
                question: gap.sample_conversations[0] || gap.cluster_query,
                category: gap.category,
              })
            }
          >
            補齊此 FAQ
          </Button>
          <Button
            size="small"
            type="link"
            style={{ color: '#5B5FC7' }}
            onClick={() => onTestQuery(gap.cluster_query)}
          >
            測試現狀
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <Card
      size="small"
      title={
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <Text strong style={{ fontSize: '14px' }}>
              待補知識缺口庫 (Knowledge Gaps)
            </Text>
            <Text type="secondary" style={{ fontSize: '12px', marginLeft: 8 }}>
              系統由每日 Teams 對話中自動語意聚類出「同仁反覆詢問、但知識庫查無解答」的高頻盲區
            </Text>
          </div>
        </div>
      }
      style={{ borderRadius: 8 }}
    >
      <Table
        columns={columns}
        dataSource={gaps}
        rowKey="id"
        pagination={false}
        size="middle"
      />
    </Card>
  );
};
