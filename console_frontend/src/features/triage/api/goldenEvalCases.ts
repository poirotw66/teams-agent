import { backofficeClient } from '../../../shared/api/generated/backoffice-client';
import { loadAuthSession } from '../../../shared/auth/session';
import { ConversationDetail } from '../../../shared/api/types';

export type GoldenEvalCaseCreateResult = {
  caseId: string;
  revisionId?: string;
};

function resolveOwnerUnitId(): string {
  const stored = loadAuthSession();
  const fromSession = String(stored.ownerUnits || '')
    .split(',')
    .map((part) => part.trim())
    .find(Boolean);
  return fromSession || 'IT Service Desk';
}

function extractCaseIds(payload: Record<string, unknown>): GoldenEvalCaseCreateResult {
  const caseNode =
    payload.case && typeof payload.case === 'object'
      ? (payload.case as Record<string, unknown>)
      : payload;
  const revisionNode =
    payload.revision && typeof payload.revision === 'object'
      ? (payload.revision as Record<string, unknown>)
      : undefined;

  const caseId = String(caseNode.case_id || caseNode.caseId || '').trim();
  if (!caseId) {
    throw new Error('Golden Eval API 未回傳 case_id');
  }

  const revisionId = revisionNode
    ? String(revisionNode.revision_id || revisionNode.revisionId || '').trim() || undefined
    : undefined;

  return { caseId, revisionId };
}

/**
 * Persist a triage conversation as a Golden Eval case candidate.
 * Creates a case only; set membership / publish remain a separate workflow.
 */
export async function createGoldenEvalCaseFromConversation(
  conversation: ConversationDetail,
): Promise<GoldenEvalCaseCreateResult> {
  const firstUserMsg = conversation.messages.find((message) => message.sender === 'user');
  const query = (firstUserMsg?.content || conversation.topic_summary || '').trim();
  if (!query) {
    throw new Error('此對話沒有可用的提問內容，無法建立 Golden Eval 案例');
  }

  const title = (conversation.topic_summary || query).trim().slice(0, 200);
  const botMsg = conversation.messages.find((message) => message.sender === 'bot');

  const response = await backofficeClient.create_case_api_evaluations_cases_post({
    body: {
      title,
      query,
      owner_unit_id: resolveOwnerUnitId(),
      behavior: 'ANSWER_WITH_CITATION',
      reference_answer: botMsg?.content || undefined,
      source_type: 'CONVERSATION',
      source_id: conversation.id,
      tags: ['triage-conversation'],
      metadata: {
        conversation_id: conversation.id,
        reporter_dept: conversation.reporter_dept,
      },
    },
  });

  return extractCaseIds(response);
}
