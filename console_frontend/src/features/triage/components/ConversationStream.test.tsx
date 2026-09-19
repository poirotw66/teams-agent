import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ConversationStream } from './ConversationStream';
import { ConversationDetail } from '../../../shared/api/types';

describe('ConversationStream', () => {
  afterEach(() => {
    cleanup();
  });

  it('renders placeholder when no conversation is selected', () => {
    render(<ConversationStream conversation={null} />);
    expect(screen.getByText('請從左側佇列中選擇一筆對話進行檢視與分診')).toBeTruthy();
  });

  it('renders conversation messages and reporter metadata', () => {
    const mockConversation: ConversationDetail = {
      id: 'conv-123',
      session_id: 'sess-123',
      reporter_name: '王小明',
      reporter_dept: '財務部',
      reporter_ext: '1234',
      started_at: '2026-09-19 10:00',
      status: 'RESOLVED',
      category: 'VPN',
      messages: [
        {
          id: 'msg-1',
          sender: 'user',
          content: '請問如何連線公司 VPN？',
          timestamp: '10:00:05',
        },
        {
          id: 'msg-2',
          sender: 'bot',
          content: '請依照 [S1] 指引設定 VPN Client。',
          timestamp: '10:00:15',
          citations: [
            {
              document_id: 'doc-vpn-guide',
              document_title: 'VPN 操作手冊 v2',
              similarity_score: 98,
              snippet: '下載 GlobalProtect 並輸入 portal 網址。',
              updated_at: '2026-09-15',
              source_type: 'DOCUMENT',
            },
          ],
        },
      ],
    };

    render(<ConversationStream conversation={mockConversation} />);

    expect(screen.getByText(/財務部 - 王小明/)).toBeTruthy();
    expect(screen.getByText(/已結案/)).toBeTruthy();
    expect(screen.getByText('請問如何連線公司 VPN？')).toBeTruthy();
    expect(screen.getByText(/請依照/)).toBeTruthy();
  });

  it('opens citation drawer on citation badge click', async () => {
    const user = userEvent.setup();
    const mockConversation: ConversationDetail = {
      id: 'conv-456',
      session_id: 'sess-456',
      reporter_name: '李小華',
      reporter_dept: '資訊部',
      started_at: '2026-09-19 11:00',
      status: 'PENDING_REVIEW',
      category: 'EMAIL',
      messages: [
        {
          id: 'msg-10',
          sender: 'bot',
          content: '參考資料 [S1]',
          timestamp: '11:00:10',
          citations: [
            {
              document_id: 'doc-email-faq',
              document_title: '企業信箱設定常見問題',
              similarity_score: 92,
              snippet: '設定 IMAP/SMTP 伺服器資訊。',
              updated_at: '2026-09-12',
              source_type: 'DOCUMENT',
            },
          ],
        },
      ],
    };

    render(<ConversationStream conversation={mockConversation} />);

    // Initially 1 instance in CitationList
    expect(screen.getAllByText('企業信箱設定常見問題').length).toBe(1);

    const citationBadge = screen.getByTitle('點擊查看引用依據：S1');
    expect(citationBadge).toBeTruthy();
    await user.click(citationBadge);

    // After clicking, the citation drawer opens and displays the title in the drawer header
    expect(screen.getAllByText('企業信箱設定常見問題').length).toBeGreaterThanOrEqual(2);
  });
});
