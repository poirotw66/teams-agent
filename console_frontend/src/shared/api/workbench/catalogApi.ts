/** Service catalog Portal API client (BFF `/api/knowledge/catalog*`). */

import { apiClient } from '../client';

export type CatalogServiceRow = {
  serviceId: string;
  officialName?: string | null;
  aliases?: string[];
  documentId: string;
  versionId?: string | null;
  sourcePath?: string | null;
  aclGroups?: string[];
  ownerUnitId?: string | null;
};

export type CatalogDraft = {
  schemaVersion?: number;
  releaseId?: string;
  tenantId?: string;
  status?: string;
  services?: CatalogServiceRow[];
  updatedAt?: string | null;
  updatedBy?: string | null;
  reason?: string | null;
};

export type CatalogGetResponse = {
  draft: CatalogDraft | null;
  governance?: string;
  remainingGaps?: string[];
};

export type CatalogMutationResponse = {
  draft: CatalogDraft;
};

export async function fetchCatalogDraft(): Promise<CatalogGetResponse> {
  return apiClient<CatalogGetResponse>('/api/knowledge/catalog');
}

export async function saveCatalogDraft(
  services: CatalogServiceRow[],
): Promise<CatalogMutationResponse> {
  return apiClient<CatalogMutationResponse>('/api/knowledge/catalog/draft', {
    method: 'PUT',
    body: JSON.stringify({ services }),
  });
}

export async function submitCatalogReview(
  reason?: string,
): Promise<CatalogMutationResponse> {
  return apiClient<CatalogMutationResponse>('/api/knowledge/catalog/submit-review', {
    method: 'POST',
    body: JSON.stringify({ reason: reason || null }),
  });
}

export async function approveCatalog(
  reason?: string,
): Promise<CatalogMutationResponse> {
  return apiClient<CatalogMutationResponse>('/api/knowledge/catalog/approve', {
    method: 'POST',
    body: JSON.stringify({ reason: reason || null }),
  });
}

export async function rejectCatalog(
  reason?: string,
): Promise<CatalogMutationResponse> {
  return apiClient<CatalogMutationResponse>('/api/knowledge/catalog/reject', {
    method: 'POST',
    body: JSON.stringify({ reason: reason || null }),
  });
}
