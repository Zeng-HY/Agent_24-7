// 设置 → 手机通知 (notify.py): an iPhone gets them through Bark (paste its address), an Android phone in the ntfy app,
// which subscribes to this computer itself (ntfy_feed.py; turned on here); a computer shows both. Send one to try,
// turn it off, see what happened to the last turns. And the link a notification opens (/?open=codex:<id>) opens that
// conversation.
(function () {
  'use strict';

  const params = new URLSearchParams(location.search);
  const target = params.get('open');
  if (target) {  // the link is used once: a refresh later shows the page as it was left
    params.delete('open');
    const rest = params.toString();
    try { history.replaceState(history.state, '', location.pathname + (rest ? '?' + rest : '') + location.hash); } catch (e) {}
    const at = target.indexOf(':'), app = target.slice(0, at), id = target.slice(at + 1);
    const go = async () => {
      if (!Agents.validId(app) || !id || (cur && cur.app === app && cur.id === id)) return;
      try { openConv(await api('/api/chat?app=' + encodeURIComponent(app) + '&id=' + encodeURIComponent(id) + '&n=60')); }
      catch (e) { toast('没能打开这个对话：' + e.message, true); }
    };
    if (document.readyState === 'complete') go(); else addEventListener('load', go, {once: true});
  }

  const body = document.getElementById('settingsBody');
  if (!body) return;
  // Bark is an iPhone app, so an Android phone shows only ntfy; a computer shows both, Bark last
  const system = phoneSystem(), iPhone = system === 'iphone';
  const ntfyGroup = el('div', 'setting-group'), ntfyNote = el('div', 'setting-note');
  const barkGroup = el('div', 'setting-group'), barkNote = el('div', 'setting-note'), recentNote = el('div', 'setting-note');
  // 定时任务 governs 遥应's own notices and Bark too, so it shows on every phone and on a computer (11-24)
  const autoGroup = el('div', 'setting-group'), autoNote = el('div', 'setting-note');
  ntfyGroup.dataset.channel = ntfyNote.dataset.channel = 'ntfy';
  barkGroup.dataset.channel = barkNote.dataset.channel = 'bark';
  body.append(el('div', 'setting-title', '手机通知'), ...(iPhone ? [] : [ntfyGroup, ntfyNote]),
    ...(system === 'android' ? [] : [barkGroup, barkNote]), autoGroup, autoNote, recentNote);
  let state = {configured: false, server: '', recent: [], automations: 'codex',
               ntfy: {on: false, topic: 'agent-remote', server: '', listening: 0, last_seen: ''}};
  let busy = false, draft = '';

  function row(text, onclick, cls) {  // an action, so no › (that one means another page opens)
    const b = el('button', 'menu-row setting-row' + (cls ? ' ' + cls : ''));
    b.type = 'button'; b.append(el('span', '', text)); b.onclick = onclick;
    return b;
  }
  function copyRow(label, value) {  // what is typed into the ntfy app; a tap copies it
    const b = el('button', 'menu-row setting-row'), name = el('span', '', label), shown = el('span', 'setting-value', value);
    name.style.flex = 'none'; shown.style.cssText = 'flex:1;min-width:0;text-align:right;overflow-wrap:anywhere';
    b.type = 'button'; b.append(name, shown);
    b.onclick = () => (navigator.clipboard ? navigator.clipboard.writeText(value) : Promise.reject())
      .then(() => toast('已复制'), () => toast('没复制成功，照着抄：' + value, true));
    return b;
  }
  function choiceRow(label, value, onclick) {  // the current choice on the right; a tap changes it
    const b = el('button', 'menu-row setting-row'), name = el('span', '', label), shown = el('span', 'setting-value', value);
    shown.style.cssText = 'flex:none;text-align:right';
    b.type = 'button'; b.append(name, shown); b.onclick = onclick;
    return b;
  }
  function paint() {
    paintNtfy();
    paintBark();
    paintAutomations();
    const recent = (state.recent || []).slice(0, 3);
    recentNote.textContent = recent.length ? '最近：' + recent.map(r => r.time + ' ' + r.text).join('\n') : '';
    recentNote.hidden = !recent.length;
  }
  function relayMode(n) {  // opened through the relay (/d/…) or from another origin than the computer itself
    if (location.pathname.indexOf('/d/') === 0) return true;
    if (!n.server) return false;
    try { return new URL(n.server).origin !== location.origin; } catch (e) { return false; }
  }
  function paintNtfy() {
    // 11-24: only this computer's Tailscale address works as an ntfy server; the origin the page came from may be
    // the relay's, which asks for a sign-in the app never has.
    const n = state.ntfy || {}, server = (n.server || '').replace(/\/+$/, ''), relay = relayMode(n);
    ntfyGroup.replaceChildren();
    if (n.on) {
      const on = el('div', 'setting-row'); on.append(el('span', '', '已开 · ntfy'), el('span', 'setting-value', n.listening ? '手机连着' : '手机没连着'));
      ntfyGroup.append(on);
    }
    ntfyGroup.append(copyRow('主题', n.topic || 'agent-remote'));
    if (server) ntfyGroup.append(copyRow('服务器', server));
    else {  // no Tailscale address: nothing to copy, and saying so is better than the page's origin
      const none = el('div', 'setting-row'), shown = el('span', 'setting-value', '这台电脑没有 Tailscale 地址');
      shown.style.cssText = 'flex:1;min-width:0;text-align:right;overflow-wrap:anywhere';
      none.append(el('span', '', '服务器'), shown);
      ntfyGroup.append(none);
    }
    if (n.on) ntfyGroup.append(row('试推一条', () => call('/api/notify/test', {channel: 'ntfy'})), row('关掉', () => call('/api/notify/ntfy', {on: false}), 'danger'));
    else ntfyGroup.append(row('打开并试推一条', () => call('/api/notify/ntfy', {on: true})));
    let note = !n.on ? '安卓手机用 ntfy App 收。① 装 ntfy（Google Play、F-Droid 都有）；② 在 ntfy 里点 ＋，主题名称填上面的主题，' +
        '勾上「使用其他服务器」，地址填上面的服务器，点「订阅」；③ 回到这里点「打开并试推一条」。点主题或服务器就能复制。手机上的 Tailscale 要一直连着才收得到。'
      : n.listening ? '对话做完时推到 ntfy App。手机正开着那个对话时不推。'
      : '现在没有手机连着：看看 ntfy 里订阅了上面的主题和服务器没有，手机上的 Tailscale 连着没有。' +
        (n.last_seen ? '上次连着是 ' + n.last_seen + '。' : '') + '没连着时做完的对话，连上后会补推（12 小时内的）。';
    if (n.on) note += ' ntfy 那条「正在监听通知」可以藏起来：长按它，只关「后台服务」这一类，通知照常收。';
    if (relay) note += ' 经中转用遥应的安卓手机：新版遥应安卓会自带通知，不用 ntfy；现在想用 ntfy，手机要连着 Tailscale。';
    ntfyNote.textContent = note;
  }
  const AUTOMATION_WORDS = {codex: '跟 Codex 一样', failed: '只推失败的', off: '不推'};
  function paintAutomations() {
    const value = state.automations || 'codex';
    autoGroup.replaceChildren(choiceRow('Codex 定时任务', AUTOMATION_WORDS[value] || AUTOMATION_WORDS.codex,
      () => changeAutomations(value)));
    autoNote.textContent = '跟 Codex 一样：Codex 在电脑上提醒的才推；任务在 Codex 里设了「只在失败时通知」的，成功不推。';
  }
  async function changeAutomations(current) {
    const order = ['codex', 'failed', 'off'], next = order[(order.indexOf(current) + 1) % order.length];
    await call('/api/notify/automations', {mode: next});
  }
  function paintBark() {
    barkGroup.replaceChildren();
    if (state.configured) {
      const on = el('div', 'setting-row'); on.append(el('span', '', '已开'), el('span', 'setting-value', state.server));
      barkGroup.append(on, row('试推一条', () => call('/api/notify/test', {channel: 'bark'})), row('关掉', () => call('/api/notify', {address: ''}), 'danger'));
      barkNote.textContent = iPhone ? '对话做完时推到这部手机。手机正开着那个对话时不推。' : '对话做完时推到装了 Bark 的 iPhone。';
      return;
    }
    const field = el('div', 'setting-row'), input = el('input');
    input.type = 'text'; input.placeholder = '粘贴 Bark 的推送地址'; input.autocomplete = 'off'; input.spellcheck = false;
    input.setAttribute('autocapitalize', 'off'); input.setAttribute('aria-label', 'Bark 的推送地址');
    input.value = draft; input.oninput = () => { draft = input.value; };
    field.append(input);
    barkGroup.append(field, row('保存并试推一条', () => {
      if (!input.value.trim()) { toast('先把 Bark 的推送地址贴进来', true); input.focus(); return; }
      call('/api/notify', {address: input.value});
    }));
    barkNote.textContent = iPhone ? '对话做完时推到这部手机。先在 iPhone 上装 Bark，在它首页复制 https://api.day.app/ 开头的地址，贴在上面。' :
      'iPhone 用 Bark 收：在 iPhone 上装 Bark，把它首页 https://api.day.app/ 开头的地址贴在上面。';
  }
  async function call(path, data) {
    if (busy) return; busy = true; body.querySelectorAll('[data-channel] button').forEach(b => b.disabled = true);
    try { const r = await api(path, data, 30000); toast(r.text || '好了'); draft = ''; await load(); }
    catch (e) { toast(e.message, true); }
    finally { busy = false; body.querySelectorAll('[data-channel] button').forEach(b => b.disabled = false); }
  }
  async function load() {  // painted again only when something changed, so a box being typed in stays as it is
    let next = state;
    try { next = {...state, ...await api('/api/notify')}; } catch (e) {}
    if (JSON.stringify(next) !== JSON.stringify(state)) { state = next; paint(); }
  }
  paint();
  load();
  document.getElementById('settingsBtn')?.addEventListener('click', load);  // the latest outcomes when it opens
  // back from the ntfy app, where the subscription was just added: whether the phone is connected now
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
})();
