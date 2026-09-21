/**
 * Single source of truth for console routes, navigation metadata, and
 * required read capabilities. Keep App resources, Header nav, and access
 * control aligned with this registry.
 */

export type NavGroupId =
  | 'work'
  | 'knowledge'
  | 'quality'
  | 'operations'
  | 'governance';

export type ConsoleRouteDefinition = {
  id: string;
  path: string;
  label: string;
  /** Refine resource name used by access control. */
  resource: string;
  navGroup: NavGroupId;
  /** Capability any-of for page read access. Empty means unmapped (deny). */
  readCapabilities: readonly string[];
  /** Show in the primary Header menu. */
  showInPrimaryNav?: boolean;
  /** Path prefixes that should keep this nav item selected. */
  activePathPrefixes?: readonly string[];
  /** Legacy aliases that redirect to this path. */
  aliases?: readonly string[];
};

export const CONSOLE_ROUTES: readonly ConsoleRouteDefinition[] = [
  {
    id: 'dashboard',
    path: '/dashboard',
    label: '營運儀表板',
    resource: 'dashboard',
    navGroup: 'work',
    readCapabilities: ['ops.summary.read', 'ops.health.read'],
    showInPrimaryNav: true,
    aliases: ['/work'],
  },
  {
    id: 'triage',
    path: '/triage',
    label: '對話與分診',
    resource: 'triage',
    navGroup: 'work',
    readCapabilities: ['ops.conversations.read', 'ops.quality.read'],
    showInPrimaryNav: true,
    activePathPrefixes: ['/triage', '/improvements'],
    aliases: ['/improvements', '/improvements/cases'],
  },
  {
    id: 'case-detail',
    path: '/improvements/cases/:id',
    label: '品質案件詳情',
    resource: 'quality_case',
    navGroup: 'work',
    readCapabilities: ['ops.quality.read'],
    activePathPrefixes: ['/improvements/cases'],
  },
  {
    id: 'knowledge',
    path: '/knowledge',
    label: '知識庫與手冊',
    resource: 'knowledge',
    navGroup: 'knowledge',
    readCapabilities: ['ops.knowledge.read', 'ops.faq.read', 'knowledge.read'],
    showInPrimaryNav: true,
    activePathPrefixes: ['/knowledge'],
  },
  {
    id: 'knowledge-reviews',
    path: '/knowledge/reviews',
    label: '知識審核',
    resource: 'knowledge-reviews',
    navGroup: 'knowledge',
    readCapabilities: ['knowledge.review', 'ops.knowledge.read'],
  },
  {
    id: 'knowledge-releases',
    path: '/knowledge/releases',
    label: '知識 Release',
    resource: 'knowledge-releases',
    navGroup: 'knowledge',
    readCapabilities: ['knowledge.publish', 'ops.knowledge.read'],
  },
  {
    id: 'knowledge-sync',
    path: '/knowledge/sync',
    label: '知識 Sync',
    resource: 'knowledge-sync',
    navGroup: 'knowledge',
    readCapabilities: ['ops.sync.read', 'ops.knowledge.read'],
  },
  {
    id: 'knowledge-analytics',
    path: '/knowledge/analytics',
    label: '知識成效',
    resource: 'knowledge-analytics',
    navGroup: 'knowledge',
    readCapabilities: ['ops.knowledge.read', 'ops.summary.read'],
  },
  {
    id: 'knowledge-audit',
    path: '/knowledge/audit',
    label: '知識稽核',
    resource: 'knowledge-audit',
    navGroup: 'knowledge',
    readCapabilities: ['knowledge.audit.read', 'ops.audit.read'],
  },
  {
    id: 'tickets',
    path: '/tickets',
    label: 'IT 工單追蹤',
    resource: 'tickets',
    navGroup: 'work',
    readCapabilities: ['ops.conversations.read', 'ops.quality.read'],
    showInPrimaryNav: true,
  },
  {
    id: 'evaluations',
    path: '/ai/evaluations',
    label: '評測執行',
    resource: 'evaluations',
    navGroup: 'quality',
    readCapabilities: ['ops.evals.read'],
    aliases: ['/ai/evals'],
  },
  {
    id: 'examples',
    path: '/ai/examples',
    label: 'Examples',
    resource: 'examples',
    navGroup: 'quality',
    readCapabilities: ['ops.examples.read'],
  },
  {
    id: 'prompts',
    path: '/ai/prompts',
    label: 'Prompts',
    resource: 'prompts',
    navGroup: 'quality',
    readCapabilities: ['ops.prompts.read'],
  },
  {
    id: 'models',
    path: '/ai/models',
    label: '模型設定',
    resource: 'models',
    navGroup: 'governance',
    readCapabilities: ['ops.models.read'],
  },
  {
    id: 'flags',
    path: '/ai/flags',
    label: 'Feature Flags',
    resource: 'flags',
    navGroup: 'governance',
    readCapabilities: ['ops.flags.read'],
  },
  {
    id: 'health',
    path: '/operations/health',
    label: '系統健康',
    resource: 'health',
    navGroup: 'operations',
    readCapabilities: ['ops.health.read', 'ops.summary.read'],
    showInPrimaryNav: true,
  },
  {
    id: 'issues',
    path: '/operations/issues',
    label: '議題摘要',
    resource: 'issues',
    navGroup: 'operations',
    readCapabilities: ['ops.issues.read', 'ops.summary.read'],
  },
  {
    id: 'routes',
    path: '/operations/routes',
    label: '路由摘要',
    resource: 'routes',
    navGroup: 'operations',
    readCapabilities: ['ops.summary.read'],
  },
  {
    id: 'costs',
    path: '/operations/costs',
    label: '成本摘要',
    resource: 'costs',
    navGroup: 'operations',
    readCapabilities: ['ops.cost.read'],
  },
  {
    id: 'budgets',
    path: '/operations/budgets',
    label: '預算政策',
    resource: 'budgets',
    navGroup: 'operations',
    readCapabilities: ['ops.budget.read'],
  },
  {
    id: 'search',
    path: '/operations/search',
    label: '跨實體搜尋',
    resource: 'search',
    navGroup: 'operations',
    readCapabilities: ['ops.search.read'],
  },
  {
    id: 'roles',
    path: '/governance/roles',
    label: '角色權限',
    resource: 'roles',
    navGroup: 'governance',
    readCapabilities: ['ops.roles.read'],
  },
  {
    id: 'retention',
    path: '/governance/retention',
    label: '保存政策',
    resource: 'retention',
    navGroup: 'governance',
    readCapabilities: ['ops.retention.read'],
  },
  {
    id: 'masking',
    path: '/governance/masking',
    label: '脫敏遮罩',
    resource: 'masking',
    navGroup: 'governance',
    readCapabilities: ['ops.config.read'],
  },
  {
    id: 'audit',
    path: '/governance/audit',
    label: '治理稽核',
    resource: 'audit',
    navGroup: 'governance',
    readCapabilities: ['ops.audit.read'],
  },
] as const;

/** Write actions that are not page-level resources. */
export const CONSOLE_WRITE_ACTIONS: Readonly<
  Record<string, { resource: string; action: string; capabilities: readonly string[] }>
> = {
  faqWrite: {
    resource: 'knowledge',
    action: 'create',
    capabilities: ['ops.faq.write', 'knowledge.create', 'knowledge.edit'],
  },
  broadcastWrite: {
    resource: 'dashboard',
    action: 'edit',
    capabilities: ['ops.alerts.manage'],
  },
  conversationResolve: {
    resource: 'triage',
    action: 'resolve',
    capabilities: ['ops.quality.resolve'],
  },
  conversationRootCause: {
    resource: 'triage',
    action: 'edit',
    capabilities: ['ops.quality.write'],
  },
  qualityCaseEdit: {
    resource: 'quality_case',
    action: 'edit',
    capabilities: ['ops.quality.write'],
  },
  qualityCaseCreate: {
    resource: 'quality_case',
    action: 'create',
    capabilities: ['ops.quality.write'],
  },
  qualityCaseResolve: {
    resource: 'quality_case',
    action: 'resolve',
    capabilities: ['ops.quality.resolve'],
  },
  qualityCaseClose: {
    resource: 'quality_case',
    action: 'close',
    capabilities: ['ops.quality.resolve'],
  },
  goldenEvalCreate: {
    resource: 'evaluations',
    action: 'create',
    capabilities: ['ops.evals.write'],
  },
  ticketEscalate: {
    resource: 'tickets',
    action: 'create',
    capabilities: ['ops.quality.write'],
  },
};

export function listPrimaryNavRoutes(): ConsoleRouteDefinition[] {
  return CONSOLE_ROUTES.filter((route) => route.showInPrimaryNav);
}

export const NAV_GROUP_LABELS: Record<NavGroupId, string> = {
  work: '我的工作／分診',
  knowledge: '知識內容',
  quality: '品質驗收',
  operations: '營運分析',
  governance: '系統管理',
};

/** Secondary routes for overflow / grouped navigation (excludes primary strip). */
export function listSecondaryNavRoutes(): ConsoleRouteDefinition[] {
  return CONSOLE_ROUTES.filter(
    (route) => !route.showInPrimaryNav && !route.path.includes(':'),
  );
}

export function buildGroupedOverflowNavItems(): Array<{
  groupId: NavGroupId;
  groupLabel: string;
  routes: ConsoleRouteDefinition[];
}> {
  const groups: NavGroupId[] = [
    'work',
    'knowledge',
    'quality',
    'operations',
    'governance',
  ];
  return groups
    .map((groupId) => ({
      groupId,
      groupLabel: NAV_GROUP_LABELS[groupId],
      routes: listSecondaryNavRoutes().filter((route) => route.navGroup === groupId),
    }))
    .filter((group) => group.routes.length > 0);
}

export function resolveSelectedMenuKeys(pathname: string): string[] {
  const primary = resolvePrimaryNavKey(pathname);
  const exactSecondary = listSecondaryNavRoutes().find(
    (route) => pathname === route.path || pathname.startsWith(`${route.path}/`),
  );
  if (exactSecondary) {
    return [exactSecondary.path, `group:${exactSecondary.navGroup}`];
  }
  return [primary];
}

export function toRefineResources(): Array<{
  name: string;
  list: string;
  meta: { label: string };
}> {
  const seen = new Set<string>();
  const resources: Array<{ name: string; list: string; meta: { label: string } }> = [];
  for (const route of CONSOLE_ROUTES) {
    if (seen.has(route.resource)) {
      continue;
    }
    if (route.path.includes(':')) {
      continue;
    }
    seen.add(route.resource);
    resources.push({
      name: route.resource,
      list: route.path,
      meta: { label: route.label },
    });
  }
  return resources;
}

export function findRouteByResource(resource: string): ConsoleRouteDefinition | undefined {
  return CONSOLE_ROUTES.find((route) => route.resource === resource);
}

export function resolvePrimaryNavKey(pathname: string): string {
  for (const route of listPrimaryNavRoutes()) {
    const prefixes = route.activePathPrefixes || [route.path];
    if (prefixes.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))) {
      return route.path;
    }
  }
  const exact = listPrimaryNavRoutes().find((route) => route.path === pathname);
  return exact?.path || '/dashboard';
}

export function hasAnyCapability(
  granted: Iterable<string>,
  required: readonly string[],
): boolean {
  if (required.length === 0) {
    return false;
  }
  const caps = granted instanceof Set ? granted : new Set(granted);
  return required.some((capability) => caps.has(capability));
}

export function evaluateResourceAccess(params: {
  resource?: string;
  action?: string;
  capabilities: Iterable<string>;
}): { can: boolean; reason?: string } {
  const resource = String(params.resource || '').trim();
  const action = String(params.action || 'list').trim();
  const caps = params.capabilities instanceof Set
    ? params.capabilities
    : new Set(params.capabilities);

  if (!resource) {
    return { can: false, reason: '未指定資源，預設拒絕存取' };
  }

  // Explicit write-action aliases used by global buttons.
  for (const writeAction of Object.values(CONSOLE_WRITE_ACTIONS)) {
    if (writeAction.resource === resource && writeAction.action === action) {
      const allowed = hasAnyCapability(caps, writeAction.capabilities);
      return {
        can: allowed,
        reason: allowed
          ? undefined
          : `需要寫入能力：${writeAction.capabilities.join(' 或 ')}`,
      };
    }
  }

  const route = findRouteByResource(resource);
  if (!route) {
    if (import.meta.env.DEV) {
      console.warn(`[access] unmapped resource denied: ${resource}:${action}`);
    }
    return {
      can: false,
      reason: `未映射資源「${resource}」已拒絕（fail closed）`,
    };
  }

  if (action === 'list' || action === 'show' || action === 'read' || !action) {
    const allowed = hasAnyCapability(caps, route.readCapabilities);
    return {
      can: allowed,
      reason: allowed
        ? undefined
        : `需要檢視能力：${route.readCapabilities.join(' 或 ')}`,
    };
  }

  // Unknown write action on a mapped resource: deny unless a write mapping exists.
  if (import.meta.env.DEV) {
    console.warn(`[access] unmapped action denied: ${resource}:${action}`);
  }
  return {
    can: false,
    reason: `未映射動作「${resource}:${action}」已拒絕（fail closed）`,
  };
}
