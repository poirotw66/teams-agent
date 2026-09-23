import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../shared/api/client';

const resetForIdentityChange = vi.fn();

vi.mock('../../shared/api/workbenchStore', () => ({
  workbenchStore: {
    resetForIdentityChange: (...args: unknown[]) => resetForIdentityChange(...args),
  },
}));

vi.mock('../../shared/api/client', async () => {
  const actual = await vi.importActual<typeof import('../../shared/api/client')>(
    '../../shared/api/client',
  );
  return {
    ...actual,
    apiClient: vi.fn(),
  };
});

describe('authProvider onError status handling', () => {
  afterEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
  });

  it('logs out on 401 and clears identity-bound state', async () => {
    const { authProvider } = await import('./authProvider');
    const result = await authProvider.onError?.(new ApiError('unauthorized', 401));
    expect(result?.logout).toBe(true);
    expect(resetForIdentityChange).toHaveBeenCalled();
  });

  it('does not log out on 403', async () => {
    const { authProvider } = await import('./authProvider');
    const result = await authProvider.onError?.(new ApiError('forbidden', 403));
    expect(result?.logout).toBeUndefined();
    expect(result?.error).toBeInstanceOf(Error);
    expect(resetForIdentityChange).not.toHaveBeenCalled();
  });
});
