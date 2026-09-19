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
import { ConversationsSlice } from "./conversationsSlice";
import { DocumentsSlice } from "./documentsSlice";
import { FaqsSlice } from "./faqsSlice";
import { OverviewSlice } from "./overviewSlice";
import {
  createReloadHooksPlaceholder,
  StoreCore,
  WorkbenchSliceContext,
} from "./storeCore";
import { TicketsSlice } from "./ticketsSlice";
import { ChunkingProfile } from "./types";

/**
 * Thin facade that preserves the historical workbenchStore public API.
 * Domain behavior lives in cohesive slices that share mutable state + notify.
 */
class WorkbenchStore {
  private readonly core = new StoreCore();
  private readonly overview: OverviewSlice;
  private readonly conversations: ConversationsSlice;
  private readonly tickets: TicketsSlice;
  private readonly faqs: FaqsSlice;
  private readonly documents: DocumentsSlice;

  constructor() {
    const reloads = createReloadHooksPlaceholder();
    const ctx: WorkbenchSliceContext = {
      state: this.core.state,
      notify: () => this.core.notify(),
      reloads,
    };

    this.overview = new OverviewSlice(ctx);
    this.conversations = new ConversationsSlice(ctx);
    this.tickets = new TicketsSlice(ctx);
    this.faqs = new FaqsSlice(ctx);
    this.documents = new DocumentsSlice(ctx);

    reloads.loadAll = () => this.loadAll();
    reloads.loadOverview = () => this.overview.loadOverview();
    reloads.loadTickets = () => this.tickets.loadTickets();
    reloads.loadDocuments = () => this.documents.loadDocuments();

    this.core.setLoadAllHandler(() => this.loadAll());
  }

  public subscribe(listener: () => void): () => void {
    return this.core.subscribe(listener);
  }

  public ensureLoaded(): void {
    this.core.ensureLoaded();
  }

  public getKpis(): DashboardKpiMetrics {
    return this.overview.getKpis();
  }

  public getSpikeAlert(): SpikeAlertItem | null {
    return this.overview.getSpikeAlert();
  }

  public getTopTopics(): TopFrequentTopic[] {
    return this.overview.getTopTopics();
  }

  public getBlindSpots(): KnowledgeBlindSpot[] {
    return this.overview.getBlindSpots();
  }

  public getConversations(): ConversationDetail[] {
    return this.conversations.getConversations();
  }

  public getConversationById(id: string): ConversationDetail | undefined {
    return this.conversations.getConversationById(id);
  }

  public getTickets(): ItTicketItem[] {
    return this.tickets.getTickets();
  }

  public getFaqs(): FaqItem[] {
    return this.faqs.getFaqs();
  }

  public getDocuments(): ManualDocumentItem[] {
    return this.documents.getDocuments();
  }

  public getKnowledgeGaps(): KnowledgeGapItem[] {
    return this.overview.getKnowledgeGaps();
  }

  public getIsLoaded(): boolean {
    return this.core.getIsLoaded();
  }

  public getIsLoading(): boolean {
    return this.core.getIsLoading();
  }

  public async loadOverview(): Promise<void> {
    return this.overview.loadOverview();
  }

  public async loadConversations(): Promise<void> {
    return this.conversations.loadConversations();
  }

  public async loadFaqs(): Promise<void> {
    return this.faqs.loadFaqs();
  }

  public async loadDocuments(): Promise<void> {
    return this.documents.loadDocuments();
  }

  public async loadTickets(): Promise<void> {
    return this.tickets.loadTickets();
  }

  public async loadAll(): Promise<void> {
    this.core.beginLoadAll();
    try {
      await Promise.allSettled([
        this.loadOverview(),
        this.loadConversations(),
        this.loadFaqs(),
        this.loadDocuments(),
        this.loadTickets(),
      ]);
      this.core.markLoaded();
    } finally {
      this.core.endLoadAll();
    }
  }

  public async quickSaveFaq(params: {
    id?: string;
    question: string;
    answer: string;
    category: string;
    resolveConversationId?: string;
  }): Promise<FaqItem> {
    return this.faqs.quickSaveFaq(params);
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
    return this.tickets.escalateTicket(params);
  }

  public async setSpikeBroadcast(
    message: string,
    durationHours: number = 2,
  ): Promise<void> {
    return this.overview.setSpikeBroadcast(message, durationHours);
  }

  public dismissSpikeAlert(): void {
    this.overview.dismissSpikeAlert();
  }

  public async resolveConversation(conversationId: string): Promise<void> {
    return this.conversations.resolveConversation(conversationId);
  }

  public async setRootCause(
    conversationId: string,
    cause:
      | "OUTDATED_DOC"
      | "MISSING_KNOWLEDGE"
      | "MISUNDERSTOOD"
      | "HARDWARE_TICKET",
  ): Promise<void> {
    return this.conversations.setRootCause(conversationId, cause);
  }

  public async uploadDocument(params: {
    file: File;
    title: string;
    category: string;
    version: string;
    profile?: ChunkingProfile;
    onProgress?: (stage: IngestionStage) => void;
  }): Promise<ManualDocumentItem> {
    return this.documents.uploadDocument(params);
  }

  public async previewDocument(
    document: ManualDocumentItem,
    profile: ChunkingProfile = "AUTO",
  ): Promise<ManualDocumentItem> {
    return this.documents.previewDocument(document, profile);
  }

  public async submitDocumentReview(
    documentId: string,
    reason: string,
  ): Promise<void> {
    return this.documents.submitDocumentReview(documentId, reason);
  }

  public async decideDocumentReview(
    documentId: string,
    decision: "APPROVED" | "CHANGES_REQUESTED",
    comment: string,
  ): Promise<void> {
    return this.documents.decideDocumentReview(documentId, decision, comment);
  }

  public async publishDocument(
    documentId: string,
    reason: string,
  ): Promise<void> {
    return this.documents.publishDocument(documentId, reason);
  }

  public async deleteDocument(documentId: string): Promise<void> {
    return this.documents.deleteDocument(documentId);
  }

  public async deleteFaq(faqId: string): Promise<void> {
    return this.faqs.deleteFaq(faqId);
  }
}

export const workbenchStore = new WorkbenchStore();
