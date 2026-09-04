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
                  <span class="status-badge ${item.status === "ACTIVE" ? "success" : item.status === "RELOAD_FAILED" ? "danger" : item.status === "DEPLOYING" ? "warning" : "default"}">
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
