// 设置 → 手机通知 (notify.py): paste Bark's address, send one to try, turn it off, see what happened to the last
// turns. And the link a notification opens (/?open=codex:<id>) opens that conversation.
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
      if (!['codex', 'claude'].includes(app) || !id || (cur && cur.app === app && cur.id === id)) return;
      try { openConv(await api('/api/chat?app=' + app + '&id=' + encodeURIComponent(id) + '&n=60')); }
      catch (e) { toast('没能打开这个对话：' + e.message, true); }
    };
    if (document.readyState === 'complete') go(); else addEventListener('load', go, {once: true});
  }

  const body = document.getElementById('settingsBody');
  if (!body) return;
  const group = el('div', 'setting-group'), note = el('div', 'setting-note');
  body.append(el('div', 'setting-title', '手机通知'), group, note);
  let state = {configured: false, server: '', recent: []}, busy = false, draft = '';
  // Bark is an iPhone app: on an Android phone (or a computer) the notes say pushes reach only an iPhone
  const iPhone = phoneSystem() === 'iphone';

  function row(text, onclick, cls) {  // an action, so no › (that one means another page opens)
    const b = el('button', 'menu-row setting-row' + (cls ? ' ' + cls : ''));
    b.type = 'button'; b.append(el('span', '', text)); b.onclick = onclick;
    return b;
  }
  function paint() {
    group.replaceChildren(); note.replaceChildren();
    if (state.configured) {
      const on = el('div', 'setting-row'); on.append(el('span', '', '已开'), el('span', 'setting-value', state.server));
      group.append(on, row('试推一条', () => call('/api/notify/test', {})), row('关掉', () => call('/api/notify', {address: ''}), 'danger'));
      const recent = (state.recent || []).slice(0, 3);
      note.textContent = recent.length ? '最近：' + recent.map(r => r.time + ' ' + r.text).join('\n') :
        (iPhone ? '对话做完时推到这部手机。' : '对话做完时推到装了 Bark 的 iPhone，安卓手机目前收不到。') + '正在用这台电脑、或手机正开着那个对话时不推。';
      return;
    }
    const field = el('div', 'setting-row'), input = el('input');
    input.type = 'text'; input.placeholder = '粘贴 Bark 的推送地址'; input.autocomplete = 'off'; input.spellcheck = false;
    input.setAttribute('autocapitalize', 'off'); input.setAttribute('aria-label', 'Bark 的推送地址');
    input.value = draft; input.oninput = () => { draft = input.value; };
    field.append(input);
    group.append(field, row('保存并试推一条', () => {
      if (!input.value.trim()) { toast('先把 Bark 的推送地址贴进来', true); input.focus(); return; }
      call('/api/notify', {address: input.value});
    }));
    note.textContent = iPhone ? '对话做完时推到这部手机。先在 iPhone 上装 Bark，在它首页复制 https://api.day.app/ 开头的地址，贴在上面。' :
      '目前只支持 iPhone 上的 Bark，安卓手机还收不到。有 iPhone 的话，在 iPhone 上装 Bark，把它首页 https://api.day.app/ 开头的地址贴在上面，对话做完时推到那部 iPhone。';
  }
  async function call(path, data) {
    if (busy) return; busy = true; group.querySelectorAll('button').forEach(b => b.disabled = true);
    try { const r = await api(path, data, 30000); toast(r.text || '好了'); draft = ''; await load(); }
    catch (e) { toast(e.message, true); }
    finally { busy = false; group.querySelectorAll('button').forEach(b => b.disabled = false); }
  }
  async function load() {  // painted again only when something changed, so a box being typed in stays as it is
    let next = state;
    try { next = {...state, ...await api('/api/notify')}; } catch (e) {}
    if (JSON.stringify(next) !== JSON.stringify(state)) { state = next; paint(); }
  }
  paint();
  load();
  document.getElementById('settingsBtn')?.addEventListener('click', load);  // the latest outcomes when it opens
})();
