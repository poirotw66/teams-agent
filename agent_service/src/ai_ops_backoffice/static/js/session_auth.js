/**
 * Shared session auth helpers for same-origin Backoffice HTML surfaces.
 * Compatible with the React console AUTH_STORAGE_KEY contract.
 * Product paths must not import /static/legacy-js/.
 */

export const AUTH_STORAGE_KEY = "ai_ops_backoffice_auth";

export function loadAuthHeaders() {
  const raw = sessionStorage.getItem(AUTH_STORAGE_KEY);
  if (!raw) {
    return {};
  }
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

export function saveAuthHeaders(headers) {
  sessionStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(headers || {}));
}

export function clearAuthHeaders() {
  sessionStorage.removeItem(AUTH_STORAGE_KEY);
}

export function authHeaders() {
  const stored = loadAuthHeaders();
  if (stored.bearerToken) {
    return { Authorization: `Bearer ${stored.bearerToken}` };
  }
  return {
    "X-Backoffice-User-Id": stored.userId || "ops.admin",
    "X-Backoffice-User-Name": stored.userName || "System Administrator",
    "X-Backoffice-Role": stored.role || "SYSTEM_ADMIN",
    "X-Backoffice-Owner-Units": stored.ownerUnits || "IT Service Desk",
    "X-Backoffice-Tenant-Id": stored.tenantId || "default",
    "X-Backoffice-Groups": stored.groups || "grp_public",
  };
}

/**
 * Ensure a session exists for HEADER auth, or send Entra users to console-v2 login.
 */
export async function ensureAuth(authConfig) {
  const mode = String(authConfig?.authMode || "HEADER").toUpperCase();
  if (mode === "ENTRA") {
    const stored = loadAuthHeaders();
    if (stored.bearerToken) {
      return stored;
    }
    const redirect = encodeURIComponent(
      `${window.location.pathname}${window.location.search}${window.location.hash}`,
    );
    window.location.assign(`/console-v2/login?redirect=${redirect}`);
    throw new Error("UNAUTHORIZED");
  }
  if (authConfig?.headerAuthAllowed === false) {
    throw new Error("UNAUTHORIZED");
  }
  const stored = loadAuthHeaders();
  if (stored.userId || stored.bearerToken) {
    return stored;
  }
  const defaults = {
    userId: "ops.admin",
    userName: "System Administrator",
    role: "SYSTEM_ADMIN",
    ownerUnits: "IT Service Desk",
  };
  saveAuthHeaders(defaults);
  return defaults;
}
