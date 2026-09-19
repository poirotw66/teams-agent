import {
  DashboardKpiMetrics,
  SpikeAlertItem,
  TopFrequentTopic,
  KnowledgeBlindSpot,
  ConversationDetail,
  ItTicketItem,
  FaqItem,
  ManualDocumentItem,
  IngestionStage,
  KnowledgeGapItem,
} from "../types";
import {
  initialDashboardKpi,
  initialSpikeAlert,
  initialTopTopics,
  initialBlindSpots,
  initialConversations,
  initialTickets,
  initialFaqs,
  initialDocuments,
  initialKnowledgeGaps,
} from "../mockData";
import {
  postConversationAction,
  fetchConversations,
} from "./conversationsApi";
import {
  deleteDocumentRequest,
  decideDocumentReviewRequest,
  fetchLegacyDocuments,
  fetchPortalDocumentList,
  mergeLegacyAndPortalDocuments,
  postPublishDocument,
  previewDocumentChunks,
  resolvePublishVersionId,
  submitDocumentReviewRequest,
  uploadDocumentViaPortal,
} from "./documentsApi";
import { deleteFaqRequest, fetchFaqs, postFaq } from "./faqsApi";
import { fetchOverview, postBroadcast } from "./overviewApi";
import { ChunkingProfile } from "./types";
import { fetchTickets, postTicket } from "./ticketsApi";

class WorkbenchStore {
  private kpis: DashboardKpiMetrics = { ...initialDashboardKpi };
  private spikeAlert: SpikeAlertItem | null = initialSpikeAlert;
  private topTopics: TopFrequentTopic[] = [...initialTopTopics];
  private blindSpots: KnowledgeBlindSpot[] = [...initialBlindSpots];
  private conversations: ConversationDetail[] = [...initialConversations];
  private tickets: ItTicketItem[] = [...initialTickets];
  private faqs: FaqItem[] = [...initialFaqs];
  private documents: ManualDocumentItem[] = [...initialDocuments];
  private gaps: KnowledgeGapItem[] = [...initialKnowledgeGaps];
  private listeners: Set<() => void> = new Set();
  private isLoaded: boolean = false;
  private loading: boolean = false;
  private loadStarted: boolean = false;

  public subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    this.ensureLoaded();
    listener();
    return () => this.listeners.delete(listener);
  }

  /** Start the first fetch when a UI surface actually subscribes. */
  public ensureLoaded(): void {
    if (this.isLoaded || this.loadStarted) {
      return;
    }
    this.loadStarted = true;
    this.loadAll().catch((err) => {
      this.loadStarted = false;
      console.warn("Workbench data load failed:", err);
    });
  }

  private notify(): void {
    for (const listener of this.listeners) {
      listener();
    }
  }

  public getKpis(): DashboardKpiMetrics {
    return { ...this.kpis };
  }

  public getSpikeAlert(): SpikeAlertItem | null {
    return this.spikeAlert ? { ...this.spikeAlert } : null;
  }

  public getTopTopics(): TopFrequentTopic[] {
    return [...this.topTopics];
  }

  public getBlindSpots(): KnowledgeBlindSpot[] {
    return [...this.blindSpots];
  }

  public getConversations(): ConversationDetail[] {
    return [...this.conversations];
  }

  public getConversationById(id: string): ConversationDetail | undefined {
    return this.conversations.find((c) => c.id === id);
  }

  public getTickets(): ItTicketItem[] {
    return [...this.tickets];
  }

  public getFaqs(): FaqItem[] {
    return [...this.faqs];
  }

  public getDocuments(): ManualDocumentItem[] {
    return [...this.documents];
  }

  public getKnowledgeGaps(): KnowledgeGapItem[] {
    return [...this.gaps];
  }

  public getIsLoaded(): boolean {
    return this.isLoaded;
  }

  public getIsLoading(): boolean {
    return this.loading;
  }

  public async loadOverview(): Promise<void> {
    try {
      const data = await fetchOverview();
      if (data.kpis) {
        this.kpis = { ...this.kpis, ...data.kpis };
      }
      if (data.spikeAlert !== undefined) {
        this.spikeAlert = data.spikeAlert;
      }
      if (Array.isArray(data.topTopics)) {
        this.topTopics = data.topTopics;
      }
      if (Array.isArray(data.blindSpots)) {
        this.blindSpots = data.blindSpots;
      }
      if (Array.isArray(data.gaps)) {
        this.gaps = data.gaps;
      }
      this.notify();
    } catch (err) {
      console.error("Failed to load overview:", err);
    }
  }

  public async loadConversations(): Promise<void> {
    try {
      const items = await fetchConversations();
      if (Array.isArray(items)) {
        this.conversations = items;
        this.notify();
      }
    } catch (err) {
      console.error("Failed to load conversations:", err);
    }
  }

  public async loadFaqs(): Promise<void> {
    try {
      const items = await fetchFaqs();
      if (Array.isArray(items)) {
        this.faqs = items;
        this.notify();
      }
    } catch (err) {
      console.error("Failed to load FAQs:", err);
    }
  }

  public async loadDocuments(): Promise<void> {
    try {
      const [legacyResult, portalResult] = await Promise.allSettled([
        fetchLegacyDocuments(),
        fetchPortalDocumentList(),
      ]);
      const legacyDocuments =
        legacyResult.status === "fulfilled" && Array.isArray(legacyResult.value)
          ? legacyResult.value
          : [];
      const portalList =
        portalResult.status === "fulfilled" ? portalResult.value : null;
      this.documents = mergeLegacyAndPortalDocuments(
        legacyDocuments,
        portalList,
      );
      this.notify();
    } catch (err) {
      console.error("Failed to load documents:", err);
    }
  }

  public async loadTickets(): Promise<void> {
    try {
      const items = await fetchTickets();
      if (Array.isArray(items)) {
        this.tickets = items;
        this.notify();
      }
    } catch (err) {
      console.error("Failed to load tickets:", err);
    }
  }

  public async loadAll(): Promise<void> {
    this.loading = true;
    try {
      await Promise.allSettled([
        this.loadOverview(),
        this.loadConversations(),
        this.loadFaqs(),
        this.loadDocuments(),
        this.loadTickets(),
      ]);
      this.isLoaded = true;
    } finally {
      this.loading = false;
      this.notify();
    }
  }

  public async quickSaveFaq(params: {
    id?: string;
    question: string;
    answer: string;
    category: string;
    resolveConversationId?: string;
  }): Promise<FaqItem> {
    const saved = await postFaq(params);

    const existingIndex = this.faqs.findIndex((f) => f.id === saved.id);
    if (existingIndex >= 0) {
      this.faqs[existingIndex] = saved;
    } else {
      this.faqs.unshift(saved);
    }

    if (params.resolveConversationId) {
      const conv = this.conversations.find(
        (c) => c.id === params.resolveConversationId,
      );
      if (conv) {
        conv.status = "RESOLVED";
      }
    }

    this.notify();
    this.loadAll().catch(() => {});
    return saved;
  }

  public async escalateTicket(params: {
    conversationId?: string;
    title: string;
    reporterName: string;
    reporterDept: string;
    reporterExt?: string;
    category: "HARDWARE" | "ACCESS" | "NETWORK" | "SOFTWARE";
    assignedTeam: string;
    notes?: string;
  }): Promise<ItTicketItem> {
    const newTicket = await postTicket(params);

    this.tickets.unshift(newTicket);
    this.kpis.escalated_ticket_count += 1;

    if (params.conversationId) {
      const conv = this.conversations.find(
        (c) => c.id === params.conversationId,
      );
      if (conv) {
        conv.status = "ESCALATED_TICKET";
        conv.associated_ticket_id = newTicket.ticket_number;
        conv.messages.push({
          id: `msg-sys-${Date.now()}`,
          sender: "system",
          content: `已成功轉派開立 IT 工單 [${newTicket.ticket_number}]（指派：${params.assignedTeam}）`,
          timestamp: "剛剛",
        });
      }
    }

    this.notify();
    this.loadTickets().catch(() => {});
    return newTicket;
  }

  public async setSpikeBroadcast(
    message: string,
    durationHours: number = 2,
  ): Promise<void> {
    await postBroadcast(message, durationHours);

    if (this.spikeAlert) {
      const expires = new Date(
        Date.now() + durationHours * 3600 * 1000,
      ).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      });
      this.spikeAlert.active_broadcast = {
        message,
        expires_at: `${expires} (有效 ${durationHours} 小時)`,
      };
      this.notify();
    }
    this.loadOverview().catch(() => {});
  }

  public dismissSpikeAlert(): void {
    if (this.spikeAlert) {
      this.spikeAlert.is_active = false;
      this.notify();
    }
  }

  public async resolveConversation(conversationId: string): Promise<void> {
    const conv = this.conversations.find((c) => c.id === conversationId);
    if (conv) {
      conv.status = "RESOLVED";
      if (this.kpis.urgent_attention_count > 0) {
        this.kpis.urgent_attention_count -= 1;
      }
      this.notify();
    }

    await postConversationAction(conversationId, {
      action: "resolve",
    }).catch((err) => {
      console.error("Failed to resolve conversation on server:", err);
    });
  }

  public async setRootCause(
    conversationId: string,
    cause:
      | "OUTDATED_DOC"
      | "MISSING_KNOWLEDGE"
      | "MISUNDERSTOOD"
      | "HARDWARE_TICKET",
  ): Promise<void> {
    const conv = this.conversations.find((c) => c.id === conversationId);
    if (conv) {
      conv.root_cause = cause;
      this.notify();
    }

    await postConversationAction(conversationId, {
      action: "root_cause",
      root_cause: cause,
    }).catch((err) => {
      console.error("Failed to update root cause on server:", err);
    });
  }

  public async uploadDocument(params: {
    file: File;
    title: string;
    category: string;
    version: string;
    profile?: ChunkingProfile;
    onProgress?: (stage: IngestionStage) => void;
  }): Promise<ManualDocumentItem> {
    const newDoc = await uploadDocumentViaPortal(params);
    this.documents.unshift(newDoc);
    this.notify();
    return newDoc;
  }

  public async previewDocument(
    document: ManualDocumentItem,
    profile: ChunkingProfile = "AUTO",
  ): Promise<ManualDocumentItem> {
    const updated = await previewDocumentChunks(document, profile);
    this.notify();
    return updated;
  }

  public async submitDocumentReview(
    documentId: string,
    reason: string,
  ): Promise<void> {
    await submitDocumentReviewRequest(documentId, reason);
    await this.loadDocuments();
  }

  public async decideDocumentReview(
    documentId: string,
    decision: "APPROVED" | "CHANGES_REQUESTED",
    comment: string,
  ): Promise<void> {
    await decideDocumentReviewRequest(documentId, decision, comment);
    await this.loadDocuments();
  }

  public async publishDocument(
    documentId: string,
    reason: string,
  ): Promise<void> {
    const versionId = await resolvePublishVersionId(documentId);
    const document = this.documents.find((item) => item.id === documentId);
    if (document) {
      document.status = "PUBLISHING";
      this.notify();
    }
    try {
      await postPublishDocument(documentId, versionId, reason);
    } finally {
      await this.loadDocuments();
    }
  }

  public async deleteDocument(documentId: string): Promise<void> {
    await deleteDocumentRequest(documentId);
    this.documents = this.documents.filter((d) => d.id !== documentId);
    this.notify();
  }

  public async deleteFaq(faqId: string): Promise<void> {
    await deleteFaqRequest(faqId);
    this.faqs = this.faqs.filter((f) => f.id !== faqId);
    this.notify();
  }
}

export const workbenchStore = new WorkbenchStore();
