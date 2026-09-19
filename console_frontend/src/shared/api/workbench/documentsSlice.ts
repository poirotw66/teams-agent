import { ManualDocumentItem, IngestionStage } from "../types";
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
import { ChunkingProfile } from "./types";
import { WorkbenchSliceContext } from "./storeCore";

export class DocumentsSlice {
  constructor(private readonly ctx: WorkbenchSliceContext) {}

  public getDocuments(): ManualDocumentItem[] {
    return [...this.ctx.state.documents];
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
      this.ctx.state.documents = mergeLegacyAndPortalDocuments(
        legacyDocuments,
        portalList,
      );
      this.ctx.notify();
    } catch (err) {
      console.error("Failed to load documents:", err);
    }
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
    this.ctx.state.documents.unshift(newDoc);
    this.ctx.notify();
    return newDoc;
  }

  public async previewDocument(
    document: ManualDocumentItem,
    profile: ChunkingProfile = "AUTO",
  ): Promise<ManualDocumentItem> {
    const updated = await previewDocumentChunks(document, profile);
    this.ctx.notify();
    return updated;
  }

  public async submitDocumentReview(
    documentId: string,
    reason: string,
  ): Promise<void> {
    await submitDocumentReviewRequest(documentId, reason);
    await this.ctx.reloads.loadDocuments();
  }

  public async decideDocumentReview(
    documentId: string,
    decision: "APPROVED" | "CHANGES_REQUESTED",
    comment: string,
  ): Promise<void> {
    await decideDocumentReviewRequest(documentId, decision, comment);
    await this.ctx.reloads.loadDocuments();
  }

  public async publishDocument(
    documentId: string,
    reason: string,
  ): Promise<void> {
    const versionId = await resolvePublishVersionId(documentId);
    const document = this.ctx.state.documents.find((item) => item.id === documentId);
    if (document) {
      document.status = "PUBLISHING";
      this.ctx.notify();
    }
    try {
      await postPublishDocument(documentId, versionId, reason);
    } finally {
      await this.ctx.reloads.loadDocuments();
    }
  }

  public async deleteDocument(documentId: string): Promise<void> {
    await deleteDocumentRequest(documentId);
    this.ctx.state.documents = this.ctx.state.documents.filter(
      (d) => d.id !== documentId,
    );
    this.ctx.notify();
  }
}
