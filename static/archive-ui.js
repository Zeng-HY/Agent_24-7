/* 左滑归档 (10-20). On the conversation list a row slides left under the finger and uncovers 归档 behind it, in two stops
   as Mail's and Telegram's do: let go after a short slide (or flick) and the row stays open on a 归档 button, which
   archives when tapped; slide on past about half the row and 归档 turns darker, and letting go there archives at once.
   Then the row slides off, the list closes up, and a bar at the bottom says 对话已归档 with 撤销 for six seconds.
   The archive is made on the computer at once (archives.py); 撤销 restores it there. Codex and DeepSeek only
   for now (Claude's comes later); a running one springs back and says why.
   设置 → 已归档对话 lists the archived ones: 恢复 brings one back; Codex ones can be ticked and deleted, after a
   confirmation, for good. DeepSeek has no delete, so its rows only restore. The main list never deletes. */
(() => {
  const list = $('convList');
  const APPS = ['codex', 'deepseek'], NAMES = {codex: 'Codex', claude: 'Claude', deepseek: 'DeepSeek'};
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const EASE = 'cubic-bezier(.32,.72,0,1)';
  const BUTTON = 88, HOLD = 30, GIVE = 0.3, GAP = 20;  // 归档 opens this wide; past it the finger goes HOLD px while the row goes GIVE of that
  const SETTLE_MS = 300, OFF_MS = 380, CLOSE_MS = 320, OFF_EASE = 'cubic-bezier(.33,.7,.35,1)', CLOSE_EASE = 'cubic-bezier(.4,0,.2,1)';
  const hidden = new Set();    // rows archived from here, kept off the list until 撤销 (a refresh would bring them back)
  const pending = new Map();   // key -> the archive request under way
  const css = el('style'); css.textContent = `
    #convList{position:relative}
    .conv.swiping{background:var(--card);position:relative;z-index:3;will-change:transform}
    .swipe-under{position:absolute;left:0;right:0;z-index:2;background:#6366f1;color:#fff;font-size:14px;font-weight:600;overflow:hidden;
      pointer-events:none;transition:background-color .2s}.swipe-under.armed{background:#4338ca}
    .swipe-label{position:absolute;left:0;top:0;bottom:0;display:flex;align-items:center;gap:5px;white-space:nowrap;will-change:transform}
    .swipe-label svg{width:20px;height:20px;transition:transform .22s cubic-bezier(.34,1.56,.64,1)}.swipe-under.armed .swipe-label svg{transform:scale(1.2)}
    .swipe-under .swipe-btn{position:absolute;top:0;right:0;bottom:0;width:${BUTTON}px;-webkit-tap-highlight-color:transparent}.swipe-under.open .swipe-btn{pointer-events:auto}
    .swipe-under.collapse,.conv.collapse{transition:height ${CLOSE_MS}ms ${CLOSE_EASE},padding ${CLOSE_MS}ms ${CLOSE_EASE},border-width ${CLOSE_MS}ms ${CLOSE_EASE},opacity ${CLOSE_MS}ms;overflow:hidden}
    .conv.returning{animation:convBack .36s ${EASE}}@keyframes convBack{from{transform:translateX(-24%);opacity:0}to{transform:none;opacity:1}}
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
  // A refresh brings back what the server still lists for a moment: rows archived here stay off until 撤销. While a row
  // is out of place (under the finger, open on 归档, gliding, leaving) the list is not rebuilt, or the 10 s refresh would
  // snap it shut under the finger; it is rebuilt once the row is back or gone.
  const baseRender = window.renderConvs;
  let s = null;      // the row out of place: {row, item, under, label, button, w, home, mark, f, armed, state: drag|open|shut|leaving, timer}
  let touch = null;  // this finger: {x, y, samples, decided, base, row, item, caught, shut}
  let stale = false, frame = 0, quietUntil = 0;
  window.renderConvs = function () {
    if (s && s.row.isConnected) { stale = true; return; }
    s = null; stale = false;
    if (hidden.size) convItems = convItems.filter(v => !hidden.has(convKey(v)));
    return baseRender.apply(this, arguments);
  };
  function settled(me) { if (me && s !== me) return; s = null; if (stale) { stale = false; renderConvs(); } }

  // ---- the gesture (second version, 10-20). The user: other apps first stop on a 归档 button you tap yourself, and only
  // a longer slide archives the whole row; ours went at once and too fast, before one could react, and 归档 smeared
  // when pulled fast. So: the row follows the finger and uncovers 归档, which waits in its button; once the button is
  // all out the row holds a moment (the next HOLD px of finger move it GIVE as much), then goes on, 归档 now keeping
  // beside its edge. Letting go settles it open on the button (tap it to archive) or, when barely moved or flung back,
  // shut; a tap elsewhere, a scroll or a drag back shuts it. Past the mark (about half the row) 归档 darkens and its
  // icon swells: letting go there archives. A flick never archives (the first version did after 50 px). Nothing that
  // follows the finger has a CSS transition (归档's 0.14 s one trailed behind a fast finger: the smear), and each
  // move is painted once a frame. The slide off, the pause and the closing up take about 0.8 s.
  function outFor(d) {  // how far the row is out (px leftward) when the finger has gone d px from where a shut row was
    if (d <= 0) return Math.max(-8, d / 5);
    const f = d <= BUTTON ? d : d <= BUTTON + HOLD ? BUTTON + (d - BUTTON) * GIVE : d - HOLD * (1 - GIVE), most = s.w * 0.86;
    return f > most ? most + (f - most) / 4 : f;
  }
  const fingerFor = f => f <= BUTTON ? f : f <= BUTTON + HOLD * GIVE ? BUTTON + (f - BUTTON) / GIVE : f + HOLD * (1 - GIVE);
  const labelAt = (me, f) => Math.min(me.home, me.w - f + GAP);  // in its button, or beside the row's edge once that has passed it
  const px = v => Math.round(v * devicePixelRatio) / devicePixelRatio;  // whole screen pixels, so the text stays sharp as it moves
  function begin(row, item) {
    const under = el('div', 'swipe-under'), label = el('span', 'swipe-label'), button = el('div', 'swipe-btn');
    label.innerHTML = icon('archive') + '<span>归档</span>'; under.setAttribute('aria-hidden', 'true'); under.append(label, button);
    under.style.top = row.offsetTop + 'px'; under.style.height = row.offsetHeight + 'px'; under.style.borderRadius = getComputedStyle(row).borderRadius;
    row.before(under); row.classList.add('swiping'); row.style.transition = 'none';
    button.addEventListener('click', tapped); window.navigationUI?.tapLabel?.(button);  // the iPhone ticks on a tap of it
    const w = row.offsetWidth, cw = label.offsetWidth;
    s = {row, item, under, label, button, w, home: w - BUTTON + (BUTTON - cw) / 2, mark: Math.round(Math.max(BUTTON + 70, Math.min(w * 0.48, w - 80))),
      f: 0, armed: false, state: 'drag', timer: 0};
    label.style.transform = `translate3d(${px(s.home)}px,0,0)`;
  }
  function schedule() { if (!frame) frame = requestAnimationFrame(paint); }
  function paint() {
    frame = 0; if (!s || s.state !== 'drag') return;
    const f = s.f, armed = f >= s.mark;
    if (armed !== s.armed) { s.armed = armed; s.under.classList.toggle('armed', armed); if (armed) window.navigationUI?.haptic?.(); }  // Android only
    s.row.style.transform = `translate3d(${px(-f)}px,0,0)`;
    s.label.style.transform = `translate3d(${px(labelAt(s, f))}px,0,0)`;
    s.label.style.opacity = String(Math.max(0.3, Math.min(1, f / 64)));
  }
  function stopPainting() { if (frame) { cancelAnimationFrame(frame); frame = 0; } }
  function glide(f, ms, done) {  // the row, and 归档 with it, settles f px out; then done()
    const me = s; me.f = f; stopPainting(); clearTimeout(me.timer);
    const t = ms ? `transform ${ms}ms ${EASE}` : 'none';
    me.row.style.transition = t; me.label.style.transition = ms ? `${t},opacity ${ms}ms` : 'none';
    me.row.style.transform = `translate3d(${-f}px,0,0)`;
    me.label.style.transform = `translate3d(${px(labelAt(me, f))}px,0,0)`; me.label.style.opacity = f ? '1' : '0.3';
    me.timer = setTimeout(() => { if (s === me) done?.(me); }, ms + 20);
  }
  function hold() {  // a finger on a row that is open or gliding: it stops where it is
    const me = s; clearTimeout(me.timer); stopPainting();
    try { me.f = -new DOMMatrixReadOnly(getComputedStyle(me.row).transform).m41; } catch (e) {}
    me.state = 'drag'; me.under.classList.remove('open'); me.row.style.transition = me.label.style.transition = 'none';
    me.row.style.transform = `translate3d(${px(-me.f)}px,0,0)`; me.label.style.transform = `translate3d(${px(labelAt(me, me.f))}px,0,0)`;
  }
  function settleOpen() {
    s.state = 'open'; s.armed = false; s.under.classList.remove('armed'); s.under.classList.add('open');
    glide(BUTTON, reduced() ? 0 : SETTLE_MS);
  }
  function shut() {
    if (!s || s.state === 'leaving') return;
    s.state = 'shut'; s.armed = false; s.under.classList.remove('open', 'armed');
    glide(0, reduced() ? 0 : SETTLE_MS, me => { me.row.classList.remove('swiping'); me.row.style.transition = me.row.style.transform = ''; me.under.remove(); settled(); });
  }
  function drop() {  // back at once, no motion: the page is leaving the list
    if (!s || s.state === 'leaving') return; const me = s; clearTimeout(me.timer); stopPainting(); touch = null;
    me.row.classList.remove('swiping'); me.row.style.transition = me.row.style.transform = ''; me.under.remove(); settled();
  }
  function tapped(e) {
    e.stopPropagation(); if (!s || s.state !== 'open') return;
    if (s.item.status === 'running') { shut(); toast('这个对话正在运行，先停止这一轮再归档', true); return; }
    leave();
  }
  function speed(samples) {  // px per ms over the last ~80 ms; negative is leftward
    const last = samples.at(-1); let first = last;
    for (let i = samples.length - 1; i >= 0 && last.t - samples[i].t < 80; i--) first = samples[i];
    return last.t > first.t ? (last.x - first.x) / (last.t - first.t) : 0;
  }
  list.addEventListener('touchstart', e => {
    touch = null; quietUntil = 0;  // a new touch: what it clicks is its own
    if (e.touches.length !== 1 || cur || overlays.length || window.workspaceUI?.composing) return;
    const t = e.touches[0], at = {x: t.clientX, y: t.clientY, samples: [{x: t.clientX, t: e.timeStamp}], decided: false};
    if (s) {
      if (s.state === 'leaving') return;  // the next swipe waits until the list has closed up
      const mine = s.row.contains(e.target) || s.under.contains(e.target);
      if (s.state === 'shut') { if (mine) touch = {...at, base: 0, row: s.row, item: s.item}; return; }  // already going back: a tap is a tap, a drag catches it
      if (!mine) { shut(); touch = {...at, shut: true}; return; }  // open: a first touch elsewhere only shuts it
      if (s.button.contains(e.target)) { touch = {...at, base: 0, row: s.row, item: s.item}; return; }  // a tap archives, a drag moves it
      hold(); touch = {...at, caught: true, base: fingerFor(s.f)}; return;
    }
    const row = e.target.closest?.('.conv'), item = itemOf(row); if (!item) return;
    touch = {...at, base: 0, row, item};
  }, {passive: true});
  list.addEventListener('touchmove', e => {
    const tt = touch; if (!tt) return; const t = e.touches[0], dx = t.clientX - tt.x, dy = t.clientY - tt.y;
    if (tt.shut) {  // sideways it neither swipes another row nor pulls the drawer out; up or down it scrolls
      if (!tt.decided && Math.hypot(dx, dy) >= 8) tt.decided = Math.abs(dx) > Math.abs(dy) ? 'side' : 'scroll';
      if (tt.decided === 'side' && e.cancelable) { e.preventDefault(); e.stopPropagation(); }
      return;
    }
    if (!tt.decided) {
      if (Math.hypot(dx, dy) < 8) return;
      if (!(Math.abs(dx) > 1.3 * Math.abs(dy) && e.cancelable) || (!s && dx > 0)) { touch = null; if (s) shut(); return; }  // a scroll, or the drawer's pull
      if (!s && !tt.row.isConnected) { touch = null; return; }  // the row went back and the list was rebuilt meanwhile
      tt.decided = true;
      if (!s) begin(tt.row, tt.item);
      else if (!tt.caught) { hold(); tt.base = fingerFor(s.f) + dx; }  // taken where it is, without a jump
    }
    e.preventDefault(); e.stopPropagation();  // the drawer's own handler further up must not take a rightward drag of an open row
    tt.samples.push({x: t.clientX, t: e.timeStamp}); if (tt.samples.length > 12) tt.samples.shift();
    s.f = outFor(tt.base - dx); schedule();
  }, {passive: false});
  list.addEventListener('touchend', e => {
    const tt = touch; touch = null; if (!tt) return;
    if (tt.shut || (tt.caught && !tt.decided)) { if (e.cancelable) e.preventDefault(); if (tt.caught) shut(); return; }  // that tap only shut the open row
    if (!tt.decided || !s) return;  // a tap: on a row it opens the conversation, on 归档 it archives
    quietUntil = performance.now() + 400; stopPainting();
    const v = speed(tt.samples);
    if (s.f >= s.mark && v < 0.3) {  // past the mark, and not flung back
      if (s.item.status === 'running') { shut(); toast('这个对话正在运行，先停止这一轮再归档', true); return; }
      leave();
    } else if (v > 0.3 || (v > -0.3 && s.f < BUTTON / 2)) shut();
    else settleOpen();
  }, {passive: false});
  list.addEventListener('touchcancel', () => { const tt = touch; touch = null; if (tt && s && s.state === 'drag') shut(); });
  // the lift after a drag is not a tap: a click that follows it at once, before any new touch, is dropped
  list.addEventListener('click', e => { if (performance.now() < quietUntil) { quietUntil = 0; e.stopImmediatePropagation(); e.preventDefault(); } }, true);
  // a touch anywhere off the list shuts an open row and goes on to do its own thing
  document.addEventListener('touchstart', e => { if (s && s.state !== 'leaving' && !list.contains(e.target)) shut(); }, {capture: true, passive: true});
  let width = innerWidth;
  addEventListener('resize', () => { if (innerWidth !== width) { width = innerWidth; drop(); } });
  document.addEventListener('visibilitychange', () => { if (document.hidden) drop(); });
  const baseOpen = window.openConv;
  window.openConv = function () { drop(); return baseOpen.apply(this, arguments); };

  // off to the left, a moment's pause, then the gap closes and the bar comes up; the archive goes to the computer meanwhile
  function leave() {
    const me = s; me.state = 'leaving'; me.under.classList.remove('open'); clearTimeout(me.timer); stopPainting();
    const key = convKey(me.item), index = convItems.findIndex(v => convKey(v) === key);
    hidden.add(key); archive(me.item, index);
    const gone = () => { me.under.remove(); if (hidden.has(key)) { me.row.remove(); convItems = convItems.filter(v => convKey(v) !== key); } settled(me); };
    if (reduced()) { showBar(me.item, index); gone(); return; }
    me.label.style.transition = 'none';  // 归档 stays where it is while the row goes
    me.row.style.transition = `transform ${OFF_MS}ms ${OFF_EASE}`; me.row.style.transform = `translate3d(${-(me.w + 24)}px,0,0)`;
    me.timer = setTimeout(() => {
      if (s !== me) return gone();  // the list was rebuilt meanwhile
      if (!hidden.has(key)) {  // refused, or 撤销 already: it slides back instead
        me.state = 'shut'; me.armed = false; me.under.classList.remove('armed');
        glide(0, SETTLE_MS, () => { me.row.classList.remove('swiping'); me.row.style.transition = me.row.style.transform = ''; me.under.remove(); settled(); });
        return;
      }
      showBar(me.item, index);
      for (const n of [me.row, me.under]) { n.style.transition = ''; n.style.height = n.offsetHeight + 'px'; n.classList.add('collapse'); }
      me.row.offsetHeight;  // the start height takes effect first, so that the change to 0 is animated (the row's inline transition is gone too)
      for (const n of [me.row, me.under]) { n.style.height = '0px'; n.style.paddingTop = n.style.paddingBottom = '0px'; n.style.borderTopWidth = '0px'; n.style.opacity = '0'; }
      me.timer = setTimeout(gone, CLOSE_MS + 40);
    }, OFF_MS + 80);
  }

  // ---- the computer, and 撤销
  async function archive(item, index) {
    const key = convKey(item);
    const job = api('/api/chat/archive', {app: item.app, id: item.id}, 60000);
    pending.set(key, job);  // the bar comes up once the row is off (leave)
    try { await job; window.sidebarUI?.load?.(true); }
    catch (e) { comeBack(item, index); hideBar(item); toast('没归档：' + e.message, true); }
    finally { if (pending.get(key) === job) pending.delete(key); }
  }
  function comeBack(item, index) {
    const key = convKey(item); hidden.delete(key);
    if (!convItems.some(v => convKey(v) === key)) convItems.splice(Math.max(0, Math.min(index, convItems.length)), 0, item);
    renderConvs();
    const row = [...list.querySelectorAll('.conv')].find(n => n.dataset.key === key);
    if (row && !reduced() && !row.classList.contains('swiping')) { row.classList.add('returning'); setTimeout(() => row.classList.remove('returning'), 360); }
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
