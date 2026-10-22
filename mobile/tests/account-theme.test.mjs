import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { build } from 'esbuild';
import { JSDOM } from 'jsdom';
const html = await readFile(new URL('./fixtures/account.html', import.meta.url), 'utf8');
const bundle = (await build({ entryPoints: ['src/account-theme.mjs'], bundle: true, write: false, format: 'iife', loader: { '.css': 'text' } })).outputFiles[0].text;
function page() {
  const dom = new JSDOM(html, { url: 'https://example.com/account', runScripts: 'outside-only' });
  const doc = dom.window.document, calls = [];
  for (const id of ['login','register','reset','logout','bind','change']) doc.getElementById(id).onclick = async () => calls.push(id);
  const originalPassword = doc.getElementById('password');
  dom.window.eval(bundle);
  return { dom, doc, calls, originalPassword };
}
test('presentation preserves the server fields and dispatches only the chosen action', async () => {
  const p = page(), $ = id => p.doc.getElementById(id);
  assert.equal($('password'), p.originalPassword);
  assert.equal($('code').parentElement.hidden, true);
  $('pad-mode-register').click();
  assert.equal($('code').parentElement.hidden, false);
  assert.equal($('login').hidden, true);
  await $('register').onclick(new p.dom.window.Event('click'));
  assert.deepEqual(p.calls, ['register']);
  $('pad-recovery').click();
  assert.equal($('reset').hidden, false);
  await $('reset').onclick(new p.dom.window.Event('click'));
  assert.deepEqual(p.calls, ['register', 'reset']);
  const before = p.doc.querySelectorAll('.pad-brand').length;
  p.dom.window.eval(bundle);
  assert.equal(p.doc.querySelectorAll('.pad-brand').length, before);
  p.dom.window.close();
});
test('login state and empty device list follow the existing server DOM', async () => {
  const p = page(), $ = id => p.doc.getElementById(id);
  $('signed').hidden = false;
  await new Promise(resolve => p.dom.window.setTimeout(resolve, 0));
  assert.equal($('name').closest('fieldset').hidden, true);
  assert.equal(p.doc.querySelector('.pad-empty').hidden, false);
  const item = p.doc.createElement('li'); item.textContent = 'Test workstation'; $('devices').append(item);
  await new Promise(resolve => p.dom.window.setTimeout(resolve, 0));
  assert.equal(p.doc.querySelector('.pad-empty').hidden, true);
  $('signed').hidden = true;
  await new Promise(resolve => p.dom.window.setTimeout(resolve, 0));
  assert.equal($('name').closest('fieldset').hidden, false);
  p.dom.window.close();
});
test('unrecognized server pages remain untouched', () => {
  const dom = new JSDOM('<html><body><h1>Other service</h1></body></html>', { url: 'https://example.com/account', runScripts: 'outside-only' });
  dom.window.eval(bundle);
  assert.equal(dom.window.document.documentElement.dataset.padTheme, undefined);
  assert.equal(dom.window.document.body.textContent, 'Other service');
  dom.window.close();
});
