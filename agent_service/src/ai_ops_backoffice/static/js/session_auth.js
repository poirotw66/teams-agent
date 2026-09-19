/**
 * Shared session auth helpers for same-origin Backoffice HTML surfaces.
 * Compatible with the React console AUTH_STORAGE_KEY contract.
 * Product paths must not import /static/legacy-js/.
 */

export const AUTH_STORAGE_KEY = "ai_ops_backoffice_auth";

let expiryTimer = null;

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

export function parseJwt(token) {
  if (!token || typeof token !== "string") return null;
  try {
    const parts = token.trim().split(".");
    if (parts.length < 2) return null;
    const base64Url = parts[1];
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    const decoded = new TextDecoder().decode(bytes);
    return JSON.parse(decoded);
  } catch {
    return null;
  }
}

export function isTokenExpired(token, bufferSeconds = 10) {
  const payload = parseJwt(token);
  if (!payload || typeof payload.exp !== "number") return false;
  return payload.exp * 1000 <= Date.now() + bufferSeconds * 1000;
}

export function getTokenExpiryDetails(token) {
  const payload = parseJwt(token);
  if (!payload || typeof payload.exp !== "number") return null;
  const expiryDate = new Date(payload.exp * 1000);
  const remainingMs = expiryDate.getTime() - Date.now();
  const isExpired = remainingMs <= 0;
  return {
    expiryDate,
    remainingMs,
    isExpired,
    formatted: expiryDate.toLocaleTimeString("zh-TW", {
      hour: "2-digit",
      minute: "2-digit",
    }),
    name:
      payload.name ||
      payload.preferred_username ||
      payload.upn ||
      payload.sub ||
      "Entra 使用者",
    upn: payload.preferred_username || payload.upn || payload.email || "",
    roles: Array.isArray(payload.roles)
      ? payload.roles
      : payload.roles
        ? [payload.roles]
        : [],
  };
}

export function scheduleExpiryWatcher(token, onExpiredCallback) {
  if (expiryTimer) {
    clearTimeout(expiryTimer);
    expiryTimer = null;
  }
  const details = getTokenExpiryDetails(token);
  if (!details) return;
  if (details.isExpired) {
    if (typeof onExpiredCallback === "function") {
      onExpiredCallback();
    } else if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("backoffice:token-expired"));
    }
    return;
  }
  expiryTimer = setTimeout(() => {
    if (typeof onExpiredCallback === "function") {
      onExpiredCallback();
    } else if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("backoffice:token-expired"));
    }
  }, Math.max(1000, details.remainingMs));
}

export function clearExpiryWatcher() {
  if (expiryTimer) {
    clearTimeout(expiryTimer);
    expiryTimer = null;
  }
}

export function logout() {
  clearAuthHeaders();
  clearExpiryWatcher();
  if (typeof window !== "undefined") {
    window.location.reload();
  }
}

/**
 * Ensure a session exists for HEADER auth, or send Entra users to console-v2 login.
 */
export async function ensureAuth(authConfig) {
  const mode = String(authConfig?.authMode || "HEADER").toUpperCase();
  if (mode === "ENTRA") {
    const stored = loadAuthHeaders();
    if (stored.bearerToken && !isTokenExpired(stored.bearerToken)) {
      scheduleExpiryWatcher(stored.bearerToken);
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
