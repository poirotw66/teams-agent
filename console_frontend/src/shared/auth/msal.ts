/** Microsoft Entra (MSAL) browser auth for console-v2. */

import {
  BrowserCacheLocation,
  InteractionRequiredAuthError,
  PublicClientApplication,
  type AccountInfo,
  type AuthenticationResult,
  type Configuration,
} from '@azure/msal-browser';
import { clearAuthSession, loadAuthSession, saveAuthSession } from './session';

export interface EntraPublicConfig {
  tenantId: string;
  clientId: string;
  scopes?: string[];
  redirectUri?: string;
}

let pca: PublicClientApplication | null = null;
let initPromise: Promise<PublicClientApplication> | null = null;
let activeConfig: EntraPublicConfig | null = null;

function defaultScopes(clientId: string, configured?: string[]): string[] {
  if (configured && configured.length > 0) {
    return configured;
  }
  return [`${clientId}/.default`, 'openid', 'profile', 'email'];
}

function buildConfig(config: EntraPublicConfig): Configuration {
  const redirectUri =
    config.redirectUri ||
    `${window.location.origin}/console-v2/login`;
  return {
    auth: {
      clientId: config.clientId,
      authority: `https://login.microsoftonline.com/${config.tenantId}`,
      redirectUri,
      postLogoutRedirectUri: redirectUri,
      navigateToLoginRequestUrl: false,
    },
    cache: {
      cacheLocation: BrowserCacheLocation.SessionStorage,
      storeAuthStateInCookie: false,
    },
  };
}

export async function ensureMsal(config: EntraPublicConfig): Promise<PublicClientApplication> {
  if (
    pca &&
    activeConfig &&
    activeConfig.clientId === config.clientId &&
    activeConfig.tenantId === config.tenantId
  ) {
    return pca;
  }
  if (initPromise) {
    return initPromise;
  }
  activeConfig = config;
  initPromise = (async () => {
    const instance = new PublicClientApplication(buildConfig(config));
    await instance.initialize();
    pca = instance;
    return instance;
  })();
  try {
    return await initPromise;
  } finally {
    initPromise = null;
  }
}

function primaryAccount(instance: PublicClientApplication): AccountInfo | null {
  const accounts = instance.getAllAccounts();
  return accounts[0] || null;
}

function persistAccessToken(result: AuthenticationResult): void {
  if (!result.accessToken) {
    return;
  }
  saveAuthSession({
    ...loadAuthSession(),
    bearerToken: result.accessToken,
  });
}

export async function handleRedirectPromise(
  config: EntraPublicConfig,
): Promise<AuthenticationResult | null> {
  const instance = await ensureMsal(config);
  const result = await instance.handleRedirectPromise();
  if (result) {
    persistAccessToken(result);
  }
  return result;
}

export async function loginWithRedirect(config: EntraPublicConfig): Promise<void> {
  const instance = await ensureMsal(config);
  await instance.loginRedirect({
    scopes: defaultScopes(config.clientId, config.scopes),
    prompt: 'select_account',
  });
}

export async function logoutWithRedirect(config: EntraPublicConfig | null): Promise<void> {
  clearAuthSession();
  if (!config?.clientId || !config.tenantId) {
    return;
  }
  const instance = await ensureMsal(config);
  const account = primaryAccount(instance);
  await instance.logoutRedirect({
    account: account || undefined,
  });
}

export async function acquireEntraAccessToken(
  config: EntraPublicConfig,
): Promise<string | null> {
  const instance = await ensureMsal(config);
  const account = primaryAccount(instance);
  if (!account) {
    return loadAuthSession().bearerToken || null;
  }
  const scopes = defaultScopes(config.clientId, config.scopes);
  try {
    const result = await instance.acquireTokenSilent({ account, scopes });
    persistAccessToken(result);
    return result.accessToken;
  } catch (error) {
    if (error instanceof InteractionRequiredAuthError) {
      await instance.acquireTokenRedirect({ account, scopes });
      return null;
    }
    throw error;
  }
}
