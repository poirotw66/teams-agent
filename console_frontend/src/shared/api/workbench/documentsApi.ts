import { apiClient } from "../client";
import { IngestionStage, ManualDocumentItem } from "../types";
import { mapPortalStatus, mapPreviewChunks } from "./mappers";
import { fetchChunkPreview, waitForIngestion } from "./portalApi";
import {
  ChunkingProfile,
  PortalDocumentDetail,
  PortalDocumentList,
  PortalImportResult,
  PendingPortalReviewList,
} from "./types";

export async function fetchLegacyDocuments(): Promise<ManualDocumentItem[]> {
  return apiClient<ManualDocumentItem[]>("/api/console/workbench/documents");
}

export async function fetchPortalDocumentList(): Promise<PortalDocumentList> {
  return apiClient<PortalDocumentList>("/api/knowledge/documents");
}

export function mergeLegacyAndPortalDocuments(
  legacyDocuments: ManualDocumentItem[],
  portalList: PortalDocumentList | null,
): ManualDocumentItem[] {
  const known = new Map(legacyDocuments.map((item) => [item.id, item]));
  if (!portalList) {
    return [...known.values()];
  }
  for (const item of portalList.items) {
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
      status: mapPortalStatus(item.status),
      chunk_count: previous?.chunk_count || 0,
      updated_at: item.updated_at,
      updated_by: item.updated_by,
      chunks: previous?.chunks,
      quality: previous?.quality,
      chunking_profile: previous?.chunking_profile,
    });
  }
  return [...known.values()];
}

export async function uploadDocumentViaPortal(params: {
  file: File;
  title: string;
  category: string;
  version: string;
  profile?: ChunkingProfile;
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
    imported = await waitForIngestion(imported.jobId, params.onProgress);
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
  const preview = await fetchChunkPreview(
    created.document.document_id,
    params.profile || "AUTO",
    created.draft_version?.version_id,
  );
  return {
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
    chunks: mapPreviewChunks(preview.chunks),
    quality: preview.quality,
    chunking_profile: preview.profile,
    ingestion_warnings: imported.warnings || [],
  };
}

export async function previewDocumentChunks(
  document: ManualDocumentItem,
  profile: ChunkingProfile = "AUTO",
): Promise<ManualDocumentItem> {
  const detail = await apiClient<PortalDocumentDetail>(
    `/api/knowledge/documents/${encodeURIComponent(document.id)}`,
  );
  const versionId =
    detail.draft_version?.version_id || detail.published_version?.version_id;
  const preview = await fetchChunkPreview(document.id, profile, versionId);
  document.chunks = mapPreviewChunks(preview.chunks);
  document.chunk_count = document.chunks.length;
  document.quality = preview.quality;
  document.chunking_profile = preview.profile;
  document.version_id = preview.versionId;
  return { ...document };
}

export async function submitDocumentReviewRequest(
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
}

export async function decideDocumentReviewRequest(
  documentId: string,
  decision: "APPROVED" | "CHANGES_REQUESTED",
  comment: string,
): Promise<void> {
  const reviews = await apiClient<PendingPortalReviewList>(
    "/api/knowledge/reviews/pending",
  );
  const review = reviews.items.find((item) => item.document_id === documentId);
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
}

export async function resolvePublishVersionId(
  documentId: string,
): Promise<string> {
  const detail = await apiClient<PortalDocumentDetail>(
    `/api/knowledge/documents/${encodeURIComponent(documentId)}`,
  );
  const versionId = detail.draft_version?.version_id;
  if (!versionId) {
    throw new Error("找不到已核准的文件版本，請重新整理後再試。");
  }
  return versionId;
}

export async function postPublishDocument(
  documentId: string,
  versionId: string,
  reason: string,
): Promise<void> {
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
}

export async function deleteDocumentRequest(documentId: string): Promise<void> {
  await apiClient(
    `/api/knowledge/documents/${encodeURIComponent(documentId)}`,
    {
      method: "DELETE",
    },
  );
}
