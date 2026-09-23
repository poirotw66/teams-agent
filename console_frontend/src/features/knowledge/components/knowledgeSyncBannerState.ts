import type { KnowledgeSyncStatus } from '../lib/syncLocalKnowledgeMirror';

export type KnowledgeSyncBannerKind =
  | 'unreachable'
  | 'loading'
  | 'in_sync'
  | 'pinned_same_release'
  | 'lag';

export type KnowledgeSyncBannerTone = 'success' | 'info' | 'warning';

export type KnowledgeSyncBannerCopy = {
  headline: string;
  description: string;
  footnote?: string;
};

export type KnowledgeSyncBannerDecision = {
  kind: KnowledgeSyncBannerKind;
  tone: KnowledgeSyncBannerTone;
  isBehind: boolean;
  releaseIdsMatch: boolean;
  inventoryComplete: boolean;
  copy: KnowledgeSyncBannerCopy;
};

export type KnowledgeSyncBannerInput = {
  sync?: KnowledgeSyncStatus | null;
  currentReleaseId?: string | null;
  error?: string | null;
  isCloudConsole?: boolean;
};

function trimReleaseId(value?: string | null): string {
  return value?.trim() || '';
}

export function releaseLabel(value?: string | null): string {
  return trimReleaseId(value) ? String(value).trim() : '—';
}

export function knowledgeReleaseIdsMatch(
  sync?: KnowledgeSyncStatus | null,
  currentReleaseId?: string | null,
): boolean {
  const cloud = trimReleaseId(sync?.cloudActiveReleaseId);
  const mirrored = trimReleaseId(sync?.mirroredReleaseId);
  const loaded = trimReleaseId(sync?.loadedReleaseId || currentReleaseId);
  return Boolean(cloud && mirrored && loaded && cloud === mirrored && mirrored === loaded);
}

export function knowledgeInventoryComplete(
  sync?: KnowledgeSyncStatus | null,
): boolean {
  return Boolean(sync?.qaSnapshotComplete || sync?.runtimeInventoryComplete);
}

export function isKnowledgeReleaseBehind(
  sync?: KnowledgeSyncStatus | null,
  currentReleaseId?: string | null,
): boolean {
  if (!sync) {
    return false;
  }
  if (knowledgeReleaseIdsMatch(sync, currentReleaseId) && knowledgeInventoryComplete(sync)) {
    return false;
  }
  const cloud = trimReleaseId(sync.cloudActiveReleaseId);
  const loaded = trimReleaseId(sync.loadedReleaseId || currentReleaseId);
  const mirrored = trimReleaseId(sync.mirroredReleaseId);
  const idsDiffer = Boolean(
    (cloud && loaded && cloud !== loaded) || (cloud && mirrored && cloud !== mirrored),
  );
  return (
    Boolean(sync.behindCloud) ||
    idsDiffer ||
    !knowledgeInventoryComplete(sync)
  );
}

function releaseTripleLine(
  sync: KnowledgeSyncStatus,
  currentReleaseId?: string | null,
): string {
  const loaded = sync.loadedReleaseId || currentReleaseId;
  const mode = sync.selectionMode ? `（${sync.selectionMode}）` : '';
  return (
    `雲端 ${releaseLabel(sync.cloudActiveReleaseId)} ／ 鏡像 ${releaseLabel(sync.mirroredReleaseId)} ／ ` +
    `此 Console 所連 Agent ${releaseLabel(loaded)}${mode}`
  );
}

function inSyncCopy(isCloudConsole: boolean, triple: string): KnowledgeSyncBannerCopy {
  if (isCloudConsole) {
    return {
      headline: '正式 Agent 已與目前正式 release 同一版',
      description: `${triple}。這只代表正式 Agent 目前載入的已發布版，不是知識文件工作區。`,
    };
  }
  return {
    headline: 'Playground Agent 已與雲端 active 同一版',
    description:
      `${triple}。這只代表 GCS 鏡像／問答索引，不是「本機測試工作區」文件表。` +
      '要比對雲端目錄請看「雲端正式鏡像」。',
  };
}

function pinnedSameCopy(isCloudConsole: boolean, triple: string): KnowledgeSyncBannerCopy {
  return {
    headline: '已釘選此版，與目前正式 release 相同',
    description: isCloudConsole
      ? `${triple}。選擇模式為 PINNED，但載入版本與正式 release 相同，並非落後。`
      : `${triple}。選擇模式為 PINNED，但載入版本與正式 release 相同，並非落後雲端。`,
  };
}

function lagCopy(
  isCloudConsole: boolean,
  sync: KnowledgeSyncStatus,
  currentReleaseId?: string | null,
): KnowledgeSyncBannerCopy {
  const triple = releaseTripleLine(sync, currentReleaseId);
  const detail =
    sync.lastError ||
    sync.detail ||
    '不得宣稱與正式環境一致。請按「立即同步」強制同步此 Console 所連 Agent，或確認釘選／sandbox 模式。';
  return {
    headline: '此 Console 所連 Agent 可能落後雲端',
    description: `${triple}。${detail}`,
    footnote: isCloudConsole
      ? '雲端正式對話靠 Portal reload；「立即同步」只更新此 Console 所連 Agent。'
      : '雲端正式對話靠 Portal reload；「立即同步」不會更新未連線的地端筆電 Playground。',
  };
}

export function resolveKnowledgeSyncBannerState(
  input: KnowledgeSyncBannerInput,
): KnowledgeSyncBannerDecision {
  const isCloudConsole = Boolean(input.isCloudConsole);
  if (input.error) {
    return {
      kind: 'unreachable',
      tone: 'warning',
      isBehind: true,
      releaseIdsMatch: false,
      inventoryComplete: false,
      copy: {
        headline: '此 Console 所連 Agent 可能落後雲端',
        description: input.error,
        footnote: isCloudConsole
          ? '「立即同步」只更新此 Console 所連 Agent，不會取代 Portal 對 Cloud Run 的 reload-knowledge。'
          : '「立即同步」只更新 BFF 所連 Agent（地端 Playground 或雲端 Console 所指目標），不會取代 Portal 對 Cloud Run 的 reload-knowledge。',
      },
    };
  }

  const sync = input.sync;
  if (!sync) {
    return {
      kind: 'loading',
      tone: 'info',
      isBehind: false,
      releaseIdsMatch: false,
      inventoryComplete: false,
      copy: {
        headline: isCloudConsole
          ? '正式 Agent 載入狀態尚未取得'
          : '從雲端正式 release 同步到本機 Playground',
        description: isCloudConsole
          ? '發布後正式對話才會換版。請稍後再查看同步狀態。'
          : '本機問答讀的是已驗證快照，不是雲端即時庫。按「立即同步」拉取 Firestore active + GCS QA artifacts。',
      },
    };
  }

  const releaseIdsMatch = knowledgeReleaseIdsMatch(sync, input.currentReleaseId);
  const inventoryComplete = knowledgeInventoryComplete(sync);
  const sameReadyRelease = releaseIdsMatch && inventoryComplete;
  const selectionMode = String(sync.selectionMode || '').toUpperCase();
  const triple = releaseTripleLine(sync, input.currentReleaseId);

  if (sameReadyRelease && selectionMode === 'PINNED') {
    return {
      kind: 'pinned_same_release',
      tone: 'success',
      isBehind: false,
      releaseIdsMatch,
      inventoryComplete,
      copy: pinnedSameCopy(isCloudConsole, triple),
    };
  }

  if (sameReadyRelease) {
    return {
      kind: 'in_sync',
      tone: 'success',
      isBehind: false,
      releaseIdsMatch,
      inventoryComplete,
      copy: inSyncCopy(isCloudConsole, triple),
    };
  }

  return {
    kind: 'lag',
    tone: 'warning',
    isBehind: true,
    releaseIdsMatch,
    inventoryComplete,
    copy: lagCopy(isCloudConsole, sync, input.currentReleaseId),
  };
}
