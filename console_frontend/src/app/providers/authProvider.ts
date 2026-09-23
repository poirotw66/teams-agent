import { AuthProvider } from '@refinedev/core';
import { apiClient, ApiError } from '../../shared/api/client';
import { logoutWithRedirect, type EntraPublicConfig } from '../../shared/auth/msal';
import {
  clearAuthSession,
  loadAuthSession,
  saveAuthSession,
} from '../../shared/auth/session';
import { workbenchStore } from '../../shared/api/workbenchStore';

let lastEntraConfig: EntraPublicConfig | null = null;

export interface UserSession {
  userId: string;
  userName: string;
  displayName: string;
  role: string;
  capabilities: string[];
  /** Portal knowledge RBAC caps from `/api/capabilities` (merged into getPermissions). */
  knowledgeCapabilities?: string[];
  ownerUnitIds: string[];
  authMode?: string;
  relaxedWorkflow?: boolean;
  knowledgeWorkspaceMode?: string;
  cloudFormalWritesAllowed?: boolean;
  cloudFormalWriteBlockReasons?: string[];
  cloudFormalWriteBlockReasonLabels?: string[];
  knowledgeWorkspaceSwitchAllowed?: boolean;
  knowledgeWorkspaceOverrideActive?: boolean;
  knowledgeWorkspaceModeSource?: string;
}

function mergedSessionCapabilities(session: UserSession): string[] {
  const ops = session.capabilities || [];
  const knowledge = session.knowledgeCapabilities || [];
  return Array.from(new Set([...ops, ...knowledge]));
}

let cachedSession: UserSession | null = null;

function clearIdentityBoundState(): void {
  cachedSession = null;
  workbenchStore.resetForIdentityChange();
}

function resolveErrorStatus(error: unknown): number | undefined {
  if (error instanceof ApiError) {
    return error.status;
  }
  if (typeof error === 'object' && error !== null && 'status' in error) {
    const status = (error as { status?: unknown }).status;
    return typeof status === 'number' ? status : undefined;
  }
  return undefined;
}

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

export const authProvider: AuthProvider = {
  check: async () => {
    try {
      const res = await apiClient<UserSession>('/api/capabilities');
      cachedSession = res;
      return {
        authenticated: true,
      };
    } catch {
      clearIdentityBoundState();
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
    // Drop prior identity-bound server state before adopting a new session.
    clearIdentityBoundState();
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
      clearIdentityBoundState();
      return {
        success: false,
        redirectTo: '/console-v2/login',
        error: new Error('登入失敗，請確認憑證後再試'),
      };
    }
  },

  logout: async () => {
    clearIdentityBoundState();
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
    const status = resolveErrorStatus(error);
    if (status === 401) {
      clearIdentityBoundState();
      return {
        logout: true,
        redirectTo: '/console-v2/login',
        error: new Error('憑證已失效，請重新登入'),
      };
    }
    if (status === 403) {
      // Keep the session; the caller stays on the page with a permission error.
      return {
        error: new Error('目前身分沒有執行此操作的權限'),
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
      authMode: cachedSession.authMode,
      relaxedWorkflow: cachedSession.relaxedWorkflow,
      knowledgeWorkspaceMode: cachedSession.knowledgeWorkspaceMode,
      cloudFormalWritesAllowed: cachedSession.cloudFormalWritesAllowed,
      cloudFormalWriteBlockReasons: cachedSession.cloudFormalWriteBlockReasons,
      cloudFormalWriteBlockReasonLabels: cachedSession.cloudFormalWriteBlockReasonLabels,
      knowledgeWorkspaceSwitchAllowed: cachedSession.knowledgeWorkspaceSwitchAllowed,
      knowledgeWorkspaceOverrideActive: cachedSession.knowledgeWorkspaceOverrideActive,
      knowledgeWorkspaceModeSource: cachedSession.knowledgeWorkspaceModeSource,
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
    return mergedSessionCapabilities(cachedSession);
  },
};

/** Reload `/api/capabilities` into the session cache (e.g. after workspace switch). */
export async function refreshCachedSession(): Promise<UserSession> {
  cachedSession = await apiClient<UserSession>('/api/capabilities');
  return cachedSession;
}
