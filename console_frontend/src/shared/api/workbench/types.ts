import type {
  ManualDocumentItem,
  ChunkQualityIssue,
  ChunkQualitySummary,
  IngestionStage,
} from "../types";

export type { OverviewApiResponse, ChunkingProfile } from "../types";

export interface PortalImportResult {
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

export interface PortalDocumentRecord {
  document_id: string;
  title: string;
  category: string;
  status: string;
  etag?: string;
  updated_at: string;
  updated_by: string;
  format?: string;
}

export interface PortalDocumentList {
  items: PortalDocumentRecord[];
}

export interface PortalDocumentDetail {
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

export interface PendingPortalReviewList {
  items: Array<{
    review_id: string;
    document_id: string;
  }>;
}

export interface ChunkPreviewResponse {
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
