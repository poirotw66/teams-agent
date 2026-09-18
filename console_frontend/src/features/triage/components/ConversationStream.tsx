import React from 'react';
import { Avatar, Card, Space, Tag, Typography } from 'antd';
import { UserOutlined } from '@ant-design/icons';
import { ConversationDetail } from '../../../shared/api/types';
import { CitationDrawer } from './conversationStream/CitationDrawer';
import { MessageBubble } from './conversationStream/MessageBubble';
import { enrichMessageMarkdown } from './conversationStream/enrichMessageMarkdown';
import { useCitationPreview } from './conversationStream/useCitationPreview';

export { enrichMessageMarkdown };

const { Text } = Typography;

interface ConversationStreamProps {
  conversation: ConversationDetail | null;
}

export const ConversationStream: React.FC<ConversationStreamProps> = ({
  conversation,
}) => {
  const {
    selectedCitation,
    drawerOpen,
    loadingPreview,
    openCitation,
    closeDrawer,
    selectCitationByIdentifier,
    handleCopyPath,
    setDrawerOpen,
  } = useCitationPreview();

  if (!conversation) {
    return (
      <Card
        style={{
          borderRadius: 8,
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Text type="secondary">請從左側佇列中選擇一筆對話進行檢視與分診</Text>
      </Card>
    );
  }

  return (
    <>
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
          {conversation.messages.map((msg) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              onSelectCitation={selectCitationByIdentifier}
              onOpenCitation={openCitation}
            />
          ))}
        </div>
      </Card>

      <CitationDrawer
        open={drawerOpen}
        citation={selectedCitation}
        loadingPreview={loadingPreview}
        onClose={closeDrawer}
        onDismiss={() => setDrawerOpen(false)}
        onCopyPath={handleCopyPath}
      />
    </>
  );
};
