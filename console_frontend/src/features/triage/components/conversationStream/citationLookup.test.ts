import { describe, expect, it } from 'vitest';
import { isPolicyCitation, resolveCitation } from './citationLookup';
import type { CitationItem } from '../../../../shared/api/types';

const sampleCitations: CitationItem[] = [
  {
    document_id: 'doc-vpn',
    document_title: 'VPN 操作手冊',
    similarity_score: 95,
    snippet: '如何重設 VPN',
    updated_at: '2026-09-10',
    source_type: 'DOCUMENT',
  },
];

describe('resolveCitation', () => {
  it('resolves S-rank citations by list index', () => {
    const cite = resolveCitation('S1', sampleCitations);
    expect(cite.document_id).toBe('doc-vpn');
    expect(cite.document_title).toContain('VPN');
  });

  it('builds a policy advisory for known POLICY-SEC ids', () => {
    const cite = resolveCitation('POLICY-SEC-001');
    expect(cite.is_policy).toBe(true);
    expect(cite.policy_id).toBe('POLICY-SEC-001');
    expect(cite.source_type).toBe('POLICY_ADVISORY');
    expect(cite.document_title).toContain('POLICY-SEC-001');
  });

  it('falls back to a placeholder document citation', () => {
    const cite = resolveCitation('missing-id');
    expect(cite.document_id).toBe('missing-id');
    expect(cite.document_title).toContain('missing-id');
  });
});

describe('isPolicyCitation', () => {
  it('detects policy advisories', () => {
    const cite = resolveCitation('POLICY-SEC-002');
    expect(isPolicyCitation(cite)).toBe(true);
  });

  it('returns false for ordinary documents', () => {
    expect(isPolicyCitation(sampleCitations[0])).toBe(false);
  });
});
