import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { message } from 'antd';
import { ApiError } from '../../../shared/api/client';
import { ConversationDetail } from '../../../shared/api/types';
import { TriageActionPanel } from './TriageActionPanel';

const resolveConversation = vi.fn();
const setRootCause = vi.fn();
const createGoldenEvalCaseFromConversation = vi.fn();

vi.mock('@refinedev/core', () => ({
  useCan: () => ({ data: { can: true } }),
}));

vi.mock('../../../shared/api/workbenchStore', () => ({
  workbenchStore: {
    resolveConversation: (...args: unknown[]) => resolveConversation(...args),
    setRootCause: (...args: unknown[]) => setRootCause(...args),
  },
}));

vi.mock('../api/goldenEvalCases', () => ({
  createGoldenEvalCaseFromConversation: (...args: unknown[]) =>
    createGoldenEvalCaseFromConversation(...args),
}));

const conversation: ConversationDetail = {
  id: 'conv-ge-1',
  session_id: 'sess-ge-1',
  reporter_name: '王小明',
  reporter_dept: '財務部',
  started_at: '2026-09-21 10:00',
  status: 'PENDING_REVIEW',
  category: 'VPN',
  topic_summary: 'VPN 連線失敗',
  messages: [
    {
      id: 'm1',
      sender: 'user',
      content: 'VPN 連不上怎麼辦？',
      timestamp: '10:00:01',
    },
  ],
};

describe('TriageActionPanel mutation feedback', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    resolveConversation.mockReset();
    setRootCause.mockReset();
    createGoldenEvalCaseFromConversation.mockReset();
  });

  it('does not show success when resolve fails', async () => {
    const user = userEvent.setup();
    const successSpy = vi.spyOn(message, 'success').mockImplementation(() => undefined as never);
    const errorSpy = vi.spyOn(message, 'error').mockImplementation(() => undefined as never);
    resolveConversation.mockRejectedValue(new ApiError('resolve failed', 500));

    render(
      <TriageActionPanel
        conversation={conversation}
        onOpenQuickFaq={() => undefined}
        onOpenEscalateModal={() => undefined}
      />,
    );

    await user.click(screen.getByRole('button', { name: /標記結案/ }));

    await waitFor(() => {
      expect(resolveConversation).toHaveBeenCalledWith('conv-ge-1');
    });
    expect(errorSpy).toHaveBeenCalled();
    expect(successSpy).not.toHaveBeenCalled();
  });

  it('shows the created case id after Golden Eval API succeeds', async () => {
    const user = userEvent.setup();
    const successSpy = vi.spyOn(message, 'success').mockImplementation(() => undefined as never);
    createGoldenEvalCaseFromConversation.mockResolvedValue({
      caseId: 'case_abc',
      revisionId: 'rev_1',
    });

    render(
      <TriageActionPanel
        conversation={conversation}
        onOpenQuickFaq={() => undefined}
        onOpenEscalateModal={() => undefined}
      />,
    );

    await user.click(screen.getByRole('button', { name: /加入 Golden Eval/ }));

    await waitFor(() => {
      expect(createGoldenEvalCaseFromConversation).toHaveBeenCalledWith(conversation);
    });
    expect(successSpy).toHaveBeenCalledWith(expect.stringContaining('case_abc'));
  });

  it('does not claim Golden Eval success when the API fails', async () => {
    const user = userEvent.setup();
    const successSpy = vi.spyOn(message, 'success').mockImplementation(() => undefined as never);
    const errorSpy = vi.spyOn(message, 'error').mockImplementation(() => undefined as never);
    createGoldenEvalCaseFromConversation.mockRejectedValue(
      new ApiError('missing capability', 403),
    );

    render(
      <TriageActionPanel
        conversation={conversation}
        onOpenQuickFaq={() => undefined}
        onOpenEscalateModal={() => undefined}
      />,
    );

    await user.click(screen.getByRole('button', { name: /加入 Golden Eval/ }));

    await waitFor(() => {
      expect(createGoldenEvalCaseFromConversation).toHaveBeenCalled();
    });
    expect(errorSpy).toHaveBeenCalled();
    expect(successSpy).not.toHaveBeenCalled();
  });
});
