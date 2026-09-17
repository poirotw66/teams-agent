import React from 'react';
import { Card, Space, Typography, Tag, Avatar, Alert, Collapse } from 'antd';
import {
  UserOutlined,
  RobotOutlined,
  DislikeOutlined,
  FileTextOutlined,
  WarningOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';
import { ConversationDetail } from '../../../shared/api/types';

const { Text, Paragraph } = Typography;

interface ConversationStreamProps {
  conversation: ConversationDetail | null;
}

export const ConversationStream: React.FC<ConversationStreamProps> = ({ conversation }) => {
  if (!conversation) {
    return (
      <Card style={{ borderRadius: 8, height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Text type="secondary">請從左側佇列中選擇一筆對話進行檢視與分診</Text>
      </Card>
    );
  }

  return (
    <Card
      title={
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <Space size="middle">
              <Avatar icon={<UserOutlined />} style={{ backgroundColor: '#5B5FC7' }} />
              <div>
                <Text strong style={{ fontSize: '15px' }}>
                  {conversation.reporter_dept} - {conversation.reporter_name}
                </Text>
                <Text type="secondary" style={{ fontSize: '12px', marginLeft: 8 }}>
                  分機：{conversation.reporter_ext || '未提供'} | 開始時間：{conversation.started_at}
                </Text>
              </div>
            </Space>
          </div>
          <Space>
            {conversation.status === 'RESOLVED' && (
              <Tag style={{ backgroundColor: '#EBF6EC', color: '#107C41', borderColor: '#BDE3C4' }}>已結案</Tag>
            )}
            {conversation.status === 'ESCALATED_TICKET' && (
              <Tag style={{ backgroundColor: '#F0F1FA', color: '#5B5FC7', borderColor: '#D1D3E0' }}>
                已轉立工單 [{conversation.associated_ticket_id}]
              </Tag>
            )}
            {conversation.status === 'PENDING_REVIEW' && (
              <Tag style={{ backgroundColor: '#FFF8E6', color: '#B78800', borderColor: '#F5D38A' }}>待排查</Tag>
            )}
          </Space>
        </div>
      }
      style={{ borderRadius: 8, height: '100%', display: 'flex', flexDirection: 'column' }}
      styles={{
        body: {
          padding: '16px',
          flex: 1,
          overflowY: 'auto',
          maxHeight: '720px',
          backgroundColor: '#f8f9fa',
        },
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {conversation.messages.map((msg) => {
          if (msg.sender === 'system') {
            return (
              <div key={msg.id} style={{ textAlign: 'center', margin: '8px 0' }}>
                <Tag color="geekblue" icon={<CheckCircleOutlined />}>
                  {msg.content} · {msg.timestamp}
                </Tag>
              </div>
            );
          }

          const isUser = msg.sender === 'user';

          return (
            <div
              key={msg.id}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: isUser ? 'flex-end' : 'flex-start',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '8px',
                  maxWidth: '85%',
                  flexDirection: isUser ? 'row-reverse' : 'row',
                }}
              >
                <Avatar
                  icon={isUser ? <UserOutlined /> : <RobotOutlined />}
                  style={{
                    backgroundColor: isUser ? '#5b5fc7' : '#4f52b2',
                    flexShrink: 0,
                    marginTop: 4,
                  }}
                />

                <div>
                  <div
                    className={isUser ? 'teams-bubble-user' : 'teams-bubble-bot'}
                    style={{
                      padding: '10px 15px',
                    }}
                  >
                    <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: '14px', color: '#242424' }}>
                      {msg.content}
                    </Paragraph>
                  </div>

                  {/* Negative feedback badge & comment */}
                  {msg.feedback === 'negative' && (
                    <div style={{ marginTop: 6, textAlign: 'right' }}>
                      <Alert
                        type="error"
                        showIcon
                        icon={<DislikeOutlined style={{ color: '#c4314b' }} />}
                        message={
                          <Text style={{ fontSize: '12px', color: '#c4314b' }}>
                            同仁點擊差評投訴：{msg.feedback_comment || '同仁未留備註'}
                          </Text>
                        }
                        style={{ padding: '4px 10px', borderRadius: 6, display: 'inline-block', backgroundColor: '#fdf3f4', borderColor: '#f6ccd2' }}
                      />
                    </div>
                  )}

                  {/* Citations details for bot responses */}
                  {!isUser && msg.citations && msg.citations.length > 0 && (
                    <div style={{ marginTop: 8 }}>
                      <Collapse
                        size="small"
                        ghost
                        defaultActiveKey={['citations']}
                        items={[
                          {
                            key: 'citations',
                            label: (
                              <Space size="small">
                                <FileTextOutlined style={{ color: '#5B5FC7' }} />
                                <Text strong style={{ fontSize: '12px', color: '#5B5FC7' }}>
                                  當時 AI 檢索與引用依據 ({msg.citations.length} 份文件)
                                </Text>
                              </Space>
                            ),
                            children: (
                              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                                {msg.citations.map((cite, idx) => (
                                  <div
                                    key={idx}
                                    style={{
                                      padding: '8px 10px',
                                      backgroundColor: '#fafafa',
                                      border: '1px solid #f0f0f0',
                                      borderRadius: 6,
                                      fontSize: '12px',
                                    }}
                                  >
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                      <Text strong>{cite.document_title}</Text>
                                      <Space>
                                        <Tag color="cyan">相似度 {cite.similarity_score}%</Tag>
                                        {cite.is_stale && (
                                          <Tag color="warning" icon={<WarningOutlined />}>
                                            ⚠️ 超過 1 年未更新
                                          </Tag>
                                        )}
                                      </Space>
                                    </div>
                                    <div style={{ marginTop: 4, color: '#595959' }}>
                                      引用段落：「{cite.snippet}」
                                    </div>
                                    <div style={{ marginTop: 2, color: '#8c8c8c', fontSize: '11px' }}>
                                      最後維護時間：{cite.updated_at}
                                    </div>
                                  </div>
                                ))}
                              </div>
                            ),
                          },
                        ]}
                      />
                    </div>
                  )}

                  <div
                    style={{
                      fontSize: '11px',
                      color: '#8c8c8c',
                      marginTop: 2,
                      textAlign: isUser ? 'right' : 'left',
                    }}
                  >
                    {msg.timestamp}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
};
