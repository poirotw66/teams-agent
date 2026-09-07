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
    const [opsAudit, governanceAudit] = await Promise.all([
      api("/api/audit-events").catch(() => ({ items: [] })),
      api("/api/governance/audit").catch(() => ({ items: [] })),
    ]);
    const panel = el("section", "panel");
    panel.append(el("h2", "", "系統稽核紀錄"));

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

    const opsItems = opsAudit.items || [];
    panel.append(el("h3", "", `營運稽核紀錄（${opsItems.length} 筆）`));
    panel.append(createAuditTable(opsItems, "營運"));

    const govItems = governanceAudit.items || [];
    panel.append(el("h3", "", `治理稽核紀錄（${govItems.length} 筆）`));
    panel.append(createAuditTable(govItems, "治理"));

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
