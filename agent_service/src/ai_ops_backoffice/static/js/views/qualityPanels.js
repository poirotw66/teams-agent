import { api, el } from "../api.js";
import { showContentModal, closeContentModal } from "../components/modal.js";
import { badge, statusBadge } from "../components/badges.js";
import { actorCapabilities } from "../app/capabilities.js";
import { isBuShellEnabled } from "../app/buShellConfig.js";
import { labelStatus } from "../app/labels.js";
import { saveNavFilters, syncLocationHash } from "../app/navigation.js";
import { showQualityCaseDetail } from "./qualityCaseDetail.js";

async function refreshQuality(state) {
  const { renderQuality } = await import("./quality.js");
  return renderQuality(state);
}

function showQualityScanModal(onConfirm) {
  const container = el("div", "form-grid");
  const callout = el(
    "div",
    "callout callout-info",
    "重新掃描會保留進行中的案例（NEW、TRIAGED、IN_PROGRESS、WAITING_REVIEW、OBSERVING），並自動將重疊之候選關聯至既有案件，避免覆蓋已指派負責人或排定維護的案例。",
  );
  callout.style.padding = "0.75rem";
  callout.style.marginBottom = "0.75rem";
  callout.style.backgroundColor = "var(--panel-muted)";
  callout.style.borderRadius = "var(--radius-sm)";
  callout.style.fontSize = "0.85rem";
  callout.style.lineHeight = "1.4";

  const periodGroup = el("div", "form-group");
  const label = el("label", "form-label", "掃描資料天數：");
  const select = el("select");
  for (const [days, text] of [
    [7, "最近 7 天"],
    [14, "最近 14 天"],
    [30, "最近 30 天（預設）"],
    [90, "最近 90 天"],
    [180, "最近 180 天"],
    [365, "最近 365 天"],
  ]) {
    const opt = el("option", "", text);
    opt.value = String(days);
    if (days === 30) opt.selected = true;
    select.append(opt);
  }
  periodGroup.append(label, select);

  const actions = el("div", "filter-bar");
  actions.style.marginTop = "1rem";
  actions.style.justifyContent = "flex-end";
  const cancelBtn = el("button", "", "取消");
  cancelBtn.addEventListener("click", () => closeContentModal());

  const confirmBtn = el("button", "button-primary", "開始掃描");
  confirmBtn.addEventListener("click", async () => {
    confirmBtn.disabled = true;
    confirmBtn.textContent = "掃描中…";
    try {
      await onConfirm(parseInt(select.value, 10));
      closeContentModal();
    } catch (err) {
      confirmBtn.disabled = false;
      confirmBtn.textContent = "開始掃描";
      showContentModal("候選掃描失敗", el("div", "error", err.message));
    }
  });

  actions.append(cancelBtn, confirmBtn);
  container.append(callout, periodGroup, actions);
  showContentModal("掃描新品質候選", container);
}

function showMergeCandidatesModal(count, onConfirm) {
  const container = el("div", "form-grid");
  const desc = el("p", "metric-label", `即將合併已選取的 ${count} 筆品質候選為新的改善案件。`);
  desc.style.marginBottom = "0.75rem";

  const titleGroup = el("div", "form-group");
  const titleLabel = el("label", "form-label", "改善案件標題（必填）：");
  const titleInput = el("input");
  titleInput.placeholder = "例如：修正特定情境下的無答案問題";
  titleInput.style.width = "100%";
  titleGroup.append(titleLabel, titleInput);

  const descGroup = el("div", "form-group");
  const descLabel = el("label", "form-label", "案件說明：");
  const descInput = el("textarea");
  descInput.value = "由營運事件候選合併";
  descInput.rows = 3;
  descInput.style.width = "100%";
  descGroup.append(descLabel, descInput);

  const prioGroup = el("div", "form-group");
  const prioLabel = el("label", "form-label", "優先級：");
  const prioSelect = el("select");
  for (const [val, lab] of [
    ["LOW", "低 (LOW)"],
    ["MEDIUM", "中 (MEDIUM)"],
    ["HIGH", "高 (HIGH)"],
    ["CRITICAL", "緊急 (CRITICAL)"],
  ]) {
    const opt = el("option", "", lab);
    opt.value = val;
    if (val === "MEDIUM") opt.selected = true;
    prioSelect.append(opt);
  }
  prioGroup.append(prioLabel, prioSelect);

  const actions = el("div", "filter-bar");
  actions.style.marginTop = "1rem";
  actions.style.justifyContent = "flex-end";
  const cancelBtn = el("button", "", "取消");
  cancelBtn.addEventListener("click", () => closeContentModal());

  const submitBtn = el("button", "button-primary", "確認合併");
  submitBtn.addEventListener("click", async () => {
    const titleVal = titleInput.value.trim();
    if (!titleVal) {
      alert("請輸入改善案件標題");
      return;
    }
    submitBtn.disabled = true;
    submitBtn.textContent = "合併中…";
    try {
      await onConfirm({
        title: titleVal,
        description: descInput.value.trim() || "由營運事件候選合併",
        priority: prioSelect.value,
      });
      closeContentModal();
    } catch (err) {
      submitBtn.disabled = false;
      submitBtn.textContent = "確認合併";
      showContentModal("合併失敗", el("div", "error", err.message));
    }
  });

  actions.append(cancelBtn, submitBtn);
  container.append(desc, titleGroup, descGroup, prioGroup, actions);
  showContentModal("合併品質候選為改善案件", container);
}


export async function buildQualityLoopPanel() {
  const panel = el("section", "panel");
  const buShell = isBuShellEnabled();
  if (!buShell) {
    panel.append(el("h2", "", "改善案件池"));
  }
  if (buShell) {
    const steps = el("details", "bu-workflow-steps");
    steps.append(el("summary", "", "閉環步驟說明"));
    steps.append(
      el(
        "p",
        "metric-label",
        "待辦／負評 → 合併案件 → 修正文件／FAQ → 審核發布 → 案例與對話驗證 → 觀察成效並結案。",
      ),
    );
    panel.append(steps);
  } else {
    panel.append(
      el(
        "p",
        "metric-label",
        "閉環步驟：待辦／負評 → 合併案件 → 修正文件／FAQ → 審核發布 → 案例與對話驗證 → 觀察成效並結案。",
      ),
    );
  }
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
  const candidateCount = candidateData.total || allCandidates.length;
  const openCaseCount = caseData.total || (caseData.items || []).length;

  // Candidate tooling mounts into this block (shown after cases under BU shell).
  const candidatesBlock = el("div", "bu-candidates-block");

  // Top action bar
  const controls = el("div", "filter-bar");
  let mergeBtn = null;

  if (allowed.has("ops.quality.write")) {
    const refresh = el("button", "", "掃描新候選");
    refresh.addEventListener("click", () => {
      showQualityScanModal(async (days) => {
        await api("/api/quality-candidates/refresh", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ days }),
        });
        await refreshQuality();
      });
    });
    controls.append(refresh);

    mergeBtn = el("button", "button-primary", "合併為改善案件 (已選 0 筆)");
    mergeBtn.disabled = true;
    mergeBtn.addEventListener("click", () => {
      if (!selected.size) return;
      showMergeCandidatesModal(selected.size, async (formValues) => {
        await api("/api/quality-candidates/merge", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            candidate_ids: [...selected],
            ...formValues,
          }),
        });
        await refreshQuality();
      });
    });
    controls.append(mergeBtn);
  }
  candidatesBlock.append(controls);

  const candidateSectionHeading = el("h3", "", `待整理候選（${candidateCount}）`);
  if (!buShell) {
    candidatesBlock.append(candidateSectionHeading);
  }

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
    candidatesBlock.append(toolbar);

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
      el("th", "", "來源追蹤"),
    );
    const thead = el("thead");
    thead.append(headerRow);
    table.append(thead);
    const tableBody = el("tbody");
    table.append(tableBody);
    tableBox.append(table);
    candidatesBlock.append(tableBox);

    const paginationBar = el("div", "candidate-pagination");
    const paginationSummary = el("span", "metric-label", "");
    const pagerButtons = el("div", "filter-bar");
    pagerButtons.style.marginBottom = "0";
    const prevBtn = el("button", "", "上一頁");
    const nextBtn = el("button", "", "下一頁");
    pagerButtons.append(prevBtn, nextBtn);
    paginationBar.append(paginationSummary, pagerButtons);
    candidatesBlock.append(paginationBar);

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

        const traceCell = el("td");
        traceCell.style.fontSize = "0.825rem";
        const traceBadges = el("div");
        traceBadges.style.display = "flex";
        traceBadges.style.flexWrap = "wrap";
        traceBadges.style.gap = "0.25rem";

        const srcType = item.source_type || "系統";
        traceBadges.append(badge(srcType, "neutral"));

        if (item.conversation_refs && item.conversation_refs.length) {
          const shortRefs = item.conversation_refs
            .slice(0, 2)
            .map((id) => String(id).slice(0, 8));
          const convText = `對話: ${shortRefs.join(", ")}${item.conversation_refs.length > 2 ? "…" : ""}`;
          const convBadge = badge(convText, "accent");
          convBadge.title = item.conversation_refs.join(", ");
          traceBadges.append(convBadge);
        }
        if (item.source_event_ids && item.source_event_ids.length) {
          const shortEvents = item.source_event_ids
            .slice(0, 2)
            .map((id) => String(id).slice(0, 8));
          const evtText = `事件: ${shortEvents.join(", ")}${item.source_event_ids.length > 2 ? "…" : ""}`;
          const evtBadge = badge(evtText, "neutral");
          evtBadge.title = item.source_event_ids.join(", ");
          traceBadges.append(evtBadge);
        }
        if (item.merged_case_id) {
          traceBadges.append(badge(`已關聯: ${item.merged_case_id.slice(0, 8)}`, "success"));
        }
        traceCell.append(traceBadges);

        row.append(selectCell, typeCell, issueCell, descCell, traceCell);
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
    candidatesBlock.append(el("p", "empty", "目前沒有待處理候選。"));
  }

  // Ongoing cases section (REQ-018)
  const casesSection = el("div", "quality-cases-section");
  const casesHeading = el("h3", "", `進行中案件（${openCaseCount}）`);
  casesSection.append(casesHeading);

  const caseFilterBar = el("div", "filter-bar");
  caseFilterBar.style.marginBottom = "0.75rem";

  const caseStatusSelect = el("select");
  caseStatusSelect.setAttribute("aria-label", "案件狀態篩選");
  const allStatusOpt = el("option", "", "全部狀態");
  allStatusOpt.value = "";
  caseStatusSelect.append(allStatusOpt);
  for (const [val, lab] of Object.entries(statusLabels)) {
    const opt = el("option", "", lab);
    opt.value = val;
    caseStatusSelect.append(opt);
  }

  const caseTypeSelect = el("select");
  caseTypeSelect.setAttribute("aria-label", "案件類型篩選");
  const allTypeOpt = el("option", "", "全部類型");
  allTypeOpt.value = "";
  caseTypeSelect.append(allTypeOpt);
  for (const [val, lab] of Object.entries(caseTypeLabels)) {
    const opt = el("option", "", lab);
    opt.value = val;
    caseTypeSelect.append(opt);
  }

  const caseOwnerInput = el("input");
  caseOwnerInput.placeholder = "篩選負責單位…";
  caseOwnerInput.style.minWidth = "160px";
  caseOwnerInput.setAttribute("aria-label", "負責單位篩選");

  const caseFilterBtn = el("button", "", "篩選案件");
  caseFilterBar.append(caseStatusSelect, caseTypeSelect, caseOwnerInput, caseFilterBtn);
  casesSection.append(caseFilterBar);

  const caseScroll = el("div", "table-responsive");
  casesSection.append(caseScroll);

  if (buShell) {
    // Daily path: established cases first; candidate triage stays collapsed.
    panel.append(casesSection);
    const candidatesPanel = el("details", "bu-candidates-panel");
    candidatesPanel.open = openCaseCount === 0 && candidateCount > 0;
    candidatesPanel.append(el("summary", "", `待整理候選（${candidateCount}）`));
    candidatesPanel.append(
      el(
        "p",
        "metric-label",
        "從回饋／無答案事件整理出的候選；合併後才進入上方進行中案件。",
      ),
      candidatesBlock,
    );
    panel.append(candidatesPanel);
  } else {
    panel.append(candidatesBlock);
    panel.append(casesSection);
  }

  function renderCasesTable(items, total) {
    casesHeading.textContent = `進行中案件（${total}）`;
    if (!items.length) {
      caseScroll.replaceChildren(el("p", "empty", "目前沒有符合條件的進行中案件。"));
      return;
    }
    const table = el("table");
    table.innerHTML =
      "<thead><tr><th>案件</th><th>類型</th><th>狀態</th><th>優先級</th><th>負責單位／承辦</th><th>下一步</th></tr></thead>";
    const body = el("tbody");
    for (const item of items) {
      const action = el("td");
      const detail = el("button", "", "查看與處理");
      detail.addEventListener("click", () => {
        if (isBuShellEnabled()) {
          saveNavFilters({ view: "quality", caseId: item.case_id, tab: "cases" });
          syncLocationHash("quality", { caseId: item.case_id, tab: "cases" });
        }
        void showQualityCaseDetail(item.case_id);
      });
      action.append(detail);
      const row = el("tr");
      row.append(
        el("td", "", item.title),
        el("td", "", caseTypeLabels[item.case_type] || item.case_type || "-"),
        el("td", "", statusLabels[item.status] || labelStatus(item.status) || item.status),
        el("td", "", labelStatus(item.priority) || item.priority),
        el("td", "", `${item.owner_unit_id} / ${item.assignee_id || "未指派"}`),
        action,
      );
      body.append(row);
    }
    table.append(body);
    caseScroll.replaceChildren(table);
  }

  async function loadFilteredCases() {
    caseScroll.replaceChildren(el("p", "empty", "載入中…"));
    const params = new URLSearchParams();
    if (caseStatusSelect.value) params.set("status", caseStatusSelect.value);
    if (caseTypeSelect.value) params.set("case_type", caseTypeSelect.value);
    if (caseOwnerInput.value.trim()) params.set("owner_unit_id", caseOwnerInput.value.trim());
    try {
      const data = await api(`/api/quality-cases?${params.toString()}`);
      renderCasesTable(data.items || [], data.total || (data.items || []).length);
    } catch (err) {
      caseScroll.replaceChildren(el("div", "error", err.message));
    }
  }

  caseFilterBtn.addEventListener("click", loadFilteredCases);
  caseStatusSelect.addEventListener("change", loadFilteredCases);
  caseTypeSelect.addEventListener("change", loadFilteredCases);
  caseOwnerInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadFilteredCases();
  });

  renderCasesTable(caseData.items || [], caseData.total || (caseData.items || []).length);

  return panel;
}

export { buildGapPanel } from "./gapPanel.js";
