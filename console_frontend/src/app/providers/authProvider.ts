import { AuthProvider } from '@refinedev/core';
import { apiClient } from '../../shared/api/client';

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

  login: async () => {
    return {
      success: true,
      redirectTo: '/console-v2/work',
    };
  },

  logout: async () => {
    cachedSession = null;
    return {
      success: true,
      redirectTo: '/',
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
