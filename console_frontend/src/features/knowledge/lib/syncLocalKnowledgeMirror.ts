/** Shared Sync Now helper for the Console-connected Agent mirror. */

import { apiClient, ApiError } from '../../../shared/api/client';
import type { ManualChunkItem, ManualDocumentItem } from '../../../shared/api/types';

export type KnowledgeMirrorDocument = {
  documentId?: string | null;
  title?: string | null;
  versionId?: string | null;
  sourcePath?: string | null;
  contentState?: string | null;
};

export type KnowledgeMirrorDocumentPreview = KnowledgeMirrorDocument & {
  releaseId?: string | null;
  chunkCount?: number;
  chunks?: ManualChunkItem[];
};

export type KnowledgeSyncStatus = {
  cloudActiveReleaseId?: string | null;
  mirroredReleaseId?: string | null;
  loadedReleaseId?: string | null;
  selectionMode?: string;
  syncState?: string;
  lastSuccessfulSyncAt?: string | null;
  artifactCount?: number;
  verificationHash?: string | null;
  qaSnapshotComplete?: boolean;
  runtimeInventoryComplete?: boolean;
  indexOnlyMirror?: boolean;
  behindCloud?: boolean;
  alignedWithCloud?: boolean;
  matchesCloudProduction?: boolean;
  detail?: string | null;
  lastError?: string | null;
  documents?: KnowledgeMirrorDocument[];
};

export type SyncLocalKnowledgeMirrorOutcome =
  | {
      kind: 'aligned';
      sync: KnowledgeSyncStatus;
      message: string;
    }
  | {
      kind: 'behind';
      sync: KnowledgeSyncStatus;
      message: string;
    }
  | {
      kind: 'completed';
      sync: KnowledgeSyncStatus;
      message: string;
    }
  | {
      kind: 'agent_unreachable';
      status: 503;
      message: string;
    }
  | {
      kind: 'failed';
      message: string;
      status?: number;
    };

/** Toast shown when Portal publish succeeds, before Console-connected Agent sync. */
export const PUBLISH_SUCCESS_CLOUD_RELOAD_MESSAGE =
  '文件已發布；雲端 Agent 由 Portal reload。正在同步此 Console 所連 Agent…';

/** Toast when Sync Now aligns the Console-connected Agent with cloud active. */
export const SYNC_ALIGNED_MESSAGE =
  '此 Console 所連 Agent 已與雲端 active 一致。';

/** Toast when Sync Now finishes but loaded/mirrored may still lag cloud. */
export const SYNC_BEHIND_MESSAGE =
  '此 Console 所連 Agent 鏡像已更新，但載入版本可能仍落後雲端。請再按「立即同步」或至知識 Release 頁確認。';

/** Toast when Sync Now cannot reach the BFF Agent (503). */
export const SYNC_AGENT_UNREACHABLE_MESSAGE =
  '雲端可能已 ACTIVE，但目前無法連線此 Console 所連 Agent；不得宣稱 Playground／對話已更新。請稍後按「立即同步」。';

/** Generic Sync Now completion when neither aligned nor behind flags apply. */
export const SYNC_COMPLETED_MESSAGE = '此 Console 所連 Agent 同步完成。';

/**
 * POST `/api/console/agent-knowledge/sync` against the Agent pointed to by BFF
 * ``AGENT_API_URL`` (local Playground when Console is local; Cloud Run when
 * Console BFF points there). Does not replace Portal cloud reload.
 */
export async function syncLocalKnowledgeMirror(): Promise<SyncLocalKnowledgeMirrorOutcome> {
  try {
    const sync = await apiClient<KnowledgeSyncStatus>(
      '/api/console/agent-knowledge/sync',
      {
        method: 'POST',
      },
    );
    if (sync.alignedWithCloud || sync.matchesCloudProduction) {
      return { kind: 'aligned', sync, message: SYNC_ALIGNED_MESSAGE };
    }
    if (sync.behindCloud) {
      return { kind: 'behind', sync, message: SYNC_BEHIND_MESSAGE };
    }
    return { kind: 'completed', sync, message: SYNC_COMPLETED_MESSAGE };
  } catch (error) {
    if (error instanceof ApiError && error.status === 503) {
      return {
        kind: 'agent_unreachable',
        status: 503,
        message: SYNC_AGENT_UNREACHABLE_MESSAGE,
      };
    }
    return {
      kind: 'failed',
      status: error instanceof ApiError ? error.status : undefined,
      message:
        error instanceof Error && error.message.trim()
          ? error.message
          : '立即同步失敗。',
    };
  }
}

/**
 * Map a Sync Now outcome to antd message level (success / warning / error).
 * Callers still own whether to toast — this keeps copy and level consistent.
 */
export function syncOutcomeToastLevel(
  outcome: SyncLocalKnowledgeMirrorOutcome,
): 'success' | 'warning' | 'error' {
  switch (outcome.kind) {
    case 'aligned':
    case 'completed':
      return 'success';
    case 'behind':
    case 'agent_unreachable':
      return 'warning';
    case 'failed':
      return 'error';
  }
}

export async function fetchMirrorDocumentPreview(
  documentId: string,
): Promise<KnowledgeMirrorDocumentPreview> {
  return apiClient<KnowledgeMirrorDocumentPreview>(
    `/api/console/agent-knowledge/documents/${encodeURIComponent(documentId)}`,
  );
}

/** Adapt a GCS mirror preview to the shared Chunk Inspector document shape. */
export function mirrorPreviewToManualDocument(
  preview: KnowledgeMirrorDocumentPreview,
): ManualDocumentItem {
  const chunks = preview.chunks || [];
  return {
    id: preview.documentId || '',
    title: preview.title || preview.documentId || '雲端正式鏡像文件',
    file_name: preview.sourcePath || 'gcs-mirror',
    category: '雲端正式鏡像',
    status: 'LIVE',
    chunk_count: preview.chunkCount ?? chunks.length,
    chunks,
    version: preview.versionId || preview.releaseId || 'ACTIVE',
    version_id: preview.versionId,
    updated_at: '',
    updated_by: '',
  };
}
