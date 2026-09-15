/** Session storage compatible with the legacy console auth key. */

export const AUTH_STORAGE_KEY = 'ai_ops_backoffice_auth';

export interface AuthSession {
  bearerToken?: string;
  userId?: string;
  userName?: string;
  role?: string;
  ownerUnits?: string;
  tenantId?: string;
  groups?: string;
}

export function loadAuthSession(): AuthSession {
  const raw = sessionStorage.getItem(AUTH_STORAGE_KEY);
  if (!raw) {
    return {};
  }
  try {
    const parsed = JSON.parse(raw) as AuthSession;
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

export function saveAuthSession(session: AuthSession): void {
  sessionStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session));
}

export function clearAuthSession(): void {
  sessionStorage.removeItem(AUTH_STORAGE_KEY);
}

export function authRequestHeaders(): Record<string, string> {
  const stored = loadAuthSession();
  if (stored.bearerToken) {
    return { Authorization: `Bearer ${stored.bearerToken}` };
  }
  if (stored.userId) {
    return {
      'X-Backoffice-User-Id': stored.userId,
      'X-Backoffice-User-Name': stored.userName || stored.userId,
      'X-Backoffice-Role': stored.role || 'SYSTEM_ADMIN',
      'X-Backoffice-Owner-Units': stored.ownerUnits || 'IT Service Desk',
      'X-Backoffice-Tenant-Id': stored.tenantId || 'default',
      'X-Backoffice-Groups': stored.groups || 'grp_public',
    };
  }
  return {};
}
