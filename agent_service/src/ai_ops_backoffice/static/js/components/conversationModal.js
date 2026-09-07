import { api, el } from "../api.js";
import { actorCapabilities } from "../app/capabilities.js";
import { badge } from "./badges.js";

export function showConversationModal(detail, conversationId = detail.conversationId) {
  const root = document.getElementById("modal-root");
  root.hidden = false;
  root.replaceChildren();
  root.onclick = (e) => {
    if (e.target === root) {
      root.hidden = true;
      root.replaceChildren();
    }
  };
  const modal = el("section", "modal");
  const header = el("div", "modal-header");
  header.style.display = "flex";
  header.style.justifyContent = "space-between";
  header.style.alignItems = "center";
  header.style.marginBottom = "1rem";
  header.style.paddingBottom = "0.75rem";
  header.style.borderBottom = "1px solid var(--border-subtle, #e2e8f0)";

  const heading = el("h2", "", `對話記錄 Conversation ${conversationId}`);
  heading.style.margin = "0";

  const headerActions = el("div");
  headerActions.style.display = "flex";
  headerActions.style.gap = "0.5rem";
  headerActions.style.alignItems = "center";

  const refreshBtn = el("button", "", "🔄 重新整理");
  refreshBtn.type = "button";
  refreshBtn.title = "重新整理此對話最新內容";
  refreshBtn.addEventListener("click", async () => {
    refreshBtn.disabled = true;
    refreshBtn.textContent = "載入中…";
    try {
      const refreshed = await api(`/api/conversations/${encodeURIComponent(conversationId)}?refresh=true`);
      showConversationModal(refreshed, conversationId);
    } catch (e) {
      alert("重新整理失敗: " + e.message);
      refreshBtn.disabled = false;
      refreshBtn.textContent = "🔄 重新整理";
    }
  });

  const close = el("button", "btn-modal-close", "✕ 關閉");
  close.addEventListener("click", () => {
    root.hidden = true;
    root.replaceChildren();
  });
  headerActions.append(refreshBtn, close);
  header.append(heading, headerActions);
  modal.append(header);
  const allowed = actorCapabilities();
  if (allowed.has("ops.conversations.unmasked") && !detail.unmaskAuthorized) {
    const unmaskButton = el("button", "", "查看未遮罩內容");
    unmaskButton.addEventListener("click", async () => {
      const reason = window.prompt("請輸入查看未遮罩內容的原因（至少 3 字）：");
      if (!reason || reason.trim().length < 3) {
        return;
      }
      const refreshed = await api(
        `/api/conversations/${encodeURIComponent(conversationId)}?${new URLSearchParams({ unmask_reason: reason.trim() })}`,
      );
      showConversationModal(refreshed, conversationId);
    });
    modal.append(unmaskButton);
  }
  for (const turn of detail.turns || []) {
    const block = el("div", "panel");
    block.append(el("h3", "", turn.occurredAt));
    block.append(
      el(
        "p",
        "",
        `Issue: ${turn.issueTypeId || "-"}｜Route: ${turn.route || "-"}｜Model: ${turn.model || "-"}｜Result: ${turn.resultType || "-"}`,
      ),
    );
    if (turn.faqKey || (turn.documentIds || []).length) {
      block.append(
        el(
          "p",
          "",
          `FAQ: ${turn.faqKey || "-"}｜Documents: ${(turn.documentIds || []).join(", ") || "-"}`,
        ),
      );
    }
    block.append(
      el(
        "p",
        "",
        `Feedback: ${turn.feedbackRating || "-"}｜Resolved: ${turn.resolvedStatus || "-"}｜Handoff: ${turn.handoffStatus || "-"}｜Masked: ${turn.masked !== false}`,
      ),
    );
    if (turn.answerMasked) {
      block.append(el("p", "", `AI：${turn.answerMasked}`));
    }
    block.append(el("p", "", `使用者：${turn.messageMasked || ""}`));
    const events = el("pre", "", JSON.stringify(turn.events, null, 2));
    block.append(events);
    modal.append(block);
  }
  root.append(modal);
}
