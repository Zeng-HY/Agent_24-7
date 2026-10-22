import { Capacitor, registerPlugin } from '@capacitor/core';
import { InAppBrowser, DefaultWebViewOptions, DefaultSystemBrowserOptions } from '@capacitor/inappbrowser';
import { DEFAULT_ORIGIN, normalizeOrigin, entryUrl } from './settings.mjs';
const $ = id => document.getElementById(id);
const key = 'agent-remote.connection.v1';
const RemoteBrowser = registerPlugin('RemoteBrowser');
const android = Capacitor.getPlatform() === 'android';
let saved = {};
try { saved = JSON.parse(localStorage.getItem(key) || '{}') || {}; } catch {}
try { $('origin').value = normalizeOrigin(saved.origin || DEFAULT_ORIGIN); }
catch { $('origin').value = DEFAULT_ORIGIN; }
$('entry').value = android ? 'home' : saved.entry === 'account' ? 'account' : 'home';
$('compat').hidden = !android;
$('onboarding').hidden = !android;
if (android) $('open').textContent = '连接电脑 · 登录与配对';
$('forget').onclick = () => {
  localStorage.removeItem(key);
  $('origin').value = DEFAULT_ORIGIN;
  $('entry').value = 'home';
  $('status').textContent = '已恢复默认地址。服务中的登录状态未更改。';
};
$('connect').onsubmit = async event => {
  event.preventDefault();
  $('open').disabled = true;
  $('compat').disabled = true;
  try {
    const origin = normalizeOrigin($('origin').value);
    const entry = $('entry').value;
    const url = entryUrl(origin, entry);
    localStorage.setItem(key, JSON.stringify({ origin, entry }));
    if (!Capacitor.isNativePlatform()) {
      $('status').textContent = '网页预览已验证地址：' + url + '。应用内连接需安装移动应用；本预览不会访问服务。';
      return;
    }
    if (event.submitter?.id === 'compat') {
      await InAppBrowser.openInSystemBrowser({ url, options: DefaultSystemBrowserOptions });
      $('status').textContent = '已打开系统浏览器登录窗口，其登录状态与应用内窗口独立。';
      return;
    }
    if (android) {
      await RemoteBrowser.open({ url });
      $('status').textContent = '请在连接窗口中登录，并按提示输入电脑配对码。';
      return;
    }
    await InAppBrowser.openInWebView({ url, options: {
      ...DefaultWebViewOptions, showURL: true, showToolbar: true,
      showNavigationButtons: true, clearCache: false, clearSessionCache: false,
      closeButtonText: '返回',
      android: { ...DefaultWebViewOptions.android, hardwareBack: true, isIsolated: true }
    }});
    $('status').textContent = '已打开服务。登录失效时请在服务内重新登录。';
  } catch (error) { $('status').textContent = error.message || '打开失败，请检查地址与网络。'; }
  finally { $('open').disabled = false; $('compat').disabled = false; }
};
