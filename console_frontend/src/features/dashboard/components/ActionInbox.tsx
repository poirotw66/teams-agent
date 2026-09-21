import React, { useState } from 'react';
import {
  Card,
  Tabs,
  Badge,
  Tag,
  Button,
  Space,
  Typography,
  Empty,
  message,
} from 'antd';
import {
  ThunderboltOutlined,
  FileDoneOutlined,
  CheckOutlined,
  EyeOutlined,
  DislikeOutlined,
  QuestionCircleOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';
import {
  ConversationDetail,
  KnowledgeGapItem,
  ItTicketItem,
  FaqItem,
} from '../../../shared/api/types';
import { workbenchStore } from '../../../shared/api/workbenchStore';
import { describeMutationError } from '../../../shared/api/mutationErrors';
import { useCan } from '@refinedev/core';
import { CONSOLE_WRITE_ACTIONS } from '../../../app/routing/routeRegistry';
import { QuickFaqInitialData } from './QuickFaqDrawer';
import { EscalateTicketInitialData } from './EscalateTicketModal';

const { Text, Paragraph } = Typography;

interface ActionInboxProps {
  conversations: ConversationDetail[];
  gaps: KnowledgeGapItem[];
  tickets: ItTicketItem[];
  faqs: FaqItem[];
  onOpenQuickFaq: (data: QuickFaqInitialData) => void;
  onOpenEscalateModal: (data: EscalateTicketInitialData) => void;
  onViewConversation: (conversationId: string) => void;
  onViewTicket: (ticket: ItTicketItem) => void;
}

export const ActionInbox: React.FC<ActionInboxProps> = ({
  conversations,
  gaps,
  tickets,
  faqs,
  onOpenQuickFaq,
  onOpenEscalateModal,
  onViewConversation,
  onViewTicket,
}) => {
  const [activeTab, setActiveTab] = useState<string>('negative');
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const { data: canWriteFaq } = useCan({
    resource: CONSOLE_WRITE_ACTIONS.faqWrite.resource,
    action: CONSOLE_WRITE_ACTIONS.faqWrite.action,
  });
  const { data: canEscalate } = useCan({
    resource: CONSOLE_WRITE_ACTIONS.ticketEscalate.resource,
    action: CONSOLE_WRITE_ACTIONS.ticketEscalate.action,
  });
  const { data: canResolve } = useCan({
    resource: CONSOLE_WRITE_ACTIONS.conversationResolve.resource,
    action: CONSOLE_WRITE_ACTIONS.conversationResolve.action,
  });

  const pendingNegativeConvs = conversations.filter(
    (c) =>
      c.status === 'PENDING_REVIEW' &&
      c.messages.some((m) => m.feedback === 'negative')
  );

  const activeTickets = tickets.filter((t) => t.status !== 'CANCELLED');

  const handleMarkResolved = async (conversationId: string) => {
    if (resolvingId || !canResolve?.can) {
      return;
    }
    setResolvingId(conversationId);
    try {
      await workbenchStore.resolveConversation(conversationId);
      message.success('已標記為已確認/已排除');
    } catch (error) {
      message.error(describeMutationError(error, '結案失敗，請稍後再試'));
    } finally {
      setResolvingId(null);
    }
  };

  const renderNegativeCards = () => {
    if (pendingNegativeConvs.length === 0) {
      return (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="太棒了！目前沒有待處理的負評回饋"
        />
      );
    }

    return (
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {pendingNegativeConvs.map((conv) => {
          const negMessage =
            conv.messages.find((m) => m.feedback === 'negative') ||
            conv.messages.find((m) => m.sender === 'user');
          const botMessage = conv.messages.find((m) => m.sender === 'bot');
          const citation = botMessage?.citations?.[0];

          return (
            <Card
              key={conv.id}
              size="small"
              hoverable
              className="teams-card-hover"
              style={{
                borderRadius: 10,
                border: '1px solid #f6ccd2',
                backgroundColor: '#fffdfd',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <Space size="middle">
                    <Tag
                      style={{
                        backgroundColor: '#fdf3f4',
                        color: '#c4314b',
                        borderColor: '#f6ccd2',
                        fontWeight: 600,
                      }}
                      icon={<DislikeOutlined style={{ color: '#c4314b' }} />}
                    >
                      差評投訴
                    </Tag>
                    <Text strong style={{ fontSize: '15px' }}>
                      {conv.reporter_dept} - {conv.reporter_name}
                    </Text>
                    <Text type="secondary" style={{ fontSize: '12px' }}>
                      分機 {conv.reporter_ext} | {conv.started_at}
                    </Text>
                  </Space>
                  <Paragraph style={{ margin: '8px 0 4px 0', fontSize: '14px', color: '#c4314b' }}>
                    <Text strong style={{ color: '#c4314b' }}>同仁反饋：</Text>
                    「{negMessage?.feedback_comment || negMessage?.content}」
                  </Paragraph>

                  {citation && (
                    <div style={{ marginTop: 4 }}>
                      <Text type="secondary" style={{ fontSize: '12px' }}>
                        當時引用依據：
                      </Text>
                      <Tag color="geekblue" style={{ marginLeft: 6 }}>{citation.document_title}</Tag>
                      {citation.is_stale && (
                        <Tag color="warning">文件超過 1 年未更新</Tag>
                      )}
                    </div>
                  )}
                </div>

                <Space size="small" wrap style={{ maxWidth: 360, justifyContent: 'flex-end' }}>
                  {canWriteFaq?.can ? (
                    <Button
                      type="primary"
                      size="small"
                      icon={<ThunderboltOutlined />}
                      onClick={() =>
                        onOpenQuickFaq({
                          question: conv.messages[0]?.content || conv.topic_summary,
                          oldAnswer: botMessage?.content,
                          category: '網路通訊',
                          citationTitle: citation?.document_title,
                          resolveConversationId: conv.id,
                        })
                      }
                      style={{ backgroundColor: '#5b5fc7', borderColor: '#5b5fc7' }}
                    >
                      修訂這筆 FAQ
                    </Button>
                  ) : null}

                  {canEscalate?.can ? (
                    <Button
                      size="small"
                      icon={<FileDoneOutlined />}
                      onClick={() =>
                        onOpenEscalateModal({
                          conversationId: conv.id,
                          reporterName: conv.reporter_name,
                          reporterDept: conv.reporter_dept,
                          reporterExt: conv.reporter_ext,
                          title: conv.topic_summary,
                          chatSnippet: negMessage?.content,
                        })
                      }
                      style={{ borderColor: '#6264a7', color: '#6264a7' }}
                    >
                      轉立 IT 報修單
                    </Button>
                  ) : null}

                  <Button
                    size="small"
                    type="text"
                    icon={<EyeOutlined />}
                    onClick={() => onViewConversation(conv.id)}
                  >
                    檢視對話
                  </Button>

                  {canResolve?.can ? (
                    <Button
                      size="small"
                      type="text"
                      icon={<CheckOutlined />}
                      loading={resolvingId === conv.id}
                      disabled={resolvingId !== null && resolvingId !== conv.id}
                      onClick={() => {
                        void handleMarkResolved(conv.id);
                      }}
                    >
                      標記已處理
                    </Button>
                  ) : null}
                </Space>
              </div>
            </Card>
          );
        })}
      </Space>
    );
  };

  const renderGapCards = () => {
    if (gaps.length === 0) {
      return (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="目前沒有高頻知識缺口"
        />
      );
    }

    return (
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {gaps.map((gap) => (
          <Card
            key={gap.id}
            size="small"
            hoverable
            style={{
              borderRadius: 8,
              border: '1px solid #ffe58f',
              backgroundColor: '#fffdf5',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <Space size="middle">
                  <Tag color="warning" icon={<QuestionCircleOutlined />}>
                    知識盲區 (重複詢問 {gap.frequency} 次)
                  </Tag>
                  <Tag color="geekblue">{gap.category}</Tag>
                  <Text type="secondary" style={{ fontSize: '12px' }}>
                    {gap.detected_at}
                  </Text>
                </Space>
                <div style={{ marginTop: 8 }}>
                  <Text strong style={{ fontSize: '14px' }}>
                    高頻未解答痛點：{gap.cluster_query}
                  </Text>
                  <div style={{ marginTop: 4 }}>
                    <Text type="secondary" style={{ fontSize: '12px' }}>
                      同仁常見問法範例：{gap.sample_conversations.join(' / ')}
                    </Text>
                  </div>
                </div>
              </div>

              {canWriteFaq?.can ? (
                <Button
                  type="primary"
                  size="small"
                  icon={<ThunderboltOutlined />}
                  onClick={() =>
                    onOpenQuickFaq({
                      question: gap.sample_conversations[0] || gap.cluster_query,
                      category: gap.category,
                    })
                  }
                >
                  為此缺口建立 FAQ
                </Button>
              ) : null}
            </div>
          </Card>
        ))}
      </Space>
    );
  };

  const renderTicketCards = () => {
    if (activeTickets.length === 0) {
      return (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="目前尚無轉派之 IT 工單"
        />
      );
    }

    return (
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {activeTickets.map((ticket) => (
          <Card key={ticket.id} size="small" hoverable style={{ borderRadius: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <Space size="middle">
                  <Tag color="purple">{ticket.ticket_number}</Tag>
                  <Tag color={ticket.status === 'RESOLVED' ? 'success' : 'processing'}>
                    {ticket.status === 'RESOLVED' ? '已結案 🟢' : '處理中 🟡'}
                  </Tag>
                  <Text strong>{ticket.title}</Text>
                </Space>
                <div style={{ marginTop: 6 }}>
                  <Text type="secondary" style={{ fontSize: '12px' }}>
                    報修同仁：{ticket.reporter_dept} - {ticket.reporter_name} (分機 {ticket.reporter_ext}) | 負責組別：{ticket.assigned_team} ({ticket.assigned_agent || '待指派'}) | 更新：{ticket.updated_at}
                  </Text>
                </div>
              </div>

              <Space size="small">
                {ticket.conversation_id && (
                  <Button
                    size="small"
                    icon={<EyeOutlined />}
                    onClick={() => onViewConversation(ticket.conversation_id!)}
                  >
                    檢視原始對話
                  </Button>
                )}
                <Button
                  size="small"
                  type="primary"
                  ghost
                  onClick={() => onViewTicket(ticket)}
                >
                  檢視工單詳情
                </Button>
              </Space>
            </div>
          </Card>
        ))}
      </Space>
    );
  };

  const renderRecentFixes = () => {
    if (faqs.length === 0) {
      return (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="目前尚無快修紀錄"
        />
      );
    }

    return (
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {faqs.slice(0, 5).map((faq) => (
          <Card key={faq.id} size="small" hoverable style={{ borderRadius: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <Space size="middle">
                  <Tag color="success" icon={<CheckCircleOutlined />}>
                    已上線生效
                  </Tag>
                  <Tag color="blue">{faq.category}</Tag>
                  <Text strong>{faq.questions[0]}</Text>
                </Space>
                <Paragraph
                  ellipsis={{ rows: 1 }}
                  style={{ margin: '6px 0 0 0', color: '#595959', fontSize: '13px' }}
                >
                  標準解答：{faq.answer}
                </Paragraph>
              </div>
              <Text type="secondary" style={{ fontSize: '12px', whiteSpace: 'nowrap' }}>
                {faq.updated_at} ({faq.updated_by || '系統'})
              </Text>
            </div>
          </Card>
        ))}
      </Space>
    );
  };

  const tabItems = [
    {
      key: 'negative',
      label: (
        <Space size={6}>
          <DislikeOutlined style={{ color: '#c4314b' }} />
          <span>待處理負評</span>
          <Badge
            count={pendingNegativeConvs.length}
            overflowCount={99}
            style={{ backgroundColor: '#c4314b' }}
          />
        </Space>
      ),
      children: renderNegativeCards(),
    },
    {
      key: 'gaps',
      label: (
        <Space size={6}>
          <QuestionCircleOutlined style={{ color: '#b78800' }} />
          <span>知識缺口</span>
          <Badge
            count={gaps.length}
            style={{ backgroundColor: '#b78800' }}
          />
        </Space>
      ),
      children: renderGapCards(),
    },
    {
      key: 'tickets',
      label: (
        <Space size={6}>
          <FileDoneOutlined style={{ color: '#5b5fc7' }} />
          <span>追蹤已轉派工單</span>
          <Badge
            count={activeTickets.length}
            style={{ backgroundColor: '#5b5fc7' }}
          />
        </Space>
      ),
      children: renderTicketCards(),
    },
    {
      key: 'recent',
      label: (
        <Space size={6}>
          <CheckCircleOutlined style={{ color: '#107c41' }} />
          <span>歷史快修紀錄</span>
        </Space>
      ),
      children: renderRecentFixes(),
    },
  ];

  return (
    <Card
      title={
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <Text strong style={{ fontSize: '16px' }}>
              📋 今日待辦工作箱 (Action Inbox)
            </Text>
            <Text type="secondary" style={{ fontSize: '13px', marginLeft: 12 }}>
              拒絕繁瑣公文簽呈，直接點擊秒修或開單
            </Text>
          </div>
        </div>
      }
      style={{ borderRadius: 8, marginTop: 16 }}
    >
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={tabItems}
      />
    </Card>
  );
};
