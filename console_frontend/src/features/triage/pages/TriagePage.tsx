import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Row, Col, Typography, Segmented } from 'antd';
import { TriageQueue } from '../components/TriageQueue';
import { ConversationStream } from '../components/ConversationStream';
import { TriageActionPanel } from '../components/TriageActionPanel';
import { QuickFaqDrawer, QuickFaqInitialData } from '../../dashboard/components/QuickFaqDrawer';
import { EscalateTicketModal, EscalateTicketInitialData } from '../../dashboard/components/EscalateTicketModal';
import { workbenchStore } from '../../../shared/api/workbenchStore';
import { WorkbenchLoadErrorBanner } from '../../../shared/ui/WorkbenchLoadErrorBanner';
import { ConversationDetail } from '../../../shared/api/types';

const { Title, Text } = Typography;

type MobilePane = 'queue' | 'stream' | 'actions';

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
  const [conversationsLoaded, setConversationsLoaded] = useState(
    workbenchStore.isDomainLoaded('conversations'),
  );
  const [conversationsError, setConversationsError] = useState<string | undefined>(
    workbenchStore.getDomainErrors().conversations,
  );
  const [mobilePane, setMobilePane] = useState<MobilePane>('queue');

  const [quickFaqOpen, setQuickFaqOpen] = useState<boolean>(false);
  const [quickFaqData, setQuickFaqData] = useState<QuickFaqInitialData | null>(null);

  const [escalateOpen, setEscalateOpen] = useState<boolean>(false);
  const [escalateData, setEscalateData] = useState<EscalateTicketInitialData | null>(null);

  useEffect(() => {
    void workbenchStore.ensureDomains(['conversations']);
    const unsubscribe = workbenchStore.subscribe(() => {
      const updated = workbenchStore.getConversations();
      setConversations(updated);
      setSelectedId((prev) => prev || (updated.length > 0 ? updated[0].id : null));
      setConversationsLoaded(workbenchStore.isDomainLoaded('conversations'));
      setConversationsError(workbenchStore.getDomainErrors().conversations);
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
    setMobilePane('stream');
    setSearchParams((prev) => {
      prev.set('conversationId', id);
      return prev;
    });
  };

  const selectedConversation = conversations.find((c) => c.id === selectedId) || null;
  const queueEmptyMessage =
    conversationsError && !conversationsLoaded
      ? `無法載入對話清單：${conversationsError}`
      : conversationsLoaded && conversations.length === 0
        ? '目前沒有待分診對話'
        : undefined;

  return (
    <div>
      <WorkbenchLoadErrorBanner domains={['conversations']} />
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          對話重播與負評分診台
        </Title>
        <Text type="secondary" style={{ fontSize: '13px' }}>
          Teams 對話還原 · 引用依據透明化 · 根因標記 · FAQ 修補與工單轉派
        </Text>
      </div>

      <div style={{ marginBottom: 12 }} className="triage-mobile-pane-switch">
        <Segmented
          block
          value={mobilePane}
          onChange={(value) => setMobilePane(value as MobilePane)}
          options={[
            { label: '佇列', value: 'queue' },
            { label: '對話', value: 'stream' },
            { label: '處置', value: 'actions' },
          ]}
        />
      </div>

      <Row gutter={[16, 16]} style={{ minHeight: 'min(70vh, 720px)' }}>
        <Col
          xs={24}
          md={7}
          style={{
            minHeight: 320,
            display: mobilePane === 'queue' ? undefined : undefined,
          }}
          className={mobilePane === 'queue' ? 'triage-pane-visible' : 'triage-pane-hidden-xs'}
        >
          <TriageQueue
            conversations={conversations}
            selectedId={selectedId}
            onSelect={handleSelectConversation}
            filterTopic={filterParam}
            emptyMessage={queueEmptyMessage}
            isLoading={!conversationsLoaded && !conversationsError}
          />
        </Col>

        <Col
          xs={24}
          md={11}
          style={{ minHeight: 320 }}
          className={mobilePane === 'stream' ? 'triage-pane-visible' : 'triage-pane-hidden-xs'}
        >
          <ConversationStream conversation={selectedConversation} />
        </Col>

        <Col
          xs={24}
          md={6}
          style={{ minHeight: 320 }}
          className={mobilePane === 'actions' ? 'triage-pane-visible' : 'triage-pane-hidden-xs'}
        >
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

      <QuickFaqDrawer
        open={quickFaqOpen}
        onClose={() => setQuickFaqOpen(false)}
        initialData={quickFaqData}
      />

      <EscalateTicketModal
        open={escalateOpen}
        onClose={() => setEscalateOpen(false)}
        initialData={escalateData}
      />

      <style>{`
        .triage-mobile-pane-switch { display: block; }
        @media (min-width: 768px) {
          .triage-mobile-pane-switch { display: none; }
          .triage-pane-hidden-xs { display: block !important; }
        }
        @media (max-width: 767px) {
          .triage-pane-hidden-xs { display: none !important; }
          .triage-pane-visible { display: block !important; }
        }
      `}</style>
    </div>
  );
};
