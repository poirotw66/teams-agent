import { CitationItem } from '../../../../shared/api/types';
import { GLOBAL_SECURITY_POLICIES } from './securityPolicies';

/** Resolve a citation identifier (S1, POLICY-SEC-*, document_id, etc.) to a CitationItem. */
export function resolveCitation(
  identifier: string,
  citations?: CitationItem[]
): CitationItem {
  const list = citations || [];
  let target: CitationItem | undefined;

  // Match by rank S1, S2, etc.
  const sMatch = identifier.match(/^S(\d+)$/i);
  if (sMatch) {
    const idx = parseInt(sMatch[1], 10) - 1;
    if (list[idx]) {
      target = list[idx];
    }
  }

  // Match by document_id or chunk_id or policy_id
  if (!target) {
    target = list.find(
      (c) =>
        c.document_id === identifier ||
        c.chunk_id === identifier ||
        c.policy_id === identifier ||
        (c.document_title && c.document_title.includes(identifier))
    );
  }

  // Fallback for security policy
  if (!target && identifier.startsWith('POLICY-SEC-')) {
    const pol = GLOBAL_SECURITY_POLICIES[identifier];
    if (pol) {
      target = {
        document_id: identifier,
        document_title: `${pol.title} (${identifier})`,
        similarity_score: 100,
        snippet: pol.summary,
        content: pol.body,
        updated_at: '2026-09-10',
        source_type: 'POLICY_ADVISORY',
        is_policy: true,
        policy_id: identifier,
      };
    }
  }

  if (!target) {
    target = {
      document_id: identifier,
      document_title: `引用資料來源 (${identifier})`,
      similarity_score: 90,
      snippet: '此項目為對話標註之引用依據。',
      updated_at: '2026-09-10',
      source_type: 'DOCUMENT',
    };
  }

  return target;
}

export function isPolicyCitation(cite: CitationItem): boolean {
  return Boolean(
    cite.is_policy ||
      cite.source_type === 'POLICY_ADVISORY' ||
      (cite.chunk_id && cite.chunk_id.startsWith('POLICY-SEC'))
  );
}
