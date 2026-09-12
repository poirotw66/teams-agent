import { api } from "../api.js";
import { can } from "../capabilities.js";
import { handleConflictError } from "../errors.js";
import { escapeHtml, handleViewError, openDialog, promptDialog, showToast } from "../ui.js?v=20260831e";

const RELEASE_STATUS_LABELS = {
  ACTIVE: "正式生效 (驗證通過)",
  DEPLOYING: "發布完成 (等待生效)",
  ROLLED_BACK: "已取代",
  BUILDING: "建立中",
  READY: "待啟用",
  GATE_BLOCKED: "發布卡關 (Gate 阻擋)",
  RELOAD_FAILED: "生效失敗 (待重試)",
  FAILED: "建立失敗",
};

function formatWhen(value) {
  if (!value) return "未設定";
  return new Date(value).toLocaleString("zh-TW");
}

function releaseStatusLabel(status) {
  return RELEASE_STATUS_LABELS[status] || status;
}

function changeTypeLabel(type) {
  return { ADDED: "新增", REMOVED: "移除", UPDATED: "更新" }[type] || type;
}

function renderCompareSummary(compare) {
  if (!compare.changes.length) {
    return "<p>此版本與目前正式版本的文件清單相同。</p>";
  }
  const rows = compare.changes.map((item) => `
    <tr>
      <td>${escapeHtml(changeTypeLabel(item.change_type))}</td>
      <td>${escapeHtml(item.title)}</td>
    </tr>`).join("");
  const warnings = [];
  if (compare.target_is_older) {
    warnings.push("<p><strong>注意：</strong>此版本早於目前使用中的版本，回復後 Teams 可能缺少較新的知識內容。</p>");
  }
  if (compare.document_count_delta !== 0) {
    const deltaText = compare.document_count_delta > 0
      ? `將增加 ${compare.document_count_delta} 份文件`
      : `將減少 ${Math.abs(compare.document_count_delta)} 份文件`;
    warnings.push(`<p>${escapeHtml(deltaText)}。</p>`);
  }
  return `
    ${warnings.join("")}
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>變更</th><th>文件</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

export async function renderReleasesView(app) {
  if (!can("list_releases")) {
    app.innerHTML = `
      <section class="page">
        <header class="page-header"><h2>發布紀錄</h2></header>
        <p class="muted">你目前沒有權限查看發布紀錄。</p>
      </section>`;
    return;
  }

  app.innerHTML = `
    <section class="page">
      <header class="page-header">
        <div>
          <h2>發布紀錄</h2>
        </div>
      </header>
      <div id="releasesContent">${escapeHtml("載入中…")}</div>
    </section>`;

  const container = app.querySelector("#releasesContent");

  async function refresh() {
    await renderReleasesView(app);
  }

  try {
    const [dashboard, releases] = await Promise.all([
      api("/api/dashboard"),
      api("/api/releases"),
    ]);
    const activeId = dashboard.active_release_id;
    const rows = !releases.length
      ? "<p class=\"muted\">尚無發布紀錄。</p>"
      : `
        <table class="data-table">
          <thead>
            <tr>
              <th>版本</th>
              <th>狀態</th>
              <th>文件數</th>
              <th>建立時間</th>
              <th>啟用時間</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            ${releases.map((item) => `
              <tr>
                <td>${escapeHtml(item.release_id)}${item.release_id === activeId ? " <span class=\"muted\">（使用中）</span>" : ""}</td>
                <td>
                  <span class="status-badge ${item.status === "ACTIVE" ? "success" : item.status === "RELOAD_FAILED" || item.status === "GATE_BLOCKED" ? "danger" : item.status === "DEPLOYING" ? "warning" : "default"}">
                    ${escapeHtml(releaseStatusLabel(item.status))}
                  </span>
                  ${item.failure_summary ? `<br><small class="text-danger">${escapeHtml(item.failure_summary)}</small>` : ""}
                </td>
                <td>${item.manifest?.length || 0}</td>
                <td>${formatWhen(item.created_at)}</td>
                <td>${formatWhen(item.activated_at)}</td>
                <td>
                  ${can("manage_releases") && item.status === "RELOAD_FAILED" ? `
                    <button type="button" class="btn warning btn-sm" data-sync="${escapeHtml(item.release_id)}">重試通知 Agent</button>` : ""}
                  ${can("manage_releases") && item.release_id !== activeId && (item.status === "READY" || item.status === "GATE_BLOCKED") ? `
                    <button type="button" class="btn primary btn-sm" data-promote="${escapeHtml(item.release_id)}">啟用此版本</button>` : ""}
                  ${can("manage_releases") && item.release_id !== activeId ? `
                    <button type="button" class="btn secondary btn-sm" data-rollback="${escapeHtml(item.release_id)}">查看差異並切換</button>` : ""}
                </td>
              </tr>`).join("")}
          </tbody>
        </table>`;

    container.innerHTML = `
      <div class="panel">
        <p class="muted">目前使用中：${escapeHtml(activeId || "（無）")}</p>
        ${rows}
        <p class="muted">切換版本會更新 Teams 引用的正式知識索引並發送生效通知。請先查看差異，確認後再執行。</p>
      </div>`;

    container.querySelectorAll("[data-sync]").forEach((button) => {
      button.addEventListener("click", async () => {
        const releaseId = button.dataset.sync;
        button.disabled = true;
        button.textContent = "同步中…";
        try {
          await api(`/api/releases/${encodeURIComponent(releaseId)}/sync-agent`, {
            method: "POST",
          });
          showToast("已向 Teams 智慧助理發送重載請求");
          await refresh();
        } catch (error) {
          showToast(error.message, true);
          button.disabled = false;
          button.textContent = "重試通知 Agent";
        }
      });
    });

    container.querySelectorAll("[data-promote]").forEach((button) => {
      button.addEventListener("click", async () => {
        const releaseId = button.dataset.promote;
        const confirmed = await openDialog({
          title: "確認啟用發布版本",
          bodyHtml: `<p>確定要啟用候選版本 <strong>${escapeHtml(releaseId)}</strong> 嗎？系統將執行 Release Gate 門檻檢驗，通過後將此版本設定為正式使用中的知識索引並通知 Teams 智慧助理。</p>`,
          confirmLabel: "確認啟用",
          cancelLabel: "取消",
        });
        if (!confirmed) return;

        button.disabled = true;
        const originalText = button.textContent;
        button.textContent = "啟用中…";
        try {
          const res = await api(`/api/releases/${encodeURIComponent(releaseId)}/promote`, {
            method: "POST",
          });
          if (res?.status === "RELOAD_FAILED") {
            await openDialog({
              title: "版本已啟用，但 Agent 重新載入失敗",
              bodyHtml: `<p class="text-warning"><strong>版本 ${escapeHtml(releaseId)} 已更新為啟用狀態，但通知 Teams 智慧助理重新載入時發生錯誤：</strong></p><p class="muted" style="margin-top: 8px;">${escapeHtml(res.failure_summary || "Agent reload 失敗")}</p><p class="muted" style="margin-top: 8px;">請稍後於清單中點擊「重試通知 Agent」，或確認背景服務狀態。</p>`,
              confirmLabel: "了解",
              cancelLabel: null,
            });
          } else {
            showToast("已成功啟用候選版本");
          }
          await refresh();
        } catch (error) {
          const status = error.status;
          const code = String(error.code || "").toUpperCase();
          const msg = String(error.message || "");
          const isGateBlocked = code === "RELEASE_GATE_BLOCKED" || msg.includes("Release gate blocked") || msg.includes("門檻") || msg.includes("Gate");
          const isForbidden = status === 403 && !isGateBlocked;
          const isNotFound = status === 404 || msg.includes("404");

          if (isGateBlocked) {
            await openDialog({
              title: "啟用失敗：Release Gate 門檻未通過",
              bodyHtml: `<p class="text-danger"><strong>${escapeHtml(error.message || "發布門檻檢驗未通過")}</strong></p><p class="muted" style="margin-top: 8px;">請確認該版本已在營運後台完成 Eval 評估並通過品質指標，或由管理員建立例外後再試。</p>`,
              confirmLabel: "關閉",
              cancelLabel: null,
            });
          } else if (isForbidden) {
            await openDialog({
              title: "啟用失敗：權限不足",
              bodyHtml: `<p class="text-danger"><strong>您沒有發布或啟用版本的權限（需具備 knowledge.publish 權限）。</strong></p><p class="muted" style="margin-top: 8px;">${escapeHtml(error.message || "請洽詢系統管理員協助授權。")}</strong></p>`,
              confirmLabel: "關閉",
              cancelLabel: null,
            });
          } else if (isNotFound) {
            await openDialog({
              title: "啟用失敗：找不到版本",
              bodyHtml: `<p class="text-danger"><strong>找不到指定的候選版本 ${escapeHtml(releaseId)}。</strong></p><p class="muted" style="margin-top: 8px;">該版本可能已被刪除或尚未建立完成，請重新整理頁面後再試。</p>`,
              confirmLabel: "關閉",
              cancelLabel: null,
            });
          } else {
            await openDialog({
              title: "啟用失敗：系統或連線錯誤",
              bodyHtml: `<p class="text-danger"><strong>啟用操作遭遇非預期錯誤：${escapeHtml(error.message || "網路連線異常或服務暫時無法回應")}</strong></p><p class="muted" style="margin-top: 8px;">請檢查網路連線或稍後再試。若問題持續發生，請聯繫系統維運團隊。</p>`,
              confirmLabel: "關閉",
              cancelLabel: null,
            });
          }
          await refresh();
        } finally {
          button.disabled = false;
          button.textContent = originalText;
        }
      });
    });

    container.querySelectorAll("[data-rollback]").forEach((button) => {
      button.addEventListener("click", async () => {
        const releaseId = button.dataset.rollback;
        try {
          const compare = await api(`/api/releases/compare?target_release_id=${encodeURIComponent(releaseId)}`);
          const preview = await openDialog({
            title: "確認切換發布版本",
            bodyHtml: `
              <p>你即將切換至 <strong>${escapeHtml(releaseId)}</strong>。</p>
              ${renderCompareSummary(compare)}`,
            confirmLabel: "繼續",
            cancelLabel: "取消",
          });
          if (!preview) return;

          const reason = await promptDialog("切換發布版本", "請說明切換原因", {
            defaultValue: `切換至 ${releaseId}`,
          });
          if (reason === null) return;

          const confirmed = await openDialog({
            title: "最終確認",
            bodyHtml: `<p>此操作會更新正式發布指標，並通知 Teams 智慧助理重新載入知識索引。確定要切換至 <strong>${escapeHtml(releaseId)}</strong> 嗎？</p>`,
            confirmLabel: "執行切換",
            danger: true,
          });
          if (!confirmed) return;

          const idempotencyKey = "rollback-" + Date.now() + "-" + Math.random().toString(36).substring(2, 9);
          await api("/api/releases/rollback", {
            method: "POST",
            headers: { "Idempotency-Key": idempotencyKey },
            body: JSON.stringify({ release_id: releaseId, reason }),
          });
          showToast("已切換發布版本");
          await refresh();

        } catch (error) {
          if (await handleConflictError(error, refresh)) return;
          showToast(error.message, true);
        }
      });
    });
  } catch (error) {
    handleViewError(error, {
      view: "audit",
      container,
      onRetry: refresh,
    });
  }
}
