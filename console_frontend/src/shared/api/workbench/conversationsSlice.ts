import { ConversationDetail } from "../types";
import { postConversationAction, fetchConversations } from "./conversationsApi";
import { WorkbenchSliceContext } from "./storeCore";

export class ConversationsSlice {
  constructor(private readonly ctx: WorkbenchSliceContext) {}

  public getConversations(): ConversationDetail[] {
    return [...this.ctx.state.conversations];
  }

  public getConversationById(id: string): ConversationDetail | undefined {
    return this.ctx.state.conversations.find((c) => c.id === id);
  }

  public async loadConversations(): Promise<void> {
    try {
      const items = await fetchConversations();
      if (Array.isArray(items)) {
        this.ctx.state.conversations = items;
        this.ctx.notify();
      }
    } catch (err) {
      console.error("Failed to load conversations:", err);
      throw err;
    }
  }

  public async resolveConversation(conversationId: string): Promise<void> {
    const conv = this.ctx.state.conversations.find((c) => c.id === conversationId);
    if (conv) {
      conv.status = "RESOLVED";
      if (this.ctx.state.kpis.urgent_attention_count > 0) {
        this.ctx.state.kpis.urgent_attention_count -= 1;
      }
      this.ctx.notify();
    }

    await postConversationAction(conversationId, {
      action: "resolve",
    }).catch((err) => {
      console.error("Failed to resolve conversation on server:", err);
    });
  }

  public async setRootCause(
    conversationId: string,
    cause:
      | "OUTDATED_DOC"
      | "MISSING_KNOWLEDGE"
      | "MISUNDERSTOOD"
      | "HARDWARE_TICKET",
  ): Promise<void> {
    const conv = this.ctx.state.conversations.find((c) => c.id === conversationId);
    if (conv) {
      conv.root_cause = cause;
      this.ctx.notify();
    }

    await postConversationAction(conversationId, {
      action: "root_cause",
      root_cause: cause,
    }).catch((err) => {
      console.error("Failed to update root cause on server:", err);
    });
  }
}
