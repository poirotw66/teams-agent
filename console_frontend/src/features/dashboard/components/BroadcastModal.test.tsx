import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { message } from 'antd';
import { ApiError } from '../../../shared/api/client';
import { BroadcastModal } from './BroadcastModal';

const setSpikeBroadcast = vi.fn();

vi.mock('../../../shared/api/workbenchStore', () => ({
  workbenchStore: {
    setSpikeBroadcast: (...args: unknown[]) => setSpikeBroadcast(...args),
  },
}));

describe('BroadcastModal mutation feedback', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    setSpikeBroadcast.mockReset();
  });

  it('keeps the modal open and preserves content when broadcast fails', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const successSpy = vi.spyOn(message, 'success').mockImplementation(() => undefined as never);
    const errorSpy = vi.spyOn(message, 'error').mockImplementation(() => undefined as never);
    setSpikeBroadcast.mockRejectedValue(new ApiError('timeout', 504));

    render(
      <BroadcastModal
        open
        onClose={onClose}
        defaultTopic="VPN 中斷"
      />,
    );

    await user.click(screen.getByRole('button', { name: '啟用廣播' }));

    await waitFor(() => {
      expect(setSpikeBroadcast).toHaveBeenCalledTimes(1);
    });
    expect(errorSpy).toHaveBeenCalled();
    expect(successSpy).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByDisplayValue(/VPN 中斷/)).toBeTruthy();
  });

  it('shows server expiry after a successful broadcast', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const successSpy = vi.spyOn(message, 'success').mockImplementation(() => undefined as never);
    setSpikeBroadcast.mockResolvedValue({ expiresAt: '2026-09-21 15:00' });

    render(<BroadcastModal open onClose={onClose} defaultTopic="機房維護" />);

    await user.click(screen.getByRole('button', { name: '啟用廣播' }));

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1);
    });
    expect(successSpy).toHaveBeenCalledWith(
      expect.stringContaining('2026-09-21 15:00'),
    );
  });
});
