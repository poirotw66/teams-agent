import { api, el } from "../api.js";
import { actorCapabilities } from "../app/capabilities.js";
import { presentSystemPage } from "../app/adminChrome.js";
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

    // Global action bar & cross-domain operator search
    const actionBar = el("div", "filter-bar");
    actionBar.style.marginBottom = "1rem";
    if (allowed.has("ops.audit.read")) {
      const exportButton = el("button", "", "匯出治理 Audit JSON");
      exportButton.addEventListener("click", async () => {
        try {
          const packageData = await api("/api/governance/audit/export");
          showContentModal("治理 Audit 匯出", el("pre", "json-block", JSON.stringify(packageData, null, 2)));
        } catch (err) {
          showContentModal("匯出失敗", el("div", "error", `讀取失敗：${err.message || err}`));
        }
      });
      actionBar.append(exportButton);
    }

    const globalTraceBox = el("div", "filter-bar");
    globalTraceBox.style.marginBottom = "1.5rem";
    globalTraceBox.style.padding = "0.75rem";
    globalTraceBox.style.background = "var(--bg-card, #f8f9fa)";
    globalTraceBox.style.borderRadius = "6px";

    const globalActorInput = el("input");
    globalActorInput.placeholder = "輸入操作者 (Actor ID) 跨區追查所有重要操作…";
    globalActorInput.style.minWidth = "300px";
    globalActorInput.setAttribute("aria-label", "跨區追查操作者");

    const globalTraceBtn = el("button", "button-primary", "全域追查操作者");
    const globalResetBtn = el("button", "", "清除跨區追查");

    globalTraceBox.append(globalActorInput, globalTraceBtn, globalResetBtn);

    panel.append(actionBar);
    panel.append(globalTraceBox);

    // =========================================================================
    // Section 1: Ops Audit Events (with filtering & pagination)
    // =========================================================================
    const opsSection = el("div", "audit-ops-section");
    const opsHeading = el("h3", "", "營運稽核紀錄");
    opsSection.append(opsHeading);

    const opsFilterBar = el("div", "filter-bar");
    opsFilterBar.style.marginBottom = "0.75rem";

    const actorInput = el("input");
    actorInput.placeholder = "人員 (Actor ID)…";
    actorInput.style.minWidth = "140px";
    actorInput.setAttribute("aria-label", "營運執行者");

    const actionInput = el("input");
    actionInput.placeholder = "操作動作 (Action)…";
    actionInput.style.minWidth = "150px";
    actionInput.setAttribute("aria-label", "營運操作動作");

    const targetTypeSelect = el("select");
    targetTypeSelect.setAttribute("aria-label", "營運目標類型");
    for (const [val, lab] of [
      ["", "全部目標類型"],
      ["FEATURE_FLAG", "功能開關 (Feature Flag)"],
      ["MODEL_CONFIG", "模型設定 (Model Config)"],
      ["KNOWLEDGE_DOCUMENT", "知識文件 (Knowledge Document)"],
      ["QUALITY_CASE", "品質案件 (Quality Case)"],
      ["BUDGET_POLICY", "預算政策 (Budget Policy)"],
      ["PRICING_RATE", "定價費率 (Pricing Rate)"],
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

    opsFilterBar.append(
      actorInput,
      actionInput,
      targetTypeSelect,
      startDateInput,
      endDateInput,
      searchBtn,
      resetBtn,
    );
    opsSection.append(opsFilterBar);

    const tableBox = el("div", "");
    opsSection.append(tableBox);

    // Ops Pagination controls
    const paginationBar = el("div", "filter-bar");
    paginationBar.style.marginTop = "0.5rem";
    const prevBtn = el("button", "", "上一頁");
    const nextBtn = el("button", "", "下一頁");
    const pageInfo = el("span", "metric-label", "");
    paginationBar.append(prevBtn, nextBtn, pageInfo);
    opsSection.append(paginationBar);

    panel.append(opsSection);

    // Ops Pagination state
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
        if (items.length === 0) {
          tableBox.replaceChildren(el("p", "empty", "目前沒有符合條件的營運稽核事件紀錄。"));
        } else {
          tableBox.replaceChildren(createAuditTable(items, "營運"));
        }

        prevBtn.disabled = cursorStack.length === 0;
        nextBtn.disabled = !nextCursor;
        pageInfo.textContent = `第 ${cursorStack.length + 1} 頁`;
      } catch (err) {
        opsHeading.textContent = "營運稽核紀錄（讀取失敗）";
        tableBox.replaceChildren(el("div", "error", `讀取失敗：${err.message || err}`));
        prevBtn.disabled = true;
        nextBtn.disabled = true;
        pageInfo.textContent = "";
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

    // =========================================================================
    // Section 2: Governance Audit (with filtering & pagination - REQ-021)
    // =========================================================================
    const govSection = el("div", "audit-gov-section");
    govSection.style.marginTop = "2rem";
    const govHeading = el("h3", "", "治理稽核紀錄");
    govSection.append(govHeading);

    const govFilterBar = el("div", "filter-bar");
    govFilterBar.style.marginBottom = "0.75rem";

    const govActorInput = el("input");
    govActorInput.placeholder = "人員 (Actor ID)…";
    govActorInput.style.minWidth = "140px";
    govActorInput.setAttribute("aria-label", "治理執行者");

    const govActionInput = el("input");
    govActionInput.placeholder = "操作動作 (Action)…";
    govActionInput.style.minWidth = "150px";
    govActionInput.setAttribute("aria-label", "治理操作動作");

    const govTargetTypeSelect = el("select");
    govTargetTypeSelect.setAttribute("aria-label", "治理目標類型");
    for (const [val, lab] of [
      ["", "全部目標類型"],
      ["PROMPT", "Prompt 範本 (Prompt)"],
      ["MODEL", "模型設定 (Model)"],
      ["FLAG", "功能開關 (Flag)"],
      ["ROLE_MAPPING", "角色指派 (Role Mapping)"],
      ["RETENTION", "資料保存 (Retention)"],
      ["MASKING", "敏感遮罩 (Masking)"],
      ["EVAL", "品質評估 (Eval)"],
      ["SEARCH", "治理搜尋 (Search)"],
      ["AUDIT", "稽核操作 (Audit)"],
    ]) {
      const opt = el("option", "", lab);
      opt.value = val;
      govTargetTypeSelect.append(opt);
    }

    const govStartDateInput = el("input");
    govStartDateInput.type = "date";
    govStartDateInput.setAttribute("aria-label", "治理開始日期");

    const govEndDateInput = el("input");
    govEndDateInput.type = "date";
    govEndDateInput.setAttribute("aria-label", "治理結束日期");

    const govSearchBtn = el("button", "button-primary", "查詢");
    const govResetBtn = el("button", "", "重設");

    govFilterBar.append(
      govActorInput,
      govActionInput,
      govTargetTypeSelect,
      govStartDateInput,
      govEndDateInput,
      govSearchBtn,
      govResetBtn,
    );
    govSection.append(govFilterBar);

    const govTableBox = el("div", "");
    govSection.append(govTableBox);

    // Gov Pagination controls
    const govPaginationBar = el("div", "filter-bar");
    govPaginationBar.style.marginTop = "0.5rem";
    const govPrevBtn = el("button", "", "上一頁");
    const govNextBtn = el("button", "", "下一頁");
    const govPageInfo = el("span", "metric-label", "");
    govPaginationBar.append(govPrevBtn, govNextBtn, govPageInfo);
    govSection.append(govPaginationBar);

    panel.append(govSection);

    // Gov Pagination state
    let govCursorStack = [];
    let govCurrentCursor = null;
    let govNextCursor = null;

    async function loadGovAudit(cursor = null, isBack = false) {
      govTableBox.replaceChildren(el("p", "empty", "載入中…"));
      const params = new URLSearchParams({ limit: "25" });
      if (cursor) params.set("cursor", cursor);
      if (govActorInput.value.trim()) params.set("actor_id", govActorInput.value.trim());
      if (govActionInput.value.trim()) params.set("action", govActionInput.value.trim());
      if (govTargetTypeSelect.value) params.set("target_type", govTargetTypeSelect.value);
      if (govStartDateInput.value) params.set("start_date", govStartDateInput.value);
      if (govEndDateInput.value) params.set("end_date", govEndDateInput.value + "T23:59:59");

      try {
        const data = await api(`/api/governance/audit?${params.toString()}`);
        const items = data.items || [];
        govNextCursor = data.nextCursor || null;

        if (!isBack && govCurrentCursor !== null) {
          govCursorStack.push(govCurrentCursor);
        }
        govCurrentCursor = cursor;

        const totalNote = data.total !== undefined ? `，共 ${data.total} 筆` : "";
        govHeading.textContent = `治理稽核紀錄（本頁 ${items.length} 筆${totalNote}）`;

        if (items.length === 0) {
          govTableBox.replaceChildren(el("p", "empty", "目前沒有符合條件的治理稽核事件紀錄。"));
        } else {
          govTableBox.replaceChildren(createAuditTable(items, "治理"));
        }

        govPrevBtn.disabled = govCursorStack.length === 0;
        govNextBtn.disabled = !govNextCursor;
        govPageInfo.textContent = `第 ${govCursorStack.length + 1} 頁`;
      } catch (err) {
        govHeading.textContent = "治理稽核紀錄（讀取失敗）";
        govTableBox.replaceChildren(el("div", "error", `讀取失敗：${err.message || err}`));
        govPrevBtn.disabled = true;
        govNextBtn.disabled = true;
        govPageInfo.textContent = "";
      }
    }

    govSearchBtn.addEventListener("click", () => {
      govCursorStack = [];
      govCurrentCursor = null;
      loadGovAudit(null);
    });

    govResetBtn.addEventListener("click", () => {
      govActorInput.value = "";
      govActionInput.value = "";
      govTargetTypeSelect.value = "";
      govStartDateInput.value = "";
      govEndDateInput.value = "";
      govCursorStack = [];
      govCurrentCursor = null;
      loadGovAudit(null);
    });

    govPrevBtn.addEventListener("click", () => {
      if (govCursorStack.length > 0) {
        const prevCursor = govCursorStack.pop();
        loadGovAudit(prevCursor, true);
      }
    });

    govNextBtn.addEventListener("click", () => {
      if (govNextCursor) {
        loadGovAudit(govNextCursor, false);
      }
    });

    // Global trace action wiring
    globalTraceBtn.addEventListener("click", () => {
      const val = globalActorInput.value.trim();
      actorInput.value = val;
      govActorInput.value = val;
      cursorStack = [];
      currentCursor = null;
      govCursorStack = [];
      govCurrentCursor = null;
      loadOpsAudit(null);
      loadGovAudit(null);
    });

    globalResetBtn.addEventListener("click", () => {
      globalActorInput.value = "";
      actorInput.value = "";
      govActorInput.value = "";
      cursorStack = [];
      currentCursor = null;
      govCursorStack = [];
      govCurrentCursor = null;
      loadOpsAudit(null);
      loadGovAudit(null);
    });

    // Initial load
    await Promise.all([loadOpsAudit(), loadGovAudit()]);

    function createAuditTable(items, typeLabel) {
      if (!items || !items.length) {
        return el("p", "empty", `目前沒有符合條件的${typeLabel}稽核事件紀錄。`);
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

    presentSystemPage(
      "稽核紀錄",
      "查詢營運與治理相關操作紀錄。",
      panel,
    );
  } catch (error) {
    presentSystemPage(
      "稽核紀錄",
      null,
      el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message),
    );
  }
}