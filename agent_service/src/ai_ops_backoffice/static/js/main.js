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

async function renderConversations() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const navFilters = loadNavFilters();
    const filters = new URLSearchParams({ days: "30" });
    const issueTypeId =
      document.getElementById("conversation-issue-type")?.value ||
      (navFilters.view === "conversations" ? navFilters.issueTypeId : "");
    const route = document.getElementById("conversation-route")?.value || "";
    const model = document.getElementById("conversation-model")?.value || "";
    const actorRef = document.getElementById("conversation-actor-ref")?.value || "";
    const hasFeedback = document.getElementById("conversation-has-feedback")?.value || "";
    const handoff = document.getElementById("conversation-handoff")?.value || "";
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
    const applyFilters = el("button", "", "套用篩選");
    applyFilters.addEventListener("click", () => renderConversations());
    filterBar.append(issueInput, routeInput, modelInput, actorRefInput, feedbackSelect, handoffSelect, applyFilters);
    panel.append(filterBar);

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
      row.append(el("td", "", "").append(link));
      row.append(el("td", "", String(item.turnCount)));
      row.append(el("td", "", item.actorRef || "-"));
      row.append(el("td", "", (item.routes || []).join(", ") || "-"));
      row.append(el("td", "", item.lastOccurredAt));
      body.append(row);
    }
    table.append(body);
    panel.append(table);
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

async function renderRoutes() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const data = await api("/api/routes/summary?preset=30d");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "路由來源分析"));
    const table = el("table");
    table.innerHTML = "<thead><tr><th>Route</th><th>Count</th></tr></thead>";
    const body = el("tbody");
    for (const item of data.routeDistribution || []) {
      const row = el("tr");
      row.append(el("td", "", item.route));
      row.append(el("td", "", String(item.count)));
      body.append(row);
    }
    table.append(body);
    panel.append(table);
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

async function renderIssues() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  const filters = loadNavFilters();
  if (filters.clear) {
    clearNavFilters();
  } else if (filters.view === "issues" && filters.issueTypeId) {
    try {
      const data = await api(
        `/api/issues/${encodeURIComponent(filters.issueTypeId)}/routes?days=30`,
      );
      const panel = el("section", "panel");
      panel.append(el("h2", "", `${data.displayName} 路由分布`));
      panel.append(drillLink("返回 Issue 總覽", "issues", { clear: true }));
      const table = el("table");
      table.innerHTML = "<thead><tr><th>Route</th><th>Count</th><th>動作</th></tr></thead>";
      const body = el("tbody");
      for (const item of data.routes || []) {
        const row = el("tr");
        row.append(el("td", "", item.route));
        row.append(el("td", "", String(item.count)));
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
    const data = await api("/api/issues/summary?days=30");
    const panel = el("section", "panel");
    panel.append(el("h2", "", `Issue 分析 (${data.taxonomyVersion})`));
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

async function renderCosts() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const data = await api("/api/costs/summary?days=30");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "成本分析"));
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
    table.innerHTML = "<thead><tr><th>Component</th><th>Status</th><th>Note</th></tr></thead>";
    const body = el("tbody");
    for (const item of data.components || []) {
      const row = el("tr");
      row.append(el("td", "", item.id));
      row.append(el("td", "", item.status));
      row.append(el("td", "", item.note || item.url || ""));
      body.append(row);
    }
    table.append(body);
    panel.append(table);
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

function renderKnowledge() {
  const app = document.getElementById("app");
  const panel = el("section", "panel");
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
  panel.append(link);
  const input = el("input");
  input.placeholder = "documentId（例如 vpn-password-lockout）";
  input.style.marginTop = "1rem";
  input.style.width = "100%";
  const button = el("button", "", "查詢文件成效");
  button.style.marginTop = "0.5rem";
  const result = el("div", "");
  button.addEventListener("click", async () => {
    const documentId = input.value.trim();
    if (!documentId) return;
    result.replaceChildren(el("p", "empty", "載入中…"));
    try {
      const data = await api(
        `/api/knowledge/${encodeURIComponent(documentId)}/performance?days=30`,
      );
      result.replaceChildren(renderDocumentPerformance(data));
    } catch (error) {
      result.replaceChildren(el("div", "error", error.message));
    }
  });
  panel.append(input, button, result);
  app.replaceChildren(panel);
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
  return container;
}

async function renderQuality() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const navFilters = loadNavFilters();
    const filters = new URLSearchParams({ days: "30" });
    const rating =
      document.getElementById("feedback-rating")?.value ||
      (navFilters.view === "quality" ? navFilters.rating : "");
    const reason = document.getElementById("feedback-reason")?.value;
    const resolved = document.getElementById("feedback-resolved")?.value;
    const handoff = document.getElementById("feedback-handoff")?.value;
    if (rating) filters.set("rating", rating);
    if (reason) filters.set("reason", reason);
    if (resolved) filters.set("resolved", resolved);
    if (handoff) filters.set("handoff", handoff);

    const feedback = await api(`/api/feedback?${filters.toString()}`);
    const panel = el("section", "panel");
    panel.append(el("h2", "", "品質與回饋"));

    const filterBar = el("div", "grid");
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
    const applyFilters = el("button", "", "套用篩選");
    applyFilters.addEventListener("click", () => renderQuality());
    filterBar.append(ratingSelect, reasonInput, resolvedSelect, handoffSelect, applyFilters);
    panel.append(filterBar);

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

async function runExport(exportFormat) {
  const created = await api("/api/exports", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      export_type: "operations_summary",
      reason: "UAT export",
      days: 7,
      export_format: exportFormat,
      preset: "7d",
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
    link.download = `operations-summary-${created.jobId}.${exportFormat}`;
    link.click();
    URL.revokeObjectURL(url);
  }
  return job;
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
