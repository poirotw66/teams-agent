import { describe, expect, it } from 'vitest';
import type { KnowledgeSyncStatus } from '../lib/syncLocalKnowledgeMirror';
import {
  isKnowledgeReleaseBehind,
  resolveKnowledgeSyncBannerState,
} from './knowledgeSyncBannerState';

const SAME_RELEASE = 'release-94829b57e0e3';

function matchingPinnedSync(
  overrides: Partial<KnowledgeSyncStatus> = {},
): KnowledgeSyncStatus {
  return {
    cloudActiveReleaseId: SAME_RELEASE,
    mirroredReleaseId: SAME_RELEASE,
    loadedReleaseId: SAME_RELEASE,
    selectionMode: 'PINNED',
    syncState: 'IN_SYNC',
    qaSnapshotComplete: true,
    runtimeInventoryComplete: true,
    alignedWithCloud: false,
    matchesCloudProduction: false,
    behindCloud: false,
    ...overrides,
  };
}

describe('resolveKnowledgeSyncBannerState', () => {
  it('does not treat PINNED + matching IDs as LAG', () => {
    const decision = resolveKnowledgeSyncBannerState({
      sync: matchingPinnedSync(),
      isCloudConsole: true,
    });

    expect(decision.kind).toBe('pinned_same_release');
    expect(decision.isBehind).toBe(false);
    expect(decision.copy.headline).toBe('已釘選此版，與目前正式 release 相同');
    expect(decision.copy.headline).not.toMatch(/落後/);
    expect(decision.copy.description).not.toMatch(/地端筆電/);
    expect(decision.copy.description).not.toMatch(/Playground Agent/);
  });

  it('marks LAG when release IDs differ', () => {
    const decision = resolveKnowledgeSyncBannerState({
      sync: matchingPinnedSync({
        loadedReleaseId: 'release-old',
        alignedWithCloud: false,
        behindCloud: true,
      }),
      isCloudConsole: true,
    });

    expect(decision.kind).toBe('lag');
    expect(decision.isBehind).toBe(true);
    expect(decision.copy.headline).toMatch(/可能落後雲端/);
  });

  it('marks LAG when inventory is incomplete even if IDs match', () => {
    const decision = resolveKnowledgeSyncBannerState({
      sync: matchingPinnedSync({
        qaSnapshotComplete: false,
        runtimeInventoryComplete: false,
        indexOnlyMirror: true,
      }),
    });

    expect(decision.kind).toBe('lag');
    expect(decision.isBehind).toBe(true);
  });

  it('keeps cloud success copy free of laptop Playground wording', () => {
    const decision = resolveKnowledgeSyncBannerState({
      sync: matchingPinnedSync({
        selectionMode: 'FOLLOW_CLOUD',
        alignedWithCloud: true,
        matchesCloudProduction: true,
      }),
      isCloudConsole: true,
    });

    expect(decision.kind).toBe('in_sync');
    expect(decision.copy.headline).not.toMatch(/地端筆電/);
    expect(decision.copy.headline).not.toMatch(/Playground Agent/);
    expect(decision.copy.description).not.toMatch(/地端筆電/);
    expect(decision.copy.description).not.toMatch(/Playground Agent/);
    expect(`${decision.copy.headline}${decision.copy.description}`).not.toMatch(
      /本機測試工作區/,
    );
  });

  it('keeps laptop success copy mentioning Playground Agent', () => {
    const decision = resolveKnowledgeSyncBannerState({
      sync: matchingPinnedSync({
        selectionMode: 'FOLLOW_CLOUD',
        alignedWithCloud: true,
        matchesCloudProduction: true,
      }),
      isCloudConsole: false,
    });

    expect(decision.kind).toBe('in_sync');
    expect(decision.copy.headline).toMatch(/Playground Agent/);
  });

  it('treats Agent unreachable as behind without claiming parity', () => {
    const decision = resolveKnowledgeSyncBannerState({
      error: '此 Console 所連 Agent 同步狀態目前無法取得；不得宣稱與雲端正式知識版本一致。',
      isCloudConsole: true,
    });

    expect(decision.kind).toBe('unreachable');
    expect(decision.isBehind).toBe(true);
    expect(decision.copy.footnote).not.toMatch(/地端筆電/);
  });
});

describe('isKnowledgeReleaseBehind', () => {
  it('is not behind when the three IDs match and inventory is complete', () => {
    expect(isKnowledgeReleaseBehind(matchingPinnedSync())).toBe(false);
  });

  it('is behind when loaded differs from cloud', () => {
    expect(
      isKnowledgeReleaseBehind(
        matchingPinnedSync({
          loadedReleaseId: 'release-other',
          behindCloud: true,
        }),
      ),
    ).toBe(true);
  });
});
