import { api, el } from "../../api.js";
import { showToast } from "../../components/modal.js";
import { escapeHtml } from "./shared.js";

export async function renderSchedulesSection(container, allowed) {
  const schedTbody = container.querySelector("#schedules-tbody");
  if (!schedTbody) return;

  const loadSchedules = async () => {
    try {
      const schedules = await api("/api/evaluations/schedules");
      if (!schedules || !schedules.length) {
        schedTbody.innerHTML = '<tr><td colspan="7" class="text-muted">目前尚無排程任務。</td></tr>';
        return;
      }
      schedTbody.replaceChildren();
      for (const s of schedules) {
        const tr = el("tr");
        tr.innerHTML = `
          <td><code>${escapeHtml(s.schedule_id)}</code></td>
          <td>${escapeHtml(s.name)}</td>
          <td><code>${escapeHtml((s.set_version_id || "").slice(0, 14))}...</code></td>
          <td>${escapeHtml(s.frequency)}</td>
          <td>$${escapeHtml(s.budget_limit_usd)}</td>
          <td><span class="badge ${s.is_enabled ? "badge-success" : "badge-secondary"}">${s.is_enabled ? "啟用中" : "已停用"}</span></td>
          <td>
            ${allowed.has("ops.evals.write") ? `
              <button class="btn-sm btn-link toggle-sched-btn">${s.is_enabled ? "停用" : "啟用"}</button>
            ` : "-"}
          </td>
        `;

        const toggleBtn = tr.querySelector(".toggle-sched-btn");
        if (toggleBtn) {
          toggleBtn.addEventListener("click", async () => {
            try {
              await api(`/api/evaluations/schedules/${s.schedule_id}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ is_enabled: !s.is_enabled }),
              });
              loadSchedules();
            } catch (err) {
              showToast(`更新排程失敗: ${err.message || err}`, { tone: "error" });
            }
          });
        }

        schedTbody.append(tr);
      }
    } catch (err) {
      schedTbody.innerHTML = `<tr><td colspan="7" class="text-danger">載入排程失敗: ${escapeHtml(err.message || err)}</td></tr>`;
    }
  };

  await loadSchedules();
}
