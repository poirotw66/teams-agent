import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../../shared/api/client';
import { createGoldenEvalCaseFromConversation } from './goldenEvalCases';
import { ConversationDetail } from '../../../shared/api/types';

const createCase = vi.fn();

vi.mock('../../../shared/api/generated/backoffice-client', () => ({
  backofficeClient: {
    create_case_api_evaluations_cases_post: (...args: unknown[]) => createCase(...args),
  },
}));

vi.mock('../../../shared/auth/session', () => ({
  loadAuthSession: () => ({ ownerUnits: 'IT Service Desk' }),
}));

const conversation: ConversationDetail = {
  id: 'conv-42',
  session_id: 'sess-42',
  reporter_name: '李小華',
  reporter_dept: '資訊部',
  started_at: '2026-09-21 11:00',
  status: 'PENDING_REVIEW',
  category: 'EMAIL',
  topic_summary: 'Outlook 同步異常',
  messages: [
    {
      id: 'u1',
      sender: 'user',
      content: 'Outlook 無法同步怎麼辦？',
      timestamp: '11:00:01',
    },
    {
      id: 'b1',
      sender: 'bot',
      content: '請重新登入 Outlook 並檢查網路。',
      timestamp: '11:00:05',
    },
  ],
};

describe('createGoldenEvalCaseFromConversation', () => {
  afterEach(() => {
    createCase.mockReset();
    vi.restoreAllMocks();
  });

  it('posts a CONVERSATION-sourced case and returns the case id', async () => {
    createCase.mockResolvedValue({
      case: { case_id: 'case_99' },
      revision: { revision_id: 'rev_99' },
    });

    const result = await createGoldenEvalCaseFromConversation(conversation);

    expect(createCase).toHaveBeenCalledWith({
      body: expect.objectContaining({
        title: 'Outlook 同步異常',
        query: 'Outlook 無法同步怎麼辦？',
        owner_unit_id: 'IT Service Desk',
        source_type: 'CONVERSATION',
        source_id: 'conv-42',
        behavior: 'ANSWER_WITH_CITATION',
      }),
    });
    expect(result).toEqual({ caseId: 'case_99', revisionId: 'rev_99' });
  });

  it('propagates API failures without inventing a case id', async () => {
    createCase.mockRejectedValue(new ApiError('forbidden', 403));

    await expect(createGoldenEvalCaseFromConversation(conversation)).rejects.toBeInstanceOf(
      ApiError,
    );
  });
});
