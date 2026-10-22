import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { DEFAULT_ORIGIN, normalizeOrigin, entryUrl } from '../src/settings.mjs';
const code = (await readFile(new URL('../src/app.mjs', import.meta.url), 'utf8')).replace(/^import .*;\r?\n/gm, '');
function launch(platform, saved = {}) {
  const nodes = new Map(); const calls = [];
  const browser = { openInWebView: async x => calls.push(['webview', x]), openInSystemBrowser: async x => calls.push(['system', x]) };
  const context = vm.createContext({
    document: { getElementById(id) { if (!nodes.has(id)) nodes.set(id, {}); return nodes.get(id); } },
    localStorage: { getItem: () => JSON.stringify(saved), setItem() {}, removeItem() {} },
    Capacitor: { getPlatform: () => platform, isNativePlatform: () => platform !== 'web' },
    registerPlugin: () => ({ open: async x => calls.push(['native', x]) }),
    InAppBrowser: browser, DefaultWebViewOptions: {}, DefaultSystemBrowserOptions: {},
    DEFAULT_ORIGIN, normalizeOrigin, entryUrl
  });
  vm.runInContext(code, context);
  return { nodes, calls, submit: id => nodes.get('connect').onsubmit({ preventDefault() {}, submitter: { id } }) };
}
test('Android migrates stale account entry and opens native first-login browser', async () => {
  const app = launch('android', { origin: DEFAULT_ORIGIN, entry: 'account' });
  assert.equal(app.nodes.get('entry').value, 'home');
  assert.equal(app.nodes.get('onboarding').hidden, false);
  await app.submit('open');
  assert.equal(app.calls[0][0], 'native');
  assert.equal(app.calls[0][1].url, DEFAULT_ORIGIN + '/');
});
test('iOS retains its selected entry and official browser', async () => {
  const app = launch('ios', { entry: 'account' });
  await app.submit('open');
  assert.equal(app.calls[0][0], 'webview');
  assert.equal(app.calls[0][1].url, DEFAULT_ORIGIN + '/account');
  assert.equal(app.nodes.get('onboarding').hidden, true);
});
test('web preview and rejected URLs never open a remote browser', async () => {
  const preview = launch('web'); await preview.submit('open'); assert.equal(preview.calls.length, 0);
  const app = launch('android'); app.nodes.get('origin').value = 'https://user:secret@example.com/';
  await app.submit('open'); assert.equal(app.calls.length, 0);
  assert.equal(app.nodes.get('open').disabled, false);
});
