/**
 * Role-matrix expectations for BU shell (U4 permission acceptance).
 * Caps mirror agent_service/operations/access.py CAPABILITIES (+ knowledge bridge).
 */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';
import test from 'node:test';

const root = fileURLToPath(new URL('../../src/ai_ops_backoffice/static/js/', import.meta.url));

const ROLE_FIXTURES = {
  ANALYST: {
    capabilities: [
      'ops.summary.read',
      'ops.issues.read',
      'ops.feedback.read',
      'ops.cost.read',
      'ops.conversations.read',
      'ops.exports.read',
      'ops.evals.read',
    ],
    knowledgeBridgeEnabled: false,
    knowledgeCapabilities: [],
    expectPrimary: ['我的工作', '改善案件', '對話紀錄', '品質驗收', '營運分析'],
    forbidPrimary: ['知識內容'],
  },
  VIEWER: {
    capabilities: [
      'ops.conversations.read',
      'ops.feedback.read',
      'ops.knowledge.read',
      'ops.quality.read',
      'ops.evals.read',
      'ops.examples.read',
      'ops.exports.read',
    ],
    knowledgeBridgeEnabled: true,
    knowledgeCapabilities: ['knowledge.read'],
    expectPrimary: ['我的工作', '改善案件', '知識內容', '對話紀錄', '品質驗收'],
    expectSystem: ['分類正反例'],
    forbidPrimary: ['營運分析'],
  },
  KNOWLEDGE_ADMIN: {
    capabilities: [
      'ops.summary.read',
      'ops.issues.read',
      'ops.feedback.read',
      'ops.knowledge.read',
      'ops.conversations.read',
      'ops.quality.read',
      'ops.quality.write',
      'ops.faq.read',
      'ops.faq.write',
      'ops.examples.read',
      'ops.sync.read',
      'ops.evals.read',
    ],
    knowledgeBridgeEnabled: true,
    knowledgeCapabilities: ['knowledge.read', 'knowledge.review'],
    expectPrimary: ['我的工作', '改善案件', '知識內容', '對話紀錄', '品質驗收', '營運分析'],
    forbidPrimary: [],
  },
  SERVICE_OWNER: {
    capabilities: [
      'ops.summary.read',
      'ops.issues.read',
      'ops.feedback.read',
      'ops.cost.read',
      'ops.quality.read',
      'ops.quality.write',
      'ops.quality.resolve',
      'ops.conversations.read',
      'ops.prompts.read',
      'ops.models.read',
      'ops.flags.read',
      'ops.budget.read',
      'ops.search.read',
      'ops.evals.read',
    ],
    knowledgeBridgeEnabled: true,
    knowledgeCapabilities: ['knowledge.read'],
    expectPrimary: ['我的工作', '改善案件', '知識內容', '對話紀錄', '品質驗收', '營運分析'],
    expectSystem: ['Prompt', '模型', '功能開關', '預算與告警', '搜尋結果'],
    forbidPrimary: [],
  },
  AI_ADMIN: {
    capabilities: [
      'ops.summary.read',
      'ops.cost.read',
      'ops.issues.read',
      'ops.health.read',
      'ops.conversations.read',
      'ops.quality.read',
      'ops.examples.read',
      'ops.sync.read',
      'ops.budget.read',
      'ops.prompts.read',
      'ops.models.read',
      'ops.flags.read',
      'ops.search.read',
      'ops.retention.read',
      'ops.evals.read',
    ],
    knowledgeBridgeEnabled: false,
    knowledgeCapabilities: [],
    expectPrimary: ['我的工作', '改善案件', '對話紀錄', '品質驗收', '營運分析'],
    expectSystem: ['分類正反例', '同步工作', 'Prompt', '模型', '功能開關', '服務狀態'],
    forbidPrimary: ['知識內容'],
  },
  AUDITOR: {
    capabilities: [
      'ops.audit.read',
      'ops.exports.read',
      'ops.faq.read',
      'ops.examples.read',
      'ops.budget.read',
      'ops.prompts.read',
      'ops.models.read',
      'ops.flags.read',
      'ops.search.read',
      'ops.roles.read',
      'ops.retention.read',
      'ops.evals.read',
    ],
    knowledgeBridgeEnabled: true,
    knowledgeCapabilities: ['knowledge.read', 'knowledge.audit.read'],
    expectPrimary: ['我的工作', '知識內容', '品質驗收'],
    expectSystem: ['分類正反例', 'Prompt', '模型', '功能開關', '角色權限', '稽核', '搜尋結果'],
    forbidPrimary: ['改善案件', '對話紀錄', '營運分析'],
  },
};

const CANONICAL_VIEWS = [
  'costs', 'health', 'routes', 'issues', 'budgets', 'audit', 'models', 'flags',
  'prompts', 'roles', 'retention', 'masking', 'search', 'overview', 'conversations',
  'quality', 'knowledge', 'faq', 'contentHub', 'contentLists', 'workHub', 'sync',
  'knowledgeWork', 'knowledgeReviews', 'knowledgeReleases', 'knowledgeAudit',
  'knowledgeDocument', 'knowledgePortal', 'examples', 'evaluations',
];

async function setupBuShell() {
  const storage = new Map();
  function el(tag, className = '', text = '') {
    const node = {
      tag, className, text, children: [], handlers: {}, dataset: {},
      append(...children) { this.children.push(...children); },
      replaceChildren(...children) { this.children = children; },
      addEventListener(name, fn) { this.handlers[name] = fn; },
      setAttribute(name, value) { this[name] = value; },
      removeAttribute(name) { delete this[name]; },
      removeEventListener(name) { delete this.handlers[name]; },
    };
    Object.defineProperty(node, 'textContent', {
      get() { return this.text; },
      set(value) { this.text = value; },
    });
    return node;
  }
  const nav = el('nav');
  const context = vm.createContext({
    URLSearchParams,
    queueMicrotask,
    window: { location: { search: '', hash: '' }, __AI_OPS_BU_SHELL_V1__: true },
    location: { hash: '', search: '' },
    document: {
      getElementById: () => nav,
      body: { classList: { toggle() {}, add() {}, remove() {} } },
      createElement: (tag) => el(tag),
    },
    sessionStorage: {
      getItem: (k) => storage.get(k) ?? null,
      setItem: (k, v) => storage.set(k, v),
      removeItem: (k) => storage.delete(k),
    },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  });
  const mocks = {
    'api.js': { el },
    'app/activeView.js': { setCurrentActiveView() {} },
    'app/lifecycle.js': { leaveActivePage() {} },
    'views/conversations.js': { stopConversationPolling() {} },
  };
  const cache = new Map();
  async function load(name) {
    if (cache.has(name)) return cache.get(name);
    const mock = mocks[name];
    const module = mock
      ? new vm.SyntheticModule(Object.keys(mock), function () {
          for (const [key, value] of Object.entries(mock)) this.setExport(key, value);
        }, { context, identifier: name })
      : new vm.SourceTextModule(await readFile(path.join(root, name), 'utf8'), {
          context,
          identifier: name,
        });
    cache.set(name, module);
    return module;
  }
  async function linkModule(module) {
    if (module.status !== 'unlinked') return;
    await module.link(async (specifier, parent) => {
      const resolved = path.posix.normalize(
        path.posix.join(path.posix.dirname(parent.identifier), specifier),
      );
      const child = await load(resolved);
      await linkModule(child);
      return child;
    });
  }
  const shell = await load('app/shell.js');
  await linkModule(shell);
  await shell.evaluate();
  for (const module of cache.values()) {
    if (module.status === 'linked') await module.evaluate().catch(() => {});
  }
  const get = (name) => cache.get(name).namespace;
  const buShell = await load('app/buShell.js');
  await linkModule(buShell);
  await buShell.evaluate();
  shell.namespace.registerBuNavRenderer(buShell.namespace.renderBuNav);
  shell.namespace.bindShellRoutes({
    routes: new Proxy({}, { get: () => () => {} }),
    lifecycleViews: new Set(),
  });
  return {
    nav,
    shell: shell.namespace,
    capabilities: get('app/capabilities.js'),
    workspaces: get('app/workspaces.js'),
    buConfig: get('app/buShellConfig.js'),
  };
}

function collectLabels(nav) {
  const labels = [];
  const walk = (node) => {
    if (!node) return;
    if (node.tag === 'a' && node.text) labels.push(node.text);
    for (const child of node.children || []) walk(child);
  };
  walk(nav);
  return labels;
}

for (const [role, fixture] of Object.entries(ROLE_FIXTURES)) {
  test(`BU shell role matrix: ${role} sees expected primary/system entries`, async () => {
    const s = await setupBuShell();
    s.capabilities.setCapabilities({
      capabilities: fixture.capabilities,
      knowledgeBridgeEnabled: fixture.knowledgeBridgeEnabled,
      knowledgeCapabilities: fixture.knowledgeCapabilities,
      role,
    });
    s.shell.renderNav('overview');
    const labels = collectLabels(s.nav);
    for (const label of fixture.expectPrimary) {
      assert.ok(labels.includes(label), `${role} missing primary ${label}; got ${labels.join(',')}`);
    }
    for (const label of fixture.forbidPrimary || []) {
      assert.ok(!labels.includes(label), `${role} should not see ${label}`);
    }
    for (const label of fixture.expectSystem || []) {
      assert.ok(labels.includes(label), `${role} missing system ${label}; got ${labels.join(',')}`);
    }
    assert.ok(!s.nav.children.some((child) => child.className === 'workspace-switcher'));
  });
}

test('workspace catalog views remain in the canonical 30-view route set', async () => {
  const s = await setupBuShell();
  const catalogIds = new Set(
    s.workspaces.workspaces.flatMap((ws) => ws.items.map(([id]) => id)),
  );
  for (const id of ['workHub', 'contentLists']) {
    catalogIds.add(id);
  }
  for (const id of catalogIds) {
    assert.ok(
      CANONICAL_VIEWS.includes(id),
      `catalog view ${id} missing from canonical route list`,
    );
  }
  assert.equal(CANONICAL_VIEWS.length, 30);
});

test('BU primary + system nav ids are all canonical views', async () => {
  const s = await setupBuShell();
  const ids = [
    ...s.buConfig.BU_PRIMARY_NAV.map(([id]) => id),
    ...s.buConfig.BU_SYSTEM_NAV.map(([id]) => id),
  ];
  for (const id of ids) {
    assert.ok(CANONICAL_VIEWS.includes(id), `BU nav id ${id} not in canonical routes`);
  }
});
