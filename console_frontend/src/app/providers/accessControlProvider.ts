import { AccessControlProvider } from '@refinedev/core';
import { authProvider } from './authProvider';
import { evaluateResourceAccess } from '../routing/routeRegistry';

export const accessControlProvider: AccessControlProvider = {
  can: async ({ resource, action }) => {
    const permissions =
      ((await authProvider.getPermissions?.()) as string[] | undefined) || [];
    return evaluateResourceAccess({
      resource,
      action,
      capabilities: permissions,
    });
  },
};
