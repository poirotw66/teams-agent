import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import test from 'node:test';

async function setup() {
  function el(tag, className = '', text = '') {
    return { tag, className, text, value: '', style: {}, children: [],
      append(...children) { this.children.push(...children); },
      replaceChildren(...children) { this.children = children; },
      addEventListener() {}, setAttribute() {},
    };
  }
  const app = el('main');
  const calls = [];
  const context = vm.createContext({
    URLSearchParams,
    window: { location: { search: '', hash: '' } },
    document: { getElementById: () => app },
  });
  const mocks = {
    '../api.js': { el, metric() {}, api: async url => { calls.push(url); return { items: [] }; } },
    '../components/modal.js': { showContentModal() {}, closeContentModal() {} },
    '../components/conversationModal.js': { showConversationModal() {} },
    '../components/faqForms.js': { buildFaqForm() {}, faqPayload() {} },
    '../components/contentGuide.js': { renderContentPolicyBanner() {}, renderDecisionGuide() {} },
    '../services/export.js': { runExport() {} },
    '../app/capabilities.js': { actorCapabilities: () => new Set(['ops.faq.read', 'ops.sync.read']), canUseKnowledgeUi: () => true, getCapabilities: () => ({ knowledgeBridgeEnabled: true }) },
    '../app/navigation.js': { buildLocationHash: () => '#', drillLink() {}, loadNavFilters: () => ({ caseId: 'case-1' }), navigateTo() {} },
    '../app/buShellConfig.js': { isBuShellEnabled: () => false },
    '../app/analyticsChrome.js': {
      presentAnalyticsPage(_active, _title, _subtitle, ...nodes) {
        app.replaceChildren(...nodes.filter(Boolean));
      },
    },
    '../knowledge_portal_view.js': { renderNativeKnowledgePortal: async (_app, _caps, _nav, filters) => calls.push(filters) },
    '../app/lifecycle.js': { createPageController: x => x },
  };
  const source = await readFile(new URL('../../src/ai_ops_backoffice/static/js/views/knowledge.js', import.meta.url), 'utf8');
  const module = new vm.SourceTextModule(source, { context });
  await module.link(specifier => {
    const cleanSpecifier = specifier.split('?')[0];
    const mock = mocks[cleanSpecifier];
    if (!mock) throw new Error(`Missing mock for ${cleanSpecifier}`);
    return new vm.SyntheticModule(Object.keys(mock), function () {
      for (const [key, value] of Object.entries(mock)) this.setExport(key, value);
    }, { context });
  });
  await module.evaluate();
  return { pages: module.namespace, calls, app };
}

for (const [page, endpoint, heading] of [
  ['faqPage', '/api/faqs?', 'FAQ 管理'],
  ['syncPage', '/api/sync-jobs', '同步工作'],
  ['knowledgePage', '/api/knowledge?', '內容成效'],
]) {
  test(`${page} renders independently and requests only its own data`, async () => {
    const s = await setup();
    await s.pages[page].enter();
    assert.equal(s.calls.length, 1);
    assert.ok(s.calls[0].startsWith(endpoint));
    assert.equal(s.app.children.length, 1);
    assert.equal(s.app.children[0].children[0].text, heading);
  });
}

test('portal sections retain originating case context', async () => {
  const s = await setup();
  await s.pages.knowledgeSectionPage('reviews').enter();
  assert.equal(s.calls[0].sub, 'reviews');
  assert.equal(s.calls[0].caseId, 'case-1');
});
