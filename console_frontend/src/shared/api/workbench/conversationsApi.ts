import { apiClient } from "../client";
import { ConversationDetail } from "../types";

export async function fetchConversations(): Promise<ConversationDetail[]> {
  return apiClient<ConversationDetail[]>(
    "/api/console/workbench/conversations",
  );
}

export async function postConversationAction(
  conversationId: string,
  body: Record<string, unknown>,
): Promise<void> {
  await apiClient(
    `/api/console/workbench/conversations/${encodeURIComponent(conversationId)}/action`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}
