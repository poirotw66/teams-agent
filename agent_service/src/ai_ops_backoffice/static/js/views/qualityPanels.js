import { api, el } from "../api.js";
import { showContentModal } from "../components/modal.js";
import { actorCapabilities } from "../app/capabilities.js";
import { showQualityCaseDetail } from "./qualityCaseDetail.js";

async function refreshQuality(state) {
  const { renderQuality } = await import("./quality.js");
  return renderQuality(state);
}


export async function buildQualityLoopPanel() {
  const panel = el("section", "panel");
  panel.append(el("h2", "", "改善案件池"));
  panel.append(
    el(
      "p",
      "metric-label",
      "閉環步驟：待辦／負評 → 合併案件 → 修正文件／FAQ → 審核發布 → 案例與對話驗證 → 觀察成效並結案。",
    ),
  );
  const allowed = actorCapabilities();

  const caseTypeLabels = {
    NO_ANSWER: "無答案",
    NEGATIVE_FEEDBACK: "負評",
    HANDOFF: "轉人工",
    KNOWLEDGE_GAP: "知識缺口",
    LOW_CONFIDENCE: "低信心度",
  };
  const statusLabels = {
    NEW: "新建",
    TRIAGED: "已分派",
    IN_PROGRESS: "修正中",
    WAITING_REVIEW: "待審核",
    OBSERVING: "觀察中",
    RESOLVED: "已結案",
    WONT_FIX: "不處理",
    DUPLICATE: "重複",
  };

  const [candidateData, caseData] = await Promise.all([
    api("/api/quality-candidates?status=OPEN"),
    api("/api/quality-cases"),
  ]);

  const selected = new Set();
  const allCandidates = candidateData.items || [];

  // Top action bar
  const controls = el("div", "filter-bar");
  let mergeBtn = null;

  if (allowed.has("ops.quality.write")) {
    const refresh = el("button", "", "掃描新候選");
    refresh.addEventListener("click", async () => {
      refresh.disabled = true;
      try {
        await api("/api/quality-candidates/refresh", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ days: 30 }),
        });
        await refreshQuality();
      } catch (error) {
        showContentModal("候選掃描失敗", el("div", "error", error.message));
      } finally {
        refresh.disabled = false;
      }
    });
    controls.append(refresh);

    mergeBtn = el("button", "button-primary", "合併為改善案件 (已選 0 筆)");
    mergeBtn.disabled = true;
    mergeBtn.addEventListener("click", async () => {
      if (!selected.size) return;
      const title = window.prompt(`請輸入改善案件標題（將合併 ${selected.size} 筆候選）：`);
      if (!title?.trim()) return;
      try {
        mergeBtn.disabled = true;
        mergeBtn.textContent = "合併中…";
        await api("/api/quality-candidates/merge", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            candidate_ids: [...selected],
            title: title.trim(),
            description: "由營運事件候選合併",
            priority: "MEDIUM",
          }),
        });
        await refreshQuality();
      } catch (error) {
        showContentModal("合併失敗", el("div", "error", error.message));
      } finally {
        updateSelectionState();
      }
    });
    controls.append(mergeBtn);
  }
  panel.append(controls);

  const candidateSectionHeading = el("h3", "", `待合併候選（${candidateData.total || 0}）`);
  panel.append(candidateSectionHeading);

  if (allCandidates.length) {
    let searchQuery = "";
    let selectedCaseType = "";
    let currentPage = 1;
    let pageSize = 25;

    const toolbar = el("div", "candidate-toolbar");

    const searchInput = el("input");
    searchInput.placeholder = "搜尋候選摘要、問題類型…";
    searchInput.style.minWidth = "220px";
    searchInput.addEventListener("input", () => {
      searchQuery = searchInput.value.toLowerCase().trim();
      currentPage = 1;
      renderCandidatesTable();
    });

    const typeSelect = el("select");
    const allOpt = el("option", "", "全部案件類型");
    allOpt.value = "";
    typeSelect.append(allOpt);
    for (const [val, lab] of Object.entries(caseTypeLabels)) {
      const opt = el("option", "", lab);
      opt.value = val;
      typeSelect.append(opt);
    }
    typeSelect.addEventListener("change", () => {
      selectedCaseType = typeSelect.value;
      currentPage = 1;
      renderCandidatesTable();
    });

    const selectFilteredBtn = el("button", "", "選取篩選結果");
    selectFilteredBtn.addEventListener("click", () => {
      const filtered = getFiltered();
      for (const item of filtered) selected.add(item.candidate_id);
      renderCandidatesTable();
    });

    const clearSelectionBtn = el("button", "", "清除選取");
    clearSelectionBtn.addEventListener("click", () => {
      selected.clear();
      renderCandidatesTable();
    });

    const pageSizeSelect = el("select");
    for (const size of [25, 50, 100, "all"]) {
      const opt = el("option", "", size === "all" ? "顯示全部" : `每頁 ${size} 筆`);
      opt.value = String(size);
      if (size === 25) opt.selected = true;
      pageSizeSelect.append(opt);
    }
    pageSizeSelect.addEventListener("change", () => {
      pageSize = pageSizeSelect.value === "all" ? "all" : parseInt(pageSizeSelect.value, 10);
      currentPage = 1;
      renderCandidatesTable();
    });

    const selectionCounter = el("span", "metric-label", `已選取 0 筆`);

    toolbar.append(searchInput, typeSelect, selectFilteredBtn, clearSelectionBtn, pageSizeSelect, selectionCounter);
    panel.append(toolbar);

    const tableBox = el("div", "table-scroll-box candidate-scroll-box");
    const table = el("table", "candidate-table");
    const headerRow = el("tr");
    const headerSelectTh = el("th");
    const headerSelectAllCheckbox = el("input");
    headerSelectAllCheckbox.type = "checkbox";
    headerSelectAllCheckbox.title = "選取／取消本頁全部";
    headerSelectTh.append(headerSelectAllCheckbox);

    headerRow.append(
      headerSelectTh,
      el("th", "", "案件類型"),
      el("th", "", "問題類型"),
      el("th", "", "摘要"),
    );
    table.append(el("thead", "", headerRow));
    const tableBody = el("tbody");
    table.append(tableBody);
    tableBox.append(table);
    panel.append(tableBox);

    const paginationBar = el("div", "candidate-pagination");
    const paginationSummary = el("span", "metric-label", "");
    const pagerButtons = el("div", "filter-bar");
    pagerButtons.style.marginBottom = "0";
    const prevBtn = el("button", "", "上一頁");
    const nextBtn = el("button", "", "下一頁");
    pagerButtons.append(prevBtn, nextBtn);
    paginationBar.append(paginationSummary, pagerButtons);
    panel.append(paginationBar);

    function getFiltered() {
      return allCandidates.filter((item) => {
        if (selectedCaseType && item.case_type !== selectedCaseType) {
          return false;
        }
        if (searchQuery) {
          const desc = (item.description || "").toLowerCase();
          const issue = (item.issue_type_display_name || item.issue_type_id || "").toLowerCase();
          const type = (caseTypeLabels[item.case_type] || item.case_type || "").toLowerCase();
          const title = (item.title || "").toLowerCase();
          if (!desc.includes(searchQuery) && !issue.includes(searchQuery) && !type.includes(searchQuery) && !title.includes(searchQuery)) {
            return false;
          }
        }
        return true;
      });
    }

    function updateSelectionState() {
      selectionCounter.textContent = `已選取 ${selected.size} 筆`;
      if (mergeBtn) {
        mergeBtn.disabled = selected.size === 0;
        mergeBtn.textContent = `合併為改善案件 (已選 ${selected.size} 筆)`;
      }
    }

    function renderCandidatesTable() {
      const filtered = getFiltered();
      const totalFiltered = filtered.length;
      const effectivePageSize = pageSize === "all" ? Math.max(totalFiltered, 1) : pageSize;
      const totalPages = Math.max(1, Math.ceil(totalFiltered / effectivePageSize));
      if (currentPage > totalPages) currentPage = totalPages;
      if (currentPage < 1) currentPage = 1;

      const startIndex = (currentPage - 1) * effectivePageSize;
      const pageItems = filtered.slice(startIndex, startIndex + effectivePageSize);

      tableBody.replaceChildren();

      let allPageSelected = pageItems.length > 0;
      for (const item of pageItems) {
        const isChecked = selected.has(item.candidate_id);
        if (!isChecked) allPageSelected = false;

        const checkbox = el("input");
        checkbox.type = "checkbox";
        checkbox.checked = isChecked;

        const row = el("tr");
        if (isChecked) row.classList.add("is-selected");

        const updateRowCheck = (checked) => {
          if (checked) {
            selected.add(item.candidate_id);
            row.classList.add("is-selected");
          } else {
            selected.delete(item.candidate_id);
            row.classList.remove("is-selected");
          }
          checkbox.checked = checked;
          updateSelectionState();
          headerSelectAllCheckbox.checked = pageItems.every((it) => selected.has(it.candidate_id));
        };

        checkbox.addEventListener("change", () => updateRowCheck(checkbox.checked));

        const selectCell = el("td");
        selectCell.append(checkbox);

        const typeCell = el("td");
        const typeBadge = el("span", "badge", caseTypeLabels[item.case_type] || item.case_type);
        typeCell.append(typeBadge);

        const issueCell = el(
          "td",
          "",
          item.issue_type_display_name || item.issue_type_id || "未分類",
        );

        const descCell = el("td", "", item.description || "-");
        descCell.style.overflowWrap = "break-word";

        row.append(selectCell, typeCell, issueCell, descCell);
        tableBody.append(row);
      }

      headerSelectAllCheckbox.checked = allPageSelected;

      paginationSummary.textContent = `第 ${currentPage} / ${totalPages} 頁（篩選結果 ${totalFiltered} 筆 / 全部 ${candidateData.total || allCandidates.length} 筆）`;
      prevBtn.disabled = currentPage <= 1;
      nextBtn.disabled = currentPage >= totalPages;

      updateSelectionState();
    }

    headerSelectAllCheckbox.addEventListener("change", () => {
      const filtered = getFiltered();
      const effectivePageSize = pageSize === "all" ? Math.max(filtered.length, 1) : pageSize;
      const startIndex = (currentPage - 1) * effectivePageSize;
      const pageItems = filtered.slice(startIndex, startIndex + effectivePageSize);
      for (const item of pageItems) {
        if (headerSelectAllCheckbox.checked) {
          selected.add(item.candidate_id);
        } else {
          selected.delete(item.candidate_id);
        }
      }
      renderCandidatesTable();
    });

    prevBtn.addEventListener("click", () => {
      if (currentPage > 1) {
        currentPage--;
        renderCandidatesTable();
      }
    });

    nextBtn.addEventListener("click", () => {
      currentPage++;
      renderCandidatesTable();
    });

    renderCandidatesTable();
  } else {
    panel.append(el("p", "empty", "目前沒有待處理候選。"));
  }

  // Ongoing cases section
  panel.append(el("h3", "", `進行中案件（${caseData.total || 0}）`));
  if ((caseData.items || []).length) {
    const table = el("table");
    table.innerHTML =
      "<thead><tr><th>案件</th><th>狀態</th><th>優先級</th><th>負責單位／承辦</th><th>下一步</th></tr></thead>";
    const body = el("tbody");
    for (const item of caseData.items) {
      const action = el("td");
      const detail = el("button", "", "查看與處理");
      detail.addEventListener("click", () => showQualityCaseDetail(item.case_id));
      action.append(detail);
      const row = el("tr");
      row.append(
        el("td", "", item.title),
        el("td", "", statusLabels[item.status] || item.status),
        el("td", "", item.priority),
        el("td", "", `${item.owner_unit_id} / ${item.assignee_id || "未指派"}`),
        action,
      );
      body.append(row);
    }
    table.append(body);
    const caseScroll = el("div", "table-responsive");
    caseScroll.append(table);
    panel.append(caseScroll);
  } else {
    panel.append(el("p", "empty", "目前沒有進行中案件。"));
  }
  return panel;
}

export async function buildGapPanel() {
  const panel = el("section", "panel");
  panel.append(el("h2", "", "Knowledge Gap 排序"));
  const data = await api("/api/gaps/summary?days=30");
  panel.append(el("p", "metric-label", `規則版本：${data.scoreVersion}｜Taxonomy：${data.taxonomyVersion}`));
  if (!(data.items || []).length) {
    panel.append(el("p", "empty", "目前沒有可評分的 Gap。"));
    return panel;
  }
  const table = el("table");
  table.innerHTML = "<thead><tr><th>Issue</th><th>Gap Score</th><th>頻率</th><th>無答案</th><th>負評</th><th>轉人工</th><th>成本</th></tr></thead>";
  const body = el("tbody");
  for (const item of data.items) {
    const row = el("tr");
    row.append(
      el("td", "", item.displayName || item.issueTypeId),
      el("td", "", item.gapScore.toFixed(2)),
      el("td", "", item.components.frequency.toFixed(2)),
      el("td", "", item.components.noAnswerRate.toFixed(2)),
      el("td", "", item.components.negativeFeedbackRate.toFixed(2)),
      el("td", "", item.components.handoffRate.toFixed(2)),
      el("td", "", item.components.estimatedCostUsd.toFixed(2)),
    );
    body.append(row);
  }
  table.append(body);
  const gapScroll = el("div", "table-responsive");
  gapScroll.append(table);
  panel.append(gapScroll);
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
  return panel;
}
