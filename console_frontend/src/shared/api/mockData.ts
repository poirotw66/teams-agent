/** Initial empty defaults for workbench data structures.
 * All live data is retrieved from real backend APIs.
 */

import {
  DashboardKpiMetrics,
  SpikeAlertItem,
  TopFrequentTopic,
  KnowledgeBlindSpot,
  ConversationDetail,
  ItTicketItem,
  FaqItem,
  ManualDocumentItem,
  KnowledgeGapItem,
} from './types';

export const initialDashboardKpi: DashboardKpiMetrics = {
  total_inquiries_today: 0,
  inquiries_trend_percentage: 0,
  ai_resolution_rate: 0,
  ai_resolved_count: 0,
  escalated_ticket_count: 0,
  satisfaction_rate: 0,
  negative_feedback_count: 0,
  urgent_attention_count: 0,
};

export const initialSpikeAlert: SpikeAlertItem | null = null;
export const initialTopTopics: TopFrequentTopic[] = [];
export const initialBlindSpots: KnowledgeBlindSpot[] = [];
export const initialConversations: ConversationDetail[] = [];
export const initialTickets: ItTicketItem[] = [];
export const initialFaqs: FaqItem[] = [];
export const initialDocuments: ManualDocumentItem[] = [];
export const initialKnowledgeGaps: KnowledgeGapItem[] = [];
