import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../client';
import {
  createInitialWorkbenchState,
  createReloadHooksPlaceholder,
  WorkbenchSliceContext,
} from './storeCore';
import { ConversationsSlice } from './conversationsSlice';
import * as conversationsApi from './conversationsApi';

describe('ConversationsSlice mutations', () => {
  let ctx: WorkbenchSliceContext;
  let slice: ConversationsSlice;

  beforeEach(() => {
    const state = createInitialWorkbenchState();
    state.conversations = [
      {
        id: 'conv-1',
        session_id: 'sess-1',
        reporter_name: '王小明',
        reporter_dept: '財務部',
        started_at: '2026-09-21 10:00',
        status: 'PENDING_REVIEW',
        category: 'VPN',
        messages: [],
      },
    ];
    state.kpis.urgent_attention_count = 2;
    ctx = {
      state,
      notify: vi.fn(),
      reloads: createReloadHooksPlaceholder(),
    };
    slice = new ConversationsSlice(ctx);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('does not mark resolved or change KPI when the resolve API fails', async () => {
    vi.spyOn(conversationsApi, 'postConversationAction').mockRejectedValue(
      new ApiError('server unavailable', 503),
    );

    await expect(slice.resolveConversation('conv-1')).rejects.toBeInstanceOf(ApiError);

    expect(ctx.state.conversations[0]?.status).toBe('PENDING_REVIEW');
    expect(ctx.state.kpis.urgent_attention_count).toBe(2);
    expect(ctx.notify).not.toHaveBeenCalled();
  });

  it('updates local state only after resolve API succeeds', async () => {
    vi.spyOn(conversationsApi, 'postConversationAction').mockResolvedValue(undefined);

    await slice.resolveConversation('conv-1');

    expect(conversationsApi.postConversationAction).toHaveBeenCalledWith('conv-1', {
      action: 'resolve',
    });
    expect(ctx.state.conversations[0]?.status).toBe('RESOLVED');
    expect(ctx.state.kpis.urgent_attention_count).toBe(1);
    expect(ctx.notify).toHaveBeenCalled();
  });

  it('does not update root cause when the API fails', async () => {
    vi.spyOn(conversationsApi, 'postConversationAction').mockRejectedValue(
      new ApiError('forbidden', 403),
    );

    await expect(
      slice.setRootCause('conv-1', 'OUTDATED_DOC'),
    ).rejects.toBeInstanceOf(ApiError);

    expect(ctx.state.conversations[0]?.root_cause).toBeUndefined();
    expect(ctx.notify).not.toHaveBeenCalled();
  });

  it('updates root cause only after the API succeeds', async () => {
    vi.spyOn(conversationsApi, 'postConversationAction').mockResolvedValue(undefined);

    await slice.setRootCause('conv-1', 'MISSING_KNOWLEDGE');

    expect(conversationsApi.postConversationAction).toHaveBeenCalledWith('conv-1', {
      action: 'root_cause',
      root_cause: 'MISSING_KNOWLEDGE',
    });
    expect(ctx.state.conversations[0]?.root_cause).toBe('MISSING_KNOWLEDGE');
    expect(ctx.notify).toHaveBeenCalled();
  });
});
