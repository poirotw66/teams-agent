import { api, el } from "../../api.js";
import { attributionCell } from "../../components/badges.js";
import {
  emptyState,
  formatCount,
  formatPercent,
  kpiStrip,
  pageHeader,
  routeBadge,
} from "../../components/analyticsUi.js";
import { createPeriodControls } from "../../components/period.js";
import { createExportButton } from "../../services/export.js";
import { drillLink, navigateTo } from "../../app/navigation.js";
import { showConversationModal } from "../../components/conversationModal.js";
import { showToast } from "../../components/modal.js";
import { withReturnTo } from "../../app/returnTo.js";
import { periodLabel, periodToNavFilters } from "./issueActions.js";

export function renderIssueRouteDrill(data, period, query, onPeriodChange) {
  const panel = el("section", "panel");
  const back = drillLink("← 返回問題總覽", "issues", { clear: true });
  panel.append(
    pageHeader(
      `${data.displayName || data.issueTypeId}｜問題分析詳情`,
      `代碼：${data.issueTypeId}｜權責單位：${data.ownerUnitId || "未指定"}｜期間：${periodLabel(period)}`,
      back,
    ),
  );

  const toolbar = el("div", "analytics-toolbar");
  if (onPeriodChange) {
    toolbar.append(createPeriodControls(period, (next) => onPeriodChange({ ...next, query })));
  }
  toolbar.append(
    createExportButton("routes_summary", period, {
      issue_type_id: data.issueTypeId,
    }),
  );
  panel.append(toolbar);

  const totalCount = data.totalCount || 0;
  const negCount = data.negativeFeedbackCount || 0;
  const handoffCount = data.handoffCount || 0;
  const noAnsCount = data.noAnswerCount || 0;

  const negRate = totalCount > 0 ? formatPercent(negCount / totalCount) : "0%";
  const handoffRate = totalCount > 0 ? formatPercent(handoffCount / totalCount) : "0%";

  panel.append(
    kpiStrip([
      { label: "出現次數", value: formatCount(totalCount) },
      {
        label: "負評次數",
        value: negCount > 0 ? `${formatCount(negCount)} 筆 (${negRate})` : "尚無負評",
      },
      {
        label: "轉人工客服",
        value: `${formatCount(handoffCount)} 次 (${handoffRate})`,
      },
      { label: "未能回答", value: formatCount(noAnsCount) },
    ]),
  );

  if (data.description) {
    const descCard = el("div", "content-guide");
    descCard.style.margin = "0.75rem 0 1.25rem";
    descCard.innerHTML = `<strong>問題說明：</strong> ${data.description}`;
    panel.append(descCard);
  }

  // 1. 處理方式 (Route Distribution)
  const secRoutes = el("section", "analytics-section");
  secRoutes.style.marginBottom = "1.5rem";
  const routeTitle = el("div", "analytics-section-title");
  routeTitle.append(
    el("h3", "", "處理方式（AI 處置分流分布）"),
    el("span", "metric-label", "AI 如何處理此問題：FAQ、知識檢索 HYBRID、轉真人客服 HANDOFF 等"),
  );
  secRoutes.append(routeTitle);

  const routes = data.routes || [];
  if (!routes.length) {
    secRoutes.append(
      emptyState(
        "此問題在選定期間尚無分流紀錄",
        "可拉長查詢期間，或至對話驗證確認是否已有 issue.extracted 與 route.selected 事件。",
      ),
    );
  } else {
    const routeTable = el("table");
    routeTable.innerHTML = `
      <thead>
        <tr>
          <th>處理方式 (Route)</th>
          <th>次數</th>
          <th>佔比</th>
          <th>回答依據（FAQ／知識庫文件）</th>
        </tr>
      </thead>
    `;
    const tbody = el("tbody");
    for (const rt of routes) {
      const row = el("tr");
      const rtCell = el("td");
      rtCell.append(routeBadge(rt.route));
      row.append(rtCell);
      row.append(el("td", "", formatCount(rt.count)));
      const sharePct = totalCount > 0 ? formatPercent(rt.count / totalCount) : "-";
      row.append(el("td", "", sharePct));
      row.append(attributionCell(rt.attribution, { issueTypeId: data.issueTypeId }));
      tbody.append(row);
    }
    routeTable.append(tbody);
    const wrap = el("div", "table-responsive");
    wrap.append(routeTable);
    secRoutes.append(wrap);
  }
  panel.append(secRoutes);

  // 2. 回答依據與知識文件 (Knowledge Sources & FAQ Keys)
  const allDocIds = new Set();
  const allSourcePaths = new Set();
  const allFaqKeys = new Set();
  for (const rt of routes) {
    const attr = rt.attribution || {};
    (attr.documentIds || []).forEach((item) => item.id && allDocIds.add(item.id));
    (attr.sourcePaths || []).forEach((item) => item.id && allSourcePaths.add(item.id));
    (attr.faqKeys || []).forEach((item) => item.id && allFaqKeys.add(item.id));
  }

  const secSources = el("section", "analytics-section");
  secSources.style.marginBottom = "1.5rem";
  const srcTitle = el("div", "analytics-section-title");
  srcTitle.append(
    el("h3", "", "回答依據與知識文件（改善入口）"),
    el("span", "metric-label", "AI 回答此問題時引用的知識庫文件或 FAQ 項目，可快速檢視或修訂"),
  );
  secSources.append(srcTitle);

  const sourcesBox = el("div");
  sourcesBox.style.padding = "0.85rem 1rem";
  sourcesBox.style.background = "var(--panel-muted, #f8fafc)";
  sourcesBox.style.border = "1px solid var(--border-subtle, #e2e8f0)";
  sourcesBox.style.borderRadius = "var(--radius-sm, 8px)";

  if (!allDocIds.size && !allSourcePaths.size && !allFaqKeys.size) {
    sourcesBox.append(el("p", "empty", "未引用具體文件或 FAQ（可能多由對話模型直接回覆或直接轉人工）。"));
  } else {
    if (allSourcePaths.size || allDocIds.size) {
      const docGroup = el("div");
      docGroup.style.marginBottom = "0.75rem";
      const docHeading = el("div", "", "📚 引用的知識庫文件：");
      docHeading.style.fontWeight = "600";
      docHeading.style.marginBottom = "0.35rem";
      docGroup.append(docHeading);

      const list = el("ul");
      list.style.margin = "0";
      list.style.paddingLeft = "1.25rem";

      const combinedDocs = Array.from(allSourcePaths.size ? allSourcePaths : allDocIds);
      for (const doc of combinedDocs) {
        const li = el("li");
        li.style.marginBottom = "0.35rem";
        li.append(el("span", "analytics-mono", doc));
        li.append(document.createTextNode(" "));

        const actionBtn = el("button", "btn-secondary btn-small", "📄 前往知識庫檢視／修訂");
        actionBtn.style.fontSize = "0.75rem";
        actionBtn.style.padding = "0.15rem 0.5rem";
        actionBtn.style.marginLeft = "0.5rem";
        actionBtn.addEventListener("click", () => {
          navigateTo("knowledge", { query: doc });
        });
        li.append(actionBtn);
        list.append(li);
      }
      docGroup.append(list);
      sourcesBox.append(docGroup);
    }

    if (allFaqKeys.size) {
      const faqGroup = el("div");
      const faqHeading = el("div", "", "❓ 引用的 FAQ 項目：");
      faqHeading.style.fontWeight = "600";
      faqHeading.style.marginBottom = "0.35rem";
      faqGroup.append(faqHeading);

      const list = el("ul");
      list.style.margin = "0";
      list.style.paddingLeft = "1.25rem";
      for (const key of allFaqKeys) {
        const li = el("li");
        li.style.marginBottom = "0.35rem";
        li.append(el("span", "analytics-mono", key));
        li.append(document.createTextNode(" "));

        const actionBtn = el("button", "btn-secondary btn-small", "❓ 前往 FAQ 編輯");
        actionBtn.style.fontSize = "0.75rem";
        actionBtn.style.padding = "0.15rem 0.5rem";
        actionBtn.style.marginLeft = "0.5rem";
        actionBtn.addEventListener("click", () => {
          navigateTo("faq", { query: key });
        });
        li.append(actionBtn);
        list.append(li);
      }
      faqGroup.append(list);
      sourcesBox.append(faqGroup);
    }
  }
  secSources.append(sourcesBox);
  panel.append(secSources);

  // 3. 使用者負評紀錄
  const secFeedback = el("section", "analytics-section");
  secFeedback.style.marginBottom = "1.5rem";
  const fbTitle = el("div", "analytics-section-title");
  fbTitle.append(
    el("h3", "", `使用者負評紀錄 (${negCount} 筆)`),
    el("span", "metric-label", "查看使用者對此問題回答的不滿原因與上下文，協助確認需補充之知識"),
  );
  secFeedback.append(fbTitle);

  const feedbacks = data.negativeFeedbacks || [];
  if (!feedbacks.length) {
    secFeedback.append(el("p", "empty", "選定期間內尚無負評紀錄。"));
  } else {
    const fbList = el("div");
    fbList.style.display = "flex";
    fbList.style.flexDirection = "column";
    fbList.style.gap = "0.75rem";

    for (const fb of feedbacks) {
      const item = el("div");
      item.style.padding = "0.75rem 1rem";
      item.style.borderLeft = "4px solid var(--text-danger, #ef4444)";
      item.style.background = "var(--panel-muted, #f8fafc)";
      item.style.borderRadius = "4px";

      const topRow = el("div");
      topRow.style.display = "flex";
      topRow.style.justifyContent = "space-between";
      topRow.style.fontSize = "0.8rem";
      topRow.style.color = "var(--text-muted, #64748b)";

      topRow.append(
        el("span", "", `時間：${fb.occurredAt ? fb.occurredAt.replace("T", " ").slice(0, 19) : "-"}`),
        fb.resolvedStatus ? el("span", "badge badge-neutral", fb.resolvedStatus) : el("span"),
      );
      item.append(topRow);

      const reasonRow = el("div");
      reasonRow.style.marginTop = "0.35rem";
      reasonRow.style.fontSize = "0.9rem";
      reasonRow.style.fontWeight = "600";
      reasonRow.style.color = "var(--text-danger, #b91c1c)";
      reasonRow.textContent = `❌ 負評原因：${fb.reason || "未填寫原因"}`;
      item.append(reasonRow);

      if (fb.userMessage) {
        const uMsg = el("div");
        uMsg.style.fontSize = "0.85rem";
        uMsg.style.marginTop = "0.25rem";
        uMsg.innerHTML = `<span style="color:var(--text-muted);">提問：</span> ${fb.userMessage}`;
        item.append(uMsg);
      }

      if (fb.aiReply) {
        const aReply = el("div");
        aReply.style.fontSize = "0.85rem";
        aReply.style.marginTop = "0.2rem";
        aReply.innerHTML = `<span style="color:var(--text-muted);">回覆：</span> ${fb.aiReply.slice(0, 140)}${fb.aiReply.length > 140 ? "…" : ""}`;
        item.append(aReply);
      }

      if (fb.conversationId) {
        const viewConvBtn = el("button", "button-link", "🔍 查看該筆對話");
        viewConvBtn.style.fontSize = "0.75rem";
        viewConvBtn.style.marginTop = "0.4rem";
        viewConvBtn.addEventListener("click", async () => {
          try {
            const detail = await api(`/api/conversations/${encodeURIComponent(fb.conversationId)}`);
            showConversationModal(detail, fb.conversationId);
          } catch (err) {
            showToast(`無法載入對話：${err.message}`, { tone: "error" });
          }
        });
        item.append(viewConvBtn);
      }

      fbList.append(item);
    }
    secFeedback.append(fbList);
  }
  panel.append(secFeedback);

  // 4. Action Footer
  const footer = el("div", "filter-bar");
  footer.style.marginTop = "1.5rem";
  footer.style.paddingTop = "1rem";
  footer.style.borderTop = "1px solid var(--border-subtle, #e2e8f0)";
  footer.style.display = "flex";
  footer.style.justifyContent = "space-between";
  footer.style.alignItems = "center";

  const leftActions = el("div");
  leftActions.style.display = "flex";
  leftActions.style.gap = "0.6rem";
  leftActions.style.flexWrap = "wrap";

  leftActions.append(
    drillLink(
      `💬 查看相關對話 (${formatCount(totalCount)} 筆)`,
      "conversations",
      withReturnTo(
        {
          issueTypeId: data.issueTypeId,
          ...periodToNavFilters(period),
        },
        "issues",
        {
          issueTypeId: data.issueTypeId,
          ...periodToNavFilters(period),
        },
      ),
    ),
  );

  if (negCount > 0) {
    leftActions.append(
      drillLink(
        `⚠️ 前往品質案件處理 (${formatCount(negCount)} 筆負評)`,
        "quality",
        withReturnTo(
          {
            rating: "DOWN",
            issueTypeId: data.issueTypeId,
            ...periodToNavFilters(period),
          },
          "issues",
          {
            issueTypeId: data.issueTypeId,
            ...periodToNavFilters(period),
          },
        ),
      ),
    );
  }

  footer.append(leftActions, back);
  panel.append(footer);
  return panel;
}
