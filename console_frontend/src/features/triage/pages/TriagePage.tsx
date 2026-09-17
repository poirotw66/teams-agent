import React, { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Row, Col, Typography } from 'antd';
import { TriageQueue } from '../components/TriageQueue';
import { ConversationStream } from '../components/ConversationStream';
import { TriageActionPanel } from '../components/TriageActionPanel';
import { QuickFaqDrawer, QuickFaqInitialData } from '../../dashboard/components/QuickFaqDrawer';
import { EscalateTicketModal, EscalateTicketInitialData } from '../../dashboard/components/EscalateTicketModal';
import { workbenchStore } from '../../../shared/api/workbenchStore';
import { ConversationDetail } from '../../../shared/api/types';

const { Title, Text } = Typography;

export const TriagePage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const convIdParam = searchParams.get('conversationId');
  const filterParam = searchParams.get('filter');

  const [conversations, setConversations] = useState<ConversationDetail[]>(
    workbenchStore.getConversations()
  );
  const [selectedId, setSelectedId] = useState<string | null>(
    convIdParam || (conversations.length > 0 ? conversations[0].id : null)
  );

  const [quickFaqOpen, setQuickFaqOpen] = useState<boolean>(false);
  const [quickFaqData, setQuickFaqData] = useState<QuickFaqInitialData | null>(null);

  const [escalateOpen, setEscalateOpen] = useState<boolean>(false);
  const [escalateData, setEscalateData] = useState<EscalateTicketInitialData | null>(null);

  useEffect(() => {
    const unsubscribe = workbenchStore.subscribe(() => {
      const updated = workbenchStore.getConversations();
      setConversations(updated);
      setSelectedId((prev) => prev || (updated.length > 0 ? updated[0].id : null));
    });
    return unsubscribe;
  }, []);

  useEffect(() => {
    if (convIdParam) {
      setSelectedId(convIdParam);
    }
  }, [convIdParam]);

  const handleSelectConversation = (id: string) => {
    setSelectedId(id);
    setSearchParams((prev) => {
      prev.set('conversationId', id);
      return prev;
    });
  };

  const selectedConversation = conversations.find((c) => c.id === selectedId) || null;

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          對話重播與負評分診台
        </Title>
        <Text type="secondary" style={{ fontSize: '13px' }}>
          Teams 對話還原 · 引用依據透明化 · 4大根因標記 · 10秒修補與工單轉派
        </Text>
      </div>

      <Row gutter={16} style={{ height: '760px' }}>
        {/* Left: Queue (28%) */}
        <Col xs={24} md={7} style={{ height: '100%' }}>
          <TriageQueue
            conversations={conversations}
            selectedId={selectedId}
            onSelect={handleSelectConversation}
            filterTopic={filterParam}
          />
        </Col>

        {/* Middle: Chat Stream (44%) */}
        <Col xs={24} md={11} style={{ height: '100%' }}>
          <ConversationStream conversation={selectedConversation} />
        </Col>

        {/* Right: Actions (28%) */}
        <Col xs={24} md={6} style={{ height: '100%' }}>
          <TriageActionPanel
            conversation={selectedConversation}
            onOpenQuickFaq={(data) => {
              setQuickFaqData(data);
              setQuickFaqOpen(true);
            }}
            onOpenEscalateModal={(data) => {
              setEscalateData(data);
              setEscalateOpen(true);
            }}
          />
        </Col>
      </Row>

      {/* Slide-over FAQ Drawer */}
      <QuickFaqDrawer
        open={quickFaqOpen}
        onClose={() => setQuickFaqOpen(false)}
        initialData={quickFaqData}
      />

      {/* Escalate to Ticket Modal */}
      <EscalateTicketModal
        open={escalateOpen}
        onClose={() => setEscalateOpen(false)}
        initialData={escalateData}
      />
    </div>
  );
};
