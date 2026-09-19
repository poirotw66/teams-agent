import { afterEach, describe, expect, it } from 'vitest';
import {
  AUTH_STORAGE_KEY,
  authRequestHeaders,
  clearAuthSession,
  loadAuthSession,
  saveAuthSession,
} from './session';

describe('auth session helpers', () => {
  afterEach(() => {
    sessionStorage.clear();
  });

  it('round-trips a saved session through loadAuthSession', () => {
    saveAuthSession({
      bearerToken: 'token-1',
      userId: 'u-1',
      userName: 'Ada',
      role: 'SYSTEM_ADMIN',
    });

    expect(sessionStorage.getItem(AUTH_STORAGE_KEY)).toBeTruthy();
    expect(loadAuthSession()).toEqual({
      bearerToken: 'token-1',
      userId: 'u-1',
      userName: 'Ada',
      role: 'SYSTEM_ADMIN',
    });
  });

  it('prefers bearer Authorization headers when a token is present', () => {
    saveAuthSession({ bearerToken: 'secret-token' });
    expect(authRequestHeaders()).toEqual({
      Authorization: 'Bearer secret-token',
    });
  });

  it('falls back to header-auth identity fields without a bearer token', () => {
    saveAuthSession({
      userId: 'ops-1',
      userName: 'Ops',
      role: 'OPERATOR',
      ownerUnits: 'IT',
      tenantId: 't1',
      groups: 'g1',
    });
    expect(authRequestHeaders()).toMatchObject({
      'X-Backoffice-User-Id': 'ops-1',
      'X-Backoffice-User-Name': 'Ops',
      'X-Backoffice-Role': 'OPERATOR',
    });
  });

  it('clears the session storage key', () => {
    saveAuthSession({ userId: 'x' });
    clearAuthSession();
    expect(loadAuthSession()).toEqual({});
    expect(sessionStorage.getItem(AUTH_STORAGE_KEY)).toBeNull();
  });
});
