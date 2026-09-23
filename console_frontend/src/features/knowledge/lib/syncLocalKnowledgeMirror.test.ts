import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../../shared/api/client';
import {
  PUBLISH_SUCCESS_CLOUD_RELOAD_MESSAGE,
  SYNC_AGENT_UNREACHABLE_MESSAGE,
  SYNC_ALIGNED_MESSAGE,
  SYNC_BEHIND_MESSAGE,
  SYNC_COMPLETED_MESSAGE,
  syncLocalKnowledgeMirror,
  syncOutcomeToastLevel,
} from './syncLocalKnowledgeMirror';

const apiClient = vi.fn();

vi.mock('../../../shared/api/client', async () => {
  const actual = await vi.importActual<typeof import('../../../shared/api/client')>(
    '../../../shared/api/client',
  );
  return {
    ...actual,
    apiClient: (...args: unknown[]) => apiClient(...args),
  };
});

describe('syncLocalKnowledgeMirror', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    apiClient.mockReset();
  });

  it('returns aligned when Agent reports alignedWithCloud', async () => {
    apiClient.mockResolvedValue({
      alignedWithCloud: true,
      cloudActiveReleaseId: 'rel-a',
      mirroredReleaseId: 'rel-a',
      loadedReleaseId: 'rel-a',
    });

    const outcome = await syncLocalKnowledgeMirror();

    expect(apiClient).toHaveBeenCalledWith('/api/console/agent-knowledge/sync', {
      method: 'POST',
    });
    expect(outcome).toEqual({
      kind: 'aligned',
      sync: expect.objectContaining({ alignedWithCloud: true }),
      message: SYNC_ALIGNED_MESSAGE,
    });
    expect(syncOutcomeToastLevel(outcome)).toBe('success');
  });

  it('returns aligned when matchesCloudProduction is true', async () => {
    apiClient.mockResolvedValue({
      matchesCloudProduction: true,
      behindCloud: false,
    });

    const outcome = await syncLocalKnowledgeMirror();

    expect(outcome.kind).toBe('aligned');
    expect(outcome.message).toBe(SYNC_ALIGNED_MESSAGE);
  });

  it('returns behind when Agent reports behindCloud', async () => {
    apiClient.mockResolvedValue({
      behindCloud: true,
      alignedWithCloud: false,
      cloudActiveReleaseId: 'rel-b',
      loadedReleaseId: 'rel-a',
    });

    const outcome = await syncLocalKnowledgeMirror();

    expect(outcome).toEqual({
      kind: 'behind',
      sync: expect.objectContaining({ behindCloud: true }),
      message: SYNC_BEHIND_MESSAGE,
    });
    expect(syncOutcomeToastLevel(outcome)).toBe('warning');
  });

  it('returns completed when neither aligned nor behind', async () => {
    apiClient.mockResolvedValue({
      syncState: 'IN_SYNC',
      mirroredReleaseId: 'rel-a',
    });

    const outcome = await syncLocalKnowledgeMirror();

    expect(outcome.kind).toBe('completed');
    expect(outcome.message).toBe(SYNC_COMPLETED_MESSAGE);
    expect(syncOutcomeToastLevel(outcome)).toBe('success');
  });

  it('returns agent_unreachable on 503 without claiming Playground updated', async () => {
    apiClient.mockRejectedValue(new ApiError('Agent API URL is not configured', 503));

    const outcome = await syncLocalKnowledgeMirror();

    expect(outcome).toEqual({
      kind: 'agent_unreachable',
      status: 503,
      message: SYNC_AGENT_UNREACHABLE_MESSAGE,
    });
    expect(syncOutcomeToastLevel(outcome)).toBe('warning');
    expect(outcome.message).toMatch(/不得宣稱/);
    expect(outcome.message).not.toMatch(/已與雲端 active 一致/);
  });

  it('returns failed for non-503 errors', async () => {
    apiClient.mockRejectedValue(new ApiError('forbidden', 403));

    const outcome = await syncLocalKnowledgeMirror();

    expect(outcome).toEqual({
      kind: 'failed',
      status: 403,
      message: 'forbidden',
    });
    expect(syncOutcomeToastLevel(outcome)).toBe('error');
  });

  it('keeps publish success copy distinct from Sync Now', () => {
    expect(PUBLISH_SUCCESS_CLOUD_RELOAD_MESSAGE).toMatch(/Portal reload/);
    expect(PUBLISH_SUCCESS_CLOUD_RELOAD_MESSAGE).toMatch(/Console 所連 Agent/);
    expect(PUBLISH_SUCCESS_CLOUD_RELOAD_MESSAGE).not.toMatch(/雙後端/);
  });
});
