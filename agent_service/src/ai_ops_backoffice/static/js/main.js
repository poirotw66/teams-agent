import { api, el, metric, ensureAuth, authHeaders } from "./api.js";

const routes = {
  overview: renderOverview,
  conversations: renderConversations,
  issues: renderIssues,
  routes: renderRoutes,
  costs: renderCosts,
  health: renderHealth,
  knowledge: renderKnowledge,
  quality: renderQuality,
  audit: renderAudit,
};

const navItems = [
  ["overview", "營運總覽", "ops.summary.read"],
  ["conversations", "對話紀錄", "ops.conversations.read"],
  ["issues", "Issue 分析", "ops.issues.read"],
  ["routes", "路由來源", "ops.issues.read"],
  ["costs", "成本分析", "ops.cost.read"],
  ["health", "系統健康度", "ops.health.read"],
  ["knowledge", "知識營運", "ops.knowledge.read"],
  ["quality", "品質改善", "ops.feedback.read"],
  ["audit", "稽核紀錄", "ops.audit.read"],
];

const NAV_FILTERS_KEY = "ai_ops_nav_filters";

function saveNavFilters(filters) {
  sessionStorage.setItem(NAV_FILTERS_KEY, JSON.stringify(filters));
}

function loadNavFilters() {
  const raw = sessionStorage.getItem(NAV_FILTERS_KEY);
  if (!raw) {
    return {};
  }
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

function clearNavFilters() {
  sessionStorage.removeItem(NAV_FILTERS_KEY);
}

function navigateTo(view, filters = {}) {
  saveNavFilters({ view, ...filters });
  renderNav(view);
}

function drillLink(label, view, filters = {}) {
  const link = el("a", "drill-link", label);
  link.href = "#";
  link.addEventListener("click", (event) => {
    event.preventDefault();
    navigateTo(view, filters);
  });
  return link;
}

function periodSelect(current = "7d") {
  const select = el("select", "");
  select.innerHTML = `
    <option value="today">今天</option>
    <option value="7d">最近 7 天</option>
    <option value="30d">最近 30 天</option>
    <option value="month">本月</option>
    <option value="6m">最近 6 個月</option>
    <option value="custom">自訂期間</option>
  `;
  select.value = current;
  return select;
}

function customPeriodInputs(startValue = "", endValue = "") {
  const wrap = el("div", "filter-bar");
  const start = el("input");
  start.type = "date";
  start.id = "custom-start-date";
  start.value = startValue;
  const end = el("input");
  end.type = "date";
  end.id = "custom-end-date";
  end.value = endValue;
  wrap.append(el("label", "", "開始"), start, el("label", "", "結束"), end);
  return wrap;
}

function buildPeriodQuery(prefix = "") {
  const presetEl = document.getElementById(`${prefix}overview-preset`);
  const preset = presetEl?.value || "7d";
  if (preset === "custom") {
    const start = document.getElementById(`${prefix}custom-start-date`)?.value;
    const end = document.getElementById(`${prefix}custom-end-date`)?.value;
    const params = new URLSearchParams();
    if (start) params.set("start_date", `${start}T00:00:00+08:00`);
    if (end) params.set("end_date", `${end}T23:59:59+08:00`);
    return params.toString();
  }
  return `preset=${encodeURIComponent(preset)}`;
}

function periodParams(state = { preset: "30d" }) {
  const params = new URLSearchParams();
  if (state.preset === "custom") {
    if (state.start) params.set("start_date", `${state.start}T00:00:00+08:00`);
    if (state.end) params.set("end_date", `${state.end}T23:59:59+08:00`);
  } else {
    params.set("preset", state.preset || "30d");
  }
  return params;
}

function createPeriodControls(state, onApply) {
  const controls = el("div", "filter-bar");
  const select = periodSelect(state.preset || "30d");
  select.setAttribute("aria-label", "分析期間");
  const custom = customPeriodInputs(state.start || "", state.end || "");
  custom.hidden = select.value !== "custom";
  select.addEventListener("change", () => {
    custom.hidden = select.value !== "custom";
  });
  const apply = el("button", "", "套用期間");
  apply.addEventListener("click", () => {
    const inputs = custom.querySelectorAll("input");
    onApply({
      preset: select.value,
      start: inputs[0]?.value || "",
      end: inputs[1]?.value || "",
    });
  });
  controls.append(select, custom, apply);
  return controls;
}

function attributionText(attribution = {}) {
  const labels = {
    faqKeys: "FAQ",
    documentIds: "Document",
    versionIds: "Version",
    releaseIds: "Release",
  };
  const parts = [];
  for (const [key, label] of Object.entries(labels)) {
    const values = (attribution[key] || []).map((item) => `${item.id} (${item.count})`);
    if (values.length) parts.push(`${label}: ${values.join(", ")}`);
  }
  return parts.join(" | ") || "-";
}

function showContentModal(title, content) {
  const root = document.getElementById("modal-root");
  root.hidden = false;
  root.replaceChildren();
  const modal = el("section", "modal");
  const close = el("button", "", "關閉");
  close.addEventListener("click", () => {
    root.hidden = true;
    root.replaceChildren();
  });
  modal.append(el("h2", "", title), close, content);
  root.append(modal);
}

function showConversationModal(detail, conversationId = detail.conversationId) {
  const root = document.getElementById("modal-root");
  root.hidden = false;
  root.replaceChildren();
  const modal = el("section", "modal");
  const close = el("button", "", "關閉");
  close.addEventListener("click", () => {
    root.hidden = true;
    root.replaceChildren();
  });
  modal.append(el("h2", "", `Conversation ${conversationId}`), close);
  const allowed = new Set(capabilities?.capabilities || []);
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

let capabilities = null;

async function boot() {
  const authConfig = await fetch("/api/auth/config").then((response) => response.json());
  await ensureAuth(authConfig);
  capabilities = await api("/api/capabilities");
  renderNav("overview");
  document.getElementById("meta-panel").textContent =
    `角色：${capabilities.role}｜驗證：${capabilities.authMode}｜資料更新：即時讀取 Analytics Store`;
}

function renderNav(active) {
  const nav = document.getElementById("nav");
  nav.replaceChildren();
  const allowed = new Set(capabilities?.capabilities || []);
  for (const [id, label, capability] of navItems) {
    if (capability && !allowed.has(capability)) {
      continue;
    }
    const button = el("button", active === id ? "active" : "", label);
    button.addEventListener("click", () => {
      renderNav(id);
      routes[id]();
    });
    nav.append(button);
  }
  routes[active]();
}

async function renderOverview() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  const preset = document.getElementById("overview-preset")?.value || "7d";
  try {
    const data = await api(`/api/operations/summary?${buildPeriodQuery()}`);
    const panel = el("section", "panel");
    const filterBar = el("div", "filter-bar");
    const select = periodSelect(preset);
    select.id = "overview-preset";
    select.addEventListener("change", () => {
      const custom = document.getElementById("overview-custom-period");
      if (custom) {
        custom.hidden = select.value !== "custom";
      }
    });
    const apply = el("button", "", "套用期間");
    apply.addEventListener("click", () => renderOverview());
    filterBar.append(select, apply);
    const customPeriod = customPeriodInputs(
      document.getElementById("custom-start-date")?.value || "",
      document.getElementById("custom-end-date")?.value || "",
    );
    customPeriod.id = "overview-custom-period";
    customPeriod.hidden = preset !== "custom";
    filterBar.append(customPeriod);
    panel.append(filterBar);
    panel.append(el("h2", "", `營運總覽（${data.periodPreset}）`));
    const grid = el("div", "grid");
    grid.append(
      metric("Conversation", data.conversationCount),
      metric("Turn", data.turnCount),
      metric("Active User", data.activeUserCount),
      metric("Issue", data.issueOccurrenceCount),
      metric("Knowledge 回答", data.knowledgeAnswerCount),
      metric("FAQ 回答", data.faqAnswerCount),
      metric("無答案", data.noAnswerCount ?? 0),
      metric("澄清", data.clarificationCount ?? 0),
      metric("Handoff", data.handoffCount),
      metric("Ticket", data.ticketCount),
      metric("負評", data.negativeFeedbackCount),
      metric("已解決回饋", data.resolvedFeedbackCount ?? 0),
      metric("Total Tokens", data.totalTokens ?? 0),
      metric("估算成本 USD", data.estimatedCostUsd),
      metric("成本完整率", data.costCoverage),
      metric("錯誤率", data.errorRate ?? 0),
      metric("P50 延遲 ms", data.p50LatencyMs ?? "-"),
      metric("P95 延遲 ms", data.p95LatencyMs ?? "-"),
    );
    panel.append(el("p", "", `資料更新：${data.updatedAt}｜時區：${data.timezone}`));
    if (data.dataDelayWarning) {
      panel.append(el("div", "warning", data.dataDelayWarning));
    }
    const drillBar = el("div", "filter-bar");
    drillBar.append(
      drillLink("查看 Issue 分析", "issues"),
      drillLink("查看負評回饋", "quality", { rating: "DOWN" }),
      drillLink("查看成本", "costs"),
      drillLink("查看路由", "routes"),
    );
    panel.append(drillBar);
    panel.append(grid);
    const table = el("table");
    table.innerHTML = "<thead><tr><th>Issue Type</th><th>Count</th><th>動作</th></tr></thead>";
    const body = el("tbody");
    for (const item of data.topIssueTypes || []) {
      const row = el("tr");
      row.append(el("td", "", item.issueTypeId));
      row.append(el("td", "", String(item.count)));
      const actions = el("td", "");
      actions.append(
        drillLink("Issue", "issues", { issueTypeId: item.issueTypeId }),
        document.createTextNode(" "),
        drillLink("路由", "routes", { issueTypeId: item.issueTypeId }),
      );
      row.append(actions);
      body.append(row);
    }
    table.append(body);
    panel.append(table);

    const definitions = data.metricDefinitions || {};
    if (Object.keys(definitions).length) {
      panel.append(el("h3", "", "指標定義"));
      const defTable = el("table");
      defTable.innerHTML = "<thead><tr><th>指標</th><th>定義</th></tr></thead>";
      const defBody = el("tbody");
      for (const [key, value] of Object.entries(definitions)) {
        const row = el("tr");
        row.append(el("td", "", key));
        row.append(el("td", "", String(value)));
        defBody.append(row);
      }
      defTable.append(defBody);
      panel.append(defTable);
    }
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

async function renderConversations(state = {}) {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const navFilters = loadNavFilters();
    const period = state.period || { preset: "30d" };
    const savedFilters = state.filters || {};
    const filters = periodParams(period);
    filters.set("limit", "25");
    if (state.cursor) filters.set("cursor", state.cursor);
    const issueTypeId =
      savedFilters.issueTypeId ||
      (navFilters.view === "conversations" ? navFilters.issueTypeId : "");
    const route = savedFilters.route || "";
    const model = savedFilters.model || "";
    const actorRef = savedFilters.actorRef || "";
    const hasFeedback = savedFilters.hasFeedback || "";
    const handoff = savedFilters.handoff || "";
    if (issueTypeId) filters.set("issue_type_id", issueTypeId);
    if (route) filters.set("route", route);
    if (model) filters.set("model", model);
    if (actorRef) filters.set("actor_ref", actorRef);
    if (hasFeedback) filters.set("has_feedback", hasFeedback);
    if (handoff) filters.set("handoff", handoff);

    const data = await api(`/api/conversations?${filters.toString()}`);
    const panel = el("section", "panel");
    panel.append(el("h2", "", "對話紀錄（遮罩摘要）"));

    const filterBar = el("div", "filter-bar");
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
    actorRefInput.placeholder = "Actor Ref";
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
      exportButton.disabled = true;
      exportButton.textContent = "匯出中…";
      const queryFilters = {
        issue_type_id: issueInput.value || undefined,
        route: routeInput.value || undefined,
        model: modelInput.value || undefined,
        actor_ref: actorRefInput.value || undefined,
        has_feedback: feedbackSelect.value ? feedbackSelect.value === "true" : undefined,
        handoff: handoffSelect.value ? handoffSelect.value === "true" : undefined,
        ...Object.fromEntries(periodParams(period)),
      };
      try {
        await runExport("csv", "conversations", 30, queryFilters);
      } catch (error) {
        showContentModal("匯出失敗", el("div", "error", error.message));
      } finally {
        exportButton.disabled = false;
        exportButton.textContent = "匯出 CSV";
      }
    });
    filterBar.append(
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
      "<thead><tr><th>Conversation</th><th>Turns</th><th>Actor</th><th>Routes</th><th>Last Seen</th></tr></thead>";
    const body = el("tbody");
    for (const item of data.items) {
      const row = el("tr");
      const link = el("a", "", item.conversationId);
      link.href = "#";
      link.addEventListener("click", async (event) => {
        event.preventDefault();
        const detail = await api(`/api/conversations/${encodeURIComponent(item.conversationId)}`);
        showConversationModal(detail);
      });
      const conversationCell = el("td");
      conversationCell.append(link);
      row.append(conversationCell);
      row.append(el("td", "", String(item.turnCount)));
      row.append(el("td", "", item.actorRef || "-"));
      row.append(el("td", "", (item.routes || []).join(", ") || "-"));
      row.append(el("td", "", item.lastOccurredAt));
      body.append(row);
    }
    table.append(body);
    panel.append(table);
    const history = state.history || [];
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

async function renderRoutes(period = { preset: "30d" }) {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const data = await api(`/api/routes/summary?${periodParams(period).toString()}`);
    const panel = el("section", "panel");
    panel.append(el("h2", "", "路由來源分析"));
    panel.append(createPeriodControls(period, renderRoutes));
    panel.append(createExportButton("routes_summary", 30));
    const table = el("table");
    table.innerHTML = "<thead><tr><th>Route</th><th>Count</th><th>實際來源</th></tr></thead>";
    const body = el("tbody");
    for (const item of data.routeDistribution || []) {
      const row = el("tr");
      row.append(el("td", "", item.route));
      row.append(el("td", "", String(item.count)));
      row.append(el("td", "", attributionText(item.attribution)));
      body.append(row);
    }
    table.append(body);
    panel.append(table);
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

async function renderIssues(period = { preset: "30d" }) {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  const filters = loadNavFilters();
  if (filters.clear) {
    clearNavFilters();
  } else if (filters.view === "issues" && filters.issueTypeId) {
    try {
      const data = await api(
        `/api/issues/${encodeURIComponent(filters.issueTypeId)}/routes?${periodParams(period).toString()}`,
      );
      const panel = el("section", "panel");
      panel.append(el("h2", "", `${data.displayName} 路由分布`));
      panel.append(createPeriodControls(period, renderIssues));
      panel.append(drillLink("返回 Issue 總覽", "issues", { clear: true }));
      panel.append(
        createExportButton("routes_summary", 30, {
          issue_type_id: data.issueTypeId,
        }),
      );
      const table = el("table");
      table.innerHTML = "<thead><tr><th>Route</th><th>Count</th><th>實際來源</th><th>動作</th></tr></thead>";
      const body = el("tbody");
      for (const item of data.routes || []) {
        const row = el("tr");
        row.append(el("td", "", item.route));
        row.append(el("td", "", String(item.count)));
        row.append(el("td", "", attributionText(item.attribution)));
        const actions = el("td", "");
        actions.append(
          drillLink("對話", "conversations"),
          document.createTextNode(" "),
          drillLink("回饋", "quality", { issueTypeId: data.issueTypeId }),
        );
        row.append(actions);
        body.append(row);
      }
      table.append(body);
      panel.append(table);
      app.replaceChildren(panel);
      return;
    } catch (error) {
      app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
      return;
    }
  }
  try {
    const data = await api(`/api/issues/summary?${periodParams(period).toString()}`);
    const panel = el("section", "panel");
    panel.append(el("h2", "", `Issue 分析 (${data.taxonomyVersion})`));
    panel.append(createPeriodControls(period, renderIssues));
    panel.append(createExportButton("issues_summary", 30));
    panel.append(el("p", "", `未分類：${data.unclassifiedCount}`));
    const table = el("table");
    table.innerHTML =
      "<thead><tr><th>Issue Type</th><th>Display Name</th><th>Count</th><th>Share</th><th>負評率</th><th>Handoff</th><th>成本 USD</th><th>動作</th></tr></thead>";
    const body = el("tbody");
    for (const item of data.items) {
      const row = el("tr");
      row.append(el("td", "", item.issueTypeId));
      row.append(el("td", "", item.displayName));
      row.append(el("td", "", String(item.count)));
      row.append(el("td", "", String(item.share)));
      row.append(el("td", "", String(item.negativeFeedbackRate ?? 0)));
      row.append(el("td", "", String(item.handoffRate ?? 0)));
      row.append(el("td", "", String(item.estimatedCostUsd ?? 0)));
      const actions = el("td", "");
      actions.append(
        drillLink("路由", "issues", { issueTypeId: item.issueTypeId }),
        document.createTextNode(" "),
        drillLink("回饋", "quality", { rating: "DOWN", issueTypeId: item.issueTypeId }),
      );
      row.append(actions);
      body.append(row);
    }
    table.append(body);
    panel.append(table);

    if (data.hierarchy?.length) {
      panel.append(el("h3", "", "Taxonomy 階層"));
      const tree = el("ul", "issue-tree");
      for (const node of data.hierarchy) {
        tree.append(renderIssueTreeNode(node));
      }
      panel.append(tree);
    }
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

function renderIssueTreeNode(node, depth = 0) {
  const item = el("li", "");
  const label = `${"  ".repeat(depth)}${node.displayName} (${node.aggregateCount ?? node.count})`;
  item.append(el("span", "", label));
  item.append(
    drillLink(" 路由", "issues", { issueTypeId: node.issueTypeId }),
  );
  if (node.children?.length) {
    const children = el("ul", "");
    for (const child of node.children) {
      children.append(renderIssueTreeNode(child, depth + 1));
    }
    item.append(children);
  }
  return item;
}

async function renderCosts(period = { preset: "30d" }) {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const data = await api(`/api/costs/summary?${periodParams(period).toString()}`);
    const panel = el("section", "panel");
    panel.append(el("h2", "", "成本分析"));
    panel.append(createPeriodControls(period, renderCosts));
    panel.append(metric("Total USD", data.totalEstimatedCostUsd));
    if (data.totalEstimatedCostTwd !== undefined) {
      panel.append(metric("Total TWD", data.totalEstimatedCostTwd));
      panel.append(el("p", "", `匯率：${data.usdTwdExchangeRate} TWD/USD`));
    }
    panel.append(el("p", "", `缺少成本資料事件：${data.missingCostEventCount}`));
    panel.append(el("p", "", `Input tokens：${data.inputTokens}｜Output tokens：${data.outputTokens}`));
    if (data.embeddingTokens !== undefined || data.toolContextTokens !== undefined) {
      panel.append(
        el(
          "p",
          "",
          `Embedding tokens：${data.embeddingTokens ?? 0}｜Tool context tokens：${data.toolContextTokens ?? 0}`,
        ),
      );
    }
    panel.append(el("p", "", `Pricing version：${data.pricingVersion}`));
    const table = el("table");
    table.innerHTML = "<thead><tr><th>Date</th><th>Estimated USD</th></tr></thead>";
    const body = el("tbody");
    for (const item of data.byDay || []) {
      const row = el("tr");
      row.append(el("td", "", item.date));
      row.append(el("td", "", String(item.estimatedCostUsd)));
      body.append(row);
    }
    table.append(body);
    panel.append(el("h3", "", "依日期"), table);

    const routeTable = el("table");
    routeTable.innerHTML = "<thead><tr><th>Route</th><th>Estimated USD</th></tr></thead>";
    const routeBody = el("tbody");
    for (const item of data.byRoute || []) {
      const row = el("tr");
      row.append(el("td", "", item.route));
      row.append(el("td", "", String(item.estimatedCostUsd)));
      routeBody.append(row);
    }
    routeTable.append(routeBody);
    panel.append(el("h3", "", "依 Route"), routeTable);

    const issueTable = el("table");
    issueTable.innerHTML =
      "<thead><tr><th>Issue Type</th><th>Display Name</th><th>Estimated USD</th></tr></thead>";
    const issueBody = el("tbody");
    for (const item of data.byIssueType || []) {
      const row = el("tr");
      row.append(el("td", "", item.issueTypeId));
      row.append(el("td", "", item.displayName || "-"));
      row.append(el("td", "", String(item.estimatedCostUsd)));
      issueBody.append(row);
    }
    issueTable.append(issueBody);
    panel.append(el("h3", "", "依 Issue Type"), issueTable);

    for (const [heading, items, key] of [
      ["依 Model", data.byModel, "model"],
      ["依 Provider", data.byProvider, "provider"],
      ["依 Component", data.byComponent, "component"],
      ["依 Knowledge Backend", data.byBackend, "backend"],
    ]) {
      const dimensionTable = el("table");
      dimensionTable.innerHTML = `<thead><tr><th>${heading.replace("依 ", "")}</th><th>Events</th><th>Estimated USD</th></tr></thead>`;
      const dimensionBody = el("tbody");
      for (const item of items || []) {
        const row = el("tr");
        row.append(el("td", "", item[key] || "unknown"));
        row.append(el("td", "", String(item.eventCount ?? 0)));
        row.append(el("td", "", String(item.estimatedCostUsd ?? "-")));
        dimensionBody.append(row);
      }
      dimensionTable.append(dimensionBody);
      panel.append(el("h3", "", heading), dimensionTable);
    }
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

async function renderHealth() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const data = await api("/api/health/summary");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "系統健康度"));
    if (data.simulatedAnomalies) {
      panel.append(
        el("div", "warning", "目前為模擬異常模式，部分元件狀態為測試用途。"),
      );
    }
    if (data.monitoringLinks?.cloudMonitoring) {
      const links = el("div", "filter-bar");
      const monitoringLink = el("a", "button-link", "Cloud Monitoring");
      monitoringLink.href = data.monitoringLinks.cloudMonitoring;
      monitoringLink.target = "_blank";
      const loggingLink = el("a", "button-link", "Cloud Logging");
      loggingLink.href = data.monitoringLinks.cloudLogging;
      loggingLink.target = "_blank";
      links.append(monitoringLink, loggingLink);
      panel.append(links);
    }
    const table = el("table");
    table.innerHTML = [
      "<thead><tr><th>Component</th><th>Status</th><th>24h Requests</th>",
      "<th>Availability</th><th>Error</th><th>Timeout</th>",
      "<th>P50 ms</th><th>P95 ms</th><th>Note</th></tr></thead>",
    ].join("");
    const body = el("tbody");
    for (const item of data.components || []) {
      const row = el("tr");
      row.append(el("td", "", item.id));
      row.append(el("td", "", item.status));
      row.append(
        el(
          "td",
          "",
          item.telemetryStatus === "AVAILABLE" ? String(item.requestCount) : "NO DATA",
        ),
      );
      for (const value of [item.availabilityRate, item.errorRate, item.timeoutRate]) {
        row.append(el("td", "", value == null ? "-" : `${(value * 100).toFixed(1)}%`));
      }
      row.append(el("td", "", item.p50LatencyMs == null ? "-" : String(item.p50LatencyMs)));
      row.append(el("td", "", item.p95LatencyMs == null ? "-" : String(item.p95LatencyMs)));
      row.append(el("td", "", item.note || item.url || ""));
      body.append(row);
    }
    table.append(body);
    panel.append(table);
    if ((data.recentAnomalies || []).length) {
      const anomalyTable = el("table");
      anomalyTable.innerHTML = "<thead><tr><th>時間</th><th>Component</th><th>Status</th><th>Error Type</th><th>Correlation</th></tr></thead>";
      const anomalyBody = el("tbody");
      for (const item of data.recentAnomalies) {
        const row = el("tr");
        row.append(el("td", "", item.occurredAt));
        row.append(el("td", "", item.component));
        row.append(el("td", "", item.status));
        row.append(el("td", "", item.errorType));
        row.append(el("td", "", item.correlationId || "-"));
        anomalyBody.append(row);
      }
      anomalyTable.append(anomalyBody);
      panel.append(el("h3", "", "最近異常"), anomalyTable);
    }
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

async function renderKnowledge() {
  const app = document.getElementById("app");
  const panel = el("section", "panel");
  const faqPanel = el("section", "panel");
  panel.append(el("h2", "", "知識營運"));
  panel.append(
    el(
      "p",
      "",
      "文件維護、審核、發布與測試仍由 Knowledge Portal 提供。下方可查看文件成效。",
    ),
  );
  const link = el("a", "button-link", "開啟 Knowledge Portal");
  link.href = capabilities?.knowledgePortalUrl || "http://127.0.0.1:8091";
  link.target = "_blank";
  const exportButton = el("button", "", "匯出 CSV");
  exportButton.style.marginLeft = "0.5rem";
  panel.append(link, exportButton);

  const filters = el("form", "filter-bar");
  filters.style.marginTop = "1rem";
  const query = el("input");
  query.placeholder = "搜尋標題或文件 ID";
  query.setAttribute("aria-label", "搜尋知識文件");
  const status = el("select");
  status.setAttribute("aria-label", "生命週期狀態");
  for (const [value, label] of [
    ["", "所有狀態"],
    ["DRAFT", "草稿"],
    ["IN_REVIEW", "審核中"],
    ["APPROVED", "已核准"],
    ["PUBLISHED", "已發布"],
    ["ARCHIVED", "已封存"],
  ]) {
    const option = el("option", "", label);
    option.value = value;
    status.append(option);
  }
  const submit = el("button", "", "套用篩選");
  submit.type = "submit";
  filters.append(query, status, submit);
  const result = el("div", "");
  panel.append(filters, result);
  app.replaceChildren(panel, faqPanel);

  async function loadDocuments(cursor = "") {
    result.replaceChildren(el("p", "empty", "載入中…"));
    try {
      const params = new URLSearchParams({ days: "30", limit: "50" });
      if (query.value.trim()) params.set("query", query.value.trim());
      if (status.value) params.set("status", status.value);
      if (cursor) params.set("cursor", cursor);
      const data = await api(`/api/knowledge?${params.toString()}`);
      result.replaceChildren(renderKnowledgeInventory(data, loadDocuments));
    } catch (error) {
      result.replaceChildren(el("div", "error", error.message));
    }
  }

  filters.addEventListener("submit", (event) => {
    event.preventDefault();
    loadDocuments();
  });
  exportButton.addEventListener("click", async () => {
    exportButton.disabled = true;
    exportButton.textContent = "匯出中…";
    try {
      await runExport("csv", "knowledge_performance", 30);
    } catch (error) {
      result.prepend(el("div", "error", error.message));
    } finally {
      exportButton.disabled = false;
      exportButton.textContent = "匯出 CSV";
    }
  });
  await Promise.all([loadDocuments(), renderFaqManagement(faqPanel)]);
}

async function renderFaqManagement(panel) {
  panel.replaceChildren(el("h2", "", "FAQ 治理"), el("p", "empty", "載入中…"));
  const allowed = new Set(capabilities?.capabilities || []);
  if (!allowed.has("ops.faq.read")) {
    panel.replaceChildren(el("h2", "", "FAQ 治理"), el("div", "forbidden", "FORBIDDEN"));
    return;
  }
  try {
    const heading = el("h2", "", "FAQ 治理");
    const actions = el("div", "filter-bar");
    const query = el("input");
    query.placeholder = "搜尋 FAQ Key 或問題";
    const status = el("select");
    status.innerHTML = `
      <option value="">全部狀態</option>
      <option value="DRAFT">DRAFT</option>
      <option value="IN_REVIEW">IN_REVIEW</option>
      <option value="CHANGES_REQUESTED">CHANGES_REQUESTED</option>
      <option value="APPROVED">APPROVED</option>
      <option value="ACTIVE">ACTIVE</option>
      <option value="DISABLED">DISABLED</option>
    `;
    const result = el("div");
    const load = async () => {
      const params = new URLSearchParams();
      if (query.value.trim()) params.set("query", query.value.trim());
      if (status.value) params.set("status", status.value);
      const data = await api(`/api/faqs?${params}`);
      result.replaceChildren();
      summary.textContent = `共 ${data.total || 0} 筆`;
      if (!(data.items || []).length) {
        result.append(el("p", "empty", "沒有符合條件的 FAQ。"));
        return;
      }
      const table = el("table");
      table.innerHTML = "<thead><tr><th>FAQ</th><th>狀態</th><th>Owner</th><th>版本</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const item of data.items) {
        const row = el("tr");
        const name = el("td");
        name.append(
          el("strong", "", item.version.content.question),
          el("div", "metric-label", item.faq.faq_key),
        );
        const action = el("td");
        const detail = el("button", "", "查看與處理");
        detail.addEventListener("click", () => showFaqDetail(item.faq.faq_id, panel));
        action.append(detail);
        row.append(
          name,
          el("td", "", item.faq.status),
          el("td", "", item.version.content.owner_unit_id),
          el("td", "", `v${item.version.version_number}`),
          action,
        );
        body.append(row);
      }
      table.append(body);
      result.append(table);
    };
    const searchButton = el("button", "", "套用篩選");
    searchButton.addEventListener("click", load);
    query.addEventListener("keydown", (event) => {
      if (event.key === "Enter") load();
    });
    if (allowed.has("ops.faq.write")) {
      const createButton = el("button", "", "新增 FAQ");
      createButton.addEventListener("click", () => showFaqCreateModal(panel));
      actions.append(createButton);
    }
    const summary = el("span", "metric-label", "");
    actions.append(query, status, searchButton, summary);
    panel.replaceChildren(heading, actions, result);
    await load();
  } catch (error) {
    panel.replaceChildren(el("h2", "", "FAQ 治理"), el("div", "error", error.message));
  }
}

function faqField(label, name, value = "", multiline = false, required = true) {
  const wrap = el("label", "form-field");
  wrap.append(el("span", "metric-label", label));
  const input = el(multiline ? "textarea" : "input");
  input.name = name;
  input.value = value;
  input.required = required;
  wrap.append(input);
  return wrap;
}

function showFaqCreateModal(panel) {
  const form = el("form", "form-grid");
  form.append(
    faqField("FAQ Key", "faq_key"),
    faqField("問題", "question"),
    faqField("固定答案", "answer", "", true),
    faqField("分類", "category"),
    faqField("關鍵字（逗號分隔）", "keywords"),
    faqField("Owner Unit", "owner_unit_id", "IT Service Desk"),
    faqField("Business Contact", "business_contact", "IT Service Desk"),
    faqField("Issue Type IDs（逗號分隔）", "issue_type_ids"),
    faqField("Audience Groups（逗號分隔；空白代表 ALL）", "audience_group_ids", "", false, false),
  );
  const message = el("div");
  const submit = el("button", "", "建立草稿");
  submit.type = "submit";
  form.append(submit, message);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    message.replaceChildren();
    const values = new FormData(form);
    const split = (name) => String(values.get(name) || "").split(",").map((item) => item.trim()).filter(Boolean);
    const groups = split("audience_group_ids");
    try {
      const created = await api("/api/faqs", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({
          faq_key: values.get("faq_key"), question: values.get("question"),
          answer: values.get("answer"), category: values.get("category"),
          keywords: split("keywords"), owner_unit_id: values.get("owner_unit_id"),
          business_contact: values.get("business_contact"), issue_type_ids: split("issue_type_ids"),
          audience_type: groups.length ? "GROUPS" : "ALL", audience_group_ids: groups,
        }),
      });
      document.getElementById("modal-root").hidden = true;
      await renderFaqManagement(panel);
      showFaqDetail(created.faq.faq_id, panel);
    } catch (error) {
      message.replaceChildren(el("div", "error", error.message));
    } finally {
      submit.disabled = false;
    }
  });
  showContentModal("新增 FAQ 草稿", form);
}

async function showFaqDetail(faqId, panel) {
  try {
    const detail = await api(`/api/faqs/${encodeURIComponent(faqId)}`);
    const allowed = new Set(capabilities?.capabilities || []);
    const faq = detail.faq;
    const current = detail.versions.at(-1);
    const content = el("div");
    content.append(
      el("p", "", `狀態：${faq.status}｜版本：v${current.version_number}｜ETag：${faq.etag}`),
      el("p", "", `問題：${current.content.question}`),
      el("p", "", `答案：${current.content.answer}`),
      el("p", "", `Owner：${current.content.owner_unit_id}｜Issue：${current.content.issue_type_ids.join(", ")}`),
    );
    const actions = el("div", "filter-bar");
    const run = async (path, payload) => {
      try {
        await api(path, {
          method: "POST",
          headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
          body: JSON.stringify(payload),
        });
        await renderFaqManagement(panel);
        await showFaqDetail(faqId, panel);
      } catch (error) {
        showContentModal("FAQ 操作失敗", el("div", "error", error.message));
      }
    };
    if (allowed.has("ops.faq.write") && ["DRAFT", "CHANGES_REQUESTED"].includes(current.status)) {
      for (const [kind, label] of [["POSITIVE", "新增正例"], ["NEGATIVE", "新增反例"]]) {
        const button = el("button", "", label);
        button.addEventListener("click", async () => {
          const utterance = window.prompt(`${label}問法`);
          if (!utterance) return;
          await run(`/api/faqs/${faqId}/versions/${current.version_id}/tests`, {
            expected_etag: faq.etag, kind, utterance,
            expected_audience_group_ids: current.content.audience_group_ids,
          });
        });
        actions.append(button);
      }
      const submit = el("button", "", "送審");
      submit.addEventListener("click", () => run(
        `/api/faqs/${faqId}/versions/${current.version_id}/submit`, { expected_etag: faq.etag },
      ));
      actions.append(submit);
    }
    if (allowed.has("ops.faq.review") && current.status === "IN_REVIEW") {
      const approve = el("button", "", "核准");
      approve.addEventListener("click", () => run(
        `/api/faqs/${faqId}/versions/${current.version_id}/review`,
        { expected_etag: faq.etag, approve: true, reason: "管理員已審閱內容與正反例" },
      ));
      const reject = el("button", "", "退回修改");
      reject.addEventListener("click", () => {
        const reason = window.prompt("請輸入退回原因");
        if (!reason?.trim()) return;
        run(`/api/faqs/${faqId}/versions/${current.version_id}/review`, {
          expected_etag: faq.etag, approve: false, reason: reason.trim(),
        });
      });
      actions.append(approve, reject);
    }
    if (allowed.has("ops.faq.activate") && current.status === "APPROVED") {
      const activate = el("button", "", "啟用");
      activate.addEventListener("click", () => run(
        `/api/faqs/${faqId}/versions/${current.version_id}/activate`,
        { expected_etag: faq.etag, reason: "管理員核准啟用" },
      ));
      actions.append(activate);
    }
    if (allowed.has("ops.faq.disable") && faq.status === "ACTIVE") {
      const disable = el("button", "", "停用");
      disable.addEventListener("click", () => run(
        `/api/faqs/${faqId}/disable`, { expected_etag: faq.etag, reason: "管理員停用" },
      ));
      actions.append(disable);
    }
    content.append(actions, el("h3", "", `測試案例（${detail.tests.length}）`));
    for (const test of detail.tests) content.append(el("p", "", `${test.kind}｜${test.utterance}`));
    content.append(el("h3", "", `Audit（${detail.audit.length}）`));
    for (const event of detail.audit) content.append(el("p", "metric-label", `${event.occurred_at}｜${event.action}｜${event.actor_id}`));
    showContentModal(current.content.question, content);
  } catch (error) {
    showContentModal("FAQ", el("div", "error", error.message));
  }
}

function renderKnowledgeInventory(data, loadDocuments) {
  const container = el("div");
  if (data.warning) container.append(el("p", "warning", data.warning));
  const summary = el(
    "p",
    "",
    `共 ${data.total || 0} 份文件｜績效期間 ${data.periodDays || 30} 天`,
  );
  container.append(summary);
  if (!(data.items || []).length) {
    container.append(el("p", "empty", "沒有符合條件的知識文件。"));
    return container;
  }
  const table = el("table");
  table.innerHTML = [
    "<thead><tr>",
    "<th>文件</th><th>Owner</th><th>生命週期</th><th>解析 / 索引</th>",
    "<th>命中</th><th>對話</th><th>負面回饋</th><th>操作</th>",
    "</tr></thead>",
  ].join("");
  const body = el("tbody");
  for (const item of data.items) {
    const row = el("tr");
    const documentCell = el("td");
    documentCell.append(
      el("strong", "", item.title || item.documentId),
      el("div", "metric-label", item.documentId),
    );
    const detailButton = el("button", "", "查看成效");
    detailButton.addEventListener("click", async () => {
      detailButton.disabled = true;
      try {
        const detail = await api(
          `/api/knowledge/${encodeURIComponent(item.documentId)}/performance?days=30`,
        );
        showContentModal(item.title || item.documentId, renderDocumentPerformance(detail));
      } catch (error) {
        showContentModal("知識文件成效", el("div", "error", error.message));
      } finally {
        detailButton.disabled = false;
      }
    });
    const actionCell = el("td");
    actionCell.append(detailButton);
    row.append(
      documentCell,
      el("td", "", item.ownerUnitId || "-"),
      el("td", "", item.lifecycleStatus || "UNKNOWN"),
      el("td", "", `${item.parseStatus || "UNKNOWN"} / ${item.indexStatus || "UNKNOWN"}`),
      el("td", "", String(item.hitCount || 0)),
      el("td", "", String(item.conversationCount || 0)),
      el("td", "", String(item.negativeFeedbackCount || 0)),
      actionCell,
    );
    body.append(row);
  }
  table.append(body);
  container.append(table);
  if (data.nextCursor) {
    const next = el("button", "", "下一頁");
    next.style.marginTop = "1rem";
    next.addEventListener("click", () => loadDocuments(data.nextCursor));
    container.append(next);
  }
  return container;
}

function renderDocumentPerformance(data) {
  const container = el("div", "panel");
  container.style.marginTop = "1rem";
  const grid = el("div", "grid");
  grid.append(
    metric("命中次數", data.hitCount),
    metric("對話數", data.conversationCount),
    metric("正面回饋", data.positiveFeedbackCount),
    metric("負面回饋", data.negativeFeedbackCount),
  );
  container.append(grid);

  if (data.governance) {
    const governance = data.governance;
    const govPanel = el("div", "panel");
    govPanel.append(el("h3", "", "文件治理狀態"));
    if (governance.status === "available") {
      govPanel.append(
        el(
          "p",
          "",
          `生命週期：${governance.lifecycleStatus}｜格式：${governance.formatType}｜解析：${governance.parseStatus}｜索引：${governance.indexStatus}`,
        ),
      );
      if (governance.portalUrl) {
        const portalLink = el("a", "button-link", "在 Knowledge Portal 開啟");
        portalLink.href = governance.portalUrl;
        portalLink.target = "_blank";
        govPanel.append(portalLink);
      }
    } else {
      govPanel.append(el("p", "", governance.note || `狀態：${governance.status}`));
    }
    container.append(govPanel);
  }

  const issueTable = el("table");
  issueTable.innerHTML =
    "<thead><tr><th>Issue Type</th><th>Display Name</th><th>Count</th></tr></thead>";
  const issueBody = el("tbody");
  for (const item of data.issueTypeDistribution || []) {
    const row = el("tr");
    row.append(el("td", "", item.issueTypeId));
    row.append(el("td", "", item.displayName || "-"));
    row.append(el("td", "", String(item.count)));
    issueBody.append(row);
  }
  issueTable.append(issueBody);
  container.append(el("h3", "", "Issue 分布"), issueTable);

  const releaseTable = el("table");
  releaseTable.innerHTML = "<thead><tr><th>Release</th><th>Hits</th></tr></thead>";
  const releaseBody = el("tbody");
  for (const item of data.releaseAttribution || []) {
    const row = el("tr");
    row.append(el("td", "", item.releaseId));
    row.append(el("td", "", String(item.hitCount)));
    releaseBody.append(row);
  }
  releaseTable.append(releaseBody);
  container.append(el("h3", "", "版本歸因"), releaseTable);

  const recentTable = el("table");
  recentTable.innerHTML = "<thead><tr><th>時間</th><th>Conversation</th><th>Issue</th><th>Release</th><th>Chunk</th></tr></thead>";
  const recentBody = el("tbody");
  for (const item of data.recentHits || []) {
    const row = el("tr");
    row.append(el("td", "", item.occurredAt));
    const conversation = el("a", "", item.conversationId || "-");
    conversation.href = "#";
    conversation.addEventListener("click", async (event) => {
      event.preventDefault();
      const detail = await api(`/api/conversations/${encodeURIComponent(item.conversationId)}`);
      showConversationModal(detail);
    });
    const conversationCell = el("td");
    conversationCell.append(conversation);
    row.append(conversationCell);
    row.append(el("td", "", item.issueTypeId || "-"));
    row.append(el("td", "", item.releaseId || "-"));
    row.append(el("td", "", item.chunkId || "-"));
    recentBody.append(row);
  }
  recentTable.append(recentBody);
  container.append(el("h3", "", "最近命中對話"), recentTable);
  return container;
}

async function renderQuality(state = {}) {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const navFilters = loadNavFilters();
    const period = state.period || { preset: "30d" };
    const savedFilters = state.filters || {};
    const filters = periodParams(period);
    filters.set("limit", "25");
    if (state.cursor) filters.set("cursor", state.cursor);
    const rating =
      savedFilters.rating ||
      (navFilters.view === "quality" ? navFilters.rating : "");
    const issueTypeId =
      savedFilters.issueTypeId ||
      (navFilters.view === "quality" ? navFilters.issueTypeId : "");
    const reason = savedFilters.reason || "";
    const resolved = savedFilters.resolved || "";
    const handoff = savedFilters.handoff || "";
    if (rating) filters.set("rating", rating);
    if (issueTypeId) filters.set("issue_type_id", issueTypeId);
    if (reason) filters.set("reason", reason);
    if (resolved) filters.set("resolved", resolved);
    if (handoff) filters.set("handoff", handoff);

    const feedback = await api(`/api/feedback?${filters.toString()}`);
    const panel = el("section", "panel");
    panel.append(el("h2", "", "品質與回饋"));

    const filterBar = el("div", "grid");
    const issueInput = el("input");
    issueInput.id = "feedback-issue-type";
    issueInput.placeholder = "Issue Type ID";
    issueInput.value = issueTypeId;
    const ratingSelect = el("select", "");
    ratingSelect.id = "feedback-rating";
    ratingSelect.innerHTML =
      '<option value="">全部 Rating</option><option value="UP">UP</option><option value="DOWN">DOWN</option>';
    if (rating) ratingSelect.value = rating;
    const reasonInput = el("input");
    reasonInput.id = "feedback-reason";
    reasonInput.placeholder = "Reason";
    reasonInput.value = reason || "";
    const resolvedSelect = el("select", "");
    resolvedSelect.id = "feedback-resolved";
    resolvedSelect.innerHTML =
      '<option value="">全部 Resolved</option><option value="RESOLVED">RESOLVED</option><option value="UNRESOLVED">UNRESOLVED</option>';
    if (resolved) resolvedSelect.value = resolved;
    const handoffSelect = el("select", "");
    handoffSelect.id = "feedback-handoff";
    handoffSelect.innerHTML =
      '<option value="">全部 Handoff</option><option value="true">有 Handoff</option><option value="false">無 Handoff</option>';
    if (handoff) handoffSelect.value = handoff;
    const currentFilters = () => ({
      issueTypeId: issueInput.value.trim(),
      rating: ratingSelect.value,
      reason: reasonInput.value.trim(),
      resolved: resolvedSelect.value,
      handoff: handoffSelect.value,
    });
    const applyFilters = el("button", "", "套用篩選");
    applyFilters.addEventListener("click", () =>
      renderQuality({ period, filters: currentFilters(), cursor: "", history: [] }),
    );
    const exportButton = createExportButton("feedback", 30, () => ({
      issue_type_id: issueInput.value || undefined,
      rating: ratingSelect.value || undefined,
      feedback_reason: reasonInput.value || undefined,
      resolved_status: resolvedSelect.value || undefined,
      handoff: handoffSelect.value ? handoffSelect.value === "true" : undefined,
      ...Object.fromEntries(periodParams(period)),
    }));
    filterBar.append(
      issueInput,
      ratingSelect,
      reasonInput,
      resolvedSelect,
      handoffSelect,
      applyFilters,
      exportButton,
    );
    panel.append(filterBar);
    panel.append(
      createPeriodControls(period, (nextPeriod) =>
        renderQuality({
          period: nextPeriod,
          filters: currentFilters(),
          cursor: "",
          history: [],
        }),
      ),
    );

    if (!feedback.items.length) {
      panel.append(el("p", "empty", "目前沒有符合條件的回饋事件。"));
    } else {
      const table = el("table");
      table.innerHTML =
        "<thead><tr><th>時間</th><th>Rating</th><th>Issue</th><th>來源</th><th>Conversation</th><th>Reason</th></tr></thead>";
      const body = el("tbody");
      for (const item of feedback.items) {
        const trace = item.trace || {};
        const source = trace.faqKey
          ? `FAQ:${trace.faqKey}`
          : (trace.documentIds || []).join(", ") || "-";
        const row = el("tr");
        row.append(el("td", "", item.occurredAt));
        row.append(el("td", "", item.rating));
        row.append(
          el(
            "td",
            "",
            trace.issueTypeDisplayName || trace.issueTypeId || String(item.issueId ?? "-"),
          ),
        );
        row.append(el("td", "", source));
        const convLink = el("a", "", item.conversationId ?? "-");
        convLink.href = "#";
        convLink.addEventListener("click", async (event) => {
          event.preventDefault();
          const detail = await api(
            `/api/conversations/${encodeURIComponent(item.conversationId)}`,
          );
          showConversationModal({ ...detail, conversationId: item.conversationId });
        });
        row.append(el("td", "", "").append(convLink));
        row.append(el("td", "", item.reason ?? "-"));
        body.append(row);
      }
      table.append(body);
      panel.append(table);
    }
    const history = state.history || [];
    const pager = el("div", "filter-bar");
    if (history.length) {
      const previous = el("button", "", "上一頁");
      previous.addEventListener("click", () =>
        renderQuality({
          period,
          filters: currentFilters(),
          cursor: history.at(-1),
          history: history.slice(0, -1),
        }),
      );
      pager.append(previous);
    }
    if (feedback.nextCursor) {
      const next = el("button", "", "下一頁");
      next.addEventListener("click", () =>
        renderQuality({
          period,
          filters: currentFilters(),
          cursor: feedback.nextCursor,
          history: [...history, state.cursor || ""],
        }),
      );
      pager.append(next);
    }
    if (pager.childElementCount) panel.append(pager);
    const exportPanel = el("section", "panel");
    exportPanel.append(el("h3", "", "非同步匯出"));
    const csvButton = el("button", "", "建立 CSV 營運摘要匯出");
    csvButton.addEventListener("click", async () => {
      await runExport("csv");
    });
    const xlsxButton = el("button", "", "建立 XLSX 營運摘要匯出");
    xlsxButton.style.marginLeft = "0.5rem";
    xlsxButton.addEventListener("click", async () => {
      await runExport("xlsx");
    });
    exportPanel.append(csvButton, xlsxButton);
    app.replaceChildren(panel, exportPanel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

async function runExport(
  exportFormat,
  exportType = "operations_summary",
  days = 7,
  queryFilters = {},
) {
  const created = await api("/api/exports", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      export_type: exportType,
      reason: "UAT export",
      days,
      export_format: exportFormat,
      preset: `${days}d`,
      ...queryFilters,
    }),
  });
  const job = await pollExport(created.jobId);
  if (job.status === "COMPLETED") {
    const response = await fetch(`/api/exports/${encodeURIComponent(created.jobId)}/download`, {
      headers: authHeaders(),
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${exportType.replaceAll("_", "-")}-${created.jobId}.${exportFormat}`;
    link.click();
    URL.revokeObjectURL(url);
  }
  return job;
}

function createExportButton(exportType, days, queryFilters = {}) {
  const button = el("button", "", "匯出 CSV");
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "匯出中…";
    try {
      const filters = typeof queryFilters === "function" ? queryFilters() : queryFilters;
      await runExport("csv", exportType, days, filters);
    } catch (error) {
      showContentModal("匯出失敗", el("div", "error", error.message));
    } finally {
      button.disabled = false;
      button.textContent = "匯出 CSV";
    }
  });
  return button;
}

async function pollExport(jobId) {
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const job = await api(`/api/exports/${encodeURIComponent(jobId)}`);
    if (job.status === "COMPLETED" || job.status === "FAILED" || job.status === "EXPIRED") {
      return job;
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  return { jobId, status: "RUNNING" };
}

async function renderAudit() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const data = await api("/api/audit-events");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "稽核紀錄"));
    panel.append(el("pre", "", JSON.stringify(data, null, 2)));
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

boot();
