/** HTTP client for AI Ops Backoffice APIs */

import { authRequestHeaders } from '../auth/session';

export class ApiError extends Error {
  status: number;
  data: unknown;

  constructor(message: string, status: number, data?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

export async function apiClient<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;

  const headers = new Headers(options.headers || {});
  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }
  for (const [name, value] of Object.entries(authRequestHeaders())) {
    if (!headers.has(name)) {
      headers.set(name, value);
    }
  }

  // Same-origin cookies plus explicit Bearer / HEADER actor identity.
  const response = await fetch(url, {
    ...options,
    headers,
    credentials: 'same-origin',
  });

  if (!response.ok) {
    let errorDetail = response.statusText;
    let data: unknown = null;
    try {
      data = await response.json();
      if (data && typeof data === 'object') {
        const payload = data as {
          detail?: unknown;
          error?: { message?: unknown; code?: unknown };
          message?: unknown;
        };
        if (typeof payload.error?.message === 'string' && payload.error.message.trim()) {
          errorDetail = payload.error.message;
        } else if (typeof payload.detail === 'string' && payload.detail.trim()) {
          errorDetail = payload.detail;
        } else if (payload.detail != null) {
          errorDetail = String(payload.detail);
        } else if (typeof payload.message === 'string' && payload.message.trim()) {
          errorDetail = payload.message;
        }
      }
    } catch {
      // Non-JSON error response
    }
    throw new ApiError(errorDetail, response.status, data);
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return {} as T;
  }

  return response.json() as Promise<T>;
}
