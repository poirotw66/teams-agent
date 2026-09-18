import {
  ManualChunkItem,
  ManualChunkImage,
  ManualDocumentItem,
} from "../types";
import { ChunkPreviewResponse } from "./types";

export function mapPreviewChunks(
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
    images: (chunk.images || []).map(
      (image): ManualChunkImage => ({
        path: image.path,
        filename: image.filename,
        alt_text: image.alt_text,
        content_type: image.content_type,
        url: image.url,
      }),
    ),
  }));
}

export function mapPortalStatus(
  status: string,
): ManualDocumentItem["status"] {
  if (status === "PUBLISHED") return "LIVE";
  if (status === "IN_REVIEW") return "IN_REVIEW";
  if (status === "APPROVED") return "APPROVED";
  if (status === "CHANGES_REQUESTED") return "CHANGES_REQUESTED";
  if (status === "PUBLISHING") return "PUBLISHING";
  if (status === "UNPUBLISHED" || status === "DISCARDED") return "ARCHIVED";
  if (status === "PUBLISH_FAILED") return "FAILED";
  return "DRAFT";
}
