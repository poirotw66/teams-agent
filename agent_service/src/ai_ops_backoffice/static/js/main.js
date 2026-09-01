import { api, el, metric, DEFAULT_HEADERS } from "./api.js";

const routes = {
  overview: renderOverview,
  conversations: renderConversations,
  issues: renderIssues,
  costs: renderCosts,
  health: renderHealth,
  knowledge: renderKnowledge,
  quality: renderQuality,
  governance: renderGovernance,
  audit: renderAudit,
};

const navItems = [
  ["overview", "營運總覽"],
  ["conversations", "對話紀錄"],
  ["issues", "Issue 分析"],
  ["costs", "成本分析"],
  ["health", "系統健康度"],
  ["knowledge", "知識營運"],
  ["quality", "品質改善"],
  ["governance", "AI 治理"],
  ["audit", "稽核紀錄"],
];

let capabilities = null;

async function boot() {
  capabilities = await api("/api/capabilities");
  renderNav("overview");
  document.getElementById("meta-panel").textContent =
    `角色：${capabilities.role}｜資料更新：即時讀取本機 Analytics Store`;
}

function renderNav(active) {
  const nav = document.getElementById("nav");
  nav.replaceChildren();
  for (const [id, label] of navItems) {
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
  try {
    const data = await api("/api/operations/summary?days=7");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "最近 7 天"));
    const grid = el("div", "grid");
    grid.append(
      metric("Conversation", data.conversationCount),
      metric("Turn", data.turnCount),
      metric("Active User", data.activeUserCount),
      metric("Issue", data.issueOccurrenceCount),
      metric("Knowledge 回答", data.knowledgeAnswerCount),
      metric("FAQ 回答", data.faqAnswerCount),
      metric("估算成本 USD", data.estimatedCostUsd),
      metric("成本完整率", data.costCoverage),
    );
    panel.append(grid);
    const table = el("table");
    table.innerHTML = "<thead><tr><th>Issue Type</th><th>Count</th></tr></thead>";
    const body = el("tbody");
    for (const item of data.topIssueTypes || []) {
      const row = el("tr");
      row.append(el("td", "", item.issueTypeId));
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

async function renderConversations() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const data = await api("/api/conversations?days=30");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "對話紀錄（遮罩摘要）"));
    if (!data.items.length) {
      panel.append(el("p", "empty", "目前沒有對話事件。請先透過 Playground 或 Teams 產生流量。"));
      app.replaceChildren(panel);
      return;
    }
    const table = el("table");
    table.innerHTML =
      "<thead><tr><th>Conversation</th><th>Turns</th><th>Actor</th><th>Last Seen</th></tr></thead>";
    const body = el("tbody");
    for (const item of data.items) {
      const row = el("tr");
      const link = el("a", "", item.conversationId);
      link.href = "#";
      link.addEventListener("click", async (event) => {
        event.preventDefault();
        const detail = await api(`/api/conversations/${encodeURIComponent(item.conversationId)}`);
        alert(JSON.stringify(detail, null, 2));
      });
      row.append(el("td", "", "").append(link));
      row.append(el("td", "", String(item.turnCount)));
      row.append(el("td", "", item.actorRef || "-"));
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

async function renderIssues() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const data = await api("/api/issues/summary?days=30");
    const panel = el("section", "panel");
    panel.append(el("h2", "", `Issue 分析 (${data.taxonomyVersion})`));
    panel.append(el("p", "", `未分類：${data.unclassifiedCount}`));
    const table = el("table");
    table.innerHTML =
      "<thead><tr><th>Issue Type</th><th>Display Name</th><th>Count</th><th>Share</th></tr></thead>";
    const body = el("tbody");
    for (const item of data.items) {
      const row = el("tr");
      row.append(el("td", "", item.issueTypeId));
      row.append(el("td", "", item.displayName));
      row.append(el("td", "", String(item.count)));
      row.append(el("td", "", String(item.share)));
      body.append(row);
    }
    table.append(body);
    panel.append(table);
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

async function renderCosts() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const data = await api("/api/costs/summary?days=30");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "成本分析"));
    panel.append(metric("Total USD", data.totalEstimatedCostUsd));
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
    panel.append(table);
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
    const filters = new URLSearchParams({ days: "30" });
    const rating = document.getElementById("feedback-rating")?.value;
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
          alert(JSON.stringify({ feedback: item, conversation: detail }, null, 2));
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
    const button = el("button", "", "建立營運摘要匯出");
    button.addEventListener("click", async () => {
      const created = await api("/api/exports", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...DEFAULT_HEADERS },
        body: JSON.stringify({
          export_type: "operations_summary",
          reason: "UAT export",
          days: 7,
        }),
      });
      exportPanel.append(el("pre", "", JSON.stringify(created, null, 2)));
      const job = await pollExport(created.jobId);
      exportPanel.append(el("pre", "", JSON.stringify(job, null, 2)));
    });
    exportPanel.append(button);
    app.replaceChildren(panel, exportPanel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
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

async function renderGovernance() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const prompts = await api("/api/prompts");
    const flags = await api("/api/feature-flags");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "AI 治理（Phase 3 scaffold）"));
    panel.append(el("pre", "", JSON.stringify({ prompts, flags }, null, 2)));
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
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
