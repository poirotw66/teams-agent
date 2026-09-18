import { api, el } from "../../api.js";
import {
  showContentModal,
  closeContentModal,
  showToast,
} from "../../components/modal.js";
import { actorCapabilities } from "../../app/capabilities.js";
import { escapeHtml, actorCanManageOwnerUnits } from "./shared.js";

export async function loadSetsList(container, allowed) {
  container.replaceChildren();

  const toolbar = el("div", "toolbar-row");
  const title = el("h3", "", "題庫清單 (Eval Sets)");
  const createSetBtn = el("button", "btn-primary", "＋ 建立題庫");
  toolbar.append(title);
  if (allowed.has("ops.evals.write")) {
    toolbar.append(createSetBtn);
  }

  const tableContainer = el("div", "table-responsive");
  container.append(toolbar, tableContainer);

  const fetchSets = async () => {
    try {
      const res = await api("/api/evaluations/sets");
      if (!res.items || res.items.length === 0) {
        tableContainer.replaceChildren(el("p", "empty", "目前尚未建立任何驗收題庫。"));
        return;
      }

      const table = el("table", "data-table");
      table.innerHTML = `
        <thead>
          <tr>
            <th>題庫名稱</th>
            <th>用途 (Purpose)</th>
            <th>負責單位</th>
            <th>負責人</th>
            <th>操作</th>
          </tr>
        </thead>
      `;
      const tbody = el("tbody");
      for (const s of res.items) {
        const row = el("tr");
        const nameCell = el("td");
        nameCell.innerHTML = `<strong>${escapeHtml(s.name)}</strong><br><span class="text-muted">${escapeHtml(s.description || "")}</span>`;

        const purposeCell = el("td");
        purposeCell.innerHTML = s.purpose === "HOLDOUT"
          ? `<span class="badge badge-warning">🔒 保留集 (HOLDOUT)</span>`
          : `<span class="badge badge-success">開發集 (DEVELOPMENT)</span>`;

        const ownerCell = el("td", "", s.owner_unit_ids.join(", "));
        const leadCell = el("td", "", s.lead_owner);

        const actionsCell = el("td");
        const detailBtn = el("button", "btn-sm btn-link", "版本與成員");
        detailBtn.addEventListener("click", () => showSetDetailModal(s.set_id, allowed));
        actionsCell.append(detailBtn);

        row.append(nameCell, purposeCell, ownerCell, leadCell, actionsCell);
        tbody.append(row);
      }
      table.append(tbody);
      tableContainer.replaceChildren(table);
    } catch (err) {
      tableContainer.replaceChildren(el("div", "error", `載入失敗: ${err.message || err}`));
    }
  };

  createSetBtn.addEventListener("click", () => showCreateSetModal(() => fetchSets()));
  await fetchSets();
}

export function showCreateSetModal(onSuccess) {
  const content = el("div", "modal-body");
  content.innerHTML = `
    <h3>建立驗收題庫 (Eval Set)</h3>
    <form id="create-set-form">
      <div class="form-group">
        <label>題庫名稱 *</label>
        <input type="text" id="set-name" class="form-input" required placeholder="例：人事規定標準驗收集">
      </div>
      <div class="form-group">
        <label>題庫用途 (Purpose) *</label>
        <select id="set-purpose" class="form-select">
          <option value="DEVELOPMENT">開發集 (DEVELOPMENT) - 用於日常改版與驗證</option>
          <option value="HOLDOUT">保留集 (HOLDOUT) - 嚴格隔離，不可用於優化</option>
        </select>
      </div>
      <div class="form-group">
        <label>負責單位 (以逗號分隔) *</label>
        <input type="text" id="set-owners" class="form-input" required value="IT Service Desk">
      </div>
      <div class="form-group">
        <label>說明描述</label>
        <textarea id="set-desc" class="form-textarea" rows="2"></textarea>
      </div>
      <div class="btn-row">
        <button type="submit" class="btn-primary">建立題庫</button>
      </div>
    </form>
  `;

  const form = content.querySelector("#create-set-form");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = form.querySelector("#set-name").value.trim();
    const purpose = form.querySelector("#set-purpose").value;
    const owners = form.querySelector("#set-owners").value.split(",").map(s => s.trim()).filter(Boolean);
    const description = form.querySelector("#set-desc").value.trim();

    try {
      await api("/api/evaluations/sets", {
        method: "POST",
        body: JSON.stringify({ name, purpose, owner_unit_ids: owners, description }),
      });
      closeContentModal();
      if (onSuccess) onSuccess();
    } catch (err) {
      showToast(`建立題庫失敗: ${err.message}`, { tone: "error" });
    }
  });

  showContentModal(content);
}

export async function showSetDetailModal(setId, allowed = actorCapabilities()) {
  const content = el("div", "modal-body");
  content.innerHTML = "<p>載入題庫詳情中...</p>";
  showContentModal(content);

  try {
    const res = await api(`/api/evaluations/sets/${setId}`);
    const s = res.eval_set;
    const versions = res.versions || [];
    const canWriteSet = allowed.has("ops.evals.write") && actorCanManageOwnerUnits(s.owner_unit_ids);
    const canPublishSet = allowed.has("ops.evals.sets.publish") && actorCanManageOwnerUnits(s.owner_unit_ids);

    content.innerHTML = `
      <h3>${escapeHtml(s.name)}</h3>
      <div class="meta-grid">
        <div><strong>Set ID:</strong> ${escapeHtml(s.set_id)}</div>
        <div><strong>用途:</strong> ${escapeHtml(s.purpose)}</div>
        <div><strong>負責單位:</strong> ${escapeHtml(s.owner_unit_ids.join(", "))}</div>
        <div><strong>負責人:</strong> ${escapeHtml(s.lead_owner)}</div>
      </div>
      <h4>題庫版本</h4>
      <div id="versions-list">
        ${versions.length === 0 ? "<p class='empty'>目前無任何版本。</p>" : ""}
      </div>
      <div id="set-version-actions" class="btn-row"></div>
    `;

    const verList = content.querySelector("#versions-list");
    for (const v of versions) {
      const vCard = el("div", "card-item");
      vCard.innerHTML = `
        <strong>v${escapeHtml(v.version)}</strong> (${escapeHtml(v.status)}) - ${escapeHtml(v.case_revision_ids.length)} 題
        <br><small class="text-muted">Manifest Hash: <code>${escapeHtml(v.manifest_hash ? v.manifest_hash.slice(0, 12) : "尚未發布")}</code> | 發布時間: ${escapeHtml(v.published_at || "-")}</small>
      `;
      if (v.status === "DRAFT") {
        if (canPublishSet) {
          const publishBtn = el("button", "btn-sm btn-primary", "發布此版本");
          publishBtn.type = "button";
          publishBtn.addEventListener("click", async () => {
            publishBtn.disabled = true;
            try {
              await api(`/api/evaluations/sets/${setId}/versions/${v.set_version_id}/publish`, {
                method: "POST",
                body: JSON.stringify({ expected_etag: v.etag }),
              });
              await showSetDetailModal(setId, allowed);
            } catch (err) {
              publishBtn.disabled = false;
              showToast(`發布失敗: ${err.message}`, { tone: "error" });
            }
          });
          vCard.append(publishBtn);
        } else {
          vCard.append(el("p", "text-muted", "此版本已建立，需由具備題庫發布權限的角色完成發布。"));
        }
      }
      verList.append(vCard);
    }

    const actions = content.querySelector("#set-version-actions");
    if (canWriteSet) {
      const createVerBtn = el(
        "button",
        "btn-primary",
        canPublishSet ? "＋ 建立並發布新版本" : "＋ 建立題庫版本草稿",
      );
      createVerBtn.type = "button";
      createVerBtn.addEventListener("click", () => showPublishVersionModal(
        setId,
        () => showSetDetailModal(setId, allowed),
        canPublishSet,
      ));
      actions.append(createVerBtn);
    } else if (!allowed.has("ops.evals.write")) {
      actions.append(el("p", "text-muted", "目前角色僅可查看題庫版本；建立與發布需要對應的驗收權限。"));
    } else if (!actorCanManageOwnerUnits(s.owner_unit_ids)) {
      actions.append(el("p", "text-muted", "目前角色的單位範圍不足以管理此題庫；請切換具備所有負責單位範圍的角色。"));
    } else {
      actions.append(el("p", "text-muted", "目前角色可發布既有草稿，但沒有建立新版本的權限。"));
    }
  } catch (err) {
    content.innerHTML = `<div class="error">讀取失敗: ${escapeHtml(err.message || err)}</div>`;
  }
}

export async function showPublishVersionModal(setId, onSuccess, canPublish = false) {
  const content = el("div", "modal-body");
  content.innerHTML = "<p>載入可納入題庫的案例清單...</p>";
  showContentModal(content);

  try {
    const casesRes = await api("/api/evaluations/cases?status=APPROVED");
    const approvedCases = casesRes.items || [];

    if (approvedCases.length === 0) {
      content.innerHTML = `
        <h3>發布新題庫版本</h3>
        <p class="error">目前沒有任何已核准 (APPROVED) 的案例！根據規格 GE1-A01，未核准案例不可發布入題庫。</p>
      `;
      return;
    }

    content.innerHTML = `
      <h3>${canPublish ? "發布新題庫版本" : "建立題庫版本草稿"} (不可變快照)</h3>
      <p class="text-muted">請勾選要包含在本次版本中的核准案例${canPublish ? "，建立後會立即發布" : "；建立草稿後請由具備發布權限的角色完成發布"}：</p>
      <form id="publish-ver-form">
        <div class="cases-selector" style="max-height: 250px; overflow-y: auto; border: 1px solid #ccc; padding: 8px;">
          ${approvedCases.map(item => `
            <label style="display:block; margin-bottom: 4px;">
              <input type="checkbox" name="rev_id" value="${escapeHtml(item.current_revision.revision_id)}" checked>
              <strong>${escapeHtml(item.case.title)}</strong> (rev ${escapeHtml(item.current_revision.revision_number)}) - ${escapeHtml(item.current_revision.behavior)}
            </label>
          `).join("")}
        </div>
        <div class="btn-row" style="margin-top: 12px;">
          <button type="submit" class="btn-primary">${canPublish ? "建立並發布版本" : "建立版本草稿"}</button>
        </div>
      </form>
    `;

    const form = content.querySelector("#publish-ver-form");
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const checkedBoxes = form.querySelectorAll("input[name='rev_id']:checked");
      const revIds = Array.from(checkedBoxes).map(b => b.value);
      if (revIds.length === 0) {
        showToast("請至少選擇一個案例！", { tone: "error" });
        return;
      }

      try {
        const draftRes = await api(`/api/evaluations/sets/${setId}/versions`, {
          method: "POST",
          body: JSON.stringify({ case_revision_ids: revIds }),
        });
        const draft = draftRes.version;

        if (canPublish) {
          await api(`/api/evaluations/sets/${setId}/versions/${draft.set_version_id}/publish`, {
            method: "POST",
            body: JSON.stringify({ expected_etag: draft.etag }),
          });
          showToast("題庫版本發布成功！此版本成員與 Manifest Hash 已永久鎖定。", { tone: "success" });
        } else {
          showToast("題庫版本草稿已建立，請交由具備發布權限的角色完成發布。", { tone: "success" });
        }
        closeContentModal();
        if (onSuccess) onSuccess();
      } catch (err) {
        showToast(`發布失敗: ${err.message}`, { tone: "error" });
      }
    });
  } catch (err) {
    content.innerHTML = `<div class="error">讀取失敗: ${escapeHtml(err.message || err)}</div>`;
  }
}
