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
    return { tag, className, text, children: [], handlers: {},
      append(...children) { this.children.push(...children); },
      replaceChildren(...children) { this.children = children; },
      addEventListener(name, fn) { this.handlers[name] = fn; },
      setAttribute(name, value) { this[name] = value; },
    };
  }
  const nav = el('nav');
  const context = vm.createContext({ URLSearchParams, queueMicrotask,
    window: {}, location: { hash: '' },
    document: { getElementById: () => nav, body: { classList: { toggle() {} } } },
    sessionStorage: { getItem: k => storage.get(k) ?? null, setItem: (k,v) => storage.set(k,v), removeItem: k => storage.delete(k) },
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
    await module.link((specifier, parent) => load(path.posix.normalize(path.posix.join(path.posix.dirname(parent.identifier), specifier))));
    return module;
  }
  const shell = await load('app/shell.js');
  await shell.evaluate();
  const get = name => cache.get(name).namespace;
  const capabilities = get('app/capabilities.js');
  capabilities.setCapabilities({ capabilities: ['ops.examples.read', 'ops.feedback.read', 'ops.faq.read', 'ops.sync.read', 'ops.knowledge.read'], knowledgeBridgeEnabled: true, knowledgeCapabilities: ['knowledge.read'] });
  shell.namespace.bindShellRoutes({ routes: new Proxy({}, { get: () => () => {} }), lifecycleViews: new Set() });
  return { nav, context, navigation: get('app/navigation.js'), shell: shell.namespace, capabilities, storage };
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
  assert.deepEqual(Array.from(entries), ['faq']);
});

test('cancelled dirty-document navigation does not change workspace', async () => {
  const s = await setup();
  s.storage.set('ai_ops_active_workspace', 'knowledge_ops');
  s.context.window.__isKnowledgeDirty = () => true;
  s.context.window.__confirmKnowledgeDirty = async () => false;
  await s.navigation.navigateTo('examples', {}, { workspace: 'ai_ops' });
  assert.equal(s.navigation.activeWorkspaceId(), 'knowledge_ops');
});
