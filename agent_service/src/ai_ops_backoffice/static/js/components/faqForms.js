import { el } from "../api.js";
import { faqField } from "./forms.js";

export function buildFaqForm(content = {}) {
  const form = el("form", "form-grid");
  const answerHint = el(
    "p",
    "metric-label",
    "固定答案會原樣回覆使用者，不會寫入知識庫 RAG 索引。長文／SOP 請改用知識文件，並可手動填相關文件 ID。",
  );
  form.append(
    faqField("FAQ Key", "faq_key", content.faq_key || ""),
    faqField("問題", "question", content.question || ""),
    faqField("固定答案", "answer", content.answer || "", true),
    answerHint,
    faqField("分類", "category", content.category || ""),
    faqField("關鍵字（逗號分隔）", "keywords", (content.keywords || []).join(",")),
    faqField("Owner Unit", "owner_unit_id", content.owner_unit_id || "IT Service Desk"),
    faqField("Business Contact", "business_contact", content.business_contact || "IT Service Desk"),
    faqField("Issue Type IDs（逗號分隔）", "issue_type_ids", (content.issue_type_ids || []).join(",")),
    faqField(
      "Audience Groups（逗號分隔；空白代表 ALL）",
      "audience_group_ids",
      (content.audience_group_ids || []).join(","),
      false,
      false,
    ),
    faqField(
      "相關知識文件 ID（逗號分隔；僅手動關聯，不同步內文）",
      "related_document_ids",
      (content.related_document_ids || []).join(","),
      false,
      false,
    ),
  );
  return form;
}

export function faqPayload(form) {
  const values = new FormData(form);
  const split = (name) => String(values.get(name) || "").split(",").map((item) => item.trim()).filter(Boolean);
  const groups = split("audience_group_ids");
  return {
    faq_key: values.get("faq_key"), question: values.get("question"),
    answer: values.get("answer"), category: values.get("category"),
    keywords: split("keywords"), owner_unit_id: values.get("owner_unit_id"),
    business_contact: values.get("business_contact"), issue_type_ids: split("issue_type_ids"),
    audience_type: groups.length ? "GROUPS" : "ALL", audience_group_ids: groups,
    related_document_ids: split("related_document_ids"),
  };
}
