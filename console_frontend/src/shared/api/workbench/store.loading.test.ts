import { afterEach, describe, expect, it, vi } from 'vitest';

describe('workbenchStore loading surface', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
  });

  it('does not fetch on subscribe until ensureDomains is called', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 503,
      json: async () => ({}),
    }));
    vi.stubGlobal('fetch', fetchMock);

    const { workbenchStore } = await import('./store');
    const unsubscribe = workbenchStore.subscribe(() => undefined);
    expect(fetchMock).not.toHaveBeenCalled();

    void workbenchStore.ensureDomains(['conversations']);
    await vi.waitFor(() => {
      expect(fetchMock.mock.calls.length).toBeGreaterThan(0);
    });

    const paths = fetchMock.mock.calls.map((call) => String(call[0]));
    expect(paths.some((path) => path.includes('/conversations'))).toBe(true);
    expect(paths.some((path) => path.includes('/documents'))).toBe(false);

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
    void workbenchStore.ensureDomains(['overview']);

    expect(typeof workbenchStore.getIsLoading()).toBe('boolean');
    await vi.waitFor(() => {
      expect(seen.length).toBeGreaterThan(0);
    });

    unsubscribe();
  });

  it('starts empty and surfaces loadError when requested domains fail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 503,
        json: async () => ({}),
      })),
    );

    const { workbenchStore } = await import('./store');

    expect(workbenchStore.getTickets()).toEqual([]);
    expect(workbenchStore.getConversations()).toEqual([]);
    expect(workbenchStore.getFaqs()).toEqual([]);
    expect(workbenchStore.getDocuments()).toEqual([]);
    expect(workbenchStore.getKpis().total_inquiries_today).toBe(0);
    expect(workbenchStore.getLoadError()).toBeNull();

    const unsubscribe = workbenchStore.subscribe(() => undefined);
    await workbenchStore.ensureDomains(['tickets', 'faqs']);

    await vi.waitFor(() => {
      expect(workbenchStore.getLoadError()).toMatch(/load failed|Partial workbench|tickets|faqs/i);
    });

    expect(workbenchStore.getTickets()).toEqual([]);
    expect(workbenchStore.getFaqs()).toEqual([]);

    unsubscribe();
  });
});
