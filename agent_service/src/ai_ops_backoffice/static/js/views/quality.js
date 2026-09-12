import { api, el } from "../api.js";
import { periodParams, createPeriodControls } from "../components/period.js";
import { createExportButton, runExport } from "../services/export.js";
import { drillLink, loadNavFilters, navigateTo, saveNavFilters, syncLocationHash } from "../app/navigation.js";
import { createPageController } from "../app/lifecycle.js";
import { isBuShellEnabled } from "../app/buShellConfig.js";
import { formatTaipeiDateTime, formatUserFacingError } from "../app/labels.js";
import { withReturnTo } from "../app/returnTo.js";
import { showQualityCaseDetail } from "./qualityCaseDetail.js";
import { buildGapPanel, buildQualityLoopPanel } from "./qualityPanels.js";
import { loadingState } from "../components/state.js";

export { showQualityCaseDetail };


export async function renderQuality(state = {}) {
  const app = document.getElementById("app");
  app.replaceChildren(loadingState("正在整理改善案件與回饋…", 4));
  try {
    const navFilters = loadNavFilters();
    const buShell = isBuShellEnabled();
    const activeTab = state.tab || navFilters.tab || "cases";
    if (navFilters.view === "quality" && navFilters.caseId) {
      await showQualityCaseDetail(navFilters.caseId, { pageMode: buShell });
      if (buShell) {
        return;
      }
    }
    const period =
      state.period ||
      (navFilters.view === "quality" && (navFilters.preset || navFilters.start)
        ? {
            preset: navFilters.preset || (navFilters.start ? "custom" : "30d"),
            start: navFilters.start || "",
            end: navFilters.end || "",
          }
        : { preset: "30d" });
    const savedFilters = state.filters || {};
    const filters = periodParams(period);
    filters.set("limit", "25");
    if (state.cursor) filters.set("cursor", state.cursor);
    const rating =
      savedFilters.rating ||
      (navFilters.view === "quality" ? navFilters.rating : "");
    const issueTypeId =
      savedFilters.issueTypeId ||
      (navFilters.view === "quality" ? navFilters.issueTypeId : "");
    const reason = savedFilters.reason || "";
    const resolved = savedFilters.resolved || "";
    const handoff = savedFilters.handoff || "";
    const model = savedFilters.model || "";
    const route = savedFilters.route || "";
    if (rating) filters.set("rating", rating);
    if (issueTypeId) filters.set("issue_type_id", issueTypeId);
    if (reason) filters.set("reason", reason);
    if (resolved) filters.set("resolved", resolved);
    if (handoff) filters.set("handoff", handoff);
    if (model) filters.set("model", model);
    if (route) filters.set("route", route);

    const loadCases = !buShell || activeTab === "cases";
    const loadFeedback = !buShell || activeTab === "feedback";
    const loadGaps = !buShell || activeTab === "gaps";

    const [qualityLoopPanel, gapPanel, feedback, taxonomy] = await Promise.all([
      loadCases ? buildQualityLoopPanel() : Promise.resolve(null),
      loadGaps ? buildGapPanel() : Promise.resolve(null),
      loadFeedback ? api(`/api/feedback?${filters.toString()}`) : Promise.resolve(null),
      loadFeedback ? api("/api/taxonomy") : Promise.resolve(null),
    ]);

    const panel = el("section", "panel bu-feedback-surface");
    if (feedback) {
    panel.append(el("h2", "", "回饋與待觀察事件"));
    panel.append(
      el(
        "p",
        "metric-label",
        "先處理上方改善案件池；此處用來篩選負評／未解決／轉人工事件，並跳轉對話驗證。",
      ),
    );
    const shortcuts = el("div", "filter-bar");
    shortcuts.append(
      drillLink("修正文件", "knowledgePortal"),
      drillLink("修正 FAQ", "faq"),
      drillLink("案例集驗證", "examples"),
      drillLink("對話驗證", "conversations"),
    );
    panel.append(shortcuts);
    const filterBar = el("div", "filter-bar quality-filters");
    const filterField = (label, control, className = "") => {
      const field = el("label", `bu-filter-field ${className}`.trim());
      field.append(el("span", "", label), control);
      return field;
    };
    const issueInput = el("input");
    issueInput.id = "feedback-issue-type";
    issueInput.placeholder = "問題類型（顯示名稱或 ID）";
    issueInput.setAttribute("aria-label", "問題類型");
    issueInput.value = issueTypeId || "";
    const issueList = el("datalist");
    issueList.id = "feedback-issue-type-options";
    for (const item of taxonomy?.items || []) {
      const option = el("option");
      option.value = item.display_name || item.displayName || item.issue_type_id || item.issueTypeId || "";
      option.label = item.issue_type_id || item.issueTypeId || "";
      issueList.append(option);
      const idOption = el("option");
      idOption.value = item.issue_type_id || item.issueTypeId || "";
      idOption.label = item.display_name || item.displayName || "";
      issueList.append(idOption);
    }
    issueInput.setAttribute("list", issueList.id);
    const ratingSelect = el("select", "");
    ratingSelect.id = "feedback-rating";
    ratingSelect.setAttribute("aria-label", "評價");
    ratingSelect.innerHTML =
      '<option value="">全部評價</option><option value="UP">好評</option><option value="DOWN">負評</option>';
    if (rating) ratingSelect.value = rating;
    const reasonInput = el("input");
    reasonInput.id = "feedback-reason";
    reasonInput.placeholder = "回饋原因（關鍵字，採包含比對）";
    reasonInput.setAttribute("aria-label", "回饋原因");
    reasonInput.value = reason || "";
    const resolvedSelect = el("select", "");
    resolvedSelect.id = "feedback-resolved";
    resolvedSelect.setAttribute("aria-label", "解決狀態");
    resolvedSelect.innerHTML =
      '<option value="">全部解決狀態</option><option value="RESOLVED">已解決</option><option value="UNRESOLVED">未解決</option>';
    if (resolved) resolvedSelect.value = resolved;
    const handoffSelect = el("select", "");
    handoffSelect.id = "feedback-handoff";
    handoffSelect.setAttribute("aria-label", "轉人工");
    handoffSelect.innerHTML =
      '<option value="">全部轉人工</option><option value="true">有轉人工</option><option value="false">無轉人工</option>';
    if (handoff) handoffSelect.value = handoff;
    const routeSelect = el("select", "");
    routeSelect.id = "feedback-route";
    routeSelect.setAttribute("aria-label", "處理方式");
    routeSelect.innerHTML =
      '<option value="">全部處理方式</option><option value="FAQ">FAQ</option><option value="KNOWLEDGE">知識檢索 (RAG)</option><option value="DIRECT">直接回覆</option><option value="ESCALATE">轉人工</option>';
    if (route) routeSelect.value = route;
    const modelInput = el("input");
    modelInput.id = "feedback-model";
    modelInput.placeholder = "模型名稱";
    modelInput.setAttribute("aria-label", "模型");
    modelInput.value = model || "";
    const currentFilters = () => ({
      issueTypeId: issueInput.value.trim(),
      rating: ratingSelect.value,
      reason: reasonInput.value.trim(),
      resolved: resolvedSelect.value,
      handoff: handoffSelect.value,
      model: modelInput.value.trim(),
      route: routeSelect.value,
      ...(navFilters.returnTo ? { returnTo: navFilters.returnTo } : {}),
    });
    const applyFilters = el("button", buShell ? "button-secondary" : "", "套用篩選");
    applyFilters.addEventListener("click", () => {
      const nextPeriod = typeof periodControls?.readPeriod === "function"
        ? periodControls.readPeriod()
        : period;
      return renderQuality({
        period: nextPeriod,
        filters: currentFilters(),
        cursor: "",
        history: [],
        tab: "feedback",
      });
    });
    const exportButton = createExportButton("feedback", 30, () => ({
      issue_type_id: issueInput.value || undefined,
      rating: ratingSelect.value || undefined,
      feedback_reason: reasonInput.value || undefined,
      resolved_status: resolvedSelect.value || undefined,
      handoff: handoffSelect.value ? handoffSelect.value === "true" : undefined,
      model: modelInput.value || undefined,
      route: routeSelect.value || undefined,
      ...Object.fromEntries(periodParams(period)),
    }));
    if (buShell) {
      filterBar.append(
        filterField("問題類型", issueInput, "is-wide"),
        filterField("評價", ratingSelect),
        filterField("處理方式", routeSelect),
        filterField("模型", modelInput),
        filterField("回饋原因", reasonInput, "is-wide"),
        filterField("解決狀態", resolvedSelect),
        filterField("轉人工", handoffSelect),
      );
    } else {
      filterBar.append(
        issueInput,
        ratingSelect,
        routeSelect,
        modelInput,
        reasonInput,
        resolvedSelect,
        handoffSelect,
        applyFilters,
        exportButton,
      );
    }
    filterBar.append(issueList);
    const periodControls = createPeriodControls(period, (nextPeriod) =>
      renderQuality({
        period: nextPeriod,
        filters: currentFilters(),
        cursor: "",
        history: [],
        tab: "feedback",
      }),
      { hideApplyButton: buShell },
    );
    periodControls.classList.add("bu-period-controls");
    periodControls.prepend(el("span", "bu-filter-section-label", "期間"));
    if (buShell) {
      const filterSurface = el("div", "bu-filter-surface");
      filterSurface.append(filterBar, periodControls);
      const actionBar = el("div", "filter-bar bu-filter-actions-row");
      const actionGroup = el("div", "bu-filter-actions");
      actionGroup.append(applyFilters, exportButton);
      actionBar.append(actionGroup);
      filterSurface.append(actionBar);
      panel.append(filterSurface);
    } else {
      panel.append(filterBar, periodControls);
    }

    const ratingLabels = { UP: "好評", DOWN: "負評" };
    if (!feedback.items.length) {
      const empty = el("div", "empty bu-feedback-empty");
      empty.append(el("p", "", "目前沒有符合條件的回饋事件。"));
      empty.append(
        el(
          "p",
          "metric-label",
          "這表示篩選結果為空，不是讀取失敗。可放寬條件，或改用相同關鍵字／期間到對話紀錄查證。",
        ),
      );
      const jump = el("button", "button-primary", "改查對話紀錄（帶入關鍵字）");
      jump.type = "button";
      jump.addEventListener("click", () => {
        const keyword = issueInput.value.trim() || reasonInput.value.trim() || "";
        // Do not force hasFeedback=true: feedback empty often means no DOWN events yet;
        // forcing it empties conversation search (e.g. VPN) and blocks the fallback path.
        void navigateTo("conversations", {
          query: keyword,
          hasFeedback: "",
          preset: period.preset || "",
          start: period.start || "",
          end: period.end || "",
        });
      });
      const jumpFeedback = el("button", buShell ? "button-secondary" : "", "僅查有回饋的對話");
      jumpFeedback.type = "button";
      jumpFeedback.title = "會加上 hasFeedback=true；若結果為空可改用上方按鈕";
      jumpFeedback.addEventListener("click", () => {
        const keyword = issueInput.value.trim() || reasonInput.value.trim() || "";
        void navigateTo("conversations", {
          query: keyword,
          hasFeedback: "true",
          preset: period.preset || "",
          start: period.start || "",
          end: period.end || "",
        });
      });
      empty.append(jump, jumpFeedback);
      panel.append(empty);
    } else {
      const table = el("table");
      table.innerHTML =
        "<thead><tr><th>時間</th><th>評價</th><th>問題類型</th><th>來源</th><th>對話</th><th>原因</th><th>動作</th></tr></thead>";
      const body = el("tbody");
      for (const item of feedback.items) {
        const trace = item.trace || {};
        const source = trace.faqKey
          ? `FAQ：${trace.faqKey}`
          : (trace.sourceRefs || []).map((item) => item.title || item.documentId).join(", ")
            || (trace.documentIds || []).join(", ")
            || "-";
        const row = el("tr");
        row.append(el("td", "", formatTaipeiDateTime(item.occurredAt)));
        row.append(el("td", "", ratingLabels[item.rating] || item.rating));
        row.append(
          el(
            "td",
            "",
            trace.issueTypeDisplayName || trace.issueTypeId || String(item.issueId ?? "-"),
          ),
        );
        row.append(el("td", "", source));
        const convLink = el("a", "", "查看對話");
        convLink.href = "#";
        convLink.addEventListener("click", async (event) => {
          event.preventDefault();
          const returnFilters = {
            tab: "feedback",
            rating,
            issueTypeId: issueInput.value.trim(),
            reason: reasonInput.value.trim(),
            resolved: resolvedSelect.value,
            handoff: handoffSelect.value,
            model: modelInput.value.trim(),
            route: routeSelect.value,
            preset: period.preset || "",
            start: period.start || "",
            end: period.end || "",
          };
          void navigateTo(
            "conversations",
            withReturnTo(
              {
                conversationId: item.conversationId || "",
                turnId: item.turnId || trace.turnId || "",
              },
              "quality",
              returnFilters,
            ),
          );
        });
        const convCell = el("td");
        convCell.append(convLink);
        row.append(convCell);
        row.append(el("td", "", item.reason ?? "-"));
        const actionCell = el("td");
        actionCell.append(
          drillLink(
            "驗證回答",
            "conversations",
            withReturnTo(
              {
                conversationId: item.conversationId || "",
                turnId: item.turnId || trace.turnId || "",
                issueTypeId: trace.issueTypeId || "",
              },
              "quality",
              {
                tab: "feedback",
                rating,
                issueTypeId: issueInput.value.trim(),
                reason: reasonInput.value.trim(),
                resolved: resolvedSelect.value,
                handoff: handoffSelect.value,
                model: modelInput.value.trim(),
                route: routeSelect.value,
                preset: period.preset || "",
                start: period.start || "",
                end: period.end || "",
              },
            ),
          ),
        );
        row.append(actionCell);
        body.append(row);
      }
      table.append(body);
      const feedbackScroll = el("div", "table-responsive");
      feedbackScroll.append(table);
      panel.append(feedbackScroll);
    }
    const history = state.history || [];
    const pager = el("div", "filter-bar");
    if (history.length) {
      const previous = el("button", "", "上一頁");
      previous.addEventListener("click", () =>
        renderQuality({
          period,
          filters: currentFilters(),
          cursor: history.at(-1),
          history: history.slice(0, -1),
          tab: "feedback",
        }),
      );
      pager.append(previous);
    }
    if (feedback.nextCursor) {
      const next = el("button", "", "下一頁");
      next.addEventListener("click", () =>
        renderQuality({
          period,
          filters: currentFilters(),
          cursor: feedback.nextCursor,
          history: [...history, state.cursor || ""],
          tab: "feedback",
        }),
      );
      pager.append(next);
    }
    if (pager.childElementCount) panel.append(pager);
    }
    const exportPanel = el("section", "panel bu-export-panel");
    exportPanel.append(el("h3", "", "匯出營運摘要"));
    exportPanel.append(
      el("p", "metric-label", "匯出會留下稽核原因；不會改變案件或文件狀態。"),
    );
    const csvButton = el("button", buShell ? "button-secondary" : "", "建立 CSV 營運摘要匯出");
    csvButton.addEventListener("click", async () => {
      await runExport("csv");
    });
    const xlsxButton = el("button", buShell ? "button-secondary" : "", "建立 XLSX 營運摘要匯出");
    xlsxButton.addEventListener("click", async () => {
      await runExport("xlsx");
    });
    const exportActions = el("div", "bu-filter-actions");
    exportActions.append(csvButton, xlsxButton);
    exportPanel.append(exportActions);

    if (buShell) {
      const header = el("div", "bu-page-header");
      header.append(el("h2", "", "改善案件"));
      header.append(
        el("p", "metric-label", "將回饋轉成可追蹤的改善，直到驗證結果。"),
      );
      const tabs = el("div", "bu-quality-tabs");
      for (const [key, label] of [
        ["cases", "案件"],
        ["feedback", "回饋事件"],
        ["gaps", "知識缺口"],
      ]) {
        const button = el("button", key === activeTab ? "active" : "", label);
        button.type = "button";
        button.addEventListener("click", () => {
          const preserved = { ...loadNavFilters(), view: "quality", tab: key };
          saveNavFilters(preserved);
          syncLocationHash("quality", preserved);
          void renderQuality({ ...state, tab: key, cursor: "", history: [] });
        });
        tabs.append(button);
      }
      const bodyNodes = [];
      if (activeTab === "cases" && qualityLoopPanel) bodyNodes.push(qualityLoopPanel);
      if (activeTab === "feedback" && feedback) bodyNodes.push(panel);
      if (activeTab === "gaps" && gapPanel) bodyNodes.push(gapPanel);
      if (activeTab === "cases") bodyNodes.push(exportPanel);
      app.replaceChildren(header, tabs, ...bodyNodes);
      return;
    }

    app.replaceChildren(qualityLoopPanel, panel, gapPanel, exportPanel);
  } catch (error) {
    const isForbidden = error.message === "FORBIDDEN";
    const box = el("div", isForbidden ? "forbidden" : "error");
    box.append(el("p", "", formatUserFacingError(error)));
    if (isForbidden) {
      box.append(
        el(
          "p",
          "metric-label",
          "這是權限限制，不是「目前沒有案件」。若需要處理改善案件，請改用具備品質權限的角色。",
        ),
      );
    } else {
      const retry = el("button", "button-primary", "重試載入");
      retry.type = "button";
      retry.style.marginTop = "0.65rem";
      retry.addEventListener("click", () => {
        void renderQuality(state);
      });
      box.append(retry);
    }
    app.replaceChildren(box);
  }
}

export const qualityPage = createPageController({
  enter: async (context = {}) => renderQuality(context.state || {}),
  update: async (context = {}) => renderQuality(context.state || {}),
  leave: async () => {},
});
