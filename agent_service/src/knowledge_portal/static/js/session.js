const DEMO_IDENTITY = {
  userId: "demo.admin",
  userName: "Demo 管理者",
  role: "PLATFORM",
};

const ALL_NAV = ["work", "knowledge", "reviews", "audit", "releases"];

const state = {
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
};

export function getSession() {
  return { ...state };
}

export function updateSession(patch) {
  Object.assign(state, patch);
  if (state.demoMode) {
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

export function identityHeaders(includeJsonContentType = true) {
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
  state.demoMode = dashboard.demo_mode !== false;
  state.portalProfile = dashboard.portal_profile || "DEMO";
  state.homeRoute = dashboard.home_route || "#/work";
  if (state.demoMode) {
    state.role = DEMO_IDENTITY.role;
    state.visibleNav = [...ALL_NAV];
    return;
  }
  state.visibleNav = dashboard.visible_nav || visibleNavForRole(state.role);
  if (dashboard.actor_role) {
    state.role = dashboard.actor_role;
  }
}
