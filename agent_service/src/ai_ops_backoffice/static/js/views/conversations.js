import { api, el } from "../api.js";
import { periodParams, createPeriodControls } from "../components/period.js";
import { badge } from "../components/badges.js";
import { showContentModal } from "../components/modal.js";
import { showConversationModal, showConversationPage } from "../components/conversationModal.js";
import { runExport } from "../services/export.js";
import { getCurrentActiveView } from "../app/activeView.js";
import { loadNavFilters, saveNavFilters, syncLocationHash, buildLocationHash, workspaceForView } from "../app/navigation.js";
import { createPageController } from "../app/lifecycle.js";
import { isBuShellEnabled } from "../app/buShellConfig.js";
import { formatTaipeiDateTime, formatUserFacingError, labelRoute } from "../app/labels.js";

let conversationPollTimer = null;
let conversationAutoRefresh = false;
let conversationPollInFlight = false;
let currentConversationState = {
  period: { preset: "30d" },
  filters: {},
  cursor: "",
  history: [],
};

const CONVERSATION_FILTER_KEYS = [
  "conversationId",
  "query",
  "source",
  "channelScope",
  "issueTypeId",
  "route",
  "model",
  "actorRef",
  "hasFeedback",
  "handoff",
  "turnId",
  "returnTo",
];

function pickConversationFilters(source = {}) {
  return Object.fromEntries(
    CONVERSATION_FILTER_KEYS
      .filter((key) => Object.prototype.hasOwnProperty.call(source, key))
      .map((key) => [key, source[key]]),
  );
}

export function stopConversationPolling() {
  if (conversationPollTimer) {
    clearInterval(conversationPollTimer);
    conversationPollTimer = null;
  }
}

function isConversationFilterEditing(active = document.activeElement) {
  if (!active || active === document.body || active === document.documentElement) {
    return false;
  }
  const activeId = active.id || "";
  const tag = (active.tagName || "").toLowerCase();
  if (activeId.startsWith("conversation-") || activeId.startsWith("custom-")) {
    return true;
  }
  if (tag === "input" || tag === "textarea" || tag === "select") {
    return Boolean(active.closest?.("#app"));
  }
  return Boolean(active.closest?.(".filter-bar, .bu-ops-note, .conversation-detail"));
}

function touchConversationsFreshness(suffix = "") {
  const badge = document.getElementById("conversations-freshness");
  if (!badge) return;
  const nowTime = new Date().toLocaleTimeString("zh-TW", { hour12: false });
  badge.textContent = suffix
    ? `最後更新：${nowTime}${suffix}`
    : `最後更新：${nowTime}`;
}

function isConversationDetailRoute() {
  const navFilters = loadNavFilters();
  return navFilters.view === "conversations" && Boolean(navFilters.conversationId);
}

function startConversationPolling() {
  stopConversationPolling();
  if (!conversationAutoRefresh) return;
  conversationPollTimer = setInterval(async () => {
    if (document.hidden || conversationPollInFlight || getCurrentActiveView() !== "conversations") {
      return;
    }
    // Polling owns the list only.  Re-rendering while a detail route is open
    // would replace the user's selected turn and scroll position with the list.
    if (isConversationDetailRoute()) {
      return;
    }
    if (isConversationFilterEditing()) {
      touchConversationsFreshness("（編輯中，暫不重整）");
      return;
    }
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
    if (!conversationPollInFlight && !isConversationDetailRoute()) {
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
    const routeState = navFilters.view === "conversations" ? navFilters : {};
    const routeEntry = state.view === "conversations";
    const period =
      state.period ||
      (routeState.view === "conversations" && (routeState.preset || routeState.start)
        ? {
            preset: routeState.preset || (routeState.start ? "custom" : "30d"),
            start: routeState.start || "",
            end: routeState.end || "",
          }
        : currentConversationState.period || { preset: "30d" });
    const stateFilters = state.filters
      ? pickConversationFilters(state.filters)
      : routeEntry
        ? pickConversationFilters(state)
        : {};
    const savedFilters = routeEntry
      ? { ...pickConversationFilters(routeState), ...stateFilters }
      : { ...(currentConversationState.filters || {}), ...stateFilters };
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
    const query =
      savedFilters.query ||
      (navFilters.view === "conversations" ? navFilters.query || "" : "");
    const source = savedFilters.source || "";
    const issueTypeId =
      savedFilters.issueTypeId ||
      (navFilters.view === "conversations" ? navFilters.issueTypeId : "");
    const turnId =
      savedFilters.turnId ||
      (navFilters.view === "conversations" ? navFilters.turnId : "");
    const route = savedFilters.route || "";
    const model = savedFilters.model || "";
    const actorRef = savedFilters.actorRef || "";
    const hasFeedback =
      savedFilters.hasFeedback ||
      (navFilters.view === "conversations" ? navFilters.hasFeedback || "" : "");
    const handoff = savedFilters.handoff || "";
    const channelScope =
      savedFilters.channelScope ||
      (navFilters.view === "conversations" ? navFilters.channelScope || "" : "");
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

    let detailError = null;
    if (
      isBuShellEnabled() &&
      conversationId &&
      !state.isPolling &&
      !state.skipDetail
    ) {
      try {
        const detail = await api(
          `/api/conversations/${encodeURIComponent(conversationId)}?refresh=true`,
        );
        showConversationPage(detail, conversationId, { selectedTurnId: turnId });
        return;
      } catch (error) {
        // The list request may still be healthy, but a deep-linked detail
        // failure must remain visible instead of becoming a misleading empty
        // result. Keep the list as recovery context and offer a safe retry.
        detailError = error;
      }
    }

    if (state.isPolling) {
      if (isConversationFilterEditing()) {
        touchConversationsFreshness("（編輯中，暫不重整）");
        return;
      }
      state._preserveScrollY = window.scrollY || document.documentElement.scrollTop || 0;
      state._preserveFocusId = document.activeElement?.id || "";
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

    const heading = el("h2", "", "對話紀錄");
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
      autoRefreshLabel.classList.toggle("is-ok", conversationAutoRefresh);
      autoRefreshText.textContent = conversationAutoRefresh
        ? "🟢 即時自動更新（5s）"
        : "⚡ 即時自動更新";
      if (conversationAutoRefresh) {
        startConversationPolling();
        touchConversationsFreshness("（已開啟自動更新）");
      } else {
        stopConversationPolling();
        touchConversationsFreshness("");
      }
      // Avoid full remount so the user does not lose filter focus when toggling.
    });

    const refreshButton = el("button", "button-secondary", "立即重新整理");
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
    if (isBuShellEnabled()) {
      panel.append(
        el("p", "metric-label", "從使用者的提問，追到實際回答與引用依據。"),
      );
    }

    if (detailError) {
      const detailErrorBox = el(
        "div",
        detailError.message === "FORBIDDEN" ? "forbidden" : "error",
      );
      detailErrorBox.append(
        el(
          "p",
          "",
          detailError.message === "FORBIDDEN"
            ? "目前角色無法查看這則對話詳情。列表範圍仍保留，未將此狀態當成沒有資料。"
            : `這則對話詳情暫時無法讀取：${formatUserFacingError(detailError)}`,
        ),
      );
      if (detailError.message !== "FORBIDDEN") {
        const retryDetail = el("button", "button-primary", "重試這則對話");
        retryDetail.type = "button";
        retryDetail.addEventListener("click", () => {
          void renderConversations({
            ...currentConversationState,
            forceRefresh: true,
            isPolling: false,
          });
        });
        detailErrorBox.append(retryDetail);
      }
      panel.append(detailErrorBox);
    }

    const filterBar = el("div", "filter-bar");
    const convIdInput = el("input");
    convIdInput.id = "conversation-id-filter";
    convIdInput.placeholder = "Conversation ID";
    convIdInput.value = conversationId || "";

    const queryInput = el("input");
    queryInput.id = "conversation-query-filter";
    queryInput.placeholder = isBuShellEnabled() ? "關鍵字（提問／回答）" : "訊息關鍵字 (Query)";
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
      '<option value="">全部轉人工</option><option value="true">有轉人工</option><option value="false">無轉人工</option>';
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
      ...(navFilters.returnTo ? { returnTo: navFilters.returnTo } : {}),
    });
    const applyAll = (nextPeriod = period) => {
      const nextFilters = currentFilters();
      const periodFields = {
        preset: nextPeriod.preset || "",
        start: nextPeriod.start || "",
        end: nextPeriod.end || "",
      };
      saveNavFilters({
        view: "conversations",
        ...nextFilters,
        ...periodFields,
      });
      syncLocationHash("conversations", {
        ...nextFilters,
        ...periodFields,
      });
      return renderConversations({
        period: nextPeriod,
        filters: nextFilters,
        cursor: "",
        history: [],
      });
    };
    const periodControls = createPeriodControls(
      period,
      (nextPeriod) => applyAll(nextPeriod),
      { hideApplyButton: isBuShellEnabled() },
    );
    const applyFilters = el(
      "button",
      isBuShellEnabled() ? "button-primary" : "",
      isBuShellEnabled() ? "套用篩選與期間" : "套用篩選",
    );
    applyFilters.addEventListener("click", () => {
      const nextPeriod = typeof periodControls.readPeriod === "function"
        ? periodControls.readPeriod()
        : period;
      return applyAll(nextPeriod);
    });
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

    if (isBuShellEnabled()) {
      filterBar.append(queryInput, channelSelect, feedbackSelect, applyFilters, exportButton);
      panel.append(filterBar);
      panel.append(periodControls);
      const advanced = el("details", "bu-ops-note");
      const activeExtras = [
        conversationId && `對話 ID`,
        source && `來源`,
        issueTypeId && `問題類型`,
        route && `處理方式`,
        model && `模型`,
        actorRef && `使用者`,
        handoff && `轉人工`,
      ].filter(Boolean);
      advanced.append(
        el(
          "summary",
          "",
          activeExtras.length ? `進階篩選（已套用 ${activeExtras.length} 項）` : "進階篩選",
        ),
      );
      const advancedBar = el("div", "filter-bar");
      advancedBar.append(
        convIdInput,
        sourceInput,
        issueInput,
        routeInput,
        modelInput,
        actorRefInput,
        handoffSelect,
      );
      advanced.append(advancedBar);
      panel.append(advanced);
      const chips = [];
      if (period.preset) chips.push(`期間：${period.preset}`);
      if (query) chips.push(`關鍵字：${query}`);
      if (channelScope) chips.push(`通道：${channelSelect.options[channelSelect.selectedIndex]?.text || channelScope}`);
      if (hasFeedback) chips.push(`回饋：${hasFeedback === "true" ? "有" : "無"}`);
      for (const extra of activeExtras) chips.push(extra);
      if (chips.length) {
        panel.append(el("p", "metric-label", `目前查詢：${chips.join(" · ")}`));
      }
    } else {
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
      panel.append(periodControls);
    }

    if (!data.items.length) {
      if (detailError) {
        panel.append(
          el(
            "p",
            "metric-label",
            "目前無法判定這則對話是否存在；請先重試，不會把錯誤計為 0 件。",
          ),
        );
      } else {
        panel.append(el("p", "empty", "目前沒有符合條件的對話事件。"));
      }
      app.replaceChildren(panel);
      return;
    }
    const table = el("table");
    if (isBuShellEnabled()) {
      table.innerHTML =
        "<thead><tr><th>提問摘要</th><th>時間</th><th>回合</th><th>使用者</th><th>通道</th><th>處理方式</th><th>派工／工單</th></tr></thead>";
    } else {
      table.innerHTML =
        "<thead><tr><th>時間／對話</th><th>回合</th><th>使用者</th><th>頻道</th><th>處理方式</th><th>派工／工單</th><th>最近更新</th></tr></thead>";
    }
    const body = el("tbody");
    for (const item of data.items) {
      const row = el("tr");
      const matchedTurn =
        item.turns?.find((turn) => turn.turnId === item.matchedTurnId) ||
        item.turns?.at(-1) ||
        item.turns?.[0] ||
        null;
      const selectedTurnId = item.matchedTurnId || matchedTurn?.turnId || "";
      const preview =
        matchedTurn?.userMessage ||
        matchedTurn?.messageMasked ||
        item.preview ||
        item.summary ||
        "";
      const shortId = String(item.conversationId || "").slice(0, 8);
      const detailHash = buildLocationHash(
        workspaceForView("conversations") || "knowledge_ops",
        "conversations",
        { conversationId: item.conversationId, turnId: selectedTurnId },
      );
      const link = el("a", "", isBuShellEnabled() ? preview || `對話 ${shortId}` : item.conversationId);
      link.href = detailHash;
      link.title = item.conversationId;
      link.addEventListener("click", async (event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
          return;
        }
        event.preventDefault();
        const detail = await api(`/api/conversations/${encodeURIComponent(item.conversationId)}?refresh=true`);
        if (isBuShellEnabled()) {
          saveNavFilters({
            view: "conversations",
            conversationId: item.conversationId,
            ...currentConversationState.filters,
            turnId: selectedTurnId,
            conversationId: item.conversationId,
            preset: currentConversationState.period.preset || "",
            start: currentConversationState.period.start || "",
            end: currentConversationState.period.end || "",
          });
          syncLocationHash("conversations", {
            conversationId: item.conversationId,
            turnId: selectedTurnId,
          });
          showConversationPage(detail, item.conversationId, {
            selectedTurnId,
          });
          return;
        }
        showConversationModal(detail, item.conversationId);
      });

      if (isBuShellEnabled()) {
        const summaryCell = el("td");
        summaryCell.append(link);
        const idRow = el("div", "metric-label");
        const idText = el("span", "", shortId);
        idText.title = item.conversationId;
        const copyBtn = el("button", "button-link", "複製 ID");
        copyBtn.type = "button";
        copyBtn.style.marginLeft = "0.4rem";
        copyBtn.addEventListener("click", async (event) => {
          event.preventDefault();
          event.stopPropagation();
          try {
            await navigator.clipboard.writeText(item.conversationId);
            copyBtn.textContent = "已複製";
            setTimeout(() => {
              copyBtn.textContent = "複製 ID";
            }, 1200);
          } catch {
            window.prompt("複製對話 ID", item.conversationId);
          }
        });
        idRow.append(idText, copyBtn);
        summaryCell.append(idRow);
        row.append(summaryCell);
        row.append(el("td", "", formatTaipeiDateTime(item.lastOccurredAt)));
        row.append(el("td", "", String(item.turnCount)));
        const actorShort = String(item.actorRef || "-");
        row.append(el("td", "", actorShort.length > 18 ? `${actorShort.slice(0, 14)}…` : actorShort));
      } else {
        const conversationCell = el("td");
        conversationCell.append(link);
        row.append(conversationCell);
        row.append(el("td", "", String(item.turnCount)));
        row.append(el("td", "", item.actorRef || "-"));
      }

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

      row.append(
        el(
          "td",
          "",
          (item.routes || []).map((code) => labelRoute(code)).join("、") || "-",
        ),
      );

      const dispatchCell = el("td");
      const badges = [];
      if (item.ticketIds && item.ticketIds.length > 0) {
        const tBadge = el("span", "meta-chip is-ok", `工單 ${item.ticketIds.join(", ")}`);
        tBadge.title = `Ticket: ${item.ticketIds.join(", ")} (狀態: ${item.ticketStatus || "CREATED"})`;
        badges.push(tBadge);
      }
      if (item.handoffStatus) {
        const hBadge = el("span", "meta-chip", `轉人工 ${item.handoffStatus}`);
        badges.push(hBadge);
      }
      if (badges.length > 0) {
        for (const b of badges) dispatchCell.append(b);
      } else {
        dispatchCell.textContent = "-";
      }
      row.append(dispatchCell);

      if (!isBuShellEnabled()) {
        row.append(el("td", "", item.lastOccurredAt));
      }
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
    if (state.isPolling) {
      if (Number.isFinite(state._preserveScrollY)) {
        const y = state._preserveScrollY;
        requestAnimationFrame(() => window.scrollTo(0, y));
      }
      if (state._preserveFocusId) {
        const focusEl = document.getElementById(state._preserveFocusId);
        if (focusEl && typeof focusEl.focus === "function") {
          focusEl.focus({ preventScroll: true });
        }
      }
    }
  } catch (error) {
    const wrap = el("div");
    if (isBuShellEnabled()) {
      wrap.append(el("h2", "", "對話紀錄"));
    }
    const keptFilters = currentConversationState.filters || {};
    const keptPeriod = currentConversationState.period || {};
    const kept = [];
    const keptFilterLabels = [
      ["query", "關鍵字"],
      ["conversationId", "對話 ID"],
      ["source", "來源"],
      ["issueTypeId", "問題類型"],
      ["route", "處理方式"],
      ["model", "模型"],
      ["actorRef", "使用者"],
      ["hasFeedback", "回饋"],
      ["handoff", "轉人工"],
      ["channelScope", "通道"],
    ];
    for (const [key, label] of keptFilterLabels) {
      if (keptFilters[key]) kept.push(`${label}：${keptFilters[key]}`);
    }
    if (keptPeriod.preset) kept.push(`期間：${keptPeriod.preset}`);
    if (keptPeriod.start || keptPeriod.end) {
      kept.push(`自訂：${keptPeriod.start || "—"} ~ ${keptPeriod.end || "—"}`);
    }
    if (kept.length) {
      wrap.append(el("p", "metric-label", `目前查詢條件仍保留：${kept.join(" · ")}`));
    }
    const isForbidden = error.message === "FORBIDDEN";
    const box = el("div", isForbidden ? "forbidden" : "error");
    box.append(el("p", "", formatUserFacingError(error)));
    if (!isForbidden) {
      const retry = el("button", "button-primary", "重試載入");
      retry.type = "button";
      retry.style.marginTop = "0.65rem";
      retry.addEventListener("click", () => {
        void renderConversations({
          ...currentConversationState,
          forceRefresh: true,
          isPolling: false,
        });
      });
      box.append(retry);
    }
    wrap.append(box);
    app.replaceChildren(wrap);
  }
}

export const conversationsPage = createPageController({
  enter: async (context = {}) => renderConversations(context.state || {}),
  update: async (context = {}) => renderConversations(context.state || {}),
  leave: async () => {
    stopConversationPolling();
  },
});
