import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Typography, Space, Button } from 'antd';
import { ThunderboltOutlined } from '@ant-design/icons';
import { KpiCards } from '../components/KpiCards';
import { SpikeAlertBanner } from '../components/SpikeAlertBanner';
import { ActionInbox } from '../components/ActionInbox';
import { TopDriversPanel } from '../components/TopDriversPanel';
import { QuickFaqDrawer, QuickFaqInitialData } from '../components/QuickFaqDrawer';
import { BroadcastModal } from '../components/BroadcastModal';
import { EscalateTicketModal, EscalateTicketInitialData } from '../components/EscalateTicketModal';
import { workbenchStore } from '../../../shared/api/workbenchStore';
import { WorkbenchLoadErrorBanner } from '../../../shared/ui/WorkbenchLoadErrorBanner';
import {
  DashboardKpiMetrics,
  SpikeAlertItem,
  TopFrequentTopic,
  KnowledgeBlindSpot,
  ConversationDetail,
  ItTicketItem,
  FaqItem,
  KnowledgeGapItem,
} from '../../../shared/api/types';

const { Title, Text } = Typography;

export const DashboardPage: React.FC = () => {
  const navigate = useNavigate();
  const inboxRef = useRef<HTMLDivElement>(null);

  // Reactive store state
  const [metrics, setMetrics] = useState<DashboardKpiMetrics>(workbenchStore.getKpis());
  const [spikeAlert, setSpikeAlert] = useState<SpikeAlertItem | null>(workbenchStore.getSpikeAlert());
  const [topTopics, setTopTopics] = useState<TopFrequentTopic[]>(workbenchStore.getTopTopics());
  const [blindSpots, setBlindSpots] = useState<KnowledgeBlindSpot[]>(workbenchStore.getBlindSpots());
  const [conversations, setConversations] = useState<ConversationDetail[]>(workbenchStore.getConversations());
  const [tickets, setTickets] = useState<ItTicketItem[]>(workbenchStore.getTickets());
  const [faqs, setFaqs] = useState<FaqItem[]>(workbenchStore.getFaqs());
  const [gaps, setGaps] = useState<KnowledgeGapItem[]>(workbenchStore.getKnowledgeGaps());

  // Drawer / Modals state
  const [quickFaqOpen, setQuickFaqOpen] = useState<boolean>(false);
  const [quickFaqData, setQuickFaqData] = useState<QuickFaqInitialData | null>(null);

  const [broadcastOpen, setBroadcastOpen] = useState<boolean>(false);

  const [escalateOpen, setEscalateOpen] = useState<boolean>(false);
  const [escalateData, setEscalateData] = useState<EscalateTicketInitialData | null>(null);

  useEffect(() => {
    const unsubscribe = workbenchStore.subscribe(() => {
      setMetrics(workbenchStore.getKpis());
      setSpikeAlert(workbenchStore.getSpikeAlert());
      setTopTopics(workbenchStore.getTopTopics());
      setBlindSpots(workbenchStore.getBlindSpots());
      setConversations(workbenchStore.getConversations());
      setTickets(workbenchStore.getTickets());
      setFaqs(workbenchStore.getFaqs());
      setGaps(workbenchStore.getKnowledgeGaps());
    });
    return unsubscribe;
  }, []);

  const handleScrollToInbox = () => {
    inboxRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const handleOpenQuickFaq = (data: QuickFaqInitialData) => {
    setQuickFaqData(data);
    setQuickFaqOpen(true);
  };

  const handleOpenGlobalFaq = () => {
    setQuickFaqData(null);
    setQuickFaqOpen(true);
  };

  const handleOpenEscalate = (data: EscalateTicketInitialData) => {
    setEscalateData(data);
    setEscalateOpen(true);
  };

  const handleViewConversation = (conversationId: string) => {
    navigate(`/triage?conversationId=${conversationId}`);
  };

  const handleViewTicket = (ticket: ItTicketItem) => {
    navigate(`/tickets?ticketId=${ticket.id}`);
  };

  const handleSelectCategory = (category: string) => {
    navigate(`/knowledge?category=${encodeURIComponent(category)}`);
  };

  return (
    <div>
      <WorkbenchLoadErrorBanner />
      {/* Top Welcome & Quick Actions */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 20,
        }}
      >
        <div>
          <Title level={4} style={{ margin: 0 }}>
            營運即時儀表板
          </Title>
          <Text type="secondary" style={{ fontSize: '13px' }}>
            早晨態勢掌握 · 突發進線防護 · 10秒直修閉環
          </Text>
        </div>

        <Space>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            onClick={handleOpenGlobalFaq}
            style={{ backgroundColor: '#fa8c16', borderColor: '#fa8c16' }}
          >
            ⚡ 30秒快速新增 FAQ
          </Button>
        </Space>
      </div>

      {/* 1. Morning Pulse KPIs */}
      <KpiCards metrics={metrics} onSelectUrgent={handleScrollToInbox} />

      {/* 2. Spike Alert Banner */}
      <div style={{ marginTop: 16 }}>
        <SpikeAlertBanner
          alert={spikeAlert}
          onViewConversations={(topic) => navigate(`/triage?filter=${encodeURIComponent(topic)}`)}
          onOpenBroadcastModal={() => setBroadcastOpen(true)}
          onDismiss={() => workbenchStore.dismissSpikeAlert()}
        />
      </div>

      {/* 3. Action Inbox */}
      <div ref={inboxRef}>
        <ActionInbox
          conversations={conversations}
          gaps={gaps}
          tickets={tickets}
          faqs={faqs}
          onOpenQuickFaq={handleOpenQuickFaq}
          onOpenEscalateModal={handleOpenEscalate}
          onViewConversation={handleViewConversation}
          onViewTicket={handleViewTicket}
        />
      </div>

      {/* 4. Top Drivers & Knowledge Health */}
      <TopDriversPanel
        topTopics={topTopics}
        blindSpots={blindSpots}
        onSelectCategory={handleSelectCategory}
      />

      {/* Modals & Drawers */}
      <QuickFaqDrawer
        open={quickFaqOpen}
        onClose={() => setQuickFaqOpen(false)}
        initialData={quickFaqData}
      />

      <BroadcastModal
        open={broadcastOpen}
        onClose={() => setBroadcastOpen(false)}
        defaultTopic={spikeAlert?.topic}
      />

      <EscalateTicketModal
        open={escalateOpen}
        onClose={() => setEscalateOpen(false)}
        initialData={escalateData}
      />
    </div>
  );
};
