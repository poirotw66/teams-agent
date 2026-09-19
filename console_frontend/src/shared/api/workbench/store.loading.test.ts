import { afterEach, describe, expect, it, vi } from 'vitest';

describe('workbenchStore loading surface', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
  });

  it('exposes getIsLoading and notifies subscribers', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 503,
        json: async () => ({}),
      })),
    );

    const { workbenchStore } = await import('./store');
    const seen: boolean[] = [];
    const unsubscribe = workbenchStore.subscribe(() => {
      seen.push(workbenchStore.getIsLoading());
    });

    expect(typeof workbenchStore.getIsLoading()).toBe('boolean');
    expect(seen.length).toBeGreaterThan(0);

    unsubscribe();
  });
});
