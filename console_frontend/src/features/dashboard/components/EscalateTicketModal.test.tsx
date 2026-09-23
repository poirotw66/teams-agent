import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { message } from 'antd';
import { ApiError } from '../../../shared/api/client';
import { EscalateTicketModal } from './EscalateTicketModal';

const escalateTicket = vi.fn();

vi.mock('../../../shared/api/workbenchStore', () => ({
  workbenchStore: {
    escalateTicket: (...args: unknown[]) => escalateTicket(...args),
  },
}));

describe('EscalateTicketModal mutation feedback', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    escalateTicket.mockReset();
  });

  it('keeps the modal open and shows an error when ticket create returns 5xx', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const successSpy = vi.spyOn(message, 'success').mockImplementation(() => undefined as never);
    const errorSpy = vi.spyOn(message, 'error').mockImplementation(() => undefined as never);
    escalateTicket.mockRejectedValue(new ApiError('jira unavailable', 503));

    render(
      <EscalateTicketModal
        open
        onClose={onClose}
        initialData={{
          conversationId: 'conv-1',
          reporterName: '王小明',
          reporterDept: '財務部',
          title: '筆電進水',
          chatSnippet: '螢幕破裂無法開機',
        }}
      />,
    );

    await user.click(screen.getByRole('button', { name: /確認送出開單/ }));

    await waitFor(() => {
      expect(escalateTicket).toHaveBeenCalledTimes(1);
    });
    expect(errorSpy).toHaveBeenCalled();
    expect(successSpy).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByDisplayValue('筆電進水')).toBeTruthy();
  });
});
