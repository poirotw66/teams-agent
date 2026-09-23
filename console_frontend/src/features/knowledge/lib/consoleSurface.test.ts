import { describe, expect, it } from 'vitest';
import { defaultKnowledgePageTab, isCloudConsoleSurface } from './consoleSurface';

describe('isCloudConsoleSurface', () => {
  it('treats explicit CLOUD as cloud even when workspace stays LOCAL_SANDBOX', () => {
    expect(
      isCloudConsoleSurface({
        consoleSurface: 'CLOUD',
        knowledgeInProcess: true,
        knowledgeWorkspaceMode: 'LOCAL_SANDBOX',
      }),
    ).toBe(true);
  });

  it('treats knowledgeInProcess=false as cloud when surface is omitted', () => {
    expect(isCloudConsoleSurface({ knowledgeInProcess: false })).toBe(true);
  });

  it('keeps laptop Console local by default', () => {
    expect(isCloudConsoleSurface({ knowledgeInProcess: true })).toBe(false);
    expect(isCloudConsoleSurface({ knowledgeWorkspaceMode: 'LOCAL_SANDBOX' })).toBe(
      false,
    );
    expect(isCloudConsoleSurface(undefined)).toBe(false);
  });
});

describe('defaultKnowledgePageTab', () => {
  it('defaults cloud Console to the editable documents tab', () => {
    expect(defaultKnowledgePageTab({ consoleSurface: 'CLOUD' })).toBe('docs');
    expect(defaultKnowledgePageTab({ knowledgeInProcess: false })).toBe('docs');
  });

  it('defaults laptop Console to the mirror tab', () => {
    expect(defaultKnowledgePageTab({ knowledgeInProcess: true })).toBe(
      'cloud-mirror',
    );
    expect(defaultKnowledgePageTab(undefined)).toBe('cloud-mirror');
  });
});
