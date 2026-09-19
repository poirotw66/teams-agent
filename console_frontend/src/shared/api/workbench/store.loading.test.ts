import { afterEach, describe, expect, it, vi } from 'vitest';

describe('workbenchStore loading surface', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
  });

  it('does not fetch until a subscriber calls ensureLoaded via subscribe', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 503,
      json: async () => ({}),
    }));
    vi.stubGlobal('fetch', fetchMock);

    const { workbenchStore } = await import('./store');
    expect(fetchMock).not.toHaveBeenCalled();

    const unsubscribe = workbenchStore.subscribe(() => undefined);
    expect(fetchMock.mock.calls.length).toBeGreaterThan(0);

    unsubscribe();
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
