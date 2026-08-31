import { api } from "../api.js";
import { getSession } from "../session.js";
import { handleConflictError } from "../errors.js";
import { escapeHtml, handleViewError, promptDialog, showToast } from "../ui.js?v=20260831c";

function canManageReleases() {
  return ["MANAGER", "PLATFORM"].includes(getSession().role);
}

function formatWhen(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString("zh-TW");
}

export async function renderReleasesView(app) {
  if (!getSession().visibleNav?.includes("releases")) {
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
          <p class="eyebrow">平台管理</p>
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
                <td>${escapeHtml(item.status)}</td>
                <td>${item.manifest?.length || 0}</td>
                <td>${formatWhen(item.created_at)}</td>
                <td>${formatWhen(item.activated_at)}</td>
                <td>
                  ${canManageReleases() && item.release_id !== activeId ? `
                    <button type="button" class="btn secondary btn-sm" data-rollback="${escapeHtml(item.release_id)}">切換至此版本</button>` : ""}
                </td>
              </tr>`).join("")}
          </tbody>
        </table>`;

    container.innerHTML = `
      <div class="panel">
        <p class="muted">目前使用中：${escapeHtml(activeId || "（無）")}</p>
        ${rows}
        <p class="muted">切換版本會更新 Teams 引用的正式知識索引，請確認後再操作。</p>
      </div>`;

    container.querySelectorAll("[data-rollback]").forEach((button) => {
      button.addEventListener("click", async () => {
        const releaseId = button.dataset.rollback;
        const reason = await promptDialog("切換發布版本", "請說明原因", {
          defaultValue: `切換至 ${releaseId}`,
        });
        if (reason === null) return;
        try {
          await api("/api/releases/rollback", {
            method: "POST",
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
