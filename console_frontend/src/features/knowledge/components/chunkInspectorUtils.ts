import type { ChunkQualityIssue, ManualDocumentItem } from "../../../shared/api/types";

export const QUALITY_ISSUE_LABELS: Record<ChunkQualityIssue, string> = {
  SHORT: "段落過短",
  HEADING_ONLY: "只有標題",
  DUPLICATE: "內容重複",
};

export const anomalousChunkIds = (
  document: ManualDocumentItem | null,
): Set<string> =>
  new Set(
    (document?.chunks || [])
      .filter(
        (chunk) =>
          Boolean(chunk.quality_issues?.length) ||
          (chunk.token_count || 0) < 80 ||
          (chunk.token_count || 0) > 900,
      )
      .map((chunk) => chunk.id),
  );

export type ChunkingProfile = "AUTO" | "SLIDE_DECK" | "MANUAL" | "POLICY";
