import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BrowserRouter } from 'react-router-dom';
import { CaseDetailHeader } from './CaseDetailHeader';

describe('CaseDetailHeader', () => {
  afterEach(() => {
    cleanup();
  });

  it('renders case header details and status correctly', () => {
    render(
      <BrowserRouter>
        <CaseDetailHeader
          caseId="CASE-2026-001"
          title="VPN 連線超時異常修復"
          status="TRIAGED"
          etag={1}
          ownerUnitId="INFRA-OPS"
          submitting={false}
          onBack={() => undefined}
          onTransition={() => undefined}
          onOpenDraftModal={() => undefined}
          onOpenResolveModal={() => undefined}
          onOpenCloseModal={() => undefined}
          onRefreshObservation={() => undefined}
        />
      </BrowserRouter>
    );

    expect(screen.getByText('VPN 連線超時異常修復')).toBeTruthy();
    expect(screen.getByText('CASE-2026-001')).toBeTruthy();
    expect(screen.getByText(/權責單位[:：]\s*INFRA-OPS/)).toBeTruthy();
  });

  it('calls onBack when the return button is clicked', async () => {
    const onBack = vi.fn();
    const user = userEvent.setup();

    render(
      <BrowserRouter>
        <CaseDetailHeader
          caseId="CASE-2026-002"
          title="登入驗證碼發送延遲"
          status="IN_PROGRESS"
          etag={2}
          submitting={false}
          onBack={onBack}
          onTransition={() => undefined}
          onOpenDraftModal={() => undefined}
          onOpenResolveModal={() => undefined}
          onOpenCloseModal={() => undefined}
          onRefreshObservation={() => undefined}
        />
      </BrowserRouter>
    );

    const backButton = screen.getByRole('button', { name: /返回案件列表/i });
    expect(backButton).toBeTruthy();
    await user.click(backButton);
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
