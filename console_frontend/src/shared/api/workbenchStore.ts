import {
  DashboardKpiMetrics,
  SpikeAlertItem,
  TopFrequentTopic,
  KnowledgeBlindSpot,
  ConversationDetail,
  ItTicketItem,
  FaqItem,
  ManualDocumentItem,
  ManualChunkItem,
  ManualChunkImage,
  ChunkQualityIssue,
  ChunkQualitySummary,
  IngestionStage,
  KnowledgeGapItem,
} from "./types";
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
} from "./mockData";
import { apiClient } from "./client";

interface OverviewApiResponse {
  kpis: DashboardKpiMetrics;
  spikeAlert: SpikeAlertItem | null;
  topTopics: TopFrequentTopic[];
  blindSpots: KnowledgeBlindSpot[];
  gaps?: KnowledgeGapItem[];
}

interface PortalImportResult {
  mode?: "sync" | "async";
  jobId?: string;
  status?: string;
  result?: PortalImportResult;
  title?: string;
  owner_unit_id?: string;
  effective_at?: string;
  review_due_at?: string;
  audience_type?: "ALL_EMPLOYEES" | "RESTRICTED_GROUPS";
  audience_group_ids?: string[];
  markdown_content?: string;
  assets?: Array<{ filename: string; content_base64: string }>;
  original_asset_token?: string;
  source_type?: "PDF" | "DOCX" | "MARKDOWN_UPLOAD";
  page_count?: number;
  byteSize?: number;
  stage?: IngestionStage;
  error?: string;
  warnings?: string[];
}

interface PortalDocumentRecord {
  document_id: string;
  title: string;
  category: string;
  status: string;
  etag?: string;
  updated_at: string;
  updated_by: string;
  format?: string;
}

interface PortalDocumentList {
  items: PortalDocumentRecord[];
}

interface PortalDocumentDetail {
  document: PortalDocumentRecord;
  draft_version?: {
    version_id: string;
    version_number: number;
    original_asset_name?: string;
    original_asset_size?: number;
  };
  published_version?: {
    version_id: string;
    version_number: number;
    original_asset_name?: string;
    original_asset_size?: number;
  };
}

interface PendingPortalReviewList {
  items: Array<{
    review_id: string;
    document_id: string;
  }>;
}

interface ChunkPreviewResponse {
  documentId: string;
  versionId: string;
  releaseId: string | null;
  profile: ManualDocumentItem["chunking_profile"];
  quality: ChunkQualitySummary;
  chunks: Array<{
    id: string;
    parentId: string;
    neighborIds: string[];
    title: string;
    content: string;
    contentPreview: string;
    tokenCount: number;
    pageStart: number;
    pageEnd: number;
    headingPath: string[];
    contentHash: string;
    parserVersion: string;
    chunkerVersion: string;
    qualityIssues?: ChunkQualityIssue[];
    images?: Array<{
      path: string;
      filename: string;
      alt_text: string;
      content_type: string;
      url: string;
    }>;
  }>;
}

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

  constructor() {
    // Automatically trigger initial load from real backend APIs
    this.loadAll().catch((err) => {
      console.warn("Initial workbench data load failed:", err);
    });
  }

  public subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    listener();
    return () => this.listeners.delete(listener);
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

  // --- Real API Data Fetchers ---

  public async loadOverview(): Promise<void> {
    try {
      const data = await apiClient<OverviewApiResponse>(
        "/api/console/workbench/overview",
      );
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
      const items = await apiClient<ConversationDetail[]>(
        "/api/console/workbench/conversations",
      );
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
      const items = await apiClient<FaqItem[]>("/api/console/workbench/faqs");
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
        apiClient<ManualDocumentItem[]>("/api/console/workbench/documents"),
        apiClient<PortalDocumentList>("/api/knowledge/documents"),
      ]);
      const legacyDocuments =
        legacyResult.status === "fulfilled" && Array.isArray(legacyResult.value)
          ? legacyResult.value
          : [];
      const known = new Map(legacyDocuments.map((item) => [item.id, item]));
      if (portalResult.status === "fulfilled") {
        for (const item of portalResult.value.items) {
          if (item.status === "DISCARDED") {
            known.delete(item.document_id);
            continue;
          }
          const previous = known.get(item.document_id);
          known.set(item.document_id, {
            id: item.document_id,
            title: item.title,
            file_name: previous?.file_name || item.format || "受控文件",
            file_size_bytes: previous?.file_size_bytes || 0,
            version: previous?.version || "草稿",
            version_id: previous?.version_id,
            category: item.category,
            status: this.mapPortalStatus(item.status),
            chunk_count: previous?.chunk_count || 0,
            updated_at: item.updated_at,
            updated_by: item.updated_by,
            chunks: previous?.chunks,
            quality: previous?.quality,
            chunking_profile: previous?.chunking_profile,
          });
        }
      }
      this.documents = [...known.values()];
      this.notify();
    } catch (err) {
      console.error("Failed to load documents:", err);
    }
  }

  public async loadTickets(): Promise<void> {
    try {
      const items = await apiClient<ItTicketItem[]>(
        "/api/console/workbench/tickets",
      );
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

  // --- Real API Actions ---

  // Action: 10-Second Quick FAQ Add / Fix (persisted to faqs.json)
  public async quickSaveFaq(params: {
    id?: string;
    question: string;
    answer: string;
    category: string;
    resolveConversationId?: string;
  }): Promise<FaqItem> {
    const saved = await apiClient<FaqItem>("/api/console/workbench/faqs", {
      method: "POST",
      body: JSON.stringify(params),
    });

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

  // Action: Escalate to IT Ticket (persisted to tickets.json)
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
    const newTicket = await apiClient<ItTicketItem>(
      "/api/console/workbench/tickets",
      {
        method: "POST",
        body: JSON.stringify(params),
      },
    );

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

  // Action: Set Incident Broadcast
  public async setSpikeBroadcast(
    message: string,
    durationHours: number = 2,
  ): Promise<void> {
    await apiClient("/api/console/workbench/broadcast", {
      method: "POST",
      body: JSON.stringify({ message, durationHours }),
    });

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

  // Action: Mark Conversation Resolved
  public async resolveConversation(conversationId: string): Promise<void> {
    const conv = this.conversations.find((c) => c.id === conversationId);
    if (conv) {
      conv.status = "RESOLVED";
      if (this.kpis.urgent_attention_count > 0) {
        this.kpis.urgent_attention_count -= 1;
      }
      this.notify();
    }

    await apiClient(
      `/api/console/workbench/conversations/${encodeURIComponent(conversationId)}/action`,
      {
        method: "POST",
        body: JSON.stringify({ action: "resolve" }),
      },
    ).catch((err) => {
      console.error("Failed to resolve conversation on server:", err);
    });
  }

  // Action: Update Conversation Root Cause
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

    await apiClient(
      `/api/console/workbench/conversations/${encodeURIComponent(conversationId)}/action`,
      {
        method: "POST",
        body: JSON.stringify({ action: "root_cause", root_cause: cause }),
      },
    ).catch((err) => {
      console.error("Failed to update root cause on server:", err);
    });
  }

  // Action: Upload Manual Document (PDF/Word/MD)
  public async uploadDocument(params: {
    file: File;
    title: string;
    category: string;
    version: string;
    profile?: "AUTO" | "SLIDE_DECK" | "MANUAL" | "POLICY";
    onProgress?: (stage: IngestionStage) => void;
  }): Promise<ManualDocumentItem> {
    const extension = params.file.name.split(".").pop()?.toLowerCase();
    const importPath =
      extension === "pdf"
        ? "/api/knowledge/documents/import-pdf?async_mode=auto"
        : extension === "docx"
          ? "/api/knowledge/documents/import-docx"
          : "/api/knowledge/documents/import-markdown";
    const formData = new FormData();
    formData.append("file", params.file);
    const requestId =
      globalThis.crypto?.randomUUID?.() || `${Date.now()}-${params.file.size}`;
    params.onProgress?.("UPLOADED");
    let imported = await apiClient<PortalImportResult>(importPath, {
      method: "POST",
      headers: { "Idempotency-Key": requestId },
      body: formData,
    });
    if (imported.mode === "async" && imported.jobId) {
      imported = await this.waitForIngestion(imported.jobId, params.onProgress);
    }
    if (!imported.markdown_content) {
      throw new Error("解析完成但沒有可審查的文件內容。");
    }
    params.onProgress?.("CHUNK_REVIEW");
    const created = await apiClient<PortalDocumentDetail>(
      "/api/knowledge/documents",
      {
        method: "POST",
        headers: { "Idempotency-Key": requestId },
        body: JSON.stringify({
          title: params.title,
          summary: "",
          category: params.category,
          owner_unit_id: imported.owner_unit_id || "IT Service Desk",
          business_contact: "",
          audience_type: imported.audience_type || "ALL_EMPLOYEES",
          audience_group_ids: imported.audience_group_ids || [],
          effective_at: imported.effective_at,
          review_due_at: imported.review_due_at,
          change_summary: `Imported as ${params.version}`,
          change_reason:
            "Uploaded through the operations workbench for governed review.",
          markdown_content: imported.markdown_content,
          source_type:
            imported.source_type ||
            (extension === "pdf"
              ? "PDF"
              : extension === "docx"
                ? "DOCX"
                : "MARKDOWN_UPLOAD"),
          assets: imported.assets || [],
          original_asset_token: imported.original_asset_token,
        }),
      },
    );
    const preview = await this.fetchChunkPreview(
      created.document.document_id,
      params.profile || "AUTO",
      created.draft_version?.version_id,
    );
    const newDoc: ManualDocumentItem = {
      id: created.document.document_id,
      title: created.document.title,
      file_name: created.draft_version?.original_asset_name || params.file.name,
      file_size_bytes:
        created.draft_version?.original_asset_size || params.file.size,
      version: params.version,
      version_id: preview.versionId,
      category: created.document.category,
      status: "CHUNK_REVIEW",
      ingestion_stage: "CHUNK_REVIEW",
      chunk_count: preview.chunks.length,
      updated_at: created.document.updated_at,
      updated_by: created.document.updated_by,
      chunks: this.mapPreviewChunks(preview.chunks),
      quality: preview.quality,
      chunking_profile: preview.profile,
      ingestion_warnings: imported.warnings || [],
    };
    this.documents.unshift(newDoc);
    this.notify();
    return newDoc;
  }

  public async previewDocument(
    document: ManualDocumentItem,
    profile: "AUTO" | "SLIDE_DECK" | "MANUAL" | "POLICY" = "AUTO",
  ): Promise<ManualDocumentItem> {
    const detail = await apiClient<PortalDocumentDetail>(
      `/api/knowledge/documents/${encodeURIComponent(document.id)}`,
    );
    const versionId =
      detail.draft_version?.version_id || detail.published_version?.version_id;
    const preview = await this.fetchChunkPreview(
      document.id,
      profile,
      versionId,
    );
    document.chunks = this.mapPreviewChunks(preview.chunks);
    document.chunk_count = document.chunks.length;
    document.quality = preview.quality;
    document.chunking_profile = preview.profile;
    document.version_id = preview.versionId;
    this.notify();
    return { ...document };
  }

  public async submitDocumentReview(
    documentId: string,
    reason: string,
  ): Promise<void> {
    const detail = await apiClient<PortalDocumentDetail>(
      `/api/knowledge/documents/${encodeURIComponent(documentId)}`,
    );
    if (!detail.document.etag) {
      throw new Error("文件缺少版本識別，請重新整理後再試。");
    }
    await apiClient(
      `/api/knowledge/documents/${encodeURIComponent(documentId)}/submit-review`,
      {
        method: "POST",
        body: JSON.stringify({
          etag: detail.document.etag,
          change_reason: reason,
        }),
      },
    );
    await this.loadDocuments();
  }

  public async decideDocumentReview(
    documentId: string,
    decision: "APPROVED" | "CHANGES_REQUESTED",
    comment: string,
  ): Promise<void> {
    const reviews = await apiClient<PendingPortalReviewList>(
      "/api/knowledge/reviews/pending",
    );
    const review = reviews.items.find(
      (item) => item.document_id === documentId,
    );
    if (!review) {
      throw new Error("找不到待處理的審查，請重新整理後再試。");
    }
    await apiClient(
      `/api/knowledge/reviews/${encodeURIComponent(review.review_id)}/decision`,
      {
        method: "POST",
        body: JSON.stringify({
          decision,
          comment,
          policy_exceptions: [],
        }),
      },
    );
    await this.loadDocuments();
  }

  public async publishDocument(
    documentId: string,
    reason: string,
  ): Promise<void> {
    const detail = await apiClient<PortalDocumentDetail>(
      `/api/knowledge/documents/${encodeURIComponent(documentId)}`,
    );
    const versionId = detail.draft_version?.version_id;
    if (!versionId) {
      throw new Error("找不到已核准的文件版本，請重新整理後再試。");
    }
    const document = this.documents.find((item) => item.id === documentId);
    if (document) {
      document.status = "PUBLISHING";
      this.notify();
    }
    try {
      await apiClient(
        `/api/knowledge/documents/${encodeURIComponent(documentId)}/publish`,
        {
          method: "POST",
          headers: {
            "Idempotency-Key":
              globalThis.crypto?.randomUUID?.() ||
              `publish-${documentId}-${Date.now()}`,
          },
          body: JSON.stringify({
            version_id: versionId,
            reason,
          }),
        },
      );
    } finally {
      await this.loadDocuments();
    }
  }

  // Action: Delete Manual Document (PDF/Word/MD)
  public async deleteDocument(documentId: string): Promise<void> {
    await apiClient(
      `/api/knowledge/documents/${encodeURIComponent(documentId)}`,
      {
        method: "DELETE",
      },
    );

    this.documents = this.documents.filter((d) => d.id !== documentId);
    this.notify();
  }

  private async waitForIngestion(
    jobId: string,
    onProgress?: (stage: IngestionStage) => void,
  ): Promise<PortalImportResult> {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const job = await apiClient<PortalImportResult>(
        `/api/knowledge/v1/ingestion-jobs/${encodeURIComponent(jobId)}`,
      );
      if (job.stage) onProgress?.(job.stage);
      if (job.status === "COMPLETED" && job.result) return job.result;
      if (job.status === "FAILED") {
        throw new Error(job.error || "文件解析工作失敗。");
      }
      await new Promise((resolve) => globalThis.setTimeout(resolve, 1000));
    }
    throw new Error("文件解析逾時；工作仍保留，可稍後重新開啟。");
  }

  private async fetchChunkPreview(
    documentId: string,
    profile: "AUTO" | "SLIDE_DECK" | "MANUAL" | "POLICY",
    versionId?: string,
  ): Promise<ChunkPreviewResponse> {
    const previewPath = versionId
      ? `/api/knowledge/v1/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(versionId)}/chunk-preview`
      : `/api/knowledge/v1/documents/${encodeURIComponent(documentId)}/chunk-preview`;
    return apiClient<ChunkPreviewResponse>(`${previewPath}?profile=${profile}`);
  }

  private mapPreviewChunks(
    chunks: ChunkPreviewResponse["chunks"],
  ): ManualChunkItem[] {
    return chunks.map((chunk) => ({
      id: chunk.id,
      parent_id: chunk.parentId,
      neighbor_ids: chunk.neighborIds,
      title: chunk.title,
      content: chunk.content,
      content_preview: chunk.contentPreview,
      character_count: chunk.content.length,
      token_count: chunk.tokenCount,
      page_number: chunk.pageStart,
      page_end: chunk.pageEnd,
      heading_path: chunk.headingPath,
      content_hash: chunk.contentHash,
      parser_version: chunk.parserVersion,
      chunker_version: chunk.chunkerVersion,
      quality_issues: chunk.qualityIssues || [],
      images: (chunk.images || []).map((image): ManualChunkImage => ({
        path: image.path,
        filename: image.filename,
        alt_text: image.alt_text,
        content_type: image.content_type,
        url: image.url,
      })),
    }));
  }

  private mapPortalStatus(status: string): ManualDocumentItem["status"] {
    if (status === "PUBLISHED") return "LIVE";
    if (status === "IN_REVIEW") return "IN_REVIEW";
    if (status === "APPROVED") return "APPROVED";
    if (status === "CHANGES_REQUESTED") return "CHANGES_REQUESTED";
    if (status === "PUBLISHING") return "PUBLISHING";
    if (status === "UNPUBLISHED" || status === "DISCARDED") return "ARCHIVED";
    if (status === "PUBLISH_FAILED") return "FAILED";
    return "DRAFT";
  }

  // Action: Delete FAQ Item
  public async deleteFaq(faqId: string): Promise<void> {
    await apiClient(
      `/api/console/workbench/faqs/${encodeURIComponent(faqId)}`,
      {
        method: "DELETE",
      },
    );

    this.faqs = this.faqs.filter((f) => f.id !== faqId);
    this.notify();
  }
}

export const workbenchStore = new WorkbenchStore();
