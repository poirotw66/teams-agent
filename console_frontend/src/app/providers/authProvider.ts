import { AuthProvider } from '@refinedev/core';
import { apiClient } from '../../shared/api/client';
import { logoutWithRedirect, type EntraPublicConfig } from '../../shared/auth/msal';
import {
  clearAuthSession,
  loadAuthSession,
  saveAuthSession,
} from '../../shared/auth/session';

let lastEntraConfig: EntraPublicConfig | null = null;

async function loadEntraPublicConfig(): Promise<EntraPublicConfig | null> {
  try {
    const config = await apiClient<{
      entraTenantId?: string | null;
      entraClientId?: string | null;
      entraScopes?: string[] | null;
      loginRedirectUri?: string | null;
    }>('/api/auth/config');
    const tenantId = String(config.entraTenantId || '').trim();
    const clientId = String(config.entraClientId || '').trim();
    if (!tenantId || !clientId) {
      return null;
    }
    const next: EntraPublicConfig = {
      tenantId,
      clientId,
      scopes: Array.isArray(config.entraScopes)
        ? config.entraScopes.filter((item): item is string => typeof item === 'string' && !!item)
        : undefined,
      redirectUri: config.loginRedirectUri || undefined,
    };
    lastEntraConfig = next;
    return next;
  } catch {
    return lastEntraConfig;
  }
}

export interface UserSession {
  userId: string;
  userName: string;
  displayName: string;
  role: string;
  capabilities: string[];
  ownerUnitIds: string[];
}

let cachedSession: UserSession | null = null;

export const authProvider: AuthProvider = {
  check: async () => {
    try {
      const res = await apiClient<UserSession>('/api/capabilities');
      cachedSession = res;
      return {
        authenticated: true,
      };
    } catch {
      cachedSession = null;
      return {
        authenticated: false,
        redirectTo: '/console-v2/login',
        error: new Error('尚未通過身分驗證'),
      };
    }
  },

  login: async (params) => {
    const payload = (params || {}) as {
      accessToken?: string;
      redirectPath?: string;
    };
    if (payload.accessToken) {
      saveAuthSession({
        ...loadAuthSession(),
        bearerToken: payload.accessToken.trim(),
      });
    }
    try {
      cachedSession = await apiClient<UserSession>('/api/capabilities');
      return {
        success: true,
        redirectTo: payload.redirectPath || '/console-v2/work',
      };
    } catch {
      return {
        success: false,
        redirectTo: '/console-v2/login',
        error: new Error('登入失敗，請確認憑證後再試'),
      };
    }
  },

  logout: async () => {
    cachedSession = null;
    const entra = await loadEntraPublicConfig();
    clearAuthSession();
    if (entra) {
      try {
        await logoutWithRedirect(entra);
        return { success: true };
      } catch {
        // Fall through to local redirect when MSAL logout is unavailable.
      }
    }
    return {
      success: true,
      redirectTo: '/console-v2/login',
    };
  },

  onError: async (error) => {
    if (error?.status === 401 || error?.status === 403) {
      return {
        logout: true,
        redirectTo: '/console-v2/login',
        error: new Error('存取受限或憑證已失效'),
      };
    }
    return { error };
  },

  getIdentity: async () => {
    if (!cachedSession) {
      try {
        cachedSession = await apiClient<UserSession>('/api/capabilities');
      } catch {
        return null;
      }
    }
    return {
      id: cachedSession.userId,
      name: cachedSession.displayName || cachedSession.userName,
      role: cachedSession.role,
      ownerUnits: cachedSession.ownerUnitIds,
    };
  },

  getPermissions: async () => {
    if (!cachedSession) {
      try {
        cachedSession = await apiClient<UserSession>('/api/capabilities');
      } catch {
        return [];
      }
    }
    return cachedSession.capabilities || [];
  },
};
