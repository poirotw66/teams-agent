import { api, revokeAssetPreviewUrls } from "../../api.js";
import { clearDirtyChecker, registerDirtyChecker } from "../../dirty-state.js";
import { navigate } from "../../router.js";
import {
  escapeHtml,
  handleViewError,
  isForbiddenError,
  renderError,
  renderSkeleton,
  renderStatusBadge,
  renderViewForbidden,
} from "../../ui.js?v=20260831e";
import { hydrateAssetPreviews, loadTestData } from "./data.js";
import { captureDraftBaseline, isDraftEditorDirty } from "./editor-state.js";
import { getVisibleTabs, renderActionPanel } from "./shared.js";
import { renderContentTab } from "./tabs/content.js";
import { renderOverviewTab } from "./tabs/overview.js";
import { renderReviewTab } from "./tabs/review.js";
import { renderTestsTab } from "./tabs/tests.js";
import { renderVersionsTab } from "./tabs/versions.js";
import { wireActions } from "./wiring.js";
import { focusPendingTab, wireTabList } from "./tabs.js";

function renderTabContent(tab, documentId, detail, cases, runsByCase) {
  if (tab === "overview") return renderOverviewTab(detail);
  if (tab === "review") return renderReviewTab(detail, cases, runsByCase);
  if (tab === "content") return renderContentTab(documentId, detail, detail.draft_version);
  if (tab === "tests") return renderTestsTab(cases, runsByCase, detail);
  if (tab === "versions") return renderVersionsTab(detail);
  return "";
}

export async function renderDocumentDetailView(app, documentId, tab = "overview", query = new URLSearchParams()) {
  revokeAssetPreviewUrls();
  clearDirtyChecker();
  const caseId = query?.get("caseId") || "";
  const backCaseHtml = caseId
    ? `<button type="button" class="btn text" data-back-case style="font-weight: 600; color: #0f6cbd; margin-right: 0.5rem;">← 返回品質案件 (${escapeHtml(caseId)})</button>`
    : "";
  app.innerHTML = `
    <section class="page detail-page">
      <header class="page-header">
        <div>
          ${backCaseHtml}
          <button type="button" class="btn text" data-back>← 返回知識庫</button>
          <div id="detailHeader">${renderSkeleton(1)}</div>
        </div>
      </header>
      <div class="detail-layout">
        <div class="detail-main">
          <nav id="detailTabs" class="tab-nav" role="tablist" aria-label="文件分頁"></nav>
          <div id="detailTabContent" role="tabpanel" aria-live="polite" tabindex="0">${renderSkeleton(3)}</div>
        </div>
        <div id="detailActionPanel"></div>
      </div>
    </section>`;

  if (caseId) {
    app.querySelector("[data-back-case]")?.addEventListener("click", () => {
      if (window.__navigateCase) {
        window.__navigateCase(caseId);
      } else if (window.parent && window.parent !== window) {
        window.parent.postMessage({ type: "NAVIGATE_CASE", caseId }, "*");
      } else {
        window.location.hash = `#/knowledge_ops/quality?caseId=${encodeURIComponent(caseId)}`;
      }
    });
  }
  app.querySelector("[data-back]")?.addEventListener("click", () => navigate("#/knowledge"));

  try {
    const detail = await api(`/api/documents/${documentId}`);
    const visibleTabs = getVisibleTabs(detail);
    if (!visibleTabs.some((item) => item.id === tab)) {
      tab = "overview";
    }

    const refresh = () => renderDocumentDetailView(app, documentId, tab, query);

    app.querySelector("#detailTabs").innerHTML = visibleTabs.map((item) => `
      <button
        type="button"
        class="tab ${item.id === tab ? "active" : ""}"
        role="tab"
        id="tab-${item.id}"
        aria-selected="${item.id === tab ? "true" : "false"}"
        aria-controls="detailTabContent"
        data-tab="${item.id}"
      >${item.label}</button>`).join("");

    const tabNav = app.querySelector("#detailTabs");
    wireTabList(tabNav, documentId, tab);
    focusPendingTab();

    const tabPanel = app.querySelector("#detailTabContent");
    tabPanel.id = "detailTabContent";
    tabPanel.setAttribute("aria-labelledby", `tab-${tab}`);

    app.querySelector("#detailHeader").innerHTML = `
      <h2>${escapeHtml(detail.document.title)}</h2>
      <p>${renderStatusBadge(detail.document.status, detail.status_label)}</p>`;
    app.querySelector("#detailActionPanel").innerHTML = renderActionPanel(detail);

    let cases = [];
    let runsByCase = {};
    if ((tab === "tests" || tab === "review") && detail.draft_version) {
      ({ cases, runsByCase } = await loadTestData(documentId, detail));
    }

    app.querySelector("#detailTabContent").innerHTML = renderTabContent(
      tab,
      documentId,
      detail,
      cases,
      runsByCase,
    );

    wireActions(app, documentId, detail, refresh);
    if (tab === "content") {
      captureDraftBaseline();
      registerDirtyChecker(isDraftEditorDirty);
      if (detail.draft_assets?.items?.length) {
        await hydrateAssetPreviews(documentId, detail.draft_assets.items);
      }
    } else {
      clearDirtyChecker();
    }
  } catch (error) {
    if (isForbiddenError(error)) {
      app.querySelector("#detailTabContent").innerHTML = renderViewForbidden("document");
      app.querySelector("#detailActionPanel").innerHTML = "";
      app.querySelector("#detailTabContent [data-route]")?.addEventListener("click", (event) => {
        navigate(event.currentTarget.dataset.route);
      });
      return;
    }
    if (error.status === 404) {
      app.querySelector("#detailTabContent").innerHTML = renderError("找不到這份文件。");
      return;
    }
    handleViewError(error, {
      view: "document",
      container: app.querySelector("#detailTabContent"),
      onRetry: () => renderDocumentDetailView(app, documentId, tab),
    });
  }
}
