/* 左滑归档 (10-20). On the conversation list a row slides left under the finger and shows 归档 behind it; let go past the
   mark (or flick) and it slides off, the list closes up, and a bar at the bottom says 对话已归档 with 撤销 for six
   seconds. The archive is made on the computer at once (archives.py); 撤销 restores it there. Codex and DeepSeek only
   for now (Claude's comes later); a running one springs back and says why.
   设置 → 已归档对话 lists the archived ones: 恢复 brings one back; Codex ones can be ticked and deleted, after a
   confirmation, for good. DeepSeek has no delete, so its rows only restore. The main list never deletes. */
(() => {
  const list = $('convList');
  const APPS = ['codex', 'deepseek'], NAMES = {codex: 'Codex', claude: 'Claude', deepseek: 'DeepSeek'};
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const EASE = 'cubic-bezier(.32,.72,0,1)';
  const hidden = new Set();    // rows archived from here, kept off the list until 撤销 (a refresh would bring them back)
  const pending = new Map();   // key -> the archive request under way
  const css = el('style'); css.textContent = `
    #convList{position:relative}
    .conv.swiping{background:var(--card);position:relative;z-index:3;will-change:transform}
    .swipe-under{position:absolute;left:0;right:0;z-index:2;display:flex;align-items:center;justify-content:flex-end;gap:6px;padding:0 20px;
      background:#6366f1;color:#fff;font-size:14px;font-weight:600;overflow:hidden;pointer-events:none;border-radius:10px;transition:background .15s}
    .swipe-label{display:flex;align-items:center;gap:6px;transition:transform .14s ${EASE}}
    .swipe-under svg{width:20px;height:20px;transition:transform .18s ${EASE}}.swipe-under.armed{background:#4f46e5}.swipe-under.armed svg{transform:scale(1.18)}
    .swipe-under.collapse,.conv.collapse{transition:height .24s ${EASE},padding .24s ${EASE},margin .24s ${EASE},opacity .2s;overflow:hidden}
    .conv.returning{animation:convBack .32s ${EASE}}@keyframes convBack{from{transform:translateX(-24%);opacity:0}to{transform:none;opacity:1}}
    .undo-bar{position:fixed;left:12px;right:12px;bottom:calc(16px + env(safe-area-inset-bottom));z-index:90;display:flex;align-items:center;gap:10px;
      padding:6px 6px 6px 16px;border-radius:16px;background:#1f2430;color:#fff;box-shadow:0 8px 28px rgba(15,23,42,.28);transform:translateY(160%);opacity:0;
      transition:transform .3s ${EASE},opacity .2s;max-width:520px;margin:0 auto}
    .undo-bar.show{transform:none;opacity:1}.undo-bar .undo-text{flex:1;min-width:0;font-size:14px;line-height:1.4}.undo-bar small{display:block;color:#aab3c5;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .undo-bar button{flex:none;border:0;background:transparent;color:#9fb8ff;font-size:15px;font-weight:700;min-height:44px;padding:8px 14px;border-radius:12px}.undo-bar button:active{background:#2c3342}
    #archivedSheet .box{height:min(calc(var(--overlay-height,100dvh) - 40px),760px);max-height:none}#archivedSheet .sh-body{flex:1;min-height:0;overflow:hidden;gap:8px;padding-bottom:0}
    .arc-note{font-size:12px;color:var(--muted);line-height:1.6;margin:0;flex:none}.arc-list{flex:1;min-height:0;overflow:auto;overscroll-behavior:contain;margin:0 -14px;border-top:1px solid var(--line)}
    .arc-row{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--line);min-height:60px}
    .arc-pick{flex:none;width:44px;height:44px;margin:-6px 0 -6px -10px;border:0;background:transparent;padding:0;display:flex;align-items:center;justify-content:center}
    .arc-pick span{width:22px;height:22px;border:1.5px solid #c4c9d4;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff}.arc-pick svg{width:14px;height:14px;opacity:0}
    .arc-pick[aria-pressed=true] span{background:var(--red);border-color:var(--red)}.arc-pick[aria-pressed=true] svg{opacity:1}.arc-pick:disabled{visibility:hidden}
    .arc-main{flex:1;min-width:0}.arc-main b{display:block;font-size:15px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.arc-main small{display:block;font-size:12px;color:var(--muted);margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .arc-main .badge{margin-right:6px;vertical-align:1px}.arc-restore{flex:none;font-size:13px;font-weight:500;padding:8px 12px;border-radius:999px;min-height:36px}
    .arc-empty{padding:28px 16px;color:var(--muted);font-size:14px;text-align:center;line-height:1.7;white-space:pre-line}.arc-head{padding:10px 14px 6px;font-size:12px;color:var(--muted);font-weight:600;background:var(--bg)}
    .arc-foot{display:flex;gap:8px;padding:10px 14px;border-top:1px solid var(--line);flex:none}.arc-foot button{flex:1;min-height:48px;border-radius:14px;font-size:15px}
    .arc-foot .arc-delete{background:var(--red);border-color:var(--red);color:#fff}.arc-foot button:disabled{opacity:.45}`;
  document.head.append(css);
  ICONS.archive = 'M3 4h18v4H3zM5 8v12h14V8M10 12h4';

  // ---- which rows slide: a Codex or DeepSeek conversation of its own (not a group, a child, or a search hit's child)
  function itemOf(row) {
    if (!row || !row.dataset.key || row.matches('.conv-child,.conv-group,.conv-fold,.conv-more')) return null;
    const item = convItems.find(v => convKey(v) === row.dataset.key);
    return item && !item.group && !item.kind && APPS.includes(item.app) ? item : null;
  }
  // a refresh brings back what the server still lists for a moment: rows archived here stay off until 撤销
  const baseRender = window.renderConvs;
  window.renderConvs = function () { if (hidden.size) convItems = convItems.filter(v => !hidden.has(convKey(v))); return baseRender.apply(this, arguments); };

  // ---- the gesture
  let g = null;  // {row, item, x, y, t, dx, decided, under, width, armed, samples}
  function underFor(row) {
    const u = el('div', 'swipe-under'); u.innerHTML = '<span class="swipe-label">' + icon('archive') + '<span>归档</span></span>'; u.setAttribute('aria-hidden', 'true');
    u.style.top = row.offsetTop + 'px'; u.style.height = row.offsetHeight + 'px'; row.before(u); return u;
  }
  function place(dx) {
    const w = g.width, limit = -w * 0.72, x = dx < limit ? limit + (dx - limit) * 0.25 : Math.min(0, dx);  // past ~3/4 it drags heavier
    const mark = Math.min(w * 0.36, 150), armed = -x > mark, label = g.under.firstChild;
    g.row.style.transform = `translate3d(${x}px,0,0)`;
    // before the mark 归档 grows clearer at the right; past it, it rides along the row's edge, as Mail's does
    label.style.opacity = String(Math.min(1, 0.35 + 0.65 * -x / mark));
    label.style.transform = armed ? `translate3d(${Math.min(0, x + 34 + label.offsetWidth)}px,0,0)` : '';
    if (armed !== g.armed) { g.armed = armed; g.under.classList.toggle('armed', armed); if (armed) window.navigationUI?.haptic?.(); }
  }
  function speed(s) {  // px per ms over the last ~80 ms; negative is leftward
    const last = s.at(-1); let first = last;
    for (let i = s.length - 1; i >= 0 && last.t - s[i].t < 80; i--) first = s[i];
    return last.t > first.t ? (last.x - first.x) / (last.t - first.t) : 0;
  }
  list.addEventListener('touchstart', e => {
    g = null; if (e.touches.length !== 1 || cur || overlays.length || window.workspaceUI?.composing) return;
    const row = e.target.closest?.('.conv'), item = itemOf(row); if (!item || row.classList.contains('collapse')) return;
    const t = e.touches[0]; g = {row, item, x: t.clientX, y: t.clientY, dx: 0, decided: false, armed: false, samples: [{x: t.clientX, t: e.timeStamp}]};
  }, {passive: true});
  list.addEventListener('touchmove', e => {
    if (!g) return; const t = e.touches[0], dx = t.clientX - g.x, dy = t.clientY - g.y;
    if (!g.decided) {
      if (Math.hypot(dx, dy) < 8) return;
      if (!(dx < 0 && -dx > 1.3 * Math.abs(dy) && e.cancelable)) { g = null; return; }  // a scroll, or the drawer's rightward pull
      g.decided = true; g.width = g.row.offsetWidth; g.under = underFor(g.row); g.row.classList.add('swiping'); g.row.style.transition = 'none';
    }
    e.preventDefault(); g.dx = dx; g.samples.push({x: t.clientX, t: e.timeStamp}); if (g.samples.length > 12) g.samples.shift();
    place(dx);
  }, {passive: false});
  function release(commit) {
    const s = g; g = null; if (!s?.decided) return;
    const fling = commit && speed(s.samples) < -0.6 && -s.dx > 50;
    // the lift is not a tap on the row: a click that follows at once is swallowed, a later one is not
    const swallow = e => { e.stopImmediatePropagation(); e.preventDefault(); };
    s.row.addEventListener('click', swallow, true); setTimeout(() => s.row.removeEventListener('click', swallow, true), 450);
    if (commit && (s.armed || fling)) {
      if (s.item.status === 'running') { springBack(s); toast('这个对话正在运行，先停止这一轮再归档', true); return; }
      slideOff(s);
    } else springBack(s);
  }
  list.addEventListener('touchend', () => { if (g) release(true); });
  list.addEventListener('touchcancel', () => { if (g) release(false); });
  function springBack(s) {
    s.row.style.transition = reduced() ? 'none' : `transform .28s ${EASE}`; s.row.style.transform = '';
    const done = () => { s.row.classList.remove('swiping'); s.row.style.transition = ''; s.under.remove(); };
    if (reduced()) done(); else setTimeout(done, 300);
  }
  // off to the left, then the gap closes; the archive goes to the computer meanwhile
  function slideOff(s) {
    const key = convKey(s.item), index = convItems.findIndex(v => convKey(v) === key);
    hidden.add(key); archive(s.item, index);
    const collapse = () => {
      for (const n of [s.row, s.under]) { n.style.height = n.offsetHeight + 'px'; n.classList.add('collapse'); }
      requestAnimationFrame(() => { for (const n of [s.row, s.under]) { n.style.height = '0px'; n.style.paddingTop = n.style.paddingBottom = '0px'; n.style.opacity = '0'; n.style.borderTopWidth = '0px'; } });
      setTimeout(() => { s.under.remove(); if (hidden.has(key)) { s.row.remove(); convItems = convItems.filter(v => convKey(v) !== key); } }, 260);
    };
    if (reduced()) { s.under.remove(); s.row.remove(); convItems = convItems.filter(v => convKey(v) !== key); return; }
    s.row.style.transition = `transform .22s ${EASE}`; s.row.style.transform = `translate3d(${-s.width - 24}px,0,0)`;
    setTimeout(collapse, 200);
  }

  // ---- the computer, and 撤销
  async function archive(item, index) {
    const key = convKey(item);
    const job = api('/api/chat/archive', {app: item.app, id: item.id}, 60000);
    pending.set(key, job); showBar(item, index);
    try { await job; window.sidebarUI?.load?.(true); }
    catch (e) { comeBack(item, index); hideBar(item); toast('没归档：' + e.message, true); }
    finally { if (pending.get(key) === job) pending.delete(key); }
  }
  function comeBack(item, index) {
    const key = convKey(item); hidden.delete(key);
    if (!convItems.some(v => convKey(v) === key)) convItems.splice(Math.max(0, Math.min(index, convItems.length)), 0, item);
    renderConvs();
    const row = [...list.querySelectorAll('.conv')].find(n => n.dataset.key === key);
    if (row && !reduced()) { row.classList.add('returning'); setTimeout(() => row.classList.remove('returning'), 360); }
  }
  async function undo(item, index) {
    hideBar(item); const key = convKey(item), job = pending.get(key);
    comeBack(item, index);  // back on the list at once; the computer follows
    if (job) { try { await job; } catch (e) { return; } }  // still archiving: wait; it failed: it is back already
    try { await api('/api/chat/unarchive', {app: item.app, id: item.id}, 90000); window.sidebarUI?.load?.(true); toast('已恢复'); }
    catch (e) { hidden.add(key); convItems = convItems.filter(v => convKey(v) !== key); renderConvs(); toast('没恢复：' + e.message, true); }
  }
  const bar = el('div', 'undo-bar'); bar.id = 'archiveUndo'; bar.setAttribute('role', 'status'); bar.setAttribute('aria-live', 'polite');
  const barText = el('div', 'undo-text'), barButton = el('button', '', '撤销'); barButton.type = 'button';
  bar.append(barText, barButton); document.body.append(bar);
  let barItem = null, barTimer = 0;
  function showBar(item, index) {
    barItem = item; barText.replaceChildren(document.createTextNode('对话已归档'), el('small', '', item.title || ''));
    barButton.onclick = () => undo(item, index); bar.classList.add('show'); clearTimeout(barTimer); barTimer = setTimeout(() => hideBar(item), 6000);
  }
  function hideBar(item) { if (item && barItem !== item) return; barItem = null; clearTimeout(barTimer); bar.classList.remove('show'); }

  // ---- 设置 → 已归档对话
  const settings = $('settingsBody');
  if (settings) {
    const group = el('div', 'setting-group'), open = el('button', 'menu-row setting-row');
    open.type = 'button'; open.id = 'archivedOpen'; open.append(el('span', '', '已归档对话'), el('span', 'go', '›')); open.onclick = openArchived;
    group.append(open); settings.prepend(el('div', 'setting-title', '对话'), group);
  }
  const sheet = el('div', 'sheet'); sheet.id = 'archivedSheet'; sheet.setAttribute('aria-label', '已归档对话');
  sheet.innerHTML = '<div class="box"><div class="sh-head"><b>已归档对话</b><button class="icon-btn" aria-label="关闭">' + icon('close') + '</button></div>'
    + '<div class="sh-body"><p class="arc-note" id="arcNote"></p><div class="arc-list" id="arcList"></div></div>'
    + '<div class="arc-foot"><button id="arcAll" type="button">全选</button><button id="arcDelete" class="arc-delete" type="button" disabled>删除</button></div></div>';
  document.body.append(sheet); sheet.querySelector('.sh-head button').onclick = () => closeSheet(sheet.id); sheet.addEventListener('click', e => { if (e.target === sheet) closeSheet(sheet.id); });
  let archivedData = null, picked = new Set(), busy = false;
  const pickKey = v => v.app + ':' + v.id;
  async function openArchived() {
    picked = new Set(); archivedData = null; paintArchived(); openSheet(sheet.id);
    try { archivedData = await api('/api/chat/archived', null, 20000); } catch (e) { archivedData = {items: [], problems: [e.message], apps: [], deletable: []}; }
    paintArchived();
  }
  function paintArchived() {
    const box = $('arcList'), data = archivedData; box.replaceChildren();
    const apps = data?.apps || [], deletable = new Set(data?.deletable || []);
    $('arcNote').textContent = !data ? '' : [apps.includes('codex') ? 'Codex 的可以恢复，也可以勾选后删除；删除后电脑上也找不回来。' : '',
      apps.includes('deepseek') ? 'DeepSeek 没有删除对话的功能，只能恢复。' : '', hasApp('claude') ? 'Claude 的对话还不能从手机归档。' : ''].filter(Boolean).join('');
    if (!data) { box.append(el('div', 'arc-empty', '读取中…')); paintFoot(); return; }
    for (const p of data.problems || []) box.append(el('div', 'arc-empty', '读不到 ' + p));
    if (!data.items.length && !(data.problems || []).length) box.append(el('div', 'arc-empty', '没有已归档的对话。\n在对话列表里把一行往左滑，就能归档。'));
    let app = '';
    for (const v of data.items) {
      if (v.app !== app) { app = v.app; box.append(el('div', 'arc-head', NAMES[app] || app)); }
      const row = el('div', 'arc-row'), pick = el('button', 'arc-pick'), main = el('div', 'arc-main'), restore = el('button', 'arc-restore', '恢复');
      pick.type = restore.type = 'button'; pick.innerHTML = '<span>' + icon('check') + '</span>';
      const can = deletable.has(v.app) && v.can_delete; pick.disabled = !can || busy; pick.setAttribute('aria-pressed', String(picked.has(pickKey(v))));
      pick.setAttribute('aria-label', (picked.has(pickKey(v)) ? '不删除 ' : '选中删除 ') + v.title);
      pick.onclick = () => { const k = pickKey(v); if (picked.has(k)) picked.delete(k); else picked.add(k); paintArchived(); };
      main.append(el('b', '', v.title), el('small', '', [v.folder, v.archived_at ? '归档于 ' + ago(v.archived_at) : v.updated ? '最后活动 ' + ago(v.updated) : ''].filter(Boolean).join(' · ')));
      restore.disabled = busy; restore.onclick = () => restoreOne(v);
      row.append(pick, main, restore); box.append(row);
    }
    paintFoot();
  }
  function paintFoot() {
    const can = (archivedData?.items || []).filter(v => v.can_delete && (archivedData.deletable || []).includes(v.app));
    $('arcAll').disabled = busy || !can.length; $('arcAll').textContent = can.length && can.every(v => picked.has(pickKey(v))) ? '全不选' : '全选';
    $('arcDelete').disabled = busy || !picked.size; $('arcDelete').textContent = picked.size ? '删除（' + picked.size + '）' : '删除';
  }
  $('arcAll').onclick = () => { const can = (archivedData?.items || []).filter(v => v.can_delete); const all = can.every(v => picked.has(pickKey(v))); picked = all ? new Set() : new Set(can.map(pickKey)); paintArchived(); };
  $('arcDelete').onclick = async () => {
    const items = (archivedData?.items || []).filter(v => picked.has(pickKey(v))); if (!items.length || busy) return;
    if (!(await askConfirm('删除这 ' + items.length + ' 个对话？删除后在电脑上也找不回来。'))) return;
    busy = true; paintArchived();
    try {
      const r = await api('/api/chat/delete', {items: items.map(v => ({app: v.app, id: v.id})), confirmed: true}, 120000);
      const failed = (r.results || []).filter(x => !x.ok);
      toast(failed.length ? '删了 ' + r.deleted + ' 个，' + failed.length + ' 个没删：' + failed[0].error : '已删除 ' + r.deleted + ' 个对话', !!failed.length);
    } catch (e) { toast('没删除：' + e.message, true); }
    busy = false; picked = new Set(); await openArchivedRefresh();
  };
  async function restoreOne(v) {
    if (busy) return; busy = true; paintArchived();
    try { await api('/api/chat/unarchive', {app: v.app, id: v.id}, 90000); toast('已恢复，回到对话列表里了'); hidden.delete(pickKey(v)); window.sidebarUI?.load?.(true); loadConvs(); }
    catch (e) { toast('没恢复：' + e.message, true); }
    busy = false; await openArchivedRefresh();
  }
  async function openArchivedRefresh() {
    try { archivedData = await api('/api/chat/archived', null, 20000); } catch (e) { toast(e.message, true); }
    for (const k of [...picked]) if (!(archivedData?.items || []).some(v => pickKey(v) === k)) picked.delete(k);
    paintArchived();
  }
  window.archiveUI = {openArchived, get hidden() { return [...hidden]; }};
})();
