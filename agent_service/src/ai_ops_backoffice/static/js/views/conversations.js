import { api, el } from "../api.js";
import { periodParams, createPeriodControls } from "../components/period.js";
import { badge } from "../components/badges.js";
import { showContentModal } from "../components/modal.js";
import { showConversationModal } from "../components/conversationModal.js";
import { runExport } from "../services/export.js";
import { getCurrentActiveView } from "../app/activeView.js";
import { loadNavFilters } from "../app/navigation.js";
import { createPageController } from "../app/lifecycle.js";

let conversationPollTimer = null;
let conversationAutoRefresh = false;
let conversationPollInFlight = false;
let currentConversationState = {
  period: { preset: "30d" },
  filters: {},
  cursor: "",
  history: [],
};

export function stopConversationPolling() {
  if (conversationPollTimer) {
    clearInterval(conversationPollTimer);
    conversationPollTimer = null;
  }
}

function startConversationPolling() {
  stopConversationPolling();
  if (!conversationAutoRefresh) return;
  conversationPollTimer = setInterval(async () => {
    if (document.hidden || conversationPollInFlight || getCurrentActiveView() !== "conversations") return;
    try {
      conversationPollInFlight = true;
      await renderConversations({
        ...currentConversationState,
        forceRefresh: true,
        isPolling: true,
      });
    } finally {
      conversationPollInFlight = false;
    }
  }, 5000);
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopConversationPolling();
  } else if (conversationAutoRefresh && getCurrentActiveView() === "conversations") {
    startConversationPolling();
    if (!conversationPollInFlight) {
      renderConversations({
        ...currentConversationState,
        forceRefresh: true,
        isPolling: true,
      });
    }
  }
});

export async function renderConversations(state = {}) {
  const app = document.getElementById("app");
  if (!state.isPolling) {
    app.replaceChildren(el("div", "empty", "載入中…"));
  }
  try {
    const navFilters = loadNavFilters();
    const period =
      state.period ||
      (navFilters.view === "conversations" && (navFilters.preset || navFilters.start)
        ? {
            preset: navFilters.preset || (navFilters.start ? "custom" : "30d"),
            start: navFilters.start || "",
            end: navFilters.end || "",
          }
        : currentConversationState.period || { preset: "30d" });
    const savedFilters = state.filters || currentConversationState.filters || {};
    const cursor = state.cursor !== undefined ? state.cursor : currentConversationState.cursor;
    const history = state.history !== undefined ? state.history : currentConversationState.history;

    currentConversationState = {
      period,
      filters: savedFilters,
      cursor,
      history,
    };

    const filters = periodParams(period);
    filters.set("limit", "25");
    if (cursor) filters.set("cursor", cursor);
    const conversationId =
      savedFilters.conversationId ||
      (navFilters.view === "conversations" ? navFilters.conversationId : "");
    const query = savedFilters.query || "";
    const source = savedFilters.source || "";
    const issueTypeId =
      savedFilters.issueTypeId ||
      (navFilters.view === "conversations" ? navFilters.issueTypeId : "");
    const route = savedFilters.route || "";
    const model = savedFilters.model || "";
    const actorRef = savedFilters.actorRef || "";
    const hasFeedback = savedFilters.hasFeedback || "";
    const handoff = savedFilters.handoff || "";
    const channelScope = savedFilters.channelScope || "";
    if (conversationId) filters.set("conversation_id", conversationId);
    if (query) filters.set("query", query);
    if (source) filters.set("source", source);
    if (issueTypeId) filters.set("issue_type_id", issueTypeId);
    if (route) filters.set("route", route);
    if (model) filters.set("model", model);
    if (actorRef) filters.set("actor_ref", actorRef);
    if (hasFeedback) filters.set("has_feedback", hasFeedback);
    if (handoff) filters.set("handoff", handoff);
    if (channelScope) filters.set("channel_scope", channelScope);
    if (state.forceRefresh) filters.set("refresh", "true");

    const data = await api(`/api/conversations?${filters.toString()}`);

    if (state.isPolling) {
      const activeId = document.activeElement?.id;
      if (activeId && activeId.startsWith("conversation-")) {
        const badge = document.getElementById("conversations-freshness");
        if (badge) {
          const nowTime = new Date().toLocaleTimeString("zh-TW", { hour12: false });
          badge.textContent = `最後更新：${nowTime}`;
        }
        return;
      }
    }

    const panel = el("section", "panel");

    // Header with Title & Real-time Live Controls
    const headerRow = el("div", "split");
    headerRow.style.display = "flex";
    headerRow.style.justifyContent = "space-between";
    headerRow.style.alignItems = "center";
    headerRow.style.marginBottom = "0.75rem";
    headerRow.style.flexWrap = "wrap";
    headerRow.style.gap = "0.75rem";

    const heading = el("h2", "", "對話紀錄（遮罩摘要）");
    heading.style.margin = "0";

    const liveControls = el("div", "meta-group");
    liveControls.style.display = "flex";
    liveControls.style.alignItems = "center";
    liveControls.style.gap = "0.6rem";

    const nowTime = new Date().toLocaleTimeString("zh-TW", { hour12: false });
    const freshnessBadge = el("span", "meta-chip", `最後更新：${nowTime}`);
    freshnessBadge.id = "conversations-freshness";
    freshnessBadge.title = "目前對話清單資料抓取時間點";

    const autoRefreshLabel = el(
      "label",
      `meta-chip is-button ${conversationAutoRefresh ? "is-ok" : ""}`
    );
    autoRefreshLabel.style.cursor = "pointer";
    autoRefreshLabel.style.display = "inline-flex";
    autoRefreshLabel.style.alignItems = "center";
    autoRefreshLabel.style.gap = "0.35rem";
    autoRefreshLabel.title = "每 5 秒自動重新整理對話清單，即時呈現最新對話紀錄";

    const autoRefreshCheckbox = el("input");
    autoRefreshCheckbox.type = "checkbox";
    autoRefreshCheckbox.checked = conversationAutoRefresh;
    autoRefreshCheckbox.style.margin = "0";
    autoRefreshCheckbox.style.cursor = "pointer";

    const autoRefreshText = el(
      "span",
      "",
      conversationAutoRefresh ? "🟢 即時自動更新（5s）" : "⚡ 即時自動更新"
    );
    autoRefreshLabel.append(autoRefreshCheckbox, autoRefreshText);

    autoRefreshCheckbox.addEventListener("change", () => {
      conversationAutoRefresh = autoRefreshCheckbox.checked;
      if (conversationAutoRefresh) {
        startConversationPolling();
      } else {
        stopConversationPolling();
      }
      renderConversations({
        ...currentConversationState,
        forceRefresh: true,
      });
    });

    const refreshButton = el("button", "button-primary", "🔄 立即重新整理");
    refreshButton.type = "button";
    refreshButton.title = "即刻向後端取得最新對話記錄（繞過暫存）";
    refreshButton.addEventListener("click", () => {
      renderConversations({
        ...currentConversationState,
        forceRefresh: true,
      });
    });

    liveControls.append(freshnessBadge, autoRefreshLabel, refreshButton);
    headerRow.append(heading, liveControls);
    panel.append(headerRow);

    const filterBar = el("div", "filter-bar");
    const convIdInput = el("input");
    convIdInput.id = "conversation-id-filter";
    convIdInput.placeholder = "Conversation ID";
    convIdInput.value = conversationId || "";

    const queryInput = el("input");
    queryInput.id = "conversation-query-filter";
    queryInput.placeholder = "訊息關鍵字 (Query)";
    queryInput.value = query || "";

    const sourceInput = el("input");
    sourceInput.id = "conversation-source-filter";
    sourceInput.placeholder = "來源 (Doc / Path / FAQ)";
    sourceInput.value = source || "";

    const channelSelect = el("select", "");
    channelSelect.id = "conversation-channel-scope";
    channelSelect.innerHTML =
      '<option value="">全部通道</option><option value="playground">Playground 測試</option><option value="personal">Teams 個人 (1:1)</option><option value="channel">Teams 頻道</option><option value="group_chat">群組對話</option>';
    if (channelScope) channelSelect.value = channelScope;

    const issueInput = el("input");
    issueInput.id = "conversation-issue-type";
    issueInput.placeholder = "Issue Type ID";
    issueInput.value = issueTypeId || "";
    const routeInput = el("input");
    routeInput.id = "conversation-route";
    routeInput.placeholder = "Route";
    routeInput.value = route;
    const modelInput = el("input");
    modelInput.id = "conversation-model";
    modelInput.placeholder = "Model";
    modelInput.value = model;
    const actorRefInput = el("input");
    actorRefInput.id = "conversation-actor-ref";
    actorRefInput.placeholder = "Actor Ref / User ID";
    actorRefInput.value = actorRef || "";
    const feedbackSelect = el("select", "");
    feedbackSelect.id = "conversation-has-feedback";
    feedbackSelect.innerHTML =
      '<option value="">全部回饋</option><option value="true">有回饋</option><option value="false">無回饋</option>';
    if (hasFeedback) feedbackSelect.value = hasFeedback;
    const handoffSelect = el("select", "");
    handoffSelect.id = "conversation-handoff";
    handoffSelect.innerHTML =
      '<option value="">全部 Handoff</option><option value="true">有 Handoff</option><option value="false">無 Handoff</option>';
    if (handoff) handoffSelect.value = handoff;
    const currentFilters = () => ({
      conversationId: convIdInput.value.trim(),
      query: queryInput.value.trim(),
      source: sourceInput.value.trim(),
      channelScope: channelSelect.value,
      issueTypeId: issueInput.value.trim(),
      route: routeInput.value.trim(),
      model: modelInput.value.trim(),
      actorRef: actorRefInput.value.trim(),
      hasFeedback: feedbackSelect.value,
      handoff: handoffSelect.value,
    });
    const applyFilters = el("button", "", "套用篩選");
    applyFilters.addEventListener("click", () =>
      renderConversations({ period, filters: currentFilters(), cursor: "", history: [] }),
    );
    const exportButton = el("button", "", "匯出 CSV");
    exportButton.addEventListener("click", async () => {
      const reasonPrompt = window.prompt("請輸入匯出原因（至少 3 個字元，將寫入資安稽核紀錄）：", "對話紀錄分析與稽核");
      if (!reasonPrompt || reasonPrompt.trim().length < 3) {
        if (reasonPrompt !== null) {
          alert("匯出原因必須至少 3 個字元。");
        }
        return;
      }
      exportButton.disabled = true;
      exportButton.textContent = "匯出中…";
      const queryFilters = {
        conversation_id: convIdInput.value.trim() || undefined,
        query: queryInput.value.trim() || undefined,
        source: sourceInput.value.trim() || undefined,
        channel_scope: channelSelect.value || undefined,
        issue_type_id: issueInput.value.trim() || undefined,
        route: routeInput.value.trim() || undefined,
        model: modelInput.value.trim() || undefined,
        actor_ref: actorRefInput.value.trim() || undefined,
        has_feedback: feedbackSelect.value ? feedbackSelect.value === "true" : undefined,
        handoff: handoffSelect.value ? handoffSelect.value === "true" : undefined,
        ...Object.fromEntries(periodParams(period)),
      };
      try {
        await runExport("csv", "conversations", 30, queryFilters, reasonPrompt.trim());
      } catch (error) {
        showContentModal("匯出失敗", el("div", "error", error.message));
      } finally {
        exportButton.disabled = false;
        exportButton.textContent = "匯出 CSV";
      }
    });
    filterBar.append(
      convIdInput,
      queryInput,
      sourceInput,
      channelSelect,
      issueInput,
      routeInput,
      modelInput,
      actorRefInput,
      feedbackSelect,
      handoffSelect,
      applyFilters,
      exportButton,
    );
    panel.append(filterBar);
    panel.append(
      createPeriodControls(period, (nextPeriod) =>
        renderConversations({
          period: nextPeriod,
          filters: currentFilters(),
          cursor: "",
          history: [],
        }),
      ),
    );

    if (!data.items.length) {
      panel.append(el("p", "empty", "目前沒有符合條件的對話事件。"));
      app.replaceChildren(panel);
      return;
    }
    const table = el("table");
    table.innerHTML =
      "<thead><tr><th>Conversation</th><th>Turns</th><th>Actor</th><th>Channel</th><th>Routes</th><th>派工／工單</th><th>Last Seen</th></tr></thead>";
    const body = el("tbody");
    for (const item of data.items) {
      const row = el("tr");
      const link = el("a", "", item.conversationId);
      link.href = "#";
      link.addEventListener("click", async (event) => {
        event.preventDefault();
        const detail = await api(`/api/conversations/${encodeURIComponent(item.conversationId)}?refresh=true`);
        showConversationModal(detail, item.conversationId);
      });
      const conversationCell = el("td");
      conversationCell.append(link);
      row.append(conversationCell);
      row.append(el("td", "", String(item.turnCount)));
      row.append(el("td", "", item.actorRef || "-"));

      const channelCell = el("td");
      const channelTag = el("span", "meta-chip");
      if (item.channelScope === "playground") {
        channelTag.className = "meta-chip is-ok";
        channelTag.textContent = "Playground";
      } else if (item.channelScope === "personal") {
        channelTag.textContent = "Teams 個人";
      } else if (item.channelScope === "channel") {
        channelTag.textContent = "Teams 頻道";
      } else if (item.channelScope === "group_chat" || item.channelScope === "groupchat") {
        channelTag.textContent = "群組";
      } else {
        channelTag.textContent = item.channelScope || "-";
      }
      channelCell.append(channelTag);
      row.append(channelCell);

      row.append(el("td", "", (item.routes || []).join(", ") || "-"));

      const dispatchCell = el("td");
      const badges = [];
      if (item.ticketIds && item.ticketIds.length > 0) {
        const tBadge = el("span", "meta-chip is-ok", `🎫 ${item.ticketIds.join(", ")}`);
        tBadge.title = `Ticket: ${item.ticketIds.join(", ")} (狀態: ${item.ticketStatus || "CREATED"})`;
        badges.push(tBadge);
      }
      if (item.handoffStatus) {
        const hBadge = el("span", "meta-chip", `🤝 ${item.handoffStatus}`);
        badges.push(hBadge);
      }
      if (badges.length > 0) {
        for (const b of badges) dispatchCell.append(b);
      } else {
        dispatchCell.textContent = "-";
      }
      row.append(dispatchCell);

      row.append(el("td", "", item.lastOccurredAt));
      body.append(row);
    }
    table.append(body);
    const convScroll = el("div", "table-responsive");
    convScroll.append(table);
    panel.append(convScroll);
    const pager = el("div", "filter-bar");
    if (history.length) {
      const previous = el("button", "", "上一頁");
      previous.addEventListener("click", () =>
        renderConversations({
          period,
          filters: currentFilters(),
          cursor: history.at(-1),
          history: history.slice(0, -1),
        }),
      );
      pager.append(previous);
    }
    if (data.nextCursor) {
      const next = el("button", "", "下一頁");
      next.addEventListener("click", () =>
        renderConversations({
          period,
          filters: currentFilters(),
          cursor: data.nextCursor,
          history: [...history, state.cursor || ""],
        }),
      );
      pager.append(next);
    }
    if (pager.childElementCount) panel.append(pager);
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

export const conversationsPage = createPageController({
  enter: async (context = {}) => renderConversations(context.state || {}),
  update: async (context = {}) => renderConversations(context.state || {}),
  leave: async () => {
    stopConversationPolling();
  },
});
