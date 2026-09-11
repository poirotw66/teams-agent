// Run with: node --experimental-vm-modules --test agent_service/tests/frontend/navigation.test.mjs
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';
import test from 'node:test';

const root = fileURLToPath(new URL('../../src/ai_ops_backoffice/static/js/', import.meta.url));
async function setup() {
  const storage = new Map();
  function el(tag, className = '', text = '') {
    const node = { tag, className, text, children: [], handlers: {},
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
  const context = vm.createContext({ URLSearchParams, queueMicrotask,
    window: { location: { search: '', hash: '' } }, location: { hash: '', search: '' },
    document: { getElementById: () => nav, body: { classList: { toggle() {}, add() {}, remove() {} } }, createElement: (tag) => el(tag) },
    sessionStorage: { getItem: k => storage.get(k) ?? null, setItem: (k,v) => storage.set(k,v), removeItem: k => storage.delete(k) },
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
    const module = mock ? new vm.SyntheticModule(Object.keys(mock), function () {
      for (const [key, value] of Object.entries(mock)) this.setExport(key, value);
    }, { context, identifier: name }) : new vm.SourceTextModule(await readFile(path.join(root, name), 'utf8'), { context, identifier: name });
    cache.set(name, module);
    return module;
  }
  async function linkModule(module) {
    if (module.status !== 'unlinked') return;
    await module.link(async (specifier, parent) => {
      const resolved = path.posix.normalize(path.posix.join(path.posix.dirname(parent.identifier), specifier));
      const child = await load(resolved);
      await linkModule(child);
      return child;
    });
  }
  const shell = await load('app/shell.js');
  await linkModule(shell);
  await shell.evaluate();
  for (const module of cache.values()) {
    if (module.status === 'linked') {
      await module.evaluate().catch(() => {});
    }
  }
  const get = name => cache.get(name).namespace;
  const capabilities = get('app/capabilities.js');
  capabilities.setCapabilities({ capabilities: ['ops.examples.read', 'ops.feedback.read', 'ops.faq.read', 'ops.sync.read', 'ops.knowledge.read'], knowledgeBridgeEnabled: true, knowledgeCapabilities: ['knowledge.read'] });
  shell.namespace.bindShellRoutes({ routes: new Proxy({}, { get: () => () => {} }), lifecycleViews: new Set() });
  const returnToMod = await load('app/returnTo.js');
  await linkModule(returnToMod);
  await returnToMod.evaluate();
  return {
    nav,
    context,
    navigation: get('app/navigation.js'),
    returnTo: returnToMod.namespace,
    shell: shell.namespace,
    capabilities,
    storage,
    load,
    linkModule,
  };
}

async function setupBuShell() {
  const s = await setup();
  s.context.window.__AI_OPS_BU_SHELL_V1__ = true;
  const buShell = await s.load('app/buShell.js');
  await s.linkModule(buShell);
  await buShell.evaluate();
  s.shell.registerBuNavRenderer(buShell.namespace.renderBuNav);
  return s;
}

function collectNavLinkLabels(nav) {
  const labels = [];
  const walk = (node) => {
    if (!node) return;
    if (node.tag === 'a' && node.text) labels.push(node.text);
    for (const child of node.children || []) walk(child);
  };
  walk(nav);
  return labels;
}

test('shared case page stays in AI management, including drill links', async () => {
  const s = await setup();
  s.storage.set('ai_ops_active_workspace', 'ai_ops');
  await s.navigation.navigateTo('examples');
  assert.equal(s.navigation.activeWorkspaceId(), 'ai_ops');
  assert.equal(s.context.location.hash, '#/ai_ops/examples');
  assert.equal(s.navigation.drillLink('cases', 'examples').href, '#/ai_ops/examples');
});

test('explicit workspace switch works when its first page is shared', async () => {
  const s = await setup();
  s.storage.set('ai_ops_active_workspace', 'knowledge_ops');
  s.shell.renderNav('examples');
  const aiButton = s.nav.children[0].children.find(x => x.text === 'AI 管理');
  await aiButton.handlers.click();
  assert.equal(s.navigation.activeWorkspaceId(), 'ai_ops');
  assert.equal(s.context.location.hash, '#/ai_ops/examples');
});

test('old portal links select the new entry and preserve query context', async () => {
  const s = await setup();
  s.context.location.hash = '#/knowledge_ops/knowledgePortal?sub=reviews&caseId=case-1';
  const parsed = s.navigation.parseLocationHash();
  assert.equal(parsed.view, 'knowledgeReviews');
  assert.equal(parsed.filters.caseId, 'case-1');
  await s.navigation.navigateTo('knowledgePortal', { sub: 'work' });
  assert.equal(s.navigation.loadNavFilters().view, 'knowledgeWork');
});

test('knowledge entries respect separate FAQ, sync and review permissions', async () => {
  const s = await setup();
  let entries = s.shell.visibleWorkspaces().find(x => x.id === 'knowledge_ops').items.map(x => x[0]);
  assert.ok(entries.includes('faq') && entries.includes('sync') && entries.includes('knowledgeWork'));
  assert.ok(!entries.includes('knowledgeReviews'));
  s.capabilities.setCapabilities({ capabilities: ['ops.faq.read'], knowledgeBridgeEnabled: false });
  entries = s.shell.visibleWorkspaces()[0].items.map(x => x[0]);
  assert.deepEqual(Array.from(entries), ['contentHub', 'faq']);
});

test('cancelled dirty-document navigation does not change workspace', async () => {
  const s = await setup();
  s.storage.set('ai_ops_active_workspace', 'knowledge_ops');
  s.context.window.__isKnowledgeDirty = () => true;
  s.context.window.__confirmKnowledgeDirty = async () => false;
  await s.navigation.navigateTo('examples', {}, { workspace: 'ai_ops' });
  assert.equal(s.navigation.activeWorkspaceId(), 'knowledge_ops');
});

test('minimum permission role paths: conversations, summary overview, and governance search', async () => {
  const s = await setup();

  // 1. Conversations minimum capability: only ops.conversations.read
  s.capabilities.setCapabilities({ capabilities: ['ops.conversations.read'], knowledgeBridgeEnabled: false });
  let ws = s.shell.visibleWorkspaces();
  let kItems = ws.find(w => w.id === 'knowledge_ops')?.items.map(x => x[0]) || [];
  assert.deepEqual(Array.from(kItems), ['conversations']);
  await s.navigation.navigateTo('conversations');
  assert.equal(s.context.location.hash, '#/knowledge_ops/conversations');

  // 2. Summary overview minimum capability: only ops.summary.read
  s.capabilities.setCapabilities({ capabilities: ['ops.summary.read'], knowledgeBridgeEnabled: false });
  ws = s.shell.visibleWorkspaces();
  let pItems = ws.find(w => w.id === 'platform')?.items.map(x => x[0]) || [];
  assert.deepEqual(Array.from(pItems), ['overview']);
  await s.navigation.navigateTo('overview');
  assert.equal(s.context.location.hash, '#/platform/overview');

  // 3. Search minimum capability: only ops.search.read
  s.capabilities.setCapabilities({ capabilities: ['ops.search.read'], knowledgeBridgeEnabled: false });
  ws = s.shell.visibleWorkspaces();
  pItems = ws.find(w => w.id === 'platform')?.items.map(x => x[0]) || [];
  assert.deepEqual(Array.from(pItems), ['search']);
  await s.navigation.navigateTo('search');
  assert.equal(s.context.location.hash, '#/platform/search');
});

test('BU route aliases resolve to canonical views', async () => {
  const s = await setup();
  s.context.location.hash = '#/knowledge_ops/cases?caseId=Q-1';
  const parsed = s.navigation.parseLocationHash();
  assert.equal(parsed.view, 'quality');
  assert.equal(parsed.filters.caseId, 'Q-1');
  s.context.location.hash = '#/knowledge_ops/work';
  assert.equal(s.navigation.parseLocationHash().view, 'workHub');
  s.context.location.hash = '#/platform/analytics';
  assert.equal(s.navigation.parseLocationHash().view, 'overview');
  s.context.location.hash = '#/knowledge_ops/contentLists?tab=faq';
  assert.equal(s.navigation.parseLocationHash().view, 'contentLists');
  assert.equal(s.navigation.workspaceForView('workHub'), 'knowledge_ops');
  assert.equal(s.navigation.workspaceForView('contentLists'), 'knowledge_ops');
  s.context.location.hash = '#/knowledge_ops/docs';
  assert.equal(s.navigation.parseLocationHash().view, 'contentLists');
  s.context.location.hash = '#/knowledge_ops/knowledge';
  assert.equal(s.navigation.parseLocationHash().view, 'knowledge');
  s.context.location.hash = '#/platform/content-performance';
  assert.equal(s.navigation.parseLocationHash().view, 'knowledge');
});

test('returnTo encodes only allowlisted views and rejects external targets', async () => {
  const s = await setup();
  const returnTo = s.returnTo;
  const token = returnTo.encodeReturnTo('quality', { caseId: 'Q-9', tab: 'cases' });
  assert.equal(token, 'quality|caseId=Q-9&tab=cases');
  const parsed = returnTo.parseReturnTo(token);
  assert.equal(parsed.view, 'quality');
  assert.equal(parsed.filters.caseId, 'Q-9');
  assert.equal(parsed.filters.tab, 'cases');
  assert.equal(returnTo.encodeReturnTo('https://evil.example', {}), null);
  assert.equal(returnTo.parseReturnTo('https://evil.example'), null);
  assert.equal(returnTo.parseReturnTo('unknownView|caseId=1'), null);
  const wrapped = returnTo.withReturnTo({ conversationId: 'C-1' }, 'quality', { caseId: 'Q-9' });
  assert.equal(wrapped.conversationId, 'C-1');
  assert.equal(wrapped.returnTo, 'quality|caseId=Q-9');
});

test('BU shell primary nav hides classic workspace switcher and respects min capabilities', async () => {
  const s = await setupBuShell();
  s.capabilities.setCapabilities({
    capabilities: ['ops.conversations.read', 'ops.summary.read'],
    knowledgeBridgeEnabled: false,
  });
  s.shell.renderNav('conversations');
  const labels = collectNavLinkLabels(s.nav);
  assert.ok(labels.includes('對話紀錄'));
  assert.ok(labels.includes('營運分析'));
  assert.ok(!labels.includes('我的工作'));
  assert.ok(!labels.includes('內容維護'));
  assert.ok(!s.nav.children.some((child) => child.className === 'workspace-switcher'));
  assert.equal(s.context.location.hash, '#/knowledge_ops/conversations');
});

test('BU shell quality capability unlocks work hub and improve-cases aliases', async () => {
  const s = await setupBuShell();
  s.capabilities.setCapabilities({
    capabilities: ['ops.quality.read', 'ops.conversations.read'],
    knowledgeBridgeEnabled: false,
  });
  s.shell.renderNav('workHub');
  const labels = collectNavLinkLabels(s.nav);
  assert.ok(labels.includes('我的工作'));
  assert.ok(labels.includes('改善案件'));
  s.context.location.hash = '#/knowledge_ops/improve?caseId=Q-2&returnTo=workHub';
  const parsed = s.navigation.parseLocationHash();
  assert.equal(parsed.view, 'quality');
  assert.equal(parsed.filters.caseId, 'Q-2');
  assert.equal(parsed.filters.returnTo, 'workHub');
  const back = s.returnTo.parseReturnTo(parsed.filters.returnTo);
  assert.equal(back.view, 'workHub');
});

test('BU shell system nav includes examples when capable and keeps classic switcher off', async () => {
  const s = await setupBuShell();
  s.capabilities.setCapabilities({
    capabilities: ['ops.examples.read', 'ops.prompts.read', 'ops.conversations.read'],
    knowledgeBridgeEnabled: false,
  });
  s.shell.renderNav('examples');
  const labels = collectNavLinkLabels(s.nav);
  assert.ok(labels.includes('分類正反例'));
  assert.ok(labels.includes('Prompt'));
  assert.ok(labels.includes('對話紀錄'));
  assert.ok(!s.nav.children.some((child) => child.className === 'workspace-switcher'));
  assert.equal(s.context.location.hash.includes('/examples'), true);
});

test('old platform issue URLs remain usable under route contract', async () => {
  const s = await setup();
  s.context.location.hash = '#/platform/issues?preset=7d&issueTypeId=vpn';
  const parsed = s.navigation.parseLocationHash();
  assert.equal(parsed.workspace, 'platform');
  assert.equal(parsed.view, 'issues');
  assert.equal(parsed.filters.preset, '7d');
  assert.equal(parsed.filters.issueTypeId, 'vpn');
  s.context.location.hash = '#/platform/routes?preset=30d';
  assert.equal(s.navigation.parseLocationHash().view, 'routes');
});
