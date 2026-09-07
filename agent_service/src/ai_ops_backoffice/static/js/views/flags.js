import { api, el } from "../api.js";
import { actorCapabilities } from "../app/capabilities.js";
import { statusBadge } from "../components/badges.js";
import { showContentModal } from "../components/modal.js";
import { createPageController } from "../app/lifecycle.js";

export async function renderFlags() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = actorCapabilities();
    const data = await api("/api/governance/flags");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "Feature Flags"));
    const items = data.items || [];
    if (!items.length) {
      panel.append(el("p", "empty", "目前無 Feature Flag。"));
    } else {
      const table = el("table");
      table.innerHTML = "<thead><tr><th>Flag</th><th>Effective</th><th>Safety Locked</th><th>Owner</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const item of items) {
        const row = el("tr");
        const actions = el("td");
        const flagId = item.flag.flag_id;
        if (allowed.has("ops.flags.read")) {
          const effective = el("button", "", "查有效值");
          effective.addEventListener("click", async () => {
            const result = await api(`/api/governance/flags/${flagId}/effective?environment=lab`);
            showContentModal(`${flagId} effective`, el("pre", "json-block", JSON.stringify(result, null, 2)));
          });
          actions.append(effective);
        }
        const effCell = el("td");
        effCell.append(statusBadge(item.effective ? "ENABLED" : "DISABLED"));
        const lockCell = el("td");
        lockCell.append(statusBadge(item.flag.safety_locked ? "LOCKED" : "UNLOCKED"));
        row.append(
          el("td", "", flagId),
          effCell,
          lockCell,
          el("td", "", item.flag.owner || "-"),
          actions,
        );
        body.append(row);
      }
      table.append(body);
      const scroll = el("div", "table-responsive");
      scroll.append(table);
      panel.append(scroll);
    }
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", "error", error.message));
  }
}

export const flagsPage = createPageController({
  enter: async () => renderFlags(),
  update: async () => renderFlags(),
  leave: async () => {},
});
