import { DataProvider } from '@refinedev/core';
import { apiClient } from '../../shared/api/client';
import { WorkItemsResponse, WorkflowDetailResponse } from '../../shared/api/types';

export const dataProvider: DataProvider = {
  getList: async ({ resource, pagination, filters }) => {
    if (resource === 'work-items') {
      const bucketFilter = filters?.find((f) => 'field' in f && f.field === 'bucket');
      const bucket = bucketFilter && 'value' in bucketFilter ? String(bucketFilter.value) : 'all';
      const pageSize = pagination?.pageSize || 25;

      const cursorFilter = filters?.find((f) => 'field' in f && f.field === 'cursor');
      const cursor = cursorFilter && 'value' in cursorFilter ? String(cursorFilter.value) : '';

      const queryParams = new URLSearchParams({
        bucket,
        limit: String(pageSize),
      });
      if (cursor) {
        queryParams.set('cursor', cursor);
      }

      const res = await apiClient<WorkItemsResponse>(`/api/console/work-items?${queryParams.toString()}`);
      return {
        data: res.items as unknown as any[],
        total: res.total,
        meta: {
          next_cursor: res.next_cursor,
          snapshot_id: res.snapshot_id,
          partial: res.partial,
          sources: res.sources,
        },
      };
    }

    if (resource === 'health') {
      const res = await apiClient<any>('/api/operations/health');
      const componentsList = Object.entries(res.components || {}).map(([key, value]) => ({
        id: key,
        name: key,
        ...(value as object),
      }));
      return {
        data: componentsList,
        total: componentsList.length,
      };
    }

    const res = await apiClient<any>(`/api/${resource}`);
    const items = Array.isArray(res) ? res : res.items || [];
    return {
      data: items,
      total: typeof res.total === 'number' ? res.total : items.length,
    };
  },

  getOne: async ({ resource, id }) => {
    if (resource === 'workflows/quality_case') {
      const res = await apiClient<WorkflowDetailResponse>(`/api/console/workflows/quality_case/${id}`);
      return { data: res as unknown as any };
    }
    const res = await apiClient<any>(`/api/${resource}/${id}`);
    return { data: res };
  },

  create: async ({ resource, variables }) => {
    const res = await apiClient<any>(`/api/${resource}`, {
      method: 'POST',
      body: JSON.stringify(variables),
    });
    return { data: res };
  },

  update: async ({ resource, id, variables }) => {
    const res = await apiClient<any>(`/api/${resource}/${id}`, {
      method: 'PUT',
      body: JSON.stringify(variables),
    });
    return { data: res };
  },

  deleteOne: async ({ resource, id }) => {
    const res = await apiClient<any>(`/api/${resource}/${id}`, {
      method: 'DELETE',
    });
    return { data: res };
  },

  getApiUrl: () => '/api',

  custom: async ({ url, method, payload }) => {
    const res = await apiClient<any>(url, {
      method: method || 'GET',
      body: payload ? JSON.stringify(payload) : undefined,
    });
    return { data: res };
  },
};
