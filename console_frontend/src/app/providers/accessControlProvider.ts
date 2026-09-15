import { AccessControlProvider } from '@refinedev/core';
import { authProvider } from './authProvider';

export const accessControlProvider: AccessControlProvider = {
  can: async ({ resource, action }) => {
    const permissions = (await authProvider.getPermissions?.()) as string[] || [];
    const caps = new Set(permissions);

    // Root SYSTEM_ADMIN has full access
    if (caps.has('ops.health.read') && caps.has('ops.config.read') && caps.has('ops.quality.resolve')) {
      return { can: true };
    }

    if (resource === 'work' || resource === 'work-items') {
      return { can: true };
    }

    if (resource === 'health' || resource === 'operations') {
      const allowed = caps.has('ops.health.read') || caps.has('ops.summary.read');
      return {
        can: allowed,
        reason: allowed ? undefined : '需要平台檢視或健康檢查權限',
      };
    }

    if (resource === 'improvements' || resource === 'quality_case' || resource === 'workflows/quality_case') {
      if (action === 'resolve' || action === 'close') {
        const allowed = caps.has('ops.quality.resolve');
        return {
          can: allowed,
          reason: allowed ? undefined : '需要結案審核權限 (ops.quality.resolve)',
        };
      }
      if (action === 'edit' || action === 'create') {
        const allowed = caps.has('ops.quality.write');
        return {
          can: allowed,
          reason: allowed ? undefined : '需要品質案件編輯權限 (ops.quality.write)',
        };
      }
      const allowed = caps.has('ops.quality.read');
      return {
        can: allowed,
        reason: allowed ? undefined : '需要品質案件檢視權限 (ops.quality.read)',
      };
    }

    if (resource === 'knowledge') {
      const allowed = caps.has('ops.knowledge.read') || caps.has('ops.faq.read');
      return {
        can: allowed,
        reason: allowed ? undefined : '需要知識營運檢視權限',
      };
    }

    if (resource === 'changes') {
      const allowed = caps.has('ops.evals.read') || caps.has('ops.prompts.read') || caps.has('ops.models.read');
      return {
        can: allowed,
        reason: allowed ? undefined : '需要變更管理與評測檢視權限',
      };
    }

    return { can: true };
  },
};
