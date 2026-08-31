import { loadFluentComponents } from "./fluent.js";
import { api } from "./api.js";
import { ROLE_LABELS } from "./labels.js";
import { applyDemoPersona, getSession, syncFromDashboard, updateSession } from "./session.js";
import { navigate, startRouter } from "./router.js";
import { escapeHtml, renderViewForbidden } from "./ui.js?v=20260831c";
import { renderAuditView } from "./views/audit.js";
import { renderCreateView } from "./views/create.js";
import { renderDocumentDetailView } from "./views/document-detail.js";
import { renderKnowledgeListView } from "./views/knowledge-list.js";
import { renderReleasesView } from "./views/releases.js";
import { renderReviewsView } from "./views/reviews.js";
import { renderWorkView } from "./views/work.js";

function renderIdentityShell() {
  const session = getSession();
  const chip = document.getElementById("identityChip");
  const demoBanner = document.getElementById("demoBanner");
  const demoControls = document.getElementById("demoControls");
  const profileBadge = document.getElementById("profileBadge");

  if (demoBanner) {
    demoBanner.classList.toggle("hidden", !session.demoMode);
    demoBanner.textContent = session.demoMode
      ? `DEMO MODE · ${session.portalProfile === "GOVERNED" ? "治理設定" : "簡化流程"}`
      : "";
  }
  if (profileBadge) {
    profileBadge.textContent = session.portalProfile === "GOVERNED" ? "正式環境" : "Demo 環境";
  }
  if (chip) {
    chip.innerHTML = `
      <div class="identity-chip">
        <strong>${escapeHtml(session.userName)}</strong>
        <span>${escapeHtml(ROLE_LABELS[session.role] || session.role)} · ${escapeHtml(session.ownerUnits)}</span>
      </div>`;
  }
  if (demoControls) {
    demoControls.classList.toggle("hidden", !session.demoMode);
    const body = demoControls.querySelector(".demo-controls-body") || demoControls;
    if (session.demoMode) {
      body.innerHTML = `
        <label>
          Demo 角色
          <select id="demoRole">
            ${Object.entries(ROLE_LABELS).slice(0, 4).map(([value, label]) => `
              <option value="${value}" ${session.role === value ? "selected" : ""}>${label}</option>`).join("")}
          </select>
        </label>
        <label>
          使用者 ID
          <input id="demoUserId" value="${escapeHtml(session.userId)}">
        </label>
        <label>
          顯示名稱
          <input id="demoUserName" value="${escapeHtml(session.userName)}">
        </label>
        <button type="button" class="btn secondary btn-sm" id="applyDemoIdentity">套用身分</button>`;
      body.querySelector("#demoRole")?.addEventListener("change", (event) => {
        applyDemoPersona(event.target.value);
        renderIdentityShell();
        applyNavVisibility();
      });
      body.querySelector("#applyDemoIdentity")?.addEventListener("click", () => {
        updateSession({
          userId: body.querySelector("#demoUserId").value.trim(),
          userName: body.querySelector("#demoUserName").value.trim(),
          role: body.querySelector("#demoRole").value,
        });
        renderIdentityShell();
        navigate(window.location.hash || "#/work");
      });
    }
  }
}

function applyNavVisibility() {
  const visible = new Set(getSession().visibleNav || []);
  document.querySelectorAll("[data-nav-item]").forEach((node) => {
    node.classList.toggle("hidden", !visible.has(node.dataset.navItem));
  });
}

function setActiveNav(segments) {
  const root = segments[0] || "work";
  document.querySelectorAll("[data-nav]").forEach((node) => {
    const target = node.getAttribute("data-nav")?.replace("#/", "") || "work";
    const active = target === root;
    node.classList.toggle("active", active);
    node.setAttribute("aria-current", active ? "page" : "false");
    node.setAttribute("appearance", active ? "accent" : "stealth");
  });
}

async function renderRoute({ segments, query, app }) {
  setActiveNav(segments);
  if (segments[0] === "work" || segments.length === 0) {
    const dashboard = await renderWorkView(app);
    syncFromDashboard(dashboard);
    renderIdentityShell();
    applyNavVisibility();
    return;
  }
  if (segments[0] === "knowledge" && segments[1] === "new") {
    await renderCreateView(app);
    return;
  }
  if (segments[0] === "knowledge" && segments[1]) {
    const tab = segments[2] || "overview";
    await renderDocumentDetailView(app, segments[1], tab);
    return;
  }
  if (segments[0] === "knowledge") {
    await renderKnowledgeListView(app, query);
    return;
  }
  if (segments[0] === "reviews") {
    await renderReviewsView(app);
    return;
  }
  if (segments[0] === "audit") {
    if (!getSession().visibleNav?.includes("audit")) {
      app.innerHTML = `
        <section class="page">
          <header class="page-header"><h2>稽核紀錄</h2></header>
          ${renderViewForbidden("audit")}
        </section>`;
      app.querySelector("[data-route]")?.addEventListener("click", (event) => {
        navigate(event.currentTarget.dataset.route);
      });
      return;
    }
    await renderAuditView(app);
    return;
  }
  if (segments[0] === "releases") {
    if (!getSession().visibleNav?.includes("releases")) {
      app.innerHTML = `
        <section class="page">
          <header class="page-header"><h2>發布紀錄</h2></header>
          ${renderViewForbidden("audit")}
        </section>`;
      return;
    }
    await renderReleasesView(app);
    return;
  }
  navigate("#/work");
}

async function bootstrap() {
  await loadFluentComponents();
  document.querySelector(".skip-link")?.addEventListener("click", () => {
    requestAnimationFrame(() => document.getElementById("app")?.focus());
  });
  document.querySelectorAll("[data-nav]").forEach((node) => {
    node.addEventListener("click", () => navigate(node.dataset.nav));
  });
  try {
    const dashboard = await api("/api/dashboard");
    syncFromDashboard(dashboard);
    renderIdentityShell();
    applyNavVisibility();
  } catch {
    renderIdentityShell();
    applyNavVisibility();
  }
  startRouter(async (context) => {
    await renderRoute(context);
  });
  if (!window.location.hash) {
    navigate(getSession().homeRoute || "#/work");
  }
}

bootstrap();
