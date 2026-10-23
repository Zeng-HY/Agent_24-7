import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { DEFAULT_ORIGIN, normalizeOrigin, entryUrl } from '../src/settings.mjs';
const code = (await readFile(new URL('../src/app.mjs', import.meta.url), 'utf8')).replace(/^import .*;\r?\n/gm, '');
async function launch(platform, saved = {}) {
  const nodes = new Map(); const calls = [];
  const browser = { openInWebView: async x => calls.push(['webview', x]), openInSystemBrowser: async x => calls.push(['system', x]) };
  const context = vm.createContext({
    window: {TeleplyAbout:{mount(fn){nodes.set('aboutAction',fn);}}}, addEventListener() {},
    document: { addEventListener() {}, querySelector:()=>({textContent:""}), getElementById(id) { if (!nodes.has(id)) nodes.set(id, {}); return nodes.get(id); } },
    localStorage: { getItem: () => JSON.stringify(saved), setItem() {}, removeItem() {} },
    Capacitor: { getPlatform: () => platform, isNativePlatform: () => platform !== 'web' },
    registerPlugin: () => ({getTheme:async()=>({mode:"system"}),setTheme:async()=>{}, open: async x => calls.push(['native', x]), checkUpdate: async () => calls.push(['update']),showAbout:async()=>calls.push(['about']) }),
    InAppBrowser: browser, DefaultWebViewOptions: {}, DefaultSystemBrowserOptions: {},
    DEFAULT_ORIGIN, normalizeOrigin, entryUrl
  });
  vm.runInContext(code, context);
  await context.window.teleplyReady;
  return { nodes, calls, submit: id => nodes.get('connect').onsubmit({ preventDefault() {}, submitter: { id } }) };
}
test('Android migrates legacy pairing settings to personal account entry', async () => {
  const app = await launch('android', { origin: DEFAULT_ORIGIN, entry: 'home' });
  assert.equal(app.nodes.get('entry').value, 'account');
  await app.submit('open');
  assert.equal(app.calls[0][0], 'native');
  assert.equal(app.calls[0][1].url, DEFAULT_ORIGIN + '/account');
});
test('iOS retains its selected entry and official browser', async () => {
  const app = await launch('ios', { entry: 'account' });
  await app.submit('open');
  assert.equal(app.calls[0][0], 'webview');
  assert.equal(app.calls[0][1].url, DEFAULT_ORIGIN + '/account');
});
test('explicit current-version home choice is preserved; reset returns to account', async () => {
  const app = await launch('android', { entry: 'home', flowVersion: 3 });
  assert.equal(app.nodes.get('entry').value, 'home');
  app.nodes.get('forget').onclick();
  assert.equal(app.nodes.get('entry').value, 'account');
});
test('web preview and rejected URLs never open a remote browser', async () => {
  const preview = await launch('web'); await preview.submit('open'); assert.equal(preview.calls.length, 0);
  const app = await launch('android'); app.nodes.get('origin').value = 'https://user:secret@example.com/';
  await app.submit('open'); assert.equal(app.calls.length, 0);
  assert.equal(app.nodes.get('open').disabled, false);
});
test('only Android mounts About in settings', async () => {
  const app=await launch('android');
  assert.equal(typeof app.nodes.get('aboutAction'),'function');
  await app.nodes.get('aboutAction')();
  assert.deepEqual(app.calls,[['about']]);
  assert.equal((await launch('ios')).nodes.has('aboutAction'),false);
  assert.equal((await launch('web')).nodes.has('aboutAction'),false);
});
