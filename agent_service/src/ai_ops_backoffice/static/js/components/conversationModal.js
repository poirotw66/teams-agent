import { api, el } from "../api.js";
import { actorCapabilities } from "../app/capabilities.js";
import { isBuShellEnabled } from "../app/buShellConfig.js";
import { saveNavFilters, syncLocationHash } from "../app/navigation.js";
import { navigateReturnTo } from "../app/returnTo.js";
import { badge } from "./badges.js";

function routeLabel(route) {
  const map = {
    FAQ: "固定答案 FAQ",
    KNOWLEDGE: "知識檢索",
    TICKET: "開立工單",
    HANDOFF: "轉人工",
    CLARIFICATION: "澄清追問",
    DIRECT: "直接回覆",
    ESCALATE: "升級處理",
    FAILED: "失敗",
  };
  return map[route] || route || "—";
}

function closeModalRoot() {
  const root = document.getElementById("modal-root");
  if (!root) return;
  root.hidden = true;
  root.replaceChildren();
}

function buildConversationBody(detail, conversationId, { onRefresh, onUnmask } = {}) {
  const content = el("div", "bu-conversation-detail");
  const allowed = actorCapabilities();
  const stateBadge = el(
    "div",
    "meta-chip",
    detail.dataState === "UNMASKED_WITH_REASON"
      ? "資料狀態：有理由未遮罩（已記錄稽核）"
      : "資料狀態：敏感資訊已遮罩",
  );
  content.append(stateBadge);

  const actions = el("div", "filter-bar");
  const refreshBtn = el("button", "", "重新整理");
  refreshBtn.type = "button";
  refreshBtn.addEventListener("click", async () => {
    refreshBtn.disabled = true;
    refreshBtn.textContent = "載入中…";
    try {
      const refreshed = await api(
        `/api/conversations/${encodeURIComponent(conversationId)}?refresh=true`,
      );
      onRefresh?.(refreshed, conversationId);
    } catch (error) {
      alert(`重新整理失敗: ${error.message}`);
      refreshBtn.disabled = false;
      refreshBtn.textContent = "重新整理";
    }
  });
  actions.append(refreshBtn);
  if (allowed.has("ops.conversations.unmasked") && !detail.unmaskAuthorized) {
    const unmaskButton = el("button", "", "申請查看未遮罩內容");
    unmaskButton.addEventListener("click", async () => {
      const reason = window.prompt("請輸入查看未遮罩內容的原因（至少 3 字）：");
      if (!reason || reason.trim().length < 3) {
        return;
      }
      const refreshed = await api(
        `/api/conversations/${encodeURIComponent(conversationId)}?${new URLSearchParams({
          unmask_reason: reason.trim(),
        })}`,
      );
      onUnmask?.(refreshed, conversationId);
    });
    actions.append(unmaskButton);
  }
  content.append(actions);

  const layout = el("div", "bu-case-layout");
  const main = el("section", "bu-case-main");
  const side = el("aside", "bu-case-side");
  side.append(el("h3", "", "本回合回答依據"));
  let selectedTurn = (detail.turns || [])[0] || null;

  function renderSide(turn) {
    side.replaceChildren(el("h3", "", "本回合回答依據"));
    if (!turn) {
      side.append(el("p", "muted", "尚無回合資料。"));
      return;
    }
    side.append(
      el("p", "", `處理方式 `),
    );
    side.append(badge(routeLabel(turn.route), "accent"));
    if (turn.faqKey) {
      side.append(el("p", "metric-label", `FAQ：${turn.faqKey}`));
    }
    if ((turn.documentIds || []).length) {
      side.append(el("p", "metric-label", `文件：${turn.documentIds.join(", ")}`));
    }
    if ((turn.sourcePaths || []).length) {
      side.append(el("p", "metric-label", `來源路徑：${turn.sourcePaths.join(", ")}`));
    }
    side.append(
      el(
        "p",
        "metric-label",
        `回饋：${turn.feedbackRating || "—"}｜解決：${turn.resolvedStatus || "—"}｜轉人工：${turn.handoffStatus || "—"}`,
      ),
    );
    if (turn.ticketId || turn.ticketStatus) {
      side.append(
        el(
          "p",
          "metric-label",
          `派工：${turn.ticketId || "—"} ${turn.ticketStatus ? `[${turn.ticketStatus}]` : ""}`,
        ),
      );
    }
    const tech = el("details");
    const summary = document.createElement("summary");
    summary.textContent = "技術詳情";
    tech.append(summary);
    tech.append(
      el(
        "pre",
        "json-block",
        JSON.stringify(
          {
            conversationId,
            turnId: turn.turnId || turn.occurredAt,
            model: turn.model,
            resultType: turn.resultType,
            events: turn.events,
          },
          null,
          2,
        ),
      ),
    );
    side.append(tech);
  }

  for (const turn of detail.turns || []) {
    const block = el("div", "message");
    block.style.cursor = "pointer";
    block.append(el("div", "meta", turn.occurredAt || ""));
    if (turn.messageMasked) {
      const user = el("div", "message user");
      user.append(el("div", "meta", "使用者"));
      user.append(el("p", "", turn.messageMasked));
      block.append(user);
    }
    if (turn.answerMasked) {
      block.append(el("p", "", turn.answerMasked));
      block.append(
        el(
          "small",
          "muted",
          `引用／處理：${turn.faqKey || (turn.documentIds || []).join(", ") || routeLabel(turn.route)}`,
        ),
      );
    }
    if (turn.feedbackRating === "DOWN") {
      block.append(badge("負評", "danger"));
    }
    block.addEventListener("click", () => {
      selectedTurn = turn;
      renderSide(turn);
    });
    main.append(block);
  }
  if (!(detail.turns || []).length) {
    main.append(el("p", "empty", "此對話尚無可顯示的回合。"));
  }
  renderSide(selectedTurn);
  layout.append(main, side);
  content.append(layout);
  return content;
}

export function showConversationPage(detail, conversationId = detail.conversationId) {
  const app = document.getElementById("app");
  const page = el("div", "bu-case-page");
  const crumb = el("div", "bu-case-crumb");
  const back = el("a", "", "← 返回");
  back.href = "#";
  back.addEventListener("click", (event) => {
    event.preventDefault();
    navigateReturnTo("conversations", {});
  });
  crumb.append(back, document.createTextNode(` / ${conversationId}`));
  page.append(crumb);
  page.append(el("h2", "", "對話紀錄"));
  page.append(
    el("p", "metric-label", "從使用者的提問，追到實際回答與引用依據。"),
  );
  const rerender = (nextDetail, nextId) => {
    showConversationPage(nextDetail, nextId);
  };
  page.append(
    buildConversationBody(detail, conversationId, {
      onRefresh: rerender,
      onUnmask: rerender,
    }),
  );
  app.replaceChildren(page);
}

export function showConversationModal(detail, conversationId = detail.conversationId) {
  if (isBuShellEnabled()) {
    saveNavFilters({ view: "conversations", conversationId });
    syncLocationHash("conversations", { conversationId });
    showConversationPage(detail, conversationId);
    return;
  }
  const root = document.getElementById("modal-root");
  root.hidden = false;
  root.replaceChildren();
  root.onclick = (e) => {
    if (e.target === root) {
      closeModalRoot();
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

  const heading = el("h2", "", `對話紀錄 ${conversationId}`);
  heading.style.margin = "0";

  const headerActions = el("div");
  headerActions.style.display = "flex";
  headerActions.style.gap = "0.5rem";
  headerActions.style.alignItems = "center";

  const close = el("button", "btn-modal-close", "關閉");
  close.addEventListener("click", () => closeModalRoot());
  headerActions.append(close);
  header.append(heading, headerActions);
  modal.append(header);
  modal.append(
    buildConversationBody(detail, conversationId, {
      onRefresh: showConversationModal,
      onUnmask: showConversationModal,
    }),
  );
  root.append(modal);
}
