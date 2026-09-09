/** Unified content maintenance hub for FAQ + Knowledge documents. */

import { api, el } from "../api.js";
import {
  renderContentPolicyBanner,
  renderDecisionGuide,
} from "../components/contentGuide.js";
import { actorCapabilities, canUseKnowledgeUi } from "../app/capabilities.js";
import { drillLink, navigateTo } from "../app/navigation.js";
import { createPageController } from "../app/lifecycle.js";
import { isBuShellEnabled } from "../app/buShellConfig.js";

async function renderContentHub(panel, state = {}) {
  // BU shell: skip hub card hop — go straight to knowledge lists.
  if (isBuShellEnabled()) {
    const tab =
      state.type === "FAQ" ? "faq" : state.type === "DOCUMENT" ? "documents" : "documents";
    void navigateTo("contentLists", { tab });
    return;
  }

  const allowed = actorCapabilities();
  const type = state.type || "ALL";

  const heading = el("h2", "", "內容維護");
  const guide = renderContentPolicyBanner();
  const decision = renderDecisionGuide();
  const actions = el("div", "filter-bar");
  for (const [value, label] of [
    ["ALL", "全部類型"],
    ["FAQ", "固定答案 FAQ"],
    ["DOCUMENT", "知識文件"],
  ]) {
    const button = el("button", type === value ? "button-primary" : "", label);
    button.addEventListener("click", () => renderContentHub(panel, { type: value }));
    actions.append(button);
  }

  const body = el("div");
  if (type === "ALL" || type === "FAQ") {
    const faqCard = el("section", "panel");
    faqCard.append(
      el("h3", "", "固定答案 FAQ"),
      el(
        "p",
        "metric-label",
        "啟用後會落檔（主檔＋版本匯出），供稽核保存；Agent 仍以固定答案回覆，不進 RAG。",
      ),
    );
    if (allowed.has("ops.faq.read")) {
      try {
        const data = await api("/api/faqs");
        faqCard.append(el("p", "", `目前可見 ${data.total || 0} 筆 FAQ。`));
        const list = el("ul");
        for (const item of (data.items || []).slice(0, 8)) {
          list.append(
            el(
              "li",
              "",
              `${item.version?.content?.question || item.faq.faq_key}（${item.faq.status}）`,
            ),
          );
        }
        if ((data.items || []).length) faqCard.append(list);
      } catch (error) {
        faqCard.append(el("div", "error", error.message));
      }
      const openFaq = el("button", "", "開啟 FAQ 管理");
      openFaq.addEventListener("click", () => navigateTo("faq"));
      faqCard.append(openFaq);
    } else {
      faqCard.append(el("div", "forbidden", "沒有 FAQ 讀取權限。"));
    }
    body.append(faqCard);
  }

  if (type === "ALL" || type === "DOCUMENT") {
    const docCard = el("section", "panel");
    docCard.append(
      el("h3", "", "知識文件"),
      el(
        "p",
        "metric-label",
        "Markdown／PDF 經審核發布後進入知識索引，供 RAG 檢索引用。",
      ),
    );
    if (canUseKnowledgeUi()) {
      docCard.append(
        drillLink("開啟知識文件庫", "knowledgePortal"),
        drillLink("查看內容成效", "knowledge"),
      );
    } else {
      docCard.append(el("div", "forbidden", "知識文件庫未啟用或沒有讀取權限。"));
    }
    body.append(docCard);
  }

  panel.replaceChildren(heading, guide, decision, actions, body);
}

function showContentHub() {
  if (isBuShellEnabled()) {
    return navigateTo("contentLists", { tab: "documents" });
  }
  const panel = el("section", "panel");
  document.getElementById("app").replaceChildren(panel);
  return renderContentHub(panel);
}

export const contentHubPage = createPageController({
  enter: showContentHub,
  update: showContentHub,
  leave: async () => {},
});
