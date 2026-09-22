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
import { ChunkingProfile, PortalDocumentList } from "./types";
import { WorkbenchSliceContext } from "./storeCore";

export class DocumentsSlice {
  constructor(private readonly ctx: WorkbenchSliceContext) {}

  public getDocuments(): ManualDocumentItem[] {
    return [...this.ctx.state.documents];
  }

  public async loadDocuments(): Promise<void> {
    // Portal list is the governed source of truth and stays responsive during
    // formal publish. Legacy workbench join loads full chunks.json and must
    // not block the Knowledge page table.
    let portalList: PortalDocumentList | null = null;
    let portalError: unknown = null;
    try {
      portalList = await fetchPortalDocumentList();
      this.ctx.state.documents = mergeLegacyAndPortalDocuments([], portalList);
      this.ctx.notify();
    } catch (error) {
      portalError = error;
    }

    let legacyDocuments: ManualDocumentItem[] = [];
    try {
      legacyDocuments = await Promise.race([
        fetchLegacyDocuments(),
        new Promise<ManualDocumentItem[]>((resolve) => {
          window.setTimeout(() => resolve([]), 2500);
        }),
      ]);
    } catch (error) {
      console.warn("Legacy document enrich skipped:", error);
    }

    if (legacyDocuments.length > 0 || portalList) {
      this.ctx.state.documents = mergeLegacyAndPortalDocuments(
        legacyDocuments,
        portalList,
      );
      this.ctx.notify();
      return;
    }
    if (portalError) {
      console.error("Failed to load documents:", portalError);
      throw portalError;
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
    const index = this.ctx.state.documents.findIndex((item) => item.id === document.id);
    if (index >= 0) {
      this.ctx.state.documents[index] = {
        ...this.ctx.state.documents[index],
        ...updated,
        id: document.id,
      };
    }
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
