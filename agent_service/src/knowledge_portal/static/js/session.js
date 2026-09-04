const DEMO_IDENTITY = {
  userId: "demo.admin",
  userName: "Demo 管理者",
  role: "PLATFORM",
};

const ALL_NAV = ["work", "knowledge", "reviews", "audit", "releases"];

function embedMode() {
  return Boolean(window.__AI_OPS_KNOWLEDGE_EMBED__);
}

function initialState() {
  if (embedMode() && window.__AI_OPS_EMBED_SESSION__) {
    return {
      ...window.__AI_OPS_EMBED_SESSION__,
      capabilities: {
        ...(window.__AI_OPS_EMBED_SESSION__.capabilities || {}),
      },
    };
  }
  return {
    demoMode: true,
    portalProfile: "DEMO",
    relaxedWorkflow: true,
    minTestCasesForReview: 0,
    homeRoute: "#/work",
    visibleNav: [...ALL_NAV],
    userId: DEMO_IDENTITY.userId,
    userName: DEMO_IDENTITY.userName,
    role: DEMO_IDENTITY.role,
    ownerUnits: "IT Service Desk",
    capabilities: {
      create_document: true,
      import_markdown: true,
      list_pending_reviews: true,
      decide_review: true,
      publish: true,
      list_releases: true,
      manage_releases: true,
      view_audit: true,
    },
  };
}

const state = initialState();

export function getSession() {
  return {
    ...state,
    capabilities: { ...state.capabilities },
  };
}

export function updateSession(patch) {
  Object.assign(state, patch);
  if (state.demoMode && !embedMode()) {
    state.role = DEMO_IDENTITY.role;
    state.visibleNav = [...ALL_NAV];
  }
}

export function visibleNavForRole(role) {
  const nav = ["work", "knowledge"];
  if (["REVIEWER", "MANAGER", "PLATFORM"].includes(role)) {
    nav.push("reviews");
  }
  if (["AUDITOR", "MANAGER", "PLATFORM"].includes(role)) {
    nav.push("audit");
  }
  if (["MANAGER", "PLATFORM"].includes(role)) {
    nav.push("releases");
  }
  return nav;
}

function backofficeAuthHeaders() {
  const raw = sessionStorage.getItem("ai_ops_backoffice_auth");
  if (!raw) {
    return {};
  }
  try {
    const stored = JSON.parse(raw);
    if (stored.bearerToken) {
      return { Authorization: `Bearer ${stored.bearerToken}` };
    }
    return {
      "X-Backoffice-User-Id": stored.userId || "",
      "X-Backoffice-User-Name": stored.userName || stored.userId || "",
      "X-Backoffice-Role": stored.role || "ANALYST",
      "X-Backoffice-Owner-Units": stored.ownerUnits || "",
      "X-Backoffice-Tenant-Id": stored.tenantId || "local-development",
    };
  } catch {
    return {};
  }
}

export function identityHeaders(includeJsonContentType = true) {
  // Embed mode: never send browser X-Portal-* identities; BFF adds delegation.
  if (embedMode()) {
    const headers = { ...backofficeAuthHeaders() };
    if (includeJsonContentType) {
      headers["Content-Type"] = "application/json";
    }
    return headers;
  }
  const headers = {
    "X-Portal-User-Id": state.userId.trim(),
    "X-Portal-User-Name": encodeURIComponent(state.userName.trim()),
    "X-Portal-Role": state.demoMode ? DEMO_IDENTITY.role : state.role,
    "X-Portal-Owner-Units": state.ownerUnits,
  };
  if (includeJsonContentType) {
    headers["Content-Type"] = "application/json";
  }
  return headers;
}

export function syncFromDashboard(dashboard) {
  state.relaxedWorkflow = dashboard.relaxed_workflow !== false;
  state.minTestCasesForReview = dashboard.min_test_cases_for_review ?? 0;
  if (embedMode()) {
    state.demoMode = false;
    state.portalProfile = dashboard.portal_profile || "INTEGRATED";
    state.homeRoute = dashboard.home_route || "#/work";
    state.visibleNav = dashboard.visible_nav || visibleNavForRole(state.role);
    if (dashboard.actor_role) {
      state.role = dashboard.actor_role;
    }
    if (dashboard.capabilities) {
      state.capabilities = dashboard.capabilities;
    }
    return;
  }
  state.demoMode = dashboard.demo_mode !== false;
  state.portalProfile = dashboard.portal_profile || "DEMO";
  state.homeRoute = dashboard.home_route || "#/work";
  if (state.demoMode) {
    state.role = DEMO_IDENTITY.role;
    state.visibleNav = [...ALL_NAV];
    state.capabilities = { ...state.capabilities };
    return;
  }
  state.visibleNav = dashboard.visible_nav || visibleNavForRole(state.role);
  if (dashboard.actor_role) {
    state.role = dashboard.actor_role;
  }
  if (dashboard.capabilities) {
    state.capabilities = dashboard.capabilities;
  }
}
