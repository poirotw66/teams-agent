import { api, el } from "../api.js";
import { actorCapabilities } from "../app/capabilities.js";

async function refreshQuality() {
  const { renderQuality } = await import("./quality.js");
  return renderQuality();
}

export async function buildGapPanel() {
  const panel = el("section", "panel");
  panel.append(el("h2", "", "Knowledge Gap 排序"));

  const filterBar = el("div", "filter-bar");
  filterBar.style.marginBottom = "1rem";

  const periodSelect = el("select");
  periodSelect.setAttribute("aria-label", "期間");
  for (const [val, label] of [
    ["30", "最近 30 天"],
    ["7", "最近 7 天"],
    ["90", "最近 90 天"],
    ["180", "最近 6 個月"],
    ["365", "最近 1 年"],
  ]) {
    const opt = el("option", "", label);
    opt.value = val;
    if (val === "30") opt.selected = true;
    periodSelect.append(opt);
  }

  const issueInput = el("input");
  issueInput.placeholder = "篩選問題類型 (Issue ID)…";
  issueInput.style.minWidth = "200px";
  issueInput.setAttribute("aria-label", "問題類型");

  const sortSelect = el("select");
  sortSelect.setAttribute("aria-label", "排序欄位");
  for (const [val, label] of [
    ["gapScore", "依 Gap Score 排序"],
    ["frequency", "依頻率排序"],
    ["negativeFeedbackRate", "依負評率排序"],
    ["noAnswerRate", "依無答案率排序"],
    ["handoffRate", "依轉人工率排序"],
    ["cost", "依預估成本排序"],
  ]) {
    const opt = el("option", "", label);
    opt.value = val;
    sortSelect.append(opt);
  }

  const orderSelect = el("select");
  orderSelect.setAttribute("aria-label", "排序方向");
  for (const [val, label] of [
    ["desc", "高到低 (降冪)"],
    ["asc", "低到高 (升冪)"],
  ]) {
    const opt = el("option", "", label);
    opt.value = val;
    orderSelect.append(opt);
  }

  const applyBtn = el("button", "button-primary", "套用篩選");
  filterBar.append(periodSelect, issueInput, sortSelect, orderSelect, applyBtn);
  panel.append(filterBar);

  const metaLabel = el("p", "metric-label", "載入中…");
  panel.append(metaLabel);

  const tableContainer = el("div", "table-responsive");
  panel.append(tableContainer);

  async function loadGaps() {
    metaLabel.textContent = "載入中…";
    tableContainer.replaceChildren(el("p", "empty", "資料載入中…"));

    const params = new URLSearchParams({
      days: periodSelect.value || "30",
      sort_by: sortSelect.value || "gapScore",
      sort_order: orderSelect.value || "desc",
    });
    const issueVal = issueInput.value.trim();
    if (issueVal) params.set("issue_type_id", issueVal);

    try {
      const data = await api(`/api/gaps/summary?${params.toString()}`);
      metaLabel.textContent = `規則版本：${data.scoreVersion}｜Taxonomy：${data.taxonomyVersion}｜共 ${(data.items || []).length} 項`;

      if (!(data.items || []).length) {
        tableContainer.replaceChildren(el("p", "empty", "目前沒有符合條件的 Gap。"));
        return;
      }

      const table = el("table");
      table.innerHTML =
        "<thead><tr><th>Issue</th><th>Gap Score</th><th>頻率</th><th>無答案</th><th>負評</th><th>轉人工</th><th>成本</th></tr></thead>";
      const body = el("tbody");
      for (const item of data.items) {
        const row = el("tr");
        row.append(
          el("td", "", item.displayName || item.issueTypeId),
          el("td", "", Number(item.gapScore || 0).toFixed(2)),
          el("td", "", Number(item.components?.frequency || 0).toFixed(2)),
          el("td", "", Number(item.components?.noAnswerRate || 0).toFixed(2)),
          el("td", "", Number(item.components?.negativeFeedbackRate || 0).toFixed(2)),
          el("td", "", Number(item.components?.handoffRate || 0).toFixed(2)),
          el("td", "", Number(item.components?.estimatedCostUsd || 0).toFixed(2)),
        );
        body.append(row);
      }
      table.append(body);
      tableContainer.replaceChildren(table);
    } catch (error) {
      tableContainer.replaceChildren(el("div", "error", error.message));
    }
  }

  applyBtn.addEventListener("click", loadGaps);
  periodSelect.addEventListener("change", loadGaps);
  sortSelect.addEventListener("change", loadGaps);
  orderSelect.addEventListener("change", loadGaps);
  issueInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadGaps();
  });

  await loadGaps();

  // Cluster Section
  try {
    const clusterData = await api("/api/question-clusters");
    const allowed = actorCapabilities();
    const clusterActions = el("div", "filter-bar");
    if (allowed.has("ops.quality.write")) {
      const generate = el("button", "", "產生單位／問題類型分組");
      generate.addEventListener("click", async () => {
        await api("/api/question-clusters/generate", { method: "POST" });
        await refreshQuality();
      });
      clusterActions.append(generate);
    }
    panel.append(
      el("h3", "", `單位／問題類型分組（${clusterData.total || 0}）`),
      el(
        "p",
        "metric-label",
        "依 owner unit + issue type 分組，不是語意聚類。確認需求後再導入 embedding／人工審核。",
      ),
      clusterActions,
    );
    for (const cluster of (clusterData.items || []).filter((item) => item.status !== "SUPERSEDED")) {
      const row = el("div", "filter-bar");
      row.append(
        el("strong", "", cluster.name),
        el(
          "span",
          "metric-label",
          `${cluster.status}｜${cluster.grouping_method || "OWNER_UNIT_ISSUE_TYPE"}｜頻率 ${cluster.frequency}｜rev ${cluster.revision}`,
        ),
      );
      if (allowed.has("ops.quality.write") && cluster.status === "CANDIDATE") {
        for (const [action, label] of [["ACCEPT", "接受"], ["REJECT", "拒絕"], ["RENAME", "重新命名"]]) {
          const button = el("button", "", label);
          button.addEventListener("click", async () => {
            const name = action === "RENAME" ? window.prompt("Cluster 名稱", cluster.name) : null;
            if (action === "RENAME" && !name?.trim()) return;
            await api("/api/question-clusters/correct", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ cluster_ids: [cluster.cluster_id], action, name }),
            });
            await refreshQuality();
          });
          row.append(button);
        }
      }
      panel.append(row);
    }
  } catch (error) {
    panel.append(el("div", "error", `無法載入群組：${error.message}`));
  }

  return panel;
}
