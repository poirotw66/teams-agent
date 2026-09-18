import React from 'react';
import { Alert, Avatar, Tag, Typography } from 'antd';
import {
  CheckCircleOutlined,
  DislikeOutlined,
  RobotOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { ChatMessage, CitationItem } from '../../../../shared/api/types';
import { BotMessageMarkdown } from './BotMessageMarkdown';
import { CitationList } from './CitationList';

const { Text } = Typography;

interface MessageBubbleProps {
  message: ChatMessage;
  onSelectCitation: (identifier: string, citations?: CitationItem[]) => void;
  onOpenCitation: (cite: CitationItem) => void;
}

export const MessageBubble: React.FC<MessageBubbleProps> = ({
  message: msg,
  onSelectCitation,
  onOpenCitation,
}) => {
  if (msg.sender === 'system') {
    return (
      <div style={{ textAlign: 'center', margin: '8px 0' }}>
        <Tag color="geekblue" icon={<CheckCircleOutlined />}>
          {msg.content} · {msg.timestamp}
        </Tag>
      </div>
    );
  }

  const isUser = msg.sender === 'user';

  return (
    <div
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
          maxWidth: '88%',
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

        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            className={isUser ? 'teams-bubble-user' : 'teams-bubble-bot'}
            style={{
              padding: '12px 16px',
              fontSize: '14px',
              lineHeight: 1.6,
              overflowWrap: 'anywhere',
            }}
          >
            {isUser ? (
              <div style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>
            ) : (
              <BotMessageMarkdown
                content={msg.content}
                citations={msg.citations}
                onSelectCitation={onSelectCitation}
              />
            )}
          </div>

          {msg.feedback === 'negative' && (
            <div style={{ marginTop: 6, textAlign: 'left' }}>
              <Alert
                type="error"
                showIcon
                icon={<DislikeOutlined style={{ color: '#c4314b' }} />}
                message={
                  <Text style={{ fontSize: '12px', color: '#c4314b', fontWeight: 500 }}>
                    同仁回饋：👎 未解決 {msg.feedback_comment ? `（原因：${msg.feedback_comment}）` : '（未留備註）'}
                  </Text>
                }
                style={{
                  padding: '4px 10px',
                  borderRadius: 6,
                  display: 'inline-block',
                  backgroundColor: '#fdf3f4',
                  borderColor: '#f6ccd2',
                }}
              />
            </div>
          )}

          {msg.feedback === 'positive' && (
            <div style={{ marginTop: 6, textAlign: 'left' }}>
              <Tag
                icon={<CheckCircleOutlined style={{ color: '#107C41' }} />}
                style={{
                  backgroundColor: '#EBF6EC',
                  color: '#107C41',
                  borderColor: '#BDE3C4',
                  padding: '2px 8px',
                  borderRadius: 6,
                  fontSize: '12px',
                }}
              >
                同仁回饋：👍 已解決問題
              </Tag>
            </div>
          )}

          {!isUser && msg.citations && msg.citations.length > 0 && (
            <CitationList citations={msg.citations} onOpenCitation={onOpenCitation} />
          )}

          <div
            style={{
              fontSize: '11px',
              color: '#8c8c8c',
              marginTop: 4,
              textAlign: isUser ? 'right' : 'left',
            }}
          >
            {msg.timestamp}
          </div>
        </div>
      </div>
    </div>
  );
};
