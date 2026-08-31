const DEMO_PERSONAS = {
  CONTRIBUTOR: { userId: "contributor.demo", userName: "知識貢獻者" },
  REVIEWER: { userId: "reviewer.demo", userName: "知識審核者" },
  MANAGER: { userId: "manager.demo", userName: "知識管理者" },
  PLATFORM: { userId: "platform.demo", userName: "平台管理者" },
};

const state = {
  demoMode: true,
  portalProfile: "DEMO",
  relaxedWorkflow: true,
  minTestCasesForReview: 0,
  homeRoute: "#/work",
  visibleNav: ["work", "knowledge", "reviews", "audit"],
  userId: "manager.demo",
  userName: "知識管理者",
  role: "MANAGER",
  ownerUnits: "IT Service Desk",
};

export function getSession() {
  return { ...state };
}

export function updateSession(patch) {
  Object.assign(state, patch);
}

export function visibleNavForRole(role) {
  const nav = ["work", "knowledge"];
  if (["REVIEWER", "MANAGER", "PLATFORM"].includes(role)) {
    nav.push("reviews");
  }
  if (["AUDITOR", "MANAGER", "PLATFORM"].includes(role)) {
    nav.push("audit");
  }
  return nav;
}

export function applyDemoPersona(role) {
  const persona = DEMO_PERSONAS[role];
  if (!persona) return;
  state.userId = persona.userId;
  state.userName = persona.userName;
  state.role = role;
  state.visibleNav = visibleNavForRole(role);
}

export function identityHeaders(includeJsonContentType = true) {
  const headers = {
    "X-Portal-User-Id": state.userId.trim(),
    "X-Portal-User-Name": encodeURIComponent(state.userName.trim()),
    "X-Portal-Role": state.role,
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
  state.visibleNav = dashboard.visible_nav || visibleNavForRole(state.role);
  if (dashboard.actor_role) {
    state.role = dashboard.actor_role;
  }
}
