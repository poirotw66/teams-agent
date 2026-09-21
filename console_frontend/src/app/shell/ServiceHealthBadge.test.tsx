import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { ApiError } from '../../shared/api/client';
import { ServiceHealthBadge } from './ServiceHealthBadge';

const apiClient = vi.fn();

vi.mock('../../shared/api/client', async () => {
  const actual = await vi.importActual<typeof import('../../shared/api/client')>(
    '../../shared/api/client',
  );
  return {
    ...actual,
    apiClient: (...args: unknown[]) => apiClient(...args),
  };
});

describe('ServiceHealthBadge', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    apiClient.mockReset();
  });

  it('renders live overall status and update time after a successful fetch', async () => {
    apiClient.mockResolvedValue({
      overallStatus: 'READY',
      generatedAt: '2026-09-21T07:00:00Z',
    });

    render(<ServiceHealthBadge />);

    await waitFor(() => {
      expect(screen.getByText(/服務狀態：READY/)).toBeTruthy();
    });
    expect(screen.queryByText(/待健康 API 更新/)).toBeNull();
    expect(apiClient).toHaveBeenCalledWith('/api/health/summary');
  });

  it('does not hard-code a healthy state when the health API fails', async () => {
    apiClient.mockRejectedValue(new ApiError('down', 503));

    render(<ServiceHealthBadge />);

    await waitFor(() => {
      expect(screen.getByText(/服務狀態：無法取得/)).toBeTruthy();
    });
    expect(screen.queryByText(/正常運行/)).toBeNull();
  });
});
