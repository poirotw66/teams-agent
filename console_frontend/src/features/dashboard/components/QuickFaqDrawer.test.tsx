import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { message } from 'antd';
import { ApiError } from '../../../shared/api/client';
import { QuickFaqDrawer } from './QuickFaqDrawer';

const quickSaveFaq = vi.fn();

vi.mock('../../../shared/api/workbenchStore', () => ({
  workbenchStore: {
    quickSaveFaq: (...args: unknown[]) => quickSaveFaq(...args),
  },
}));

describe('QuickFaqDrawer mutation feedback', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    quickSaveFaq.mockReset();
  });

  it('keeps the drawer open and does not claim success when save returns 5xx', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onSaved = vi.fn();
    const successSpy = vi.spyOn(message, 'success').mockImplementation(() => undefined as never);
    const errorSpy = vi.spyOn(message, 'error').mockImplementation(() => undefined as never);
    quickSaveFaq.mockRejectedValue(new ApiError('upstream failed', 503));

    render(
      <QuickFaqDrawer
        open
        onClose={onClose}
        onSaved={onSaved}
        initialData={{
          question: 'VPN 怎麼連？',
          category: '網路通訊',
          newAnswer: '請使用 GlobalProtect',
        }}
      />,
    );

    await user.click(screen.getByRole('button', { name: /儲存 FAQ/ }));

    await waitFor(() => {
      expect(quickSaveFaq).toHaveBeenCalledTimes(1);
    });
    expect(errorSpy).toHaveBeenCalled();
    expect(successSpy).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
    expect(screen.getByDisplayValue('VPN 怎麼連？')).toBeTruthy();
  });

  it('closes only after the save API resolves', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onSaved = vi.fn();
    const successSpy = vi.spyOn(message, 'success').mockImplementation(() => undefined as never);
    quickSaveFaq.mockResolvedValue({
      id: 'faq-1',
      questions: ['VPN 怎麼連？'],
      answer: '請使用 GlobalProtect',
      category: '網路通訊',
      updated_at: '2026-09-21',
    });

    render(
      <QuickFaqDrawer
        open
        onClose={onClose}
        onSaved={onSaved}
        initialData={{
          question: 'VPN 怎麼連？',
          category: '網路通訊',
          newAnswer: '請使用 GlobalProtect',
        }}
      />,
    );

    await user.click(screen.getByRole('button', { name: /儲存 FAQ/ }));

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1);
    });
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(successSpy).toHaveBeenCalledWith(
      expect.stringContaining('FAQ 已儲存成功'),
    );
  });
});
