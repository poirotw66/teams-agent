/** Shared helpers for console mutation error messaging. */

import { ApiError } from './client';

export function describeMutationError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    const detail = error.message.trim();
    if (detail) {
      return detail;
    }
    return `${fallback}（HTTP ${error.status}）`;
  }
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return fallback;
}

/** Ant Design Form.validateFields rejects with an object that has `errorFields`. */
export function isFormValidationError(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'errorFields' in error &&
    Array.isArray((error as { errorFields: unknown }).errorFields)
  );
}
