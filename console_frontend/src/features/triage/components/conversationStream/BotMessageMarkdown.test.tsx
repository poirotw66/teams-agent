import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BotMessageMarkdown } from './BotMessageMarkdown';

describe('BotMessageMarkdown', () => {
  afterEach(() => {
    cleanup();
  });

  it('renders markdown content and citation badge labels', () => {
    render(
      <BotMessageMarkdown
        content={'請參考 [S1] VPN 手冊'}
        citations={[
          {
            document_id: 'doc-vpn',
            document_title: 'VPN 操作手冊',
            similarity_score: 95,
            snippet: '重設步驟',
            updated_at: '2026-09-10',
            source_type: 'DOCUMENT',
          },
        ]}
        onSelectCitation={() => undefined}
      />,
    );

    expect(screen.getByText(/請參考/)).toBeTruthy();
    expect(screen.getByTitle('點擊查看引用依據：S1')).toBeTruthy();
  });

  it('invokes onSelectCitation when a citation badge is clicked', async () => {
    const onSelectCitation = vi.fn();
    const user = userEvent.setup();

    render(
      <BotMessageMarkdown
        content={'來源標記 [S1]'}
        onSelectCitation={onSelectCitation}
      />,
    );

    await user.click(screen.getByTitle('點擊查看引用依據：S1'));
    expect(onSelectCitation).toHaveBeenCalledWith('S1', undefined);
  });
});
