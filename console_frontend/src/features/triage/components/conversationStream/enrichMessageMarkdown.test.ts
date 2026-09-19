import { describe, expect, it } from 'vitest';
import { enrichMessageMarkdown } from './enrichMessageMarkdown';

describe('enrichMessageMarkdown', () => {
  it('returns empty string for empty input', () => {
    expect(enrichMessageMarkdown('')).toBe('');
  });

  it('normalizes problem and resolution headers', () => {
    const out = enrichMessageMarkdown('問題：VPN 連不上\n處理方式：重開連線');
    expect(out).toContain('**問題：** VPN 連不上');
    expect(out).toContain('**處理方式：**');
  });

  it('turns citation markers into markdown links', () => {
    const out = enrichMessageMarkdown('請參考 [S1] 與 [POLICY-SEC-001]。');
    expect(out).toContain('[S1](#citation-S1)');
    expect(out).toContain('[POLICY-SEC-001](#citation-POLICY-SEC-001)');
  });

  it('unpacks inline numbered steps into list lines', () => {
    const out = enrichMessageMarkdown('步驟如下：1. 開啟設定 2. 重試連線');
    expect(out).toMatch(/1\.\s+開啟設定/);
    expect(out).toMatch(/\n2\.\s+重試連線/);
  });
});
