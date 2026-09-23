import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { ConsoleSurfaceIdentity } from '../lib/consoleSurface';

const identityState: { current: ConsoleSurfaceIdentity | undefined } = {
  current: undefined,
};

vi.mock('@refinedev/core', () => ({
  useGetIdentity: () => ({ data: identityState.current }),
}));

vi.mock('../../../shared/api/workbenchStore', () => ({
  workbenchStore: {
    getDocuments: () => [],
    getFaqs: () => [],
    getKnowledgeGaps: () => [],
    ensureDomains: () => Promise.resolve(),
    subscribe: () => () => undefined,
  },
}));

vi.mock('../components/ManualDocsManager', () => ({
  ManualDocsManager: () => <div>editable-documents-workbench</div>,
}));

vi.mock('../components/FaqManager', () => ({
  FaqManager: () => <div>faq-manager</div>,
}));

vi.mock('../components/KnowledgeGapsManager', () => ({
  KnowledgeGapsManager: () => <div>gaps-manager</div>,
}));

vi.mock('../components/PlaygroundSimulator', () => ({
  PlaygroundSimulator: () => <div>playground</div>,
}));

vi.mock('../components/CloudFormalMirrorDocs', () => ({
  CloudFormalMirrorDocs: () => <div>gcs-snapshot</div>,
}));

vi.mock('../components/KnowledgeWorkspaceBanner', () => ({
  KnowledgeWorkspaceBanner: () => null,
}));

vi.mock('../components/KnowledgeSyncLagBanner', () => ({
  KnowledgeSyncLagBanner: () => null,
}));

vi.mock('../components/FormalPublishProgressBanner', () => ({
  FormalPublishProgressBanner: () => null,
}));

vi.mock('../../../shared/ui/WorkbenchLoadErrorBanner', () => ({
  WorkbenchLoadErrorBanner: () => null,
}));

vi.mock('../../dashboard/components/QuickFaqDrawer', () => ({
  QuickFaqDrawer: () => null,
}));

describe('KnowledgePage default tab', () => {
  afterEach(() => {
    cleanup();
    identityState.current = undefined;
  });

  it('opens the editable documents tab on cloud Console', async () => {
    identityState.current = {
      consoleSurface: 'CLOUD',
      knowledgeInProcess: false,
      knowledgeWorkspaceMode: 'LOCAL_SANDBOX',
    };
    const { KnowledgePage } = await import('./KnowledgePage');
    render(
      <MemoryRouter>
        <KnowledgePage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('tab', { name: /知識文件/ }).getAttribute('aria-selected')).toBe(
      'true',
    );
    expect(screen.getByText('editable-documents-workbench')).toBeTruthy();
    expect(screen.queryByText('本機測試工作區 (0)')).toBeNull();
    expect(screen.getByText('正式 Agent 目前載入')).toBeTruthy();
  });

  it('keeps the laptop default on the mirror tab', async () => {
    identityState.current = {
      knowledgeInProcess: true,
      knowledgeWorkspaceMode: 'LOCAL_SANDBOX',
    };
    const { KnowledgePage } = await import('./KnowledgePage');
    render(
      <MemoryRouter>
        <KnowledgePage />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole('tab', { name: /雲端正式鏡像/ }).getAttribute('aria-selected'),
    ).toBe('true');
    expect(screen.getByText('本機測試工作區 (0)')).toBeTruthy();
    expect(screen.getByText('gcs-snapshot')).toBeTruthy();
  });
});
