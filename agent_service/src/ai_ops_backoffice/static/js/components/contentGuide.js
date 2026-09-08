/** Shared FAQ vs Knowledge document guidance for Knowledge Ops. */

import { el } from "../api.js";

export const CONTENT_POLICY = {
  title: "固定答案與知識文件是兩種內容，不會自動互抄",
  body:
    "FAQ（固定答案）給使用者一字不差的標準回覆，啟用後會落檔保存；知識文件給 RAG 檢索與引用。" +
    "兩者可手動標「相關」，但改一邊不會改另一邊的內文，也不會自動灌進對方的索引。",
};

export const FAQ_WHEN = [
  "答案短、必須一字不差",
  "高頻標準流程（例如重設密碼）",
  "需要快速啟用／停用",
  "可穩定對到一個 FAQ Key／Issue 類型",
];

export const DOCUMENT_WHEN = [
  "SOP、手冊、長文或含圖說明",
  "需要引用段落、多文件來源",
  "問題說法多變、靠語意檢索較合適",
  "需要發布版本與索引狀態",
];

/**
 * Recommend FAQ vs document for a quality case using plain business rules.
 * @param {{ description?: string, title?: string, issue_type_id?: string, negative_rate?: number }} qualityCase
 * @returns {{ type: "FAQ" | "DOCUMENT", reason: string }}
 */
export function recommendContentType(qualityCase = {}) {
  const text = `${qualityCase.title || ""} ${qualityCase.description || ""}`.trim();
  const length = text.length;
  const hasIssue = Boolean(qualityCase.issue_type_id);

  if (length >= 400) {
    return {
      type: "DOCUMENT",
      reason: "案件描述較長，較適合寫成知識文件供檢索引用。",
    };
  }
  if (hasIssue && length > 0 && length < 280) {
    return {
      type: "FAQ",
      reason: "已有 Issue 類型且說明偏短，較適合做成固定答案 FAQ。",
    };
  }
  if (hasIssue) {
    return {
      type: "FAQ",
      reason: "已指定 Issue 類型，可先做 FAQ；若需長文再補知識文件並手動關聯。",
    };
  }
  return {
    type: "DOCUMENT",
    reason: "尚未指定 Issue 類型，建議先寫知識文件；確認標準答法後再補 FAQ。",
  };
}

export function renderContentPolicyBanner() {
  const box = el("div", "content-guide");
  box.append(
    el("strong", "content-guide-title", CONTENT_POLICY.title),
    el("p", "content-guide-body", CONTENT_POLICY.body),
  );
  return box;
}

export function renderDecisionGuide({ recommended } = {}) {
  const box = el("div", "content-guide content-guide-decision");
  box.append(el("strong", "content-guide-title", "什麼時候用哪一種？"));

  const grid = el("div", "content-guide-grid");
  const faqCol = el("div", "content-guide-col");
  faqCol.append(el("h4", "", "用固定答案 FAQ"));
  const faqList = el("ul");
  for (const item of FAQ_WHEN) faqList.append(el("li", "", item));
  faqCol.append(faqList);

  const docCol = el("div", "content-guide-col");
  docCol.append(el("h4", "", "用知識文件"));
  const docList = el("ul");
  for (const item of DOCUMENT_WHEN) docList.append(el("li", "", item));
  docCol.append(docList);

  grid.append(faqCol, docCol);
  box.append(grid);

  if (recommended) {
    const label = recommended.type === "FAQ" ? "固定答案 FAQ" : "知識文件";
    box.append(
      el(
        "p",
        "content-guide-recommend",
        `建議先做：${label}。${recommended.reason}`,
      ),
    );
  }

  box.append(
    el(
      "p",
      "content-guide-note",
      "若兩邊都要：先完成主路徑，再用「手動關聯」互指；系統不會自動同步內文。",
    ),
  );
  return box;
}
