import { api, el, metric, ensureAuth, authHeaders } from "./api.js";

const routes = {
  overview: renderOverview,
  conversations: renderConversations,
  issues: renderIssues,
  routes: renderRoutes,
  costs: renderCosts,
  budgets: renderBudgets,
  health: renderHealth,
  knowledge: renderKnowledge,
  examples: renderExamples,
  quality: renderQuality,
  prompts: renderPrompts,
  models: renderModels,
  flags: renderFlags,
  roles: renderRoles,
  retention: renderRetention,
  masking: renderMasking,
  search: renderGovernanceSearch,
  audit: renderAudit,
};

/** Role workspaces focused on completing work, not module catalogs. */
const workspaces = [
  {
    id: "knowledge_ops",
    label: "知識營運",
    hint: "待辦 → 修正知識 → 審核發布 → 驗證回答 → 結案",
    items: [
      ["quality", "我的待辦／品質案件", "ops.feedback.read"],
      ["knowledge", "文件／FAQ", "ops.knowledge.read"],
      ["examples", "案例集驗證", "ops.examples.read"],
      ["conversations", "回答驗證", "ops.conversations.read"],
    ],
  },
  {
    id: "ai_ops",
    label: "AI 管理",
    hint: "資料集、評測、Prompt、模型與發布",
    items: [
      ["examples", "資料集／案例", "ops.examples.read"],
      ["prompts", "Prompt 與評測", "ops.prompts.read"],
      ["models", "模型設定", "ops.models.read"],
      ["flags", "Feature Flag", "ops.flags.read"],
    ],
  },
  {
    id: "platform",
    label: "平台管理",
    hint: "權限、背景工作、稽核、保存與告警",
    items: [
      ["overview", "營運總覽", "ops.summary.read"],
      ["issues", "Issue 分析", "ops.issues.read"],
      ["routes", "路由來源", "ops.issues.read"],
      ["costs", "成本分析", "ops.cost.read"],
      ["budgets", "預算與告警", "ops.budget.read"],
      ["health", "系統健康度", "ops.health.read"],
      ["roles", "權限／角色", "ops.roles.read"],
      ["retention", "保存政策", "ops.retention.read"],
      ["masking", "遮罩政策", "ops.retention.read"],
      ["search", "全域搜尋", "ops.search.read"],
      ["audit", "稽核紀錄", "ops.audit.read"],
    ],
  },
];

const ROLE_DEFAULT_WORKSPACE = {
  KNOWLEDGE_ADMIN: "knowledge_ops",
  SERVICE_OWNER: "knowledge_ops",
  AI_ADMIN: "ai_ops",
  SYSTEM_ADMIN: "platform",
  ANALYST: "platform",
  AUDITOR: "platform",
};

const NAV_FILTERS_KEY = "ai_ops_nav_filters";
const WORKSPACE_KEY = "ai_ops_active_workspace";

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
  const defaultWorkspace =
    ROLE_DEFAULT_WORKSPACE[capabilities.role] || visibleWorkspaces()[0]?.id || "platform";
  if (!sessionStorage.getItem(WORKSPACE_KEY)) {
    sessionStorage.setItem(WORKSPACE_KEY, defaultWorkspace);
  }
  const firstView = firstVisibleView(activeWorkspaceId()) || "overview";
  renderNav(firstView);
  document.getElementById("meta-panel").textContent =
    `角色：${capabilities.role}｜驗證：${capabilities.authMode}｜資料更新：即時讀取 Analytics Store`;
}

function activeWorkspaceId() {
  return sessionStorage.getItem(WORKSPACE_KEY) || "knowledge_ops";
}

function visibleWorkspaces() {
  const allowed = new Set(capabilities?.capabilities || []);
  return workspaces
    .map((workspace) => ({
      ...workspace,
      items: workspace.items.filter(([, , capability]) => !capability || allowed.has(capability)),
    }))
    .filter((workspace) => workspace.items.length > 0);
}

function firstVisibleView(workspaceId) {
  const workspace = visibleWorkspaces().find((item) => item.id === workspaceId);
  return workspace?.items[0]?.[0] || null;
}

function renderNav(active) {
  const nav = document.getElementById("nav");
  nav.replaceChildren();
  const allowed = new Set(capabilities?.capabilities || []);
  const visible = visibleWorkspaces();
  let workspaceId = activeWorkspaceId();
  if (!visible.some((item) => item.id === workspaceId)) {
    workspaceId = visible[0]?.id || "platform";
    sessionStorage.setItem(WORKSPACE_KEY, workspaceId);
  }
  const workspace = visible.find((item) => item.id === workspaceId) || visible[0];

  const switcher = el("div", "workspace-switcher");
  for (const item of visible) {
    const button = el("button", item.id === workspaceId ? "workspace active" : "workspace", item.label);
    button.type = "button";
    button.title = item.hint;
    button.addEventListener("click", () => {
      sessionStorage.setItem(WORKSPACE_KEY, item.id);
      const nextView = item.items[0]?.[0] || "overview";
      renderNav(nextView);
    });
    switcher.append(button);
  }
  nav.append(switcher);

  if (workspace?.hint) {
    nav.append(el("p", "workspace-hint", workspace.hint));
  }

  const itemRow = el("div", "nav-items");
  for (const [id, label, capability] of workspace?.items || []) {
    if (capability && !allowed.has(capability)) {
      continue;
    }
    const button = el("button", active === id ? "active" : "", label);
    button.addEventListener("click", () => {
      renderNav(id);
      routes[id]();
    });
    itemRow.append(button);
  }
  nav.append(itemRow);
  if (typeof routes[active] === "function") {
    routes[active]();
  } else if (workspace?.items[0]) {
    routes[workspace.items[0][0]]();
  }
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
      ...(data.costDisplayEnabled === false
        ? [metric("成本顯示", "已關閉")]
        : [
            metric("估算成本 USD", data.estimatedCostUsd),
            metric("成本完整率", data.costCoverage),
          ]),
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
  const syncPanel = el("section", "panel");
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
  app.replaceChildren(panel, faqPanel, syncPanel);

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
  await Promise.all([
    loadDocuments(),
    renderFaqManagement(faqPanel),
    renderSyncManagement(syncPanel),
  ]);
}

async function showSyncDetail(jobId, panel) {
  try {
    const detail = await api(`/api/sync-jobs/${encodeURIComponent(jobId)}`);
    const job = detail.job;
    const allowed = new Set(capabilities?.capabilities || []);
    const content = el("div");
    content.append(
      el("p", "", `${job.status}｜階段 ${job.current_stage}｜進度 ${job.progress_percent}%｜ETag ${job.etag}`),
      el("p", "", `範圍：${job.scope_type} ${job.scope_ids.join(", ") || "全部"}`),
      el("p", "", `文件數：${job.document_count}｜Target release：${job.target_release || "未切換"}`),
      el("p", "", `Checkpoint：${job.checkpoint_stage || "-"}｜Retry checkpoint：${job.retry_checkpoint_stage || "-"}`),
    );
    if (job.error_summary) content.append(el("div", "error", job.error_summary));
    if (job.warnings.length) content.append(el("p", "warning", job.warnings.join("；")));
    const actions = el("div", "filter-bar");
    if (allowed.has("ops.sync.write") && ["FAILED", "CANCELLED"].includes(job.status)) {
      const retry = el("button", "", "重試");
      retry.addEventListener("click", async () => {
        const reason = window.prompt("重試原因");
        if (!reason?.trim()) return;
        await api(`/api/sync-jobs/${jobId}/retry`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
          body: JSON.stringify({ reason: reason.trim() }),
        });
        await renderSyncManagement(panel);
      });
      actions.append(retry);
    }
    if (allowed.has("ops.sync.write") && ["QUEUED", "VALIDATING", "BUILDING", "VERIFYING"].includes(job.status)) {
      const cancel = el("button", "", "取消");
      cancel.addEventListener("click", async () => {
        const reason = window.prompt("取消原因");
        if (!reason?.trim()) return;
        await api(`/api/sync-jobs/${jobId}/cancel`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reason: reason.trim(), expected_etag: job.etag }),
        });
        await renderSyncManagement(panel);
      });
      actions.append(cancel);
    }
    content.append(actions, el("h3", "", `Audit（${detail.audit.length}）`));
    for (const event of detail.audit) {
      content.append(el("p", "metric-label", `${event.occurred_at}｜${event.action}｜${event.actor_id}`));
    }
    showContentModal(`Sync Job ${job.job_id}`, content);
  } catch (error) {
    showContentModal("Sync Job", el("div", "error", error.message));
  }
}

async function renderSyncManagement(panel) {
  panel.replaceChildren(el("h2", "", "重新同步 / 索引"), el("p", "empty", "載入中…"));
  const allowed = new Set(capabilities?.capabilities || []);
  try {
    const data = await api("/api/sync-jobs");
    const actions = el("div", "filter-bar");
    if (allowed.has("ops.sync.write")) {
      const create = el("button", "", "建立全量 Sync");
      create.addEventListener("click", async () => {
        const reason = window.prompt("Sync 原因");
        if (!reason?.trim()) return;
        try {
          await api("/api/sync-jobs", {
            method: "POST",
            headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
            body: JSON.stringify({ scope_type: "ALL", scope_ids: [], reason: reason.trim() }),
          });
          await renderSyncManagement(panel);
        } catch (error) {
          showContentModal("建立 Sync 失敗", el("div", "error", error.message));
        }
      });
      actions.append(create);
    }
    const result = el("div");
    if (!(data.items || []).length) {
      result.append(el("p", "empty", "目前沒有 Sync Job。"));
    } else {
      const table = el("table");
      table.innerHTML = "<thead><tr><th>時間</th><th>範圍</th><th>狀態</th><th>進度</th><th>錯誤 / 警告</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const job of data.items) {
        const action = el("td");
        const detail = el("button", "", "查看");
        detail.addEventListener("click", () => showSyncDetail(job.job_id, panel));
        action.append(detail);
        const progress = `${job.progress_percent}% / ${job.checkpoint_stage || "尚無 checkpoint"}`;
        const row = el("tr");
        row.append(
          el("td", "", job.requested_at),
          el("td", "", `${job.scope_type} ${job.scope_ids.join(", ")}`),
          el("td", "", job.status),
          el("td", "", progress),
          el("td", "", job.error_summary || job.warnings.join("；") || "-"),
          action,
        );
        body.append(row);
      }
      table.append(body);
      result.append(table);
    }
    panel.replaceChildren(el("h2", "", "重新同步 / 索引"), actions, result);
  } catch (error) {
    panel.replaceChildren(el("h2", "", "重新同步 / 索引"), el("div", "error", error.message));
  }
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

function buildFaqForm(content = {}) {
  const form = el("form", "form-grid");
  form.append(
    faqField("FAQ Key", "faq_key", content.faq_key || ""),
    faqField("問題", "question", content.question || ""),
    faqField("固定答案", "answer", content.answer || "", true),
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
  );
  return form;
}

function faqPayload(form) {
  const values = new FormData(form);
  const split = (name) => String(values.get(name) || "").split(",").map((item) => item.trim()).filter(Boolean);
  const groups = split("audience_group_ids");
  return {
    faq_key: values.get("faq_key"), question: values.get("question"),
    answer: values.get("answer"), category: values.get("category"),
    keywords: split("keywords"), owner_unit_id: values.get("owner_unit_id"),
    business_contact: values.get("business_contact"), issue_type_ids: split("issue_type_ids"),
    audience_type: groups.length ? "GROUPS" : "ALL", audience_group_ids: groups,
  };
}

function showFaqCreateModal(panel) {
  const form = buildFaqForm();
  const message = el("div");
  const submit = el("button", "", "建立草稿");
  submit.type = "submit";
  form.append(submit, message);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    message.replaceChildren();
    try {
      const created = await api("/api/faqs", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify(faqPayload(form)),
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

function showFaqEditModal(faq, version, panel) {
  const form = buildFaqForm(version.content);
  const message = el("div");
  const submit = el("button", "", "建立新版本");
  submit.type = "submit";
  form.append(submit, message);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    message.replaceChildren();
    try {
      await api(`/api/faqs/${encodeURIComponent(faq.faq_id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ ...faqPayload(form), expected_etag: faq.etag }),
      });
      await renderFaqManagement(panel);
      await showFaqDetail(faq.faq_id, panel);
    } catch (error) {
      message.replaceChildren(el("div", "error", error.message));
    } finally {
      submit.disabled = false;
    }
  });
  showContentModal(`編輯 FAQ v${version.version_number}`, form);
}

async function showFaqDetail(faqId, panel) {
  try {
    const detail = await api(`/api/faqs/${encodeURIComponent(faqId)}`);
    const allowed = new Set(capabilities?.capabilities || []);
    const faq = detail.faq;
    const current = detail.versions.find((version) => version.version_id === faq.draft_version_id)
      || detail.versions.find((version) => version.version_id === faq.published_version_id)
      || detail.versions.at(-1);
    const content = el("div");
    content.append(
      el("p", "", `FAQ：${faq.status}｜工作版本：v${current.version_number} ${current.status}｜ETag：${faq.etag}`),
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
    if (allowed.has("ops.faq.write") && current.status !== "IN_REVIEW") {
      const edit = el("button", "", "建立修訂版本");
      edit.addEventListener("click", () => showFaqEditModal(faq, current, panel));
      actions.append(edit);
    }
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
    const performance = el("button", "", "查看命中成效");
    performance.addEventListener("click", async () => {
      try {
        const data = await api(`/api/faqs/${faqId}/performance`);
        const result = el("div");
        result.append(el("p", "", `總命中：${data.totalHitCount}`));
        const versions = el("table");
        versions.innerHTML = "<thead><tr><th>Version</th><th>Hits</th></tr></thead>";
        const versionRows = el("tbody");
        for (const item of data.byVersion || []) {
          const row = el("tr");
          row.append(el("td", "", item.versionId), el("td", "", String(item.hitCount)));
          versionRows.append(row);
        }
        versions.append(versionRows);
        const recent = el("table");
        recent.innerHTML = "<thead><tr><th>時間</th><th>Conversation</th><th>Turn</th><th>Version</th></tr></thead>";
        const recentRows = el("tbody");
        for (const item of data.recentHits || []) {
          const row = el("tr");
          row.append(
            el("td", "", item.occurredAt), el("td", "", item.conversationId || "-"),
            el("td", "", item.turnId || "-"), el("td", "", item.versionId || "legacy-unattributed"),
          );
          recentRows.append(row);
        }
        recent.append(recentRows);
        result.append(el("h3", "", "版本歸因"), versions, el("h3", "", "最近命中"), recent);
        showContentModal("FAQ 命中成效", result);
      } catch (error) {
        showContentModal("FAQ 命中成效", el("div", "error", error.message));
      }
    });
    actions.append(performance);
    content.append(actions, el("h3", "", `測試案例（${detail.tests.length}）`));
    for (const test of detail.tests) content.append(el("p", "", `${test.kind}｜${test.utterance}`));
    content.append(el("h3", "", `版本歷史（${detail.versions.length}）`));
    const versions = el("table");
    versions.innerHTML = "<thead><tr><th>版本</th><th>狀態</th><th>建立者</th><th>操作</th></tr></thead>";
    const versionRows = el("tbody");
    for (const version of [...detail.versions].reverse()) {
      const action = el("td");
      const canRollback = allowed.has("ops.faq.activate")
        && version.version_id !== faq.published_version_id
        && ["SUPERSEDED", "DISABLED"].includes(version.status)
        && version.approved_by;
      if (canRollback) {
        const rollback = el("button", "", "回復此版本");
        rollback.addEventListener("click", () => {
          const reason = window.prompt(`請輸入回復 v${version.version_number} 的原因`);
          if (!reason?.trim()) return;
          run(`/api/faqs/${faqId}/versions/${version.version_id}/rollback`, {
            expected_etag: faq.etag,
            reason: reason.trim(),
          });
        });
        action.append(rollback);
      } else {
        action.textContent = version.version_id === faq.published_version_id ? "目前發布" : "-";
      }
      const row = el("tr");
      row.append(
        el("td", "", `v${version.version_number}`),
        el("td", "", version.status),
        el("td", "", version.created_by),
        action,
      );
      versionRows.append(row);
    }
    versions.append(versionRows);
    content.append(versions);
    content.append(el("h3", "", `Audit（${detail.audit.length}）`));
    for (const event of detail.audit) content.append(el("p", "metric-label", `${event.occurred_at}｜${event.action}｜${event.actor_id}`));
    showContentModal(current.content.question, content);
  } catch (error) {
    showContentModal("FAQ", el("div", "error", error.message));
  }
}

function exampleSelect(label, name, options, value = "") {
  const wrap = el("label", "form-field");
  wrap.append(el("span", "metric-label", label));
  const select = el("select");
  select.name = name;
  for (const [optionValue, optionLabel] of options) {
    const option = el("option", "", optionLabel);
    option.value = optionValue;
    select.append(option);
  }
  select.value = value;
  wrap.append(select);
  return wrap;
}

function buildExampleForm(record = null) {
  const form = el("form", "form-grid");
  if (!record) {
    form.append(
      exampleSelect("來源", "source_type", [
        ["MANUAL", "手動建立"], ["FAQ", "FAQ 版本"], ["DOCUMENT", "文件版本"],
      ]),
      faqField("Source ID", "source_id", "", false, false),
      faqField("Source Version ID", "source_version_id", "", false, false),
    );
  }
  form.append(
    faqField("案例文字", "text", record?.text || "", true),
    faqField("Expected Issue Type ID", "expected_issue_type_id", record?.expected_issue_type_id || ""),
    exampleSelect("Expected Route", "expected_route", [
      ["FAQ", "FAQ"], ["KNOWLEDGE", "KNOWLEDGE"],
      ["TICKET", "TICKET"], ["HANDOFF", "HANDOFF"],
    ], record?.expected_route || "FAQ"),
    exampleSelect("標籤", "label", [
      ["POSITIVE", "正例"], ["NEGATIVE", "反例"],
    ], record?.label || "POSITIVE"),
    faqField("原因（反例必填）", "reason", record?.reason || "", true, false),
  );
  return form;
}

function examplePayload(form) {
  const values = new FormData(form);
  return {
    text: values.get("text"),
    expected_issue_type_id: values.get("expected_issue_type_id"),
    expected_route: values.get("expected_route"),
    label: values.get("label"),
    reason: values.get("reason") || null,
  };
}

function showExampleCreateModal() {
  const form = buildExampleForm();
  const message = el("div");
  const submit = el("button", "", "建立草稿");
  submit.type = "submit";
  form.append(submit, message);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    message.replaceChildren();
    const values = new FormData(form);
    const sourceType = values.get("source_type");
    const sourceId = String(values.get("source_id") || "").trim();
    const versionId = String(values.get("source_version_id") || "").trim();
    let path = "/api/examples/manual";
    if (["FAQ", "DOCUMENT", "CONVERSATION"].includes(sourceType)) {
      if (!sourceId || (sourceType !== "CONVERSATION" && !versionId)) {
        message.replaceChildren(el("div", "error", "來源 ID 必填；FAQ/文件來源也需要 Version ID。"));
        submit.disabled = false;
        return;
      }
      if (sourceType === "CONVERSATION") {
        path = `/api/conversations/${encodeURIComponent(sourceId)}/examples`;
      } else {
        const prefix = sourceType === "FAQ" ? "/api/faqs" : "/api/knowledge";
        path = `${prefix}/${encodeURIComponent(sourceId)}/versions/${encodeURIComponent(versionId)}/examples`;
      }
    }
    try {
      const created = await api(path, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify(examplePayload(form)),
      });
      document.getElementById("modal-root").hidden = true;
      await renderExamples();
      await showExampleDetail(created.example.example_id);
    } catch (error) {
      message.replaceChildren(el("div", "error", error.message));
    } finally {
      submit.disabled = false;
    }
  });
  showContentModal("新增品質案例", form);
}

function showExampleEditModal(record) {
  const form = buildExampleForm(record);
  const message = el("div");
  const submit = el("button", "", "儲存為草稿");
  submit.type = "submit";
  form.append(submit, message);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    try {
      await api(`/api/examples/${encodeURIComponent(record.example_id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ ...examplePayload(form), expected_etag: record.etag }),
      });
      await renderExamples();
      await showExampleDetail(record.example_id);
    } catch (error) {
      message.replaceChildren(el("div", "error", error.message));
    } finally {
      submit.disabled = false;
    }
  });
  showContentModal("編輯品質案例", form);
}

async function showExampleDetail(exampleId) {
  try {
    const detail = await api(`/api/examples/${encodeURIComponent(exampleId)}`);
    const record = detail.example;
    const allowed = new Set(capabilities?.capabilities || []);
    const content = el("div");
    content.append(
      el("p", "", `${record.status}｜${record.source_type}:${record.source_id}｜ETag ${record.etag}`),
      el("p", "", record.text),
      el("p", "", `Expected：${record.expected_issue_type_id} → ${record.expected_route}`),
      el("p", "", `標籤：${record.label}｜Owner：${record.owner_unit_id}`),
    );
    if (record.reason) content.append(el("p", "", `原因：${record.reason}`));
    if (record.dataset_version) content.append(el("p", "", `Dataset：${record.dataset_version}`));
    const actions = el("div", "filter-bar");
    const run = async (path, payload) => {
      try {
        await api(path, {
          method: "POST",
          headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
          body: JSON.stringify(payload),
        });
        await renderExamples();
        await showExampleDetail(exampleId);
      } catch (error) {
        showContentModal("案例操作失敗", el("div", "error", error.message));
      }
    };
    if (allowed.has("ops.examples.write") && record.status !== "RETIRED") {
      const edit = el("button", "", "編輯");
      edit.addEventListener("click", () => showExampleEditModal(record));
      actions.append(edit);
    }
    if (allowed.has("ops.examples.verify") && ["DRAFT", "REJECTED"].includes(record.status)) {
      const verify = el("button", "", "驗證通過");
      verify.addEventListener("click", () => run(`/api/examples/${exampleId}/review`, {
        expected_etag: record.etag, approve: true, reason: "SYSTEM_ADMIN 已驗證標籤與預期結果",
      }));
      const reject = el("button", "", "拒絕");
      reject.addEventListener("click", () => {
        const reason = window.prompt("請輸入拒絕原因");
        if (reason?.trim()) run(`/api/examples/${exampleId}/review`, {
          expected_etag: record.etag, approve: false, reason: reason.trim(),
        });
      });
      actions.append(verify, reject);
    }
    if (allowed.has("ops.examples.retire") && record.status !== "RETIRED") {
      const retire = el("button", "", "退役");
      retire.addEventListener("click", () => {
        const reason = window.prompt("請輸入退役原因");
        if (reason?.trim()) run(`/api/examples/${exampleId}/retire`, {
          expected_etag: record.etag, reason: reason.trim(),
        });
      });
      actions.append(retire);
    }
    content.append(actions, el("h3", "", `Audit（${detail.audit.length}）`));
    for (const event of detail.audit) {
      content.append(el("p", "metric-label", `${event.occurred_at}｜${event.action}｜${event.actor_id}`));
    }
    showContentModal(`品質案例 ${record.example_id}`, content);
  } catch (error) {
    showContentModal("品質案例", el("div", "error", error.message));
  }
}

async function renderExamples() {
  const app = document.getElementById("app");
  const panel = el("section", "panel");
  const allowed = new Set(capabilities?.capabilities || []);
  const actions = el("div", "filter-bar");
  const sourceType = el("select");
  sourceType.innerHTML = `
    <option value="">全部來源</option><option value="FAQ">FAQ</option>
    <option value="DOCUMENT">DOCUMENT</option><option value="CONVERSATION">CONVERSATION</option>
    <option value="MANUAL">MANUAL</option>`;
  const status = el("select");
  status.innerHTML = `
    <option value="">全部狀態</option><option value="DRAFT">DRAFT</option>
    <option value="VERIFIED">VERIFIED</option><option value="REJECTED">REJECTED</option>
    <option value="RETIRED">RETIRED</option>`;
  const sourceId = el("input");
  sourceId.placeholder = "Source ID";
  const apply = el("button", "", "套用篩選");
  const result = el("div");
  const summary = el("span", "metric-label");
  const load = async () => {
    try {
      const params = new URLSearchParams();
      if (sourceType.value) params.set("source_type", sourceType.value);
      if (status.value) params.set("status", status.value);
      if (sourceId.value.trim()) params.set("source_id", sourceId.value.trim());
      const data = await api(`/api/examples?${params}`);
      result.replaceChildren();
      summary.textContent = `共 ${data.total || 0} 筆`;
      if (!(data.items || []).length) {
        result.append(el("p", "empty", "沒有符合條件的品質案例。"));
        return;
      }
      const table = el("table");
      table.innerHTML = "<thead><tr><th>案例</th><th>來源</th><th>預期</th><th>狀態</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const item of data.items) {
        const action = el("td");
        const detail = el("button", "", "查看與處理");
        detail.addEventListener("click", () => showExampleDetail(item.example_id));
        action.append(detail);
        const row = el("tr");
        row.append(
          el("td", "", item.text),
          el("td", "", `${item.source_type}:${item.source_id}`),
          el("td", "", `${item.expected_issue_type_id} → ${item.expected_route}`),
          el("td", "", item.status),
          action,
        );
        body.append(row);
      }
      table.append(body);
      result.append(table);
    } catch (error) {
      result.replaceChildren(el("div", "error", error.message));
    }
  };
  apply.addEventListener("click", load);
  if (allowed.has("ops.examples.write")) {
    const create = el("button", "", "新增案例");
    create.addEventListener("click", showExampleCreateModal);
    actions.append(create);
  }
  actions.append(sourceType, status, sourceId, apply, summary);
  panel.append(el("h2", "", "品質案例集"), actions, result);
  app.replaceChildren(panel);
  await load();
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

async function showQualityCaseDetail(caseId) {
  try {
    const detail = await api(`/api/quality-cases/${encodeURIComponent(caseId)}`);
    const qualityCase = detail.case;
    const allowed = new Set(capabilities?.capabilities || []);
    const statusLabels = {
      NEW: "新建",
      TRIAGED: "已分派",
      IN_PROGRESS: "修正中",
      WAITING_REVIEW: "待審核發布",
      OBSERVING: "觀察成效",
      RESOLVED: "已結案",
      WONT_FIX: "不處理",
      DUPLICATE: "重複案件",
    };
    const transitionLabels = {
      TRIAGED: "分派處理",
      IN_PROGRESS: "開始修正知識",
      WAITING_REVIEW: "送審／待發布",
      OBSERVING: "進入觀察",
      RESOLVED: "驗證通過並結案",
      WONT_FIX: "標記不處理",
      DUPLICATE: "標記重複",
    };
    const content = el("div");
    content.append(
      el(
        "p",
        "",
        `${statusLabels[qualityCase.status] || qualityCase.status}｜優先級 ${qualityCase.priority}`,
      ),
      el("p", "", qualityCase.description || "-"),
      el(
        "p",
        "",
        `負責單位：${qualityCase.owner_unit_id}｜承辦：${qualityCase.assignee_id || "未指派"}`,
      ),
      el(
        "p",
        "",
        `問題類型：${qualityCase.issue_type_display_name || qualityCase.issue_type_id || "未指定"}`,
      ),
      el(
        "p",
        "",
        `頻率 ${qualityCase.frequency}｜負評率 ${(qualityCase.negative_rate * 100).toFixed(1)}%｜轉人工率 ${(qualityCase.handoff_rate * 100).toFixed(1)}%`,
      ),
      el(
        "p",
        "",
        `關聯 FAQ：${qualityCase.faq_ids.join(", ") || "-"}｜文件：${qualityCase.document_ids.join(", ") || "-"}`,
      ),
    );
    const loopHints = el("div", "filter-bar");
    loopHints.append(
      el("span", "metric-label", "閉環捷徑："),
      drillLink("修正文件／FAQ", "knowledge"),
      drillLink("案例驗證", "examples"),
      drillLink("對話驗證", "conversations", {
        issueTypeId: qualityCase.issue_type_id || "",
      }),
    );
    if (capabilities?.knowledgePortalUrl) {
      const portal = el("a", "drill-link", "開啟知識入口");
      portal.href = capabilities.knowledgePortalUrl;
      portal.target = "_blank";
      portal.rel = "noopener noreferrer";
      loopHints.append(portal);
    }
    content.append(loopHints);
    const transitions = {
      NEW: ["TRIAGED", "WONT_FIX", "DUPLICATE"],
      TRIAGED: ["IN_PROGRESS", "WONT_FIX", "DUPLICATE"],
      IN_PROGRESS: ["WAITING_REVIEW", "OBSERVING", "WONT_FIX", "DUPLICATE"],
      WAITING_REVIEW: ["IN_PROGRESS", "OBSERVING", "WONT_FIX"],
      OBSERVING: ["IN_PROGRESS", "RESOLVED", "WONT_FIX"],
    };
    const actions = el("div", "filter-bar");
    if (allowed.has("ops.quality.write")) {
      const linkFaq = el("button", "", "連結既有 FAQ");
      linkFaq.addEventListener("click", async () => {
        const faqId = window.prompt("請輸入 FAQ ID");
        if (!faqId?.trim()) return;
        await api(`/api/quality-cases/${caseId}/content`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ expected_etag: qualityCase.etag, faq_id: faqId.trim() }),
        });
        await showQualityCaseDetail(caseId);
      });
      actions.append(linkFaq);
      if (allowed.has("ops.faq.write") && qualityCase.issue_type_id) {
        const draftFaq = el("button", "", "建立 FAQ 草稿");
        draftFaq.addEventListener("click", () => {
          const form = buildFaqForm({
            owner_unit_id: qualityCase.owner_unit_id,
            issue_type_ids: [qualityCase.issue_type_id],
          });
          const submit = el("button", "", "建立並連結草稿");
          submit.type = "submit";
          form.append(submit);
          form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const payload = faqPayload(form);
            await api(`/api/quality-cases/${caseId}/faq-draft`, {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                expected_case_etag: qualityCase.etag,
                faq_key: payload.faq_key, question: payload.question, answer: payload.answer,
                category: payload.category, keywords: payload.keywords,
                business_contact: payload.business_contact,
                audience_type: payload.audience_type,
                audience_group_ids: payload.audience_group_ids,
              }),
            });
            await renderQuality();
          });
          showContentModal("由品質案件建立 FAQ 草稿", form);
        });
        actions.append(draftFaq);
      }
      if (qualityCase.status === "OBSERVING") {
        const refresh = el("button", "", "刷新觀察指標");
        refresh.addEventListener("click", async () => {
          await api(`/api/quality-cases/${caseId}/observation/refresh`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ expected_etag: qualityCase.etag }),
          });
          await showQualityCaseDetail(caseId);
        });
        actions.append(refresh);
      }
    }
    for (const status of transitions[qualityCase.status] || []) {
      const terminal = ["RESOLVED", "WONT_FIX", "DUPLICATE"].includes(status);
      const capability = terminal ? "ops.quality.resolve" : "ops.quality.write";
      if (!allowed.has(capability)) continue;
      const button = el("button", "", transitionLabels[status] || status);
      button.addEventListener("click", async () => {
        const reason = window.prompt(
          `請輸入轉為「${transitionLabels[status] || status}」的原因`,
        );
        if (terminal && !reason?.trim()) return;
        try {
          await api(`/api/quality-cases/${caseId}/transition`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              expected_etag: qualityCase.etag,
              status,
              reason: reason?.trim() || null,
              resolution_type: terminal ? "MANUAL_REVIEW" : null,
            }),
          });
          await renderQuality();
          await showQualityCaseDetail(caseId);
        } catch (error) {
          showContentModal("品質案件操作失敗", el("div", "error", error.message));
        }
      });
      actions.append(button);
    }
    if (qualityCase.observation_baseline) {
      content.append(
        el("h3", "", "觀察指標"),
        el("pre", "json-block", JSON.stringify({
          baseline: qualityCase.observation_baseline,
          latest: qualityCase.observation_latest,
        }, null, 2)),
      );
    }
    content.append(actions, el("h3", "", `操作紀錄（${detail.audit.length}）`));
    for (const event of detail.audit) {
      content.append(el("p", "metric-label", `${event.occurred_at}｜${event.action}｜${event.actor_id}`));
    }
    showContentModal(qualityCase.title, content);
  } catch (error) {
    showContentModal("品質案件", el("div", "error", error.message));
  }
}

async function buildQualityLoopPanel() {
  const panel = el("section", "panel");
  panel.append(el("h2", "", "改善案件池"));
  panel.append(
    el(
      "p",
      "metric-label",
      "閉環步驟：待辦／負評 → 合併案件 → 修正文件／FAQ → 審核發布 → 案例與對話驗證 → 觀察成效並結案。",
    ),
  );
  const allowed = new Set(capabilities?.capabilities || []);
  const controls = el("div", "filter-bar");
  if (allowed.has("ops.quality.write")) {
    const refresh = el("button", "", "掃描新候選");
    refresh.addEventListener("click", async () => {
      refresh.disabled = true;
      try {
        await api("/api/quality-candidates/refresh", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ days: 30 }),
        });
        await renderQuality();
      } catch (error) {
        showContentModal("候選掃描失敗", el("div", "error", error.message));
      } finally {
        refresh.disabled = false;
      }
    });
    controls.append(refresh);
  }
  panel.append(controls);
  const caseTypeLabels = {
    NO_ANSWER: "無答案",
    NEGATIVE_FEEDBACK: "負評",
    HANDOFF: "轉人工",
    KNOWLEDGE_GAP: "知識缺口",
  };
  const statusLabels = {
    NEW: "新建",
    TRIAGED: "已分派",
    IN_PROGRESS: "修正中",
    WAITING_REVIEW: "待審核",
    OBSERVING: "觀察中",
    RESOLVED: "已結案",
    WONT_FIX: "不處理",
    DUPLICATE: "重複",
  };
  const [candidateData, caseData] = await Promise.all([
    api("/api/quality-candidates?status=OPEN"),
    api("/api/quality-cases"),
  ]);
  panel.append(el("h3", "", `待合併候選（${candidateData.total || 0}）`));
  const selected = new Set();
  if ((candidateData.items || []).length) {
    const table = el("table");
    table.innerHTML =
      "<thead><tr><th>選取</th><th>案件類型</th><th>問題類型</th><th>摘要</th></tr></thead>";
    const body = el("tbody");
    for (const item of candidateData.items) {
      const checkbox = el("input");
      checkbox.type = "checkbox";
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) selected.add(item.candidate_id);
        else selected.delete(item.candidate_id);
      });
      const selectCell = el("td");
      selectCell.append(checkbox);
      const row = el("tr");
      row.append(
        selectCell,
        el("td", "", caseTypeLabels[item.case_type] || item.case_type),
        el(
          "td",
          "",
          item.issue_type_display_name || item.issue_type_id || "未分類",
        ),
        el("td", "", item.description),
      );
      body.append(row);
    }
    table.append(body);
    panel.append(table);
    if (allowed.has("ops.quality.write")) {
      const merge = el("button", "", "合併為改善案件");
      merge.addEventListener("click", async () => {
        if (!selected.size) return;
        const title = window.prompt("改善案件標題");
        if (!title?.trim()) return;
        try {
          await api("/api/quality-candidates/merge", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              candidate_ids: [...selected], title: title.trim(),
              description: "由營運事件候選合併", priority: "MEDIUM",
            }),
          });
          await renderQuality();
        } catch (error) {
          showContentModal("合併失敗", el("div", "error", error.message));
        }
      });
      panel.append(merge);
    }
  } else {
    panel.append(el("p", "empty", "目前沒有待處理候選。"));
  }
  panel.append(el("h3", "", `進行中案件（${caseData.total || 0}）`));
  if ((caseData.items || []).length) {
    const table = el("table");
    table.innerHTML =
      "<thead><tr><th>案件</th><th>狀態</th><th>優先級</th><th>負責單位／承辦</th><th>下一步</th></tr></thead>";
    const body = el("tbody");
    for (const item of caseData.items) {
      const action = el("td");
      const detail = el("button", "", "查看與處理");
      detail.addEventListener("click", () => showQualityCaseDetail(item.case_id));
      action.append(detail);
      const row = el("tr");
      row.append(
        el("td", "", item.title),
        el("td", "", statusLabels[item.status] || item.status),
        el("td", "", item.priority),
        el("td", "", `${item.owner_unit_id} / ${item.assignee_id || "未指派"}`),
        action,
      );
      body.append(row);
    }
    table.append(body);
    panel.append(table);
  }
  return panel;
}

async function buildGapPanel() {
  const panel = el("section", "panel");
  panel.append(el("h2", "", "Knowledge Gap 排序"));
  const data = await api("/api/gaps/summary?days=30");
  panel.append(el("p", "metric-label", `規則版本：${data.scoreVersion}｜Taxonomy：${data.taxonomyVersion}`));
  if (!(data.items || []).length) {
    panel.append(el("p", "empty", "目前沒有可評分的 Gap。"));
    return panel;
  }
  const table = el("table");
  table.innerHTML = "<thead><tr><th>Issue</th><th>Gap Score</th><th>頻率</th><th>無答案</th><th>負評</th><th>轉人工</th><th>成本</th></tr></thead>";
  const body = el("tbody");
  for (const item of data.items) {
    const row = el("tr");
    row.append(
      el("td", "", item.displayName || item.issueTypeId),
      el("td", "", item.gapScore.toFixed(2)),
      el("td", "", item.components.frequency.toFixed(2)),
      el("td", "", item.components.noAnswerRate.toFixed(2)),
      el("td", "", item.components.negativeFeedbackRate.toFixed(2)),
      el("td", "", item.components.handoffRate.toFixed(2)),
      el("td", "", item.components.estimatedCostUsd.toFixed(2)),
    );
    body.append(row);
  }
  table.append(body);
  panel.append(table);
  const clusterData = await api("/api/question-clusters");
  const allowed = new Set(capabilities?.capabilities || []);
  const clusterActions = el("div", "filter-bar");
  if (allowed.has("ops.quality.write")) {
    const generate = el("button", "", "產生單位／問題類型分組");
    generate.addEventListener("click", async () => {
      await api("/api/question-clusters/generate", { method: "POST" });
      await renderQuality();
    });
    clusterActions.append(generate);
  }
  panel.append(
    el("h3", "", `單位／問題類型分組（${clusterData.total || 0}）`),
    el(
      "p",
      "metric-label",
      "依 owner unit + issue type 分組，不是語意聚類。確認需求後再導入 embedding／人工審核。",
    ),
    clusterActions,
  );
  for (const cluster of (clusterData.items || []).filter((item) => item.status !== "SUPERSEDED")) {
    const row = el("div", "filter-bar");
    row.append(
      el("strong", "", cluster.name),
      el(
        "span",
        "metric-label",
        `${cluster.status}｜${cluster.grouping_method || "OWNER_UNIT_ISSUE_TYPE"}｜頻率 ${cluster.frequency}｜rev ${cluster.revision}`,
      ),
    );
    if (allowed.has("ops.quality.write") && cluster.status === "CANDIDATE") {
      for (const [action, label] of [["ACCEPT", "接受"], ["REJECT", "拒絕"], ["RENAME", "重新命名"]]) {
        const button = el("button", "", label);
        button.addEventListener("click", async () => {
          const name = action === "RENAME" ? window.prompt("Cluster 名稱", cluster.name) : null;
          if (action === "RENAME" && !name?.trim()) return;
          await api("/api/question-clusters/correct", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ cluster_ids: [cluster.cluster_id], action, name }),
          });
          await renderQuality();
        });
        row.append(button);
      }
    }
    panel.append(row);
  }
  return panel;
}

async function renderPrompts() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = new Set(capabilities?.capabilities || []);
    const [govData, candidateData, taxonomy, examples] = await Promise.all([
      api("/api/governance/prompts"),
      api("/api/prompts/candidates"),
      api("/api/taxonomy"),
      api("/api/examples?status=VERIFIED"),
    ]);
    const item = (govData.items || [])[0];
    const active = item?.active || {};
    const promptId = item?.prompt?.prompt_id;
    const activePanel = el("section", "panel");
    activePanel.append(
      el("h2", "", "Active Issue Extractor Prompt"),
      el("p", "metric-label", `環境影響：正式 Prompt 變更需候選 → Eval → 核准 → Canary → 啟用`),
      el("p", "metric-label", `Version ${active.version || "-"}｜${active.status || "-"}｜${active.activated_at || active.created_at || "-"}`),
      el("p", "metric-label", `Content Hash ${active.content_hash || "-"}｜核准者 ${active.approved_by || "-"}`),
    );
    if (active.template) {
      const inspect = el("button", "", "檢視內容");
      inspect.addEventListener("click", () => {
        showContentModal("Active Prompt", el("pre", "json-block", active.template));
      });
      activePanel.append(inspect);
    }

    const candidatePanel = el("section", "panel");
    candidatePanel.append(el("h2", "", "Prompt Candidates（Phase 3 治理）"));
    const verified = (examples.items || []).filter((entry) => entry.dataset_version);
    if (allowed.has("ops.prompts.candidates.create") && verified.length && promptId) {
      const form = el("form", "form-grid");
      form.append(
        exampleSelect(
          "Verified Dataset",
          "dataset_version",
          verified.map((entry) => [
            entry.dataset_version,
            `${entry.dataset_version}｜${entry.expected_route} ${entry.label}`,
          ]),
        ),
      );
      const generate = el("button", "", "建立候選");
      generate.type = "submit";
      form.append(generate);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const values = new FormData(form);
        try {
          await api(`/api/governance/prompts/${promptId}/candidates`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              dataset_version: values.get("dataset_version"),
              taxonomy_version: taxonomy.taxonomyVersion,
            }),
          });
          await renderPrompts();
        } catch (error) {
          showContentModal("候選產生失敗", el("div", "error", error.message));
        }
      });
      candidatePanel.append(form);
    }
    const versions = (item?.versions || []);
    const detail = promptId ? await api(`/api/governance/prompts/${promptId}`) : { versions: [] };
    const rows = detail.versions || versions;
    if (rows.length) {
      const table = el("table");
      table.innerHTML = "<thead><tr><th>Version</th><th>狀態</th><th>Dataset</th><th>建立者</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const version of rows.slice().reverse()) {
        const actions = el("td");
        const compare = el("button", "", "比較／風險");
        compare.addEventListener("click", async () => {
          const result = await api(`/api/governance/prompts/${promptId}/versions/${version.version_id}/diff`);
          const content = el("div");
          content.append(
            el("p", "", `Active ${result.active.version}`),
            el("p", "", `Candidate ${result.candidate.version}`),
            el("p", "", `Critical Eval: ${result.eval ? (result.eval.critical_passed ? "PASS" : "FAIL") : "尚未評測"}`),
          );
          if (result.diff) content.append(el("pre", "json-block", result.diff));
          showContentModal("Prompt 比較", content);
        });
        actions.append(compare);
        const addAction = (label, path, payload) => {
          const button = el("button", "", label);
          button.addEventListener("click", async () => {
            const reason = window.prompt(`${label}原因`);
            if (!reason || reason.trim().length < 3) return;
            await api(path, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ reason: reason.trim(), ...payload }),
            });
            await renderPrompts();
          });
          actions.append(button);
        };
        if (allowed.has("ops.prompts.eval.run") && ["CANDIDATE", "EVALUATED"].includes(version.status)) {
          const evalButton = el("button", "", "執行 Eval");
          evalButton.addEventListener("click", async () => {
            await api(`/api/governance/prompts/${promptId}/versions/${version.version_id}/eval`, { method: "POST" });
            await renderPrompts();
          });
          actions.append(evalButton);
        }
        if (allowed.has("ops.prompts.approve") && version.status === "EVALUATED") {
          addAction("送審核准", `/api/governance/prompts/${promptId}/versions/${version.version_id}/approve`, {});
        }
        if (allowed.has("ops.prompts.canary") && version.status === "APPROVED") {
          addAction("開始 Canary", `/api/governance/prompts/${promptId}/versions/${version.version_id}/canary`, {
            percent: 5,
            environment: "prod",
          });
        }
        if (allowed.has("ops.prompts.canary") && version.status === "CANARY") {
          addAction("停止 Canary", `/api/governance/prompts/${promptId}/canary/stop`, {});
          const evaluate = el("button", "", "評估 Canary 指標");
          evaluate.addEventListener("click", async () => {
            const sample = window.prompt("樣本數", "50");
            if (!sample) return;
            const errorRate = window.prompt("錯誤率 0-1", "0.05");
            if (errorRate == null) return;
            const negative = window.prompt("負評率 0-1", "0.1");
            if (negative == null) return;
            const handoff = window.prompt("Handoff 率 0-1", "0.2");
            if (handoff == null) return;
            const result = await api(`/api/governance/prompts/${promptId}/canary/evaluate`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                sample_size: Number(sample),
                error_rate: Number(errorRate),
                negative_feedback_rate: Number(negative),
                handoff_rate: Number(handoff),
                safety_alerts: 0,
              }),
            });
            showContentModal("Canary 評估", el("pre", "json-block", JSON.stringify(result, null, 2)));
            await renderPrompts();
          });
          actions.append(evaluate);
        }
        if (allowed.has("ops.prompts.activate") && version.status === "CANARY") {
          addAction("啟用正式版", `/api/governance/prompts/${promptId}/versions/${version.version_id}/activate`, {});
        }
        const row = el("tr");
        row.append(
          el("td", "", version.version),
          el("td", "", version.status),
          el("td", "", version.dataset_version || "-"),
          el("td", "", version.created_by),
          actions,
        );
        body.append(row);
      }
      table.append(body);
      candidatePanel.append(table);
    } else {
      candidatePanel.append(el("p", "empty", "目前沒有 Prompt Candidate。"));
    }
    if (allowed.has("ops.prompts.rollback")) {
      const rollback = el("button", "", "回復上一健康版本");
      rollback.addEventListener("click", async () => {
        const reason = window.prompt("回復原因");
        if (!reason || reason.trim().length < 3) return;
        await api(`/api/governance/prompts/${promptId}/rollback`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reason: reason.trim() }),
        });
        await renderPrompts();
      });
      candidatePanel.append(rollback);
    }
    // Keep Phase 2 POC list visible for continuity.
    if ((candidateData.items || []).length) {
      candidatePanel.append(el("p", "metric-label", `Phase 2 POC candidates: ${candidateData.items.length}`));
    }
    app.replaceChildren(activePanel, candidatePanel);
  } catch (error) {
    app.replaceChildren(el("div", "error", error.message));
  }
}

async function renderModels() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = new Set(capabilities?.capabilities || []);
    const data = await api("/api/governance/models");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "模型／Provider Allowlist"));
    for (const item of data.items || []) {
      const active = item.active || {};
      const configId = item.config?.config_id;
      panel.append(
        el("p", "", `${configId}｜${active.provider || "-"} / ${active.model_id || "-"}｜${active.status || "無正式版"}`),
        el("p", "metric-label", `Secret Ref ${active.secret_ref || "-"}｜Fallback ${active.fallback_model_id || "-"}`),
      );
      if (allowed.has("ops.models.read") && configId) {
        const simulate = el("button", "", "模擬 Fallback");
        simulate.addEventListener("click", async () => {
          const error = window.prompt("觸發錯誤", "TIMEOUT");
          if (!error) return;
          const result = await api(`/api/governance/models/${configId}/simulate-fallback`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ error }),
          });
          showContentModal("Fallback 模擬", el("pre", "json-block", JSON.stringify(result, null, 2)));
        });
        panel.append(simulate);
      }
      if (allowed.has("ops.models.activate") && configId) {
        const rollback = el("button", "", "回復上一健康模型");
        rollback.addEventListener("click", async () => {
          const reason = window.prompt("回復原因");
          if (!reason || reason.trim().length < 3) return;
          await api(`/api/governance/models/${configId}/rollback`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reason: reason.trim() }),
          });
          await renderModels();
        });
        panel.append(rollback);
      }
    }
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", "error", error.message));
  }
}

async function renderFlags() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = new Set(capabilities?.capabilities || []);
    const data = await api("/api/governance/flags");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "Feature Flags"));
    const table = el("table");
    table.innerHTML = "<thead><tr><th>Flag</th><th>Effective</th><th>Safety Locked</th><th>Owner</th><th>操作</th></tr></thead>";
    const body = el("tbody");
    for (const item of data.items || []) {
      const row = el("tr");
      const actions = el("td");
      const flagId = item.flag.flag_id;
      if (allowed.has("ops.flags.read")) {
        const effective = el("button", "", "查有效值");
        effective.addEventListener("click", async () => {
          const result = await api(`/api/governance/flags/${flagId}/effective?environment=lab`);
          showContentModal(`${flagId} effective`, el("pre", "json-block", JSON.stringify(result, null, 2)));
        });
        actions.append(effective);
      }
      row.append(
        el("td", "", flagId),
        el("td", "", String(item.effective)),
        el("td", "", item.flag.safety_locked ? "YES" : "NO"),
        el("td", "", item.flag.owner),
        actions,
      );
      body.append(row);
    }
    table.append(body);
    panel.append(table);
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", "error", error.message));
  }
}

async function renderRoles() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = new Set(capabilities?.capabilities || []);
    const data = await api("/api/governance/roles");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "角色映射請求"));
    if (allowed.has("ops.roles.request")) {
      const form = el("form", "form-grid");
      form.append(
        faqField("目標 Principal", "target_principal", ""),
        faqField("目標角色（可空）", "target_role", ""),
        faqField("新增 capabilities（逗號分隔）", "add_capabilities", ""),
        faqField("移除 capabilities（逗號分隔）", "remove_capabilities", ""),
        faqField("理由", "reason", ""),
      );
      const submit = el("button", "", "送出角色請求");
      submit.type = "submit";
      form.append(submit);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const values = new FormData(form);
        const reason = String(values.get("reason") || "").trim();
        if (reason.length < 3) return;
        const split = (raw) => String(raw || "").split(",").map((item) => item.trim()).filter(Boolean);
        await api("/api/governance/roles/requests", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            target_principal: String(values.get("target_principal") || "").trim(),
            target_role: String(values.get("target_role") || "").trim() || null,
            add_capabilities: split(values.get("add_capabilities")),
            remove_capabilities: split(values.get("remove_capabilities")),
            reason,
          }),
        });
        await renderRoles();
      });
      panel.append(form);
    }
    if (allowed.has("ops.roles.revoke")) {
      const revoke = el("button", "", "緊急撤權");
      revoke.addEventListener("click", async () => {
        const principal = window.prompt("要撤權的 principal");
        if (!principal) return;
        const reason = window.prompt("撤權原因");
        if (!reason || reason.trim().length < 3) return;
        await api("/api/governance/roles/revoke", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ principal: principal.trim(), reason: reason.trim() }),
        });
        await renderRoles();
      });
      panel.append(revoke);
    }
    const table = el("table");
    table.innerHTML = "<thead><tr><th>Change</th><th>Principal</th><th>狀態</th><th>請求者</th><th>操作</th></tr></thead>";
    const body = el("tbody");
    for (const change of (data.items || []).slice().reverse()) {
      const actions = el("td");
      if (allowed.has("ops.roles.approve") && change.status === "REQUESTED") {
        const approve = el("button", "", "核准");
        approve.addEventListener("click", async () => {
          const reason = window.prompt("核准原因");
          if (!reason || reason.trim().length < 3) return;
          await api(`/api/governance/roles/${change.change_id}/approve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reason: reason.trim() }),
          });
          await renderRoles();
        });
        actions.append(approve);
      }
      const row = el("tr");
      row.append(
        el("td", "", change.change_id.slice(0, 8)),
        el("td", "", change.target_principal),
        el("td", "", change.status),
        el("td", "", change.requested_by),
        actions,
      );
      body.append(row);
    }
    table.append(body);
    panel.append(table);
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", "error", error.message));
  }
}

async function renderRetention() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = new Set(capabilities?.capabilities || []);
    const data = await api("/api/governance/retention");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "Retention Policies"));
    if (allowed.has("ops.retention.write")) {
      const form = el("form", "form-grid");
      form.append(
        faqField("Policy ID", "policy_id", "operational-events"),
        faqField("TTL days", "ttl_days", "365"),
        faqField("Migration plan", "migration_plan", "archive then delete"),
        faqField("理由", "reason", ""),
      );
      const submit = el("button", "", "建立 Retention 候選");
      submit.type = "submit";
      form.append(submit);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const values = new FormData(form);
        await api("/api/governance/retention/candidates", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            policy_id: String(values.get("policy_id") || "").trim(),
            ttl_days: Number(values.get("ttl_days") || 365),
            migration_plan: String(values.get("migration_plan") || "").trim(),
            reason: String(values.get("reason") || "").trim(),
          }),
        });
        await renderRetention();
      });
      panel.append(form);
    }
    const table = el("table");
    table.innerHTML = "<thead><tr><th>Policy</th><th>TTL</th><th>狀態</th><th>建立者</th><th>操作</th></tr></thead>";
    const body = el("tbody");
    for (const item of (data.items || []).slice().reverse()) {
      const actions = el("td");
      if (allowed.has("ops.retention.write") && item.status === "CANDIDATE") {
        const approve = el("button", "", "核准");
        approve.addEventListener("click", async () => {
          const reason = window.prompt("核准原因");
          if (!reason || reason.trim().length < 3) return;
          await api(`/api/governance/retention/${item.version_id}/approve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reason: reason.trim() }),
          });
          await renderRetention();
        });
        actions.append(approve);
      }
      if (allowed.has("ops.retention.write") && item.status === "APPROVED") {
        const activate = el("button", "", "啟用");
        activate.addEventListener("click", async () => {
          const reason = window.prompt("啟用原因");
          if (!reason || reason.trim().length < 3) return;
          await api(`/api/governance/retention/${item.version_id}/activate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reason: reason.trim() }),
          });
          await renderRetention();
        });
        actions.append(activate);
      }
      const row = el("tr");
      row.append(
        el("td", "", item.policy_id),
        el("td", "", String(item.ttl_days)),
        el("td", "", item.status),
        el("td", "", item.created_by),
        actions,
      );
      body.append(row);
    }
    table.append(body);
    panel.append(table);
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", "error", error.message));
  }
}

async function renderMasking() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = new Set(capabilities?.capabilities || []);
    const data = await api("/api/governance/masking");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "遮罩政策版本"));
    if (allowed.has("ops.retention.write")) {
      const form = el("form", "form-grid");
      form.append(
        faqField("Policy version", "policy_version", "mask-v2"),
        faqField("理由", "reason", ""),
      );
      const submit = el("button", "", "建立遮罩候選");
      submit.type = "submit";
      form.append(submit);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const values = new FormData(form);
        await api("/api/governance/masking/candidates", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            policy_version: String(values.get("policy_version") || "").trim(),
            reason: String(values.get("reason") || "").trim(),
          }),
        });
        await renderMasking();
      });
      panel.append(form);
    }
    const table = el("table");
    table.innerHTML = "<thead><tr><th>Version</th><th>Hash</th><th>狀態</th><th>建立者</th><th>操作</th></tr></thead>";
    const body = el("tbody");
    for (const item of (data.items || []).slice().reverse()) {
      const actions = el("td");
      if (allowed.has("ops.retention.write") && item.status === "CANDIDATE") {
        const approve = el("button", "", "核准");
        approve.addEventListener("click", async () => {
          const reason = window.prompt("核准原因");
          if (!reason || reason.trim().length < 3) return;
          await api(`/api/governance/masking/${item.version_id}/approve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reason: reason.trim() }),
          });
          await renderMasking();
        });
        actions.append(approve);
      }
      if (allowed.has("ops.retention.write") && item.status === "APPROVED") {
        const activate = el("button", "", "啟用");
        activate.addEventListener("click", async () => {
          const reason = window.prompt("啟用原因");
          if (!reason || reason.trim().length < 3) return;
          await api(`/api/governance/masking/${item.version_id}/activate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reason: reason.trim() }),
          });
          await renderMasking();
        });
        actions.append(activate);
      }
      const row = el("tr");
      row.append(
        el("td", "", item.policy_version),
        el("td", "", (item.rules_hash || "").slice(0, 12)),
        el("td", "", item.status),
        el("td", "", item.created_by),
        actions,
      );
      body.append(row);
    }
    table.append(body);
    panel.append(table);
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", "error", error.message));
  }
}

async function renderGovernanceSearch() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const panel = el("section", "panel");
    panel.append(el("h2", "", "權限感知全域搜尋"));
    const form = el("form", "form-grid");
    const input = el("input");
    input.name = "q";
    input.placeholder = "搜尋 Prompt / Flag / Model / Role / Retention / FAQ / Example / Issue / Quality / Audit";
    const submit = el("button", "", "搜尋");
    submit.type = "submit";
    form.append(input, submit);
    const results = el("div");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = await api(`/api/governance/search?q=${encodeURIComponent(input.value || "")}`);
      results.replaceChildren();
      results.append(el("p", "metric-label", `結果數 ${data.count}`));
      for (const item of data.items || []) {
        results.append(el("p", "", `[${item.type}] ${item.title} — ${item.snippet}`));
      }
    });
    panel.append(form, results);
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", "error", error.message));
  }
}

async function renderBudgets() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = new Set(capabilities?.capabilities || []);
    const [policyData, alertData] = await Promise.all([
      api("/api/budget-policies"),
      api("/api/alerts"),
    ]);
    const policyPanel = el("section", "panel");
    policyPanel.append(el("h2", "", "Budget Policies"));
    if (allowed.has("ops.budget.write")) {
      const form = el("form", "form-grid");
      const ownerOptions = (capabilities.ownerUnitIds || []).map((item) => [item, item]);
      const targetOptions = (policyData.notificationTargets || []).map((item) => [item, item]);
      form.append(
        exampleSelect("Scope", "scope_type", [
          ["PERSONAL", "Personal"], ["SERVICE", "Service"], ["TEAM", "Team"],
          ["TENANT", "Tenant"], ["GLOBAL", "Global"],
        ]),
        faqField("Scope ID", "scope_id", ""),
        exampleSelect("Period", "period", [["DAILY", "Daily"], ["MONTHLY", "Monthly"]]),
        exampleSelect("Measure", "measure", [
          ["TWD", "TWD"], ["USD", "USD"], ["TOKEN", "Token"],
          ["LLM_CALL_COUNT", "LLM Call Count"],
        ]),
        faqField("Warning Threshold", "warning_threshold", ""),
        faqField("Critical Threshold", "critical_threshold", ""),
        exampleSelect("Owner Unit", "owner_unit_id", ownerOptions),
        exampleSelect("Notification Target", "notification_target_id", targetOptions),
      );
      const submit = el("button", "", "建立 Policy");
      submit.type = "submit";
      form.append(submit);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const values = new FormData(form);
        try {
          await api("/api/budget-policies", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              scope_type: values.get("scope_type"), scope_id: values.get("scope_id"),
              period: values.get("period"), measure: values.get("measure"),
              warning_threshold: Number(values.get("warning_threshold")),
              critical_threshold: Number(values.get("critical_threshold")),
              owner_unit_id: values.get("owner_unit_id"),
              notification_target_ids: [values.get("notification_target_id")],
            }),
          });
          await renderBudgets();
        } catch (error) {
          showContentModal("建立 Policy 失敗", el("div", "error", error.message));
        }
      });
      policyPanel.append(form);
    }
    if ((policyData.items || []).length) {
      const table = el("table");
      table.innerHTML = "<thead><tr><th>Scope</th><th>期間 / 指標</th><th>門檻</th><th>狀態</th><th>版本</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const policy of policyData.items) {
        const actions = el("td");
        if (allowed.has("ops.budget.evaluate") && policy.enabled) {
          const evaluate = el("button", "", "立即評估");
          evaluate.addEventListener("click", async () => {
            try {
              const result = await api(`/api/budget-policies/${policy.policy_id}/evaluate`, { method: "POST" });
              const usage = result.usage;
              showContentModal(
                "Policy 評估結果",
                el("p", "", `Actual ${usage.actualValue}｜Coverage ${(usage.coverage * 100).toFixed(1)}%｜${usage.periodKey}`),
              );
              await renderBudgets();
            } catch (error) {
              showContentModal("評估失敗", el("div", "error", error.message));
            }
          });
          actions.append(evaluate);
        }
        if (allowed.has("ops.budget.write")) {
          const state = el("button", "", policy.enabled ? "停用" : "啟用");
          state.addEventListener("click", async () => {
            const reason = window.prompt(`${policy.enabled ? "停用" : "啟用"}原因`);
            if (!reason?.trim()) return;
            await api(`/api/budget-policies/${policy.policy_id}/state`, {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ expected_etag: policy.etag, enabled: !policy.enabled, reason }),
            });
            await renderBudgets();
          });
          actions.append(state);
        }
        const row = el("tr");
        row.append(
          el("td", "", `${policy.scope_type}:${policy.scope_id}`),
          el("td", "", `${policy.period} / ${policy.measure}`),
          el("td", "", `${policy.warning_threshold} / ${policy.critical_threshold}`),
          el("td", "", policy.enabled ? "ENABLED" : "DISABLED"),
          el("td", "", `${policy.pricing_version} / ${policy.exchange_rate_version}`),
          actions,
        );
        body.append(row);
      }
      table.append(body);
      policyPanel.append(table);
    } else {
      policyPanel.append(el("p", "empty", "目前沒有 Budget Policy。"));
    }

    const alertPanel = el("section", "panel");
    alertPanel.append(el("h2", "", `Alerts（${alertData.total || 0}）`));
    if ((alertData.items || []).length) {
      const table = el("table");
      table.innerHTML = "<thead><tr><th>Severity</th><th>Scope</th><th>Actual / Threshold</th><th>Coverage</th><th>狀態</th><th>通知</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const alert of alertData.items) {
        const actions = el("td");
        if (allowed.has("ops.alerts.manage") && alert.status !== "RESOLVED") {
          const alertActions = alert.status === "OPEN"
            ? [["acknowledge", "Acknowledge"], ["resolve", "Resolve"]]
            : [["resolve", "Resolve"]];
          for (const [action, label] of alertActions) {
            const button = el("button", "", label);
            button.addEventListener("click", async () => {
              const reason = window.prompt(`${label} 原因`);
              if (!reason?.trim()) return;
              await api(`/api/alerts/${alert.alert_id}/${action}`, {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ expected_etag: alert.etag, reason }),
              });
              await renderBudgets();
            });
            actions.append(button);
          }
          for (const deliveryItem of (alert.deliveries || []).filter((item) => item.status === "FAILED")) {
            const retry = el("button", "", "重試通知");
            retry.addEventListener("click", async () => {
              await api(`/api/alerts/${alert.alert_id}/deliveries/${deliveryItem.delivery_id}/retry`, {
                method: "POST",
              });
              await renderBudgets();
            });
            actions.append(retry);
          }
        }
        const delivery = (alert.deliveries || [])
          .map((item) => `${item.target_id}:${item.status}`).join(", ") || "-";
        const row = el("tr");
        row.append(
          el("td", "", alert.severity), el("td", "", `${alert.scope_type}:${alert.scope_id}`),
          el("td", "", `${alert.actual_value} / ${alert.threshold}`),
          el("td", "", `${(alert.coverage * 100).toFixed(1)}%`),
          el("td", "", alert.status), el("td", "", delivery), actions,
        );
        body.append(row);
      }
      table.append(body);
      alertPanel.append(table);
    } else {
      alertPanel.append(el("p", "empty", "目前沒有 Alert。"));
    }
    app.replaceChildren(policyPanel, alertPanel);
  } catch (error) {
    app.replaceChildren(el("div", "error", error.message));
  }
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

    const [qualityLoopPanel, gapPanel, feedback] = await Promise.all([
      buildQualityLoopPanel(),
      buildGapPanel(),
      api(`/api/feedback?${filters.toString()}`),
    ]);

    const panel = el("section", "panel");
    panel.append(el("h2", "", "回饋與待觀察事件"));
    panel.append(
      el(
        "p",
        "metric-label",
        "先處理上方改善案件池；此處用來篩選負評／未解決／轉人工事件，並跳轉對話驗證。",
      ),
    );
    const shortcuts = el("div", "filter-bar");
    shortcuts.append(
      drillLink("文件／FAQ 修正", "knowledge"),
      drillLink("案例集驗證", "examples"),
      drillLink("對話驗證", "conversations"),
    );
    panel.append(shortcuts);
    const filterBar = el("div", "grid");
    const issueInput = el("input");
    issueInput.id = "feedback-issue-type";
    issueInput.placeholder = "問題類型（顯示名稱或 ID）";
    issueInput.value = issueTypeId;
    const ratingSelect = el("select", "");
    ratingSelect.id = "feedback-rating";
    ratingSelect.innerHTML =
      '<option value="">全部評價</option><option value="UP">好評</option><option value="DOWN">負評</option>';
    if (rating) ratingSelect.value = rating;
    const reasonInput = el("input");
    reasonInput.id = "feedback-reason";
    reasonInput.placeholder = "回饋原因";
    reasonInput.value = reason || "";
    const resolvedSelect = el("select", "");
    resolvedSelect.id = "feedback-resolved";
    resolvedSelect.innerHTML =
      '<option value="">全部解決狀態</option><option value="RESOLVED">已解決</option><option value="UNRESOLVED">未解決</option>';
    if (resolved) resolvedSelect.value = resolved;
    const handoffSelect = el("select", "");
    handoffSelect.id = "feedback-handoff";
    handoffSelect.innerHTML =
      '<option value="">全部轉人工</option><option value="true">有轉人工</option><option value="false">無轉人工</option>';
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

    const ratingLabels = { UP: "好評", DOWN: "負評" };
    if (!feedback.items.length) {
      panel.append(el("p", "empty", "目前沒有符合條件的回饋事件。"));
    } else {
      const table = el("table");
      table.innerHTML =
        "<thead><tr><th>時間</th><th>評價</th><th>問題類型</th><th>來源</th><th>對話</th><th>原因</th><th>動作</th></tr></thead>";
      const body = el("tbody");
      for (const item of feedback.items) {
        const trace = item.trace || {};
        const source = trace.faqKey
          ? `FAQ：${trace.faqKey}`
          : (trace.documentIds || []).join(", ") || "-";
        const row = el("tr");
        row.append(el("td", "", item.occurredAt));
        row.append(el("td", "", ratingLabels[item.rating] || item.rating));
        row.append(
          el(
            "td",
            "",
            trace.issueTypeDisplayName || trace.issueTypeId || String(item.issueId ?? "-"),
          ),
        );
        row.append(el("td", "", source));
        const convLink = el("a", "", "查看對話");
        convLink.href = "#";
        convLink.addEventListener("click", async (event) => {
          event.preventDefault();
          const detail = await api(
            `/api/conversations/${encodeURIComponent(item.conversationId)}`,
          );
          showConversationModal({ ...detail, conversationId: item.conversationId });
        });
        const convCell = el("td");
        convCell.append(convLink);
        row.append(convCell);
        row.append(el("td", "", item.reason ?? "-"));
        const actionCell = el("td");
        actionCell.append(
          drillLink("驗證回答", "conversations", {
            conversationId: item.conversationId || "",
            issueTypeId: trace.issueTypeId || "",
          }),
        );
        row.append(actionCell);
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
    app.replaceChildren(qualityLoopPanel, panel, gapPanel, exportPanel);
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
    const allowed = new Set(capabilities?.capabilities || []);
    const [opsAudit, governanceAudit] = await Promise.all([
      api("/api/audit-events"),
      api("/api/governance/audit").catch(() => ({ items: [] })),
    ]);
    const panel = el("section", "panel");
    panel.append(el("h2", "", "稽核紀錄"));
    if (allowed.has("ops.audit.read")) {
      const exportButton = el("button", "", "匯出治理 Audit JSON");
      exportButton.addEventListener("click", async () => {
        const packageData = await api("/api/governance/audit/export");
        showContentModal("治理 Audit 匯出", el("pre", "json-block", JSON.stringify(packageData, null, 2)));
      });
      panel.append(exportButton);
    }
    panel.append(el("h3", "", "營運 Audit"));
    panel.append(el("pre", "", JSON.stringify(opsAudit, null, 2)));
    panel.append(el("h3", "", "治理 Audit"));
    panel.append(el("pre", "", JSON.stringify(governanceAudit, null, 2)));
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

boot();
