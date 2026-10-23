import { Capacitor, registerPlugin } from '@capacitor/core';
import { InAppBrowser, DefaultWebViewOptions, DefaultSystemBrowserOptions } from '@capacitor/inappbrowser';
import { DEFAULT_ORIGIN, normalizeOrigin, entryUrl } from './settings.mjs';
const $ = id => document.getElementById(id);
const key = 'agent-remote.connection.v1';
const RemoteBrowser = registerPlugin('RemoteBrowser');
const android = Capacitor.getPlatform() === 'android';
if (android) { document.title = '遥应'; document.querySelector('.brand span').textContent = '遥应'; }
let saved = {};
try { saved = JSON.parse(localStorage.getItem(key) || '{}') || {}; } catch {}
try { $('origin').value = normalizeOrigin(saved.origin || DEFAULT_ORIGIN); }
catch { $('origin').value = DEFAULT_ORIGIN; }
$('entry').value = android ? (saved.flowVersion === 3 && saved.entry === 'home' ? 'home' : 'account') : saved.entry === 'home' ? 'home' : 'account';
$('compat').hidden = !android;
$('update').hidden = !android;
$('update').onclick = async () => {
  try { await RemoteBrowser.checkUpdate(); }
  catch { $('status').textContent = '无法检查更新，请稍后重试'; }
};
$('forget').onclick = () => {
  localStorage.removeItem(key);
  $('origin').value = DEFAULT_ORIGIN;
  $('entry').value = 'account';
  $('status').textContent = '已恢复默认';
};
$('connect').onsubmit = async event => {
  event.preventDefault();
  $('open').disabled = true;
  $('compat').disabled = true;
  try {
    const origin = normalizeOrigin($('origin').value);
    const entry = $('entry').value;
    const url = entryUrl(origin, entry);
    localStorage.setItem(key, JSON.stringify({ origin, entry, flowVersion: 3 }));
    if (!Capacitor.isNativePlatform()) {
      $('status').textContent = url;
      return;
    }
    if (event.submitter?.id === 'compat') {
      await InAppBrowser.openInSystemBrowser({ url, options: DefaultSystemBrowserOptions });
      $('status').textContent = '已在浏览器中打开';
      return;
    }
    if (android) {
      await RemoteBrowser.open({ url });
      $('status').textContent = '';
      return;
    }
    await InAppBrowser.openInWebView({ url, options: {
      ...DefaultWebViewOptions, showURL: true, showToolbar: true,
      showNavigationButtons: true, clearCache: false, clearSessionCache: false,
      closeButtonText: '返回',
      android: { ...DefaultWebViewOptions.android, hardwareBack: true, isIsolated: true }
    }});
    $('status').textContent = '';
  } catch (error) { $('status').textContent = error.message || '打不开，请检查地址和网络'; }
  finally { $('open').disabled = false; $('compat').disabled = false; }
};

if (Capacitor.isNativePlatform() && typeof $('connect').requestSubmit === 'function') $('connect').requestSubmit();
