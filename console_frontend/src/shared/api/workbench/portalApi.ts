import { apiClient } from "../client";
import { IngestionStage } from "../types";
import {
  ChunkingProfile,
  ChunkPreviewResponse,
  PortalImportResult,
} from "./types";

export async function waitForIngestion(
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

export async function fetchChunkPreview(
  documentId: string,
  profile: ChunkingProfile,
  versionId?: string,
): Promise<ChunkPreviewResponse> {
  const previewPath = versionId
    ? `/api/knowledge/v1/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(versionId)}/chunk-preview`
    : `/api/knowledge/v1/documents/${encodeURIComponent(documentId)}/chunk-preview`;
  return apiClient<ChunkPreviewResponse>(`${previewPath}?profile=${profile}`);
}
