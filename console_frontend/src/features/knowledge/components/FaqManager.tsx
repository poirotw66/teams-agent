import React, { useState } from 'react';
import {
  Card,
  Table,
  Tag,
  Button,
  Space,
  Typography,
  Select,
  Input,
  Popconfirm,
  message,
} from 'antd';
import {
  ThunderboltOutlined,
  EditOutlined,
  SearchOutlined,
  CheckCircleOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import { FaqItem } from '../../../shared/api/types';
import { workbenchStore } from '../../../shared/api/workbenchStore';
import { QuickFaqInitialData } from '../../dashboard/components/QuickFaqDrawer';

const { Text, Paragraph } = Typography;

interface FaqManagerProps {
  faqs: FaqItem[];
  onOpenQuickFaq: (data?: QuickFaqInitialData) => void;
  onTestQuery: (query: string) => void;
}

export const FaqManager: React.FC<FaqManagerProps> = ({
  faqs,
  onOpenQuickFaq,
  onTestQuery,
}) => {
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [deletingFaqId, setDeletingFaqId] = useState<string | null>(null);

  const filteredFaqs = faqs.filter((faq) => {
    if (categoryFilter !== 'all' && faq.category !== categoryFilter) {
      return false;
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchQuestions = faq.questions.some((qStr) => qStr.toLowerCase().includes(q));
      const matchAnswer = faq.answer.toLowerCase().includes(q);
      if (!matchQuestions && !matchAnswer) return false;
    }
    return true;
  });

  const handleDeleteFaq = async (faqId: string) => {
    setDeletingFaqId(faqId);
    try {
      await workbenchStore.deleteFaq(faqId);
      message.success('已成功刪除該 FAQ 知識！');
    } catch (err: any) {
      const detail = err?.message || '伺服器連線異常';
      message.error(`刪除失敗：${detail}`);
    } finally {
      setDeletingFaqId(null);
    }
  };

  const columns = [
    {
      title: '同仁常見問法',
      key: 'questions',
      width: '35%',
      render: (_: any, faq: FaqItem) => (
        <Space direction="vertical" size={2}>
          <Text strong style={{ fontSize: '14px', color: '#5B5FC7' }}>
            {faq.questions[0]}
          </Text>
          {faq.questions.length > 1 && (
            <Text type="secondary" style={{ fontSize: '12px' }}>
              其他相似問法：{faq.questions.slice(1).join(' / ')}
            </Text>
          )}
          <Tag style={{ width: 'fit-content', marginTop: 4, backgroundColor: '#F0F1FA', color: '#5B5FC7', borderColor: '#D1D3E0' }}>
            {faq.category}
          </Tag>
        </Space>
      ),
    },
    {
      title: '標準解答內容',
      dataIndex: 'answer',
      key: 'answer',
      render: (answer: string) => (
        <Paragraph
          ellipsis={{ rows: 3, expandable: true, symbol: '展開' }}
          style={{ margin: 0, fontSize: '13px', whiteSpace: 'pre-line' }}
        >
          {answer}
        </Paragraph>
      ),
    },
    {
      title: '狀態與更新',
      key: 'updated',
      width: 150,
      render: (_: any, faq: FaqItem) => (
        <Space direction="vertical" size={2}>
          <Tag
            style={{
              backgroundColor: faq.is_active ? '#EBF6EC' : '#F5F5F7',
              color: faq.is_active ? '#107C41' : '#616161',
              borderColor: faq.is_active ? '#BDE3C4' : '#E0E0E6',
            }}
            icon={<CheckCircleOutlined />}
          >
            {faq.is_active ? '已生效' : '停用'}
          </Tag>
          <Text type="secondary" style={{ fontSize: '12px' }}>
            {faq.updated_at}
          </Text>
          {faq.updated_by && (
            <Text type="secondary" style={{ fontSize: '11px' }}>
              {faq.updated_by}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 190,
      render: (_: any, faq: FaqItem) => (
        <Space size="small">
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() =>
              onOpenQuickFaq({
                id: faq.id,
                question: faq.questions[0],
                newAnswer: faq.answer,
                category: faq.category,
              })
            }
          >
            修訂
          </Button>
          <Button
            size="small"
            type="primary"
            ghost
            onClick={() => onTestQuery(faq.questions[0])}
          >
            測試
          </Button>
          <Popconfirm
            title="確定要刪除此 FAQ 嗎？"
            okText="刪除"
            cancelText="取消"
            okButtonProps={{ danger: true, loading: deletingFaqId === faq.id }}
            onConfirm={() => handleDeleteFaq(faq.id)}
          >
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              loading={deletingFaqId === faq.id}
            />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      size="small"
      title={
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Space>
            <Input
              placeholder="搜尋問法或解答關鍵字..."
              prefix={<SearchOutlined style={{ color: '#bfbfbf' }} />}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{ width: 220 }}
              size="small"
              allowClear
            />
            <Select
              value={categoryFilter}
              onChange={setCategoryFilter}
              size="small"
              style={{ width: 140 }}
              options={[
                { label: '全部分類', value: 'all' },
                { label: '差勤/人資', value: '差勤/人資' },
                { label: '網路通訊', value: '網路通訊' },
                { label: '帳號安全', value: '帳號安全' },
              ]}
            />
          </Space>
          <Button
            type="primary"
            size="small"
            icon={<ThunderboltOutlined />}
            onClick={() => onOpenQuickFaq()}
            style={{ backgroundColor: '#5B5FC7', borderColor: '#5B5FC7' }}
          >
            快速新增 FAQ
          </Button>
        </div>
      }
      style={{ borderRadius: 8 }}
    >
      <Table
        columns={columns}
        dataSource={filteredFaqs}
        rowKey="id"
        pagination={{ pageSize: 8 }}
        size="middle"
      />
    </Card>
  );
};
