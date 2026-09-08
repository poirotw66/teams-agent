import { api, el } from "../api.js";
import { actorCapabilities } from "../app/capabilities.js";
import { statusBadge } from "../components/badges.js";
import { showContentModal } from "../components/modal.js";
import { createPageController } from "../app/lifecycle.js";

export async function renderAudit() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));

  try {
    const allowed = actorCapabilities();
    const panel = el("section", "panel");
    panel.append(el("h2", "", "系統稽核紀錄"));

    // Global action bar
    const actionBar = el("div", "filter-bar");
    actionBar.style.marginBottom = "1rem";
    if (allowed.has("ops.audit.read")) {
      const exportButton = el("button", "", "匯出治理 Audit JSON");
      exportButton.addEventListener("click", async () => {
        try {
          const packageData = await api("/api/governance/audit/export");
          showContentModal("治理 Audit 匯出", el("pre", "json-block", JSON.stringify(packageData, null, 2)));
        } catch (err) {
          showContentModal("匯出失敗", el("div", "error", err.message || err));
        }
      });
      actionBar.append(exportButton);
    }
    panel.append(actionBar);

    // Section 1: Ops Audit Events (with filtering & pagination - REQ-021)
    const opsSection = el("div", "audit-ops-section");
    const opsHeading = el("h3", "", "營運稽核紀錄");
    opsSection.append(opsHeading);

    const filterBar = el("div", "filter-bar");
    filterBar.style.marginBottom = "0.75rem";

    const actorInput = el("input");
    actorInput.placeholder = "人員 (Actor ID)…";
    actorInput.style.minWidth = "140px";
    actorInput.setAttribute("aria-label", "執行者");

    const actionInput = el("input");
    actionInput.placeholder = "操作動作 (Action)…";
    actionInput.style.minWidth = "150px";
    actionInput.setAttribute("aria-label", "操作動作");

    const targetTypeSelect = el("select");
    targetTypeSelect.setAttribute("aria-label", "目標類型");
    for (const [val, lab] of [
      ["", "全部目標類型"],
      ["FEATURE_FLAG", "功能開關 (Feature Flag)"],
      ["MODEL_CONFIG", "模型設定 (Model Config)"],
      ["KNOWLEDGE_DOCUMENT", "知識文件 (Knowledge Document)"],
      ["QUALITY_CASE", "品質案件 (Quality Case)"],
      ["BUDGET_POLICY", "預算政策 (Budget Policy)"],
    ]) {
      const opt = el("option", "", lab);
      opt.value = val;
      targetTypeSelect.append(opt);
    }

    const startDateInput = el("input");
    startDateInput.type = "date";
    startDateInput.setAttribute("aria-label", "開始日期");

    const endDateInput = el("input");
    endDateInput.type = "date";
    endDateInput.setAttribute("aria-label", "結束日期");

    const searchBtn = el("button", "button-primary", "查詢");
    const resetBtn = el("button", "", "重設");

    filterBar.append(
      actorInput,
      actionInput,
      targetTypeSelect,
      startDateInput,
      endDateInput,
      searchBtn,
      resetBtn,
    );
    opsSection.append(filterBar);

    const tableBox = el("div", "");
    opsSection.append(tableBox);

    // Pagination controls
    const paginationBar = el("div", "filter-bar");
    paginationBar.style.marginTop = "0.5rem";
    const prevBtn = el("button", "", "上一頁");
    const nextBtn = el("button", "", "下一頁");
    const pageInfo = el("span", "metric-label", "");
    paginationBar.append(prevBtn, nextBtn, pageInfo);
    opsSection.append(paginationBar);

    panel.append(opsSection);

    // Pagination state
    let cursorStack = [];
    let currentCursor = null;
    let nextCursor = null;

    async function loadOpsAudit(cursor = null, isBack = false) {
      tableBox.replaceChildren(el("p", "empty", "載入中…"));
      const params = new URLSearchParams({ limit: "25" });
      if (cursor) params.set("cursor", cursor);
      if (actorInput.value.trim()) params.set("actor_id", actorInput.value.trim());
      if (actionInput.value.trim()) params.set("action", actionInput.value.trim());
      if (targetTypeSelect.value) params.set("target_type", targetTypeSelect.value);
      if (startDateInput.value) params.set("start_date", startDateInput.value);
      if (endDateInput.value) params.set("end_date", endDateInput.value + "T23:59:59");

      try {
        const data = await api(`/api/audit-events?${params.toString()}`);
        const items = data.items || [];
        nextCursor = data.nextCursor || null;

        if (!isBack && currentCursor !== null) {
          cursorStack.push(currentCursor);
        }
        currentCursor = cursor;

        opsHeading.textContent = `營運稽核紀錄（本頁 ${items.length} 筆）`;
        tableBox.replaceChildren(createAuditTable(items, "營運"));

        prevBtn.disabled = cursorStack.length === 0;
        nextBtn.disabled = !nextCursor;
        pageInfo.textContent = `第 ${cursorStack.length + 1} 頁`;
      } catch (err) {
        tableBox.replaceChildren(el("div", "error", err.message || err));
      }
    }

    searchBtn.addEventListener("click", () => {
      cursorStack = [];
      currentCursor = null;
      loadOpsAudit(null);
    });

    resetBtn.addEventListener("click", () => {
      actorInput.value = "";
      actionInput.value = "";
      targetTypeSelect.value = "";
      startDateInput.value = "";
      endDateInput.value = "";
      cursorStack = [];
      currentCursor = null;
      loadOpsAudit(null);
    });

    prevBtn.addEventListener("click", () => {
      if (cursorStack.length > 0) {
        const prevCursor = cursorStack.pop();
        loadOpsAudit(prevCursor, true);
      }
    });

    nextBtn.addEventListener("click", () => {
      if (nextCursor) {
        loadOpsAudit(nextCursor, false);
      }
    });

    // Initial load of ops audit
    await loadOpsAudit();

    // Section 2: Governance Audit
    try {
      const governanceAudit = await api("/api/governance/audit").catch(() => ({ items: [] }));
      const govItems = governanceAudit.items || [];
      panel.append(el("h3", "", `治理稽核紀錄（${govItems.length} 筆）`));
      panel.append(createAuditTable(govItems, "治理"));
    } catch {
      // Best-effort for governance audit
    }

    function createAuditTable(items, typeLabel) {
      if (!items || !items.length) {
        return el("p", "empty", `目前沒有${typeLabel}稽核事件紀錄。`);
      }
      const table = el("table");
      table.innerHTML = `
        <thead>
          <tr>
            <th>時間</th>
            <th>執行者 / 角色</th>
            <th>操作動作</th>
            <th>目標類型 / ID</th>
            <th>結果</th>
            <th>詳情</th>
          </tr>
        </thead>
      `;
      const body = el("tbody");
      for (const item of items) {
        const row = el("tr");
        const occurred = (item.occurred_at || "").replace("T", " ").slice(0, 19) || "-";
        const actor = `${item.actor_id || "-"}${item.actor_role ? ` (${item.actor_role})` : ""}`;
        const target = item.target_type ? `${item.target_type}：${item.target_id || "-"}` : (item.target_id || "-");

        const resultCell = el("td");
        resultCell.append(statusBadge(item.result || "SUCCESS"));

        const detailCell = el("td");
        const viewBtn = el("button", "", "檢視 Payload");
        viewBtn.addEventListener("click", () => {
          showContentModal(
            `稽核事件詳情：${item.action || item.audit_id}`,
            el("pre", "json-block", JSON.stringify(item, null, 2)),
          );
        });
        detailCell.append(viewBtn);

        row.append(
          el("td", "", occurred),
          el("td", "", actor),
          el("td", "", item.action || "-"),
          el("td", "", target),
          resultCell,
          detailCell,
        );
        body.append(row);
      }
      table.append(body);
      const scroll = el("div", "table-responsive");
      scroll.append(table);
      return scroll;
    }

    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

export const auditPage = createPageController({
  enter: async () => renderAudit(),
  update: async () => renderAudit(),
  leave: async () => {},
});
