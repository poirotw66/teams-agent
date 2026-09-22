/** Knowledge workspace mode client (LOCAL_SANDBOX vs CLOUD_FORMAL). */

import { apiClient } from '../client';

export type KnowledgeWorkspacePayload = {
  knowledgeWorkspaceMode: string;
  cloudFormalWritesAllowed: boolean;
  cloudFormalWriteBlockReasons?: string[];
  cloudFormalWriteBlockReasonLabels?: string[];
  knowledgeWorkspaceSwitchAllowed?: boolean;
  knowledgeWorkspaceOverrideActive?: boolean;
  knowledgeWorkspaceModeSource?: string;
  authMode?: string;
  relaxedWorkflow?: boolean;
};

export async function fetchKnowledgeWorkspace(): Promise<KnowledgeWorkspacePayload> {
  return apiClient<KnowledgeWorkspacePayload>('/api/knowledge-workspace');
}

export async function setKnowledgeWorkspaceMode(
  mode: 'LOCAL_SANDBOX' | 'CLOUD_FORMAL',
  reason?: string,
): Promise<KnowledgeWorkspacePayload> {
  return apiClient<KnowledgeWorkspacePayload>('/api/knowledge-workspace', {
    method: 'PUT',
    body: JSON.stringify({
      knowledgeWorkspaceMode: mode,
      reason: reason || null,
    }),
  });
}

/** Clear durable override and restore env default. */
export async function resetKnowledgeWorkspaceMode(): Promise<KnowledgeWorkspacePayload> {
  return apiClient<KnowledgeWorkspacePayload>('/api/knowledge-workspace', {
    method: 'DELETE',
  });
}
