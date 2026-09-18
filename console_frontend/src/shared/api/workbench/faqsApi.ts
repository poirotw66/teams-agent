import { apiClient } from "../client";
import { FaqItem } from "../types";

export async function fetchFaqs(): Promise<FaqItem[]> {
  return apiClient<FaqItem[]>("/api/console/workbench/faqs");
}

export async function postFaq(params: {
  id?: string;
  question: string;
  answer: string;
  category: string;
  resolveConversationId?: string;
}): Promise<FaqItem> {
  return apiClient<FaqItem>("/api/console/workbench/faqs", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export async function deleteFaqRequest(faqId: string): Promise<void> {
  await apiClient(
    `/api/console/workbench/faqs/${encodeURIComponent(faqId)}`,
    {
      method: "DELETE",
    },
  );
}
