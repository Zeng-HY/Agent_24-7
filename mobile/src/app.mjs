import { Capacitor } from '@capacitor/core';
import { InAppBrowser, DefaultWebViewOptions } from '@capacitor/inappbrowser';
import { DEFAULT_ORIGIN, normalizeOrigin, entryUrl } from './settings.mjs';
const $ = id => document.getElementById(id);
const key = 'agent-remote.connection.v1';
let saved = {};
try { saved = JSON.parse(localStorage.getItem(key) || '{}') || {}; } catch {}
try { $('origin').value = normalizeOrigin(saved.origin || DEFAULT_ORIGIN); }
catch { $('origin').value = DEFAULT_ORIGIN; }
$('entry').value = saved.entry === 'account' ? 'account' : 'home';
$('forget').onclick = () => {
  localStorage.removeItem(key);
  $('origin').value = DEFAULT_ORIGIN;
  $('entry').value = 'home';
  $('status').textContent = '已恢复默认地址。服务中的登录状态未更改。';
};
$('connect').onsubmit = async event => {
  event.preventDefault();
  $('open').disabled = true;
  try {
    const origin = normalizeOrigin($('origin').value);
    const entry = $('entry').value;
    const url = entryUrl(origin, entry);
    localStorage.setItem(key, JSON.stringify({ origin, entry }));
    if (!Capacitor.isNativePlatform()) {
      $('status').textContent = '网页预览已验证地址：' + url + '。应用内连接需 iOS 构建；本预览不会访问服务。';
      return;
    }
    await InAppBrowser.openInWebView({ url, options: {
      ...DefaultWebViewOptions, showURL: true, showToolbar: true,
      showNavigationButtons: true, clearCache: false, clearSessionCache: false,
      closeButtonText: '返回'
    }});
    $('status').textContent = '已打开服务。登录失效时请在服务内重新登录。';
  } catch (error) { $('status').textContent = error.message || '打开失败，请检查地址与网络。'; }
  finally { $('open').disabled = false; }
};
