import { FaqItem } from "../types";
import { deleteFaqRequest, fetchFaqs, postFaq } from "./faqsApi";
import { WorkbenchSliceContext } from "./storeCore";

export class FaqsSlice {
  constructor(private readonly ctx: WorkbenchSliceContext) {}

  public getFaqs(): FaqItem[] {
    return [...this.ctx.state.faqs];
  }

  public async loadFaqs(): Promise<void> {
    try {
      const items = await fetchFaqs();
      if (Array.isArray(items)) {
        this.ctx.state.faqs = items;
        this.ctx.notify();
      }
    } catch (err) {
      console.error("Failed to load FAQs:", err);
      throw err;
    }
  }

  public async quickSaveFaq(params: {
    id?: string;
    question: string;
    answer: string;
    category: string;
    resolveConversationId?: string;
  }): Promise<FaqItem> {
    const saved = await postFaq(params);

    const existingIndex = this.ctx.state.faqs.findIndex((f) => f.id === saved.id);
    if (existingIndex >= 0) {
      this.ctx.state.faqs[existingIndex] = saved;
    } else {
      this.ctx.state.faqs.unshift(saved);
    }

    if (params.resolveConversationId) {
      const conv = this.ctx.state.conversations.find(
        (c) => c.id === params.resolveConversationId,
      );
      if (conv) {
        conv.status = "RESOLVED";
      }
    }

    this.ctx.notify();
    // Refresh only FAQ + overview surfaces affected by a FAQ write.
    void Promise.allSettled([
      this.ctx.reloads.loadFaqs(),
      this.ctx.reloads.loadOverview(),
    ]);
    return saved;
  }

  public async deleteFaq(faqId: string): Promise<void> {
    await deleteFaqRequest(faqId);
    this.ctx.state.faqs = this.ctx.state.faqs.filter((f) => f.id !== faqId);
    this.ctx.notify();
  }
}
