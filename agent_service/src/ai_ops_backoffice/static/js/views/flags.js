import { api, el } from "../api.js";
import { actorCapabilities } from "../app/capabilities.js";
import { statusBadge, badge } from "../components/badges.js";
import { showContentModal, closeContentModal } from "../components/modal.js";
import { createPageController } from "../app/lifecycle.js";

let selectedEnvironment = "lab";

export async function renderFlags() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = actorCapabilities();
    const data = await api("/api/governance/flags");
    const panel = el("section", "panel");

    // Header & Environment Bar
    const headerRow = el("div", "filter-bar");
    headerRow.style.justifyContent = "space-between";
    headerRow.style.alignItems = "center";
    headerRow.style.marginBottom = "1rem";

    const titleH2 = el("h2", "", "功能開關與系統設定 (Feature Flags)");
    titleH2.style.margin = "0";

    const envControls = el("div", "filter-bar");
    envControls.style.alignItems = "center";
    envControls.style.gap = "0.5rem";
    envControls.append(el("label", "metric-label", "環境 (Environment)："));

    const envSelect = el("select");
    [
      { id: "lab", name: "實驗環境 (lab)" },
      { id: "stage", name: "預發環境 (stage)" },
      { id: "prod", name: "正式環境 (prod)" },
    ].forEach((opt) => {
      const option = el("option", "", opt.name);
      option.value = opt.id;
      if (opt.id === selectedEnvironment) option.selected = true;
      envSelect.append(option);
    });
    envSelect.addEventListener("change", async (e) => {
      selectedEnvironment = e.target.value;
      await renderFlags();
    });
    envControls.append(envSelect);
    headerRow.append(titleH2, envControls);
    panel.append(headerRow);

    const items = data.items || [];
    if (!items.length) {
      panel.append(el("p", "empty", "目前無 Feature Flag。"));
      app.replaceChildren(panel);
      return;
    }

    const table = el("table");
    table.innerHTML =
      "<thead><tr><th>Flag ID</th><th>說明</th><th>安全鎖定</th><th>有效值</th><th>正式版本</th><th>操作</th></tr></thead>";
    const body = el("tbody");

    for (const item of items) {
      const flag = item.flag;
      const flagId = flag.flag_id;
      const row = el("tr");

      // Effective value in selected env
      const effCell = el("td");
      effCell.append(statusBadge(item.effective ? "ENABLED" : "DISABLED"));

      // Safety lock status
      const lockCell = el("td");
      lockCell.append(statusBadge(flag.safety_locked ? "LOCKED" : "UNLOCKED"));

      // Active version display
      const activeCell = el("td");
      if (flag.active_version_id) {
        const activeVer = (item.versions || []).find((v) => v.version_id === flag.active_version_id);
        const verVal = activeVer ? activeVer.value : "ACTIVE";
        activeCell.append(statusBadge(verVal), el("div", "metric-label", flag.active_version_id.slice(0, 8)));
      } else {
        activeCell.append(el("span", "metric-label", "預設值"));
      }

      // Actions
      const actions = el("td");
      actions.style.display = "flex";
      actions.style.gap = "0.4rem";
      actions.style.flexWrap = "wrap";

      if (allowed.has("ops.flags.write") && !flag.safety_locked) {
        const editBtn = el("button", "", "變更設定");
        editBtn.addEventListener("click", () => showFlagCandidateModal(flag, renderFlags));
        actions.append(editBtn);
      }

      if (allowed.has("ops.flags.read")) {
        const effBtn = el("button", "secondary", "查有效值");
        effBtn.addEventListener("click", async () => {
          const res = await api(`/api/governance/flags/${flagId}/effective?environment=${selectedEnvironment}`);
          showContentModal(`${flagId} (${selectedEnvironment}) 有效值`, el("pre", "json-block", JSON.stringify(res, null, 2)));
        });
        actions.append(effBtn);

        const verBtn = el("button", "secondary", `版本歷程 (${(item.versions || []).length})`);
        verBtn.addEventListener("click", () => showFlagVersionsModal(flag, item.versions || [], allowed, renderFlags));
        actions.append(verBtn);
      }

      row.append(
        el("td", "strong", flagId),
        el("td", "", flag.description || "-"),
        lockCell,
        effCell,
        activeCell,
        actions,
      );
      body.append(row);
    }

    table.append(body);
    const scroll = el("div", "table-responsive");
    scroll.append(table);
    panel.append(scroll);
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", "error", error.message));
  }
}

function showFlagCandidateModal(flag, onRefresh) {
  const form = el("form", "form-grid");
  form.style.display = "flex";
  form.style.flexDirection = "column";
  form.style.gap = "0.75rem";

  form.append(el("label", "metric-label", `Flag ID: ${flag.flag_id}`));

  const valGroup = el("div");
  valGroup.append(el("label", "metric-label", "目標值 (Value)："));
  const valSelect = el("select");
  ["ENABLED", "DISABLED"].forEach((v) => {
    const opt = el("option", "", v);
    opt.value = v;
    valSelect.append(opt);
  });
  valGroup.append(valSelect);
  form.append(valGroup);

  const envGroup = el("div");
  envGroup.append(el("label", "metric-label", "套用環境 (Environment)："));
  const envSelect = el("select");
  ["lab", "stage", "prod"].forEach((e) => {
    const opt = el("option", "", e);
    opt.value = e;
    if (e === selectedEnvironment) opt.selected = true;
    envSelect.append(opt);
  });
  envGroup.append(envSelect);
  form.append(envGroup);

  const expiryGroup = el("div");
  expiryGroup.append(el("label", "metric-label", "過期時間 (Prod 必填)："));
  const expiryInput = el("input");
  expiryInput.type = "datetime-local";
  expiryGroup.append(expiryInput);
  form.append(expiryGroup);

  const reasonGroup = el("div");
  reasonGroup.append(el("label", "metric-label", "變更原因 (Reason，至少 3 字)："));
  const reasonInput = el("input");
  reasonInput.required = true;
  reasonInput.placeholder = "請輸入變更原因";
  reasonGroup.append(reasonInput);
  form.append(reasonGroup);

  const submitBtn = el("button", "", "建立候選版本 (Submit Candidate)");
  submitBtn.type = "submit";
  form.append(submitBtn);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const reason = reasonInput.value.trim();
    if (reason.length < 3) {
      alert("變更原因至少需 3 個字元");
      return;
    }
    const env = envSelect.value;
    let expiresAt = null;
    if (expiryInput.value) {
      expiresAt = new Date(expiryInput.value).toISOString();
    } else if (env === "prod") {
      alert("正式環境 (prod) 開關必須設定過期時間！");
      return;
    }
    try {
      await api("/api/governance/flags/candidates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          flag_id: flag.flag_id,
          value: valSelect.value,
          environment: env,
          expires_at: expiresAt,
          reason: reason,
        }),
      });
      closeContentModal();
      await onRefresh();
    } catch (err) {
      alert(`建立失敗：${err.message || err}`);
    }
  });

  showContentModal(`變更開關：${flag.flag_id}`, form);
}

function showFlagVersionsModal(flag, versions, allowed, onRefresh) {
  const container = el("div");
  if (!versions.length) {
    container.append(el("p", "empty", "尚無版本紀錄。"));
    showContentModal(`${flag.flag_id} 版本歷程`, container);
    return;
  }
  const table = el("table");
  table.innerHTML =
    "<thead><tr><th>版本 ID</th><th>狀態</th><th>值</th><th>環境</th><th>建立者</th><th>原因</th><th>操作</th></tr></thead>";
  const tbody = el("tbody");

  for (const v of versions) {
    const tr = el("tr");
    const actions = el("td");

    if (v.status === "CANDIDATE" && allowed.has("ops.flags.approve")) {
      const appBtn = el("button", "", "核准 (Approve)");
      appBtn.addEventListener("click", async () => {
        const reason = window.prompt("請輸入核准原因：", "符合變更審查規範");
        if (!reason || reason.trim().length < 3) return;
        try {
          await api(`/api/governance/flags/${flag.flag_id}/versions/${v.version_id}/approve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reason: reason.trim() }),
          });
          closeContentModal();
          await onRefresh();
        } catch (err) {
          alert(`核准失敗：${err.message || err}`);
        }
      });
      actions.append(appBtn);
    }

    if (v.status === "APPROVED" && allowed.has("ops.flags.activate")) {
      const actBtn = el("button", "", "啟用 (Activate)");
      actBtn.addEventListener("click", async () => {
        const reason = window.prompt("請輸入啟用原因：", "核准後正式生效");
        if (!reason || reason.trim().length < 3) return;
        try {
          await api(`/api/governance/flags/${flag.flag_id}/versions/${v.version_id}/activate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reason: reason.trim() }),
          });
          closeContentModal();
          await onRefresh();
        } catch (err) {
          alert(`啟用失敗：${err.message || err}`);
        }
      });
      actions.append(actBtn);
    }

    tr.append(
      el("td", "metric-label", v.version_id.slice(0, 8)),
      el("td", "", statusBadge(v.status)),
      el("td", "strong", v.value),
      el("td", "", v.environment),
      el("td", "", v.created_by || "-"),
      el("td", "", v.change_reason || "-"),
      actions,
    );
    tbody.append(tr);
  }
  table.append(tbody);
  const scroll = el("div", "table-responsive");
  scroll.append(table);
  container.append(scroll);
  showContentModal(`${flag.flag_id} 版本歷程`, container);
}

export const flagsPage = createPageController({
  enter: async () => renderFlags(),
  update: async () => renderFlags(),
  leave: async () => {},
});
