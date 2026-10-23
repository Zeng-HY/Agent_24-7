/* The sidebar's conversations, grouped the way the desktop apps group them: Codex and Claude; under each, its projects,
   named as on the desktop (most recently used first, 其他对话 last); under each project, its conversations, newest first.
   Tap Codex, Claude or a project to fold or unfold it; the folds are kept on this phone. Tap a conversation to open it:
   the chat is put in place and the drawer slides away over it. 10 per project at first, 显示更多 adds 30 at a time.
   Each project's ＋ opens 新建对话 with that app and project filled in; 其他对话's ＋ starts a conversation in no project.
   Data: GET /api/chat/projects (remote.py, chat_projects.py), read when the drawer opens, at most every 15 s.

   Look (10-12, the plan the user picked: B, colours by name, restrained motion, no glass): things have colour and
   depth, actions stay thin lines. Each app has a solid mark; each project a two-layer folder, all in one grey (the user
   tried a colour per project first and preferred them plain, 10-12); 其他对话 is two stacked grey bubbles. Opening a group grows its rows in one after another while the folder lifts its front; one spring for all
   motion; with Reduce Motion it all just appears. */
(() => {
  const drawer = $('navSheet'), links = drawer && drawer.querySelector('.nav-links');
  if (!links) return;
  const FOLDS = 'lbr_sidebar_folds', MORE = 30, STALE = 15000;
  let folds = {}; try { folds = JSON.parse(localStorage.getItem(FOLDS) || '{}') || {}; } catch (e) {}
  let data = null, loadedAt = 0, loading = null, failed = '', fresh = '';
  const extra = new Map(); // "app|key" -> conversations added with 显示更多 since the last full read
  const box = el('div', 'nav-tree'); box.setAttribute('role', 'tree'); box.setAttribute('aria-label', '按项目分组的对话');
  links.append(box);
  // the icons' shared gloss (light at the top) and shade (a little dark at the bottom); not inside the drawer, which is
  // display:none while shut, and a gradient kept in a hidden drawing does not paint
  const defs = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  defs.setAttribute('width', '0'); defs.setAttribute('height', '0'); defs.setAttribute('aria-hidden', 'true'); defs.style.position = 'absolute';
  defs.innerHTML = '<defs><linearGradient id="lbrShine" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".5"/><stop offset=".55" stop-color="#fff" stop-opacity="0"/></linearGradient>'
    + '<linearGradient id="lbrShade" x1="0" y1="0" x2="0" y2="1"><stop offset=".55" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".14"/></linearGradient></defs>';
  document.body.append(defs);
  const E = 'cubic-bezier(.32,.72,0,1)'; // the one spring, as the drawer and the chat use
  const css = el('style');
  css.textContent = `.nav-tree{display:flex;flex-direction:column;padding-bottom:8px}
.tree-group{display:flex;flex-direction:column}
.tree-row{position:relative;display:flex;align-items:center;gap:9px;min-height:44px;padding:0 8px 0 12px;border-radius:12px;color:var(--text);cursor:pointer;-webkit-user-select:none;user-select:none;-webkit-touch-callout:none;outline:0;transition:background .16s}
.tree-row:active{background:rgba(29,35,48,.07)}.tree-row:focus-visible{box-shadow:inset 0 0 0 2px var(--blue)}
.tree-app{margin-top:12px;min-height:42px;font-size:14px;font-weight:600}
.tree-proj{font-size:15px;font-weight:500}
.tree-item{min-height:40px;padding-left:43px;font-size:14px}
.tree-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tree-name small{display:block;font-size:12px;color:var(--muted);overflow:hidden;text-overflow:ellipsis}
.tree-time{flex:none;font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
.tree-chev{flex:none;display:flex;color:var(--muted);transition:transform .34s ${E}}.tree-chev svg{width:16px;height:16px}
.tree-group.open>.tree-row .tree-chev{transform:rotate(90deg)}
.tree-more{min-height:40px;padding-left:43px;font-size:13px;color:var(--blue)}
.tree-note{font-size:13px;color:var(--muted);padding:8px 12px}
.tree-add{position:relative;z-index:3;flex:none;display:flex;align-items:center;justify-content:center;width:36px;height:36px;margin:-4px 0;border-radius:10px;color:var(--muted);outline:0;transition:transform .18s ${E},background .16s}
.tree-add svg{width:18px;height:18px}.tree-add:active{transform:scale(.82);background:rgba(29,35,48,.1)}.tree-add:focus-visible{box-shadow:inset 0 0 0 2px var(--blue)}
/* folding: the rows of an opening group grow in and arrive one after another; a closing group just goes */
.tree-kids{display:grid;grid-template-rows:0fr;transition:grid-template-rows .34s ${E}}
.tree-group.open>.tree-kids{grid-template-rows:1fr}
.tree-kids-in{overflow:hidden;min-height:0}
.tree-kids-in>*{opacity:0;transform:translateY(-5px);transition:opacity .2s ease,transform .34s ${E}}
.tree-group.open>.tree-kids>.tree-kids-in>*{opacity:1;transform:none;transition-delay:calc(var(--i,0)*24ms)}
/* icons */
.fd,.mark{width:24px;height:24px;flex:none;overflow:visible}
.fd{filter:drop-shadow(0 1px 1.1px rgba(40,50,70,.3))}
.fd .back{fill:#8d97a7}
.fd .face{fill:#bcc4cf}
.fd .paper{fill:#fff;transform-box:fill-box;transform-origin:50% 100%;transition:transform .34s ${E}}
.fd .front{transform-box:fill-box;transform-origin:50% 100%;transition:transform .34s ${E}}
.fd .lip{fill:none;stroke:#fff;stroke-opacity:.6;stroke-width:.7;stroke-linecap:round}
.tree-group.open>.tree-row .fd .front{transform:skewX(-13deg) scaleY(.82)}
.tree-group.open>.tree-row .fd .paper{transform:translateY(-1.8px)}
.fd.loose{filter:drop-shadow(0 1px 1.1px rgba(40,50,70,.3))}.fd.loose .b1{fill:#c3cad6}.fd.loose .b2{fill:#8792a4}
.mark{filter:drop-shadow(0 1px 1.2px rgba(20,24,33,.3))}
.mark .glyph{fill:none;stroke:#fff;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.mark.code-symbol{filter:none;color:#1e222a}.mark .m-codex{fill:#1e222a}.mark .m-claude{fill:oklch(.67 .145 42)}.mark .m-deepseek{fill:#4d6bfe}.mark .eye{fill:#fff}
/* running: a slow breathing ring round the green dot */
.tree-dot{position:absolute;left:26px;top:50%;width:7px;height:7px;margin-top:-3.5px;border-radius:50%;background:var(--green)}
.tree-dot::after{content:'';position:absolute;inset:0;border-radius:inherit;background:inherit;animation:lbrPing 1.8s ${E} infinite}
@keyframes lbrPing{0%{transform:scale(1);opacity:.55}100%{transform:scale(2.8);opacity:0}}
/* a conversation just made from the phone: lit up the next time the drawer shows it */
.tree-item.fresh{animation:lbrGlow 1.6s ease-out}
@keyframes lbrGlow{0%,30%{background:#fff4cc}100%{background:transparent}}
/* opening the drawer with a tap: its contents arrive one after another (navigation-ui.js adds lbr-entering) */
#navSheet .lbr-entering .nav-links>button,#navSheet .lbr-entering .nav-tree>.tree-group{animation:lbrRowIn .3s ${E} backwards;animation-delay:calc(var(--n,0)*24ms + 20ms)}
@keyframes lbrRowIn{from{opacity:0;transform:translateX(-10px)}}
#settingsBtn svg{transition:transform .46s ${E}}#settingsBtn.spin svg{transform:rotate(90deg)}`;
  document.head.append(css);
  const CHEV = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>';
  const PLUS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';
  const BACK = 'M2.75 6.25A1.5 1.5 0 0 1 4.25 4.75h4.9c.44 0 .86.2 1.14.55l.98 1.2h8.48a1.5 1.5 0 0 1 1.5 1.5V18a1.5 1.5 0 0 1-1.5 1.5H4.25A1.5 1.5 0 0 1 2.75 18z';
  const FACE = 'M2.75 9.6a1.5 1.5 0 0 1 1.5-1.5h15.5a1.5 1.5 0 0 1 1.5 1.5V18a1.5 1.5 0 0 1-1.5 1.5H4.25A1.5 1.5 0 0 1 2.75 18z';
  const folder = () => `<svg class="fd" viewBox="0 0 24 24" aria-hidden="true"><path class="back" d="${BACK}"/>`
    + `<rect class="paper" x="4.6" y="7.3" width="14.8" height="8" rx="1"/><g class="front"><path class="face" d="${FACE}"/>`
    + `<path d="${FACE}" fill="url(#lbrShine)"/><path d="${FACE}" fill="url(#lbrShade)"/><path class="lip" d="M3.9 8.9h16.2"/></g></svg>`;
  const BUBBLE = 'M5.25 8h9.5a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H9.4l-2.9 2.4V18H5.25a2 2 0 0 1-2-2v-6a2 2 0 0 1 2-2z';
  const LOOSE = `<svg class="fd loose" viewBox="0 0 24 24" aria-hidden="true"><path class="b1" d="M8.5 3.75h10a2 2 0 0 1 2 2v6.5a2 2 0 0 1-2 2h-1.2v2l-2.4-2H8.5a2 2 0 0 1-2-2v-6.5a2 2 0 0 1 2-2z"/>`
    + `<path class="b2" d="${BUBBLE}"/><path d="${BUBBLE}" fill="url(#lbrShine)"/></svg>`;
  const TILE = 'x="1.5" y="1.5" width="21" height="21" rx="6.2"';
  const MARK = {
    codex: `<svg class="mark code-symbol" viewBox="0 0 24 24" aria-hidden="true"><path d="m8 6-6 6 6 6m8-12 6 6-6 6m-3-14-2 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    claude: `<svg class="mark" viewBox="0 0 24 24" aria-hidden="true"><rect class="m-claude" ${TILE}/><rect ${TILE} fill="url(#lbrShine)"/><path class="glyph" d="M12 6.6v10.8M6.6 12h10.8M8.2 8.2l7.6 7.6M15.8 8.2l-7.6 7.6"/></svg>`,
    // DeepSeek's own blue with a curled whale, as Claude's orange and Codex's black (10-20)
    deepseek: `<svg class="mark" viewBox="0 0 24 24" aria-hidden="true"><rect class="m-deepseek" ${TILE}/><rect ${TILE} fill="url(#lbrShine)"/><path class="glyph" d="M6.4 10.6c.9 3.6 3.3 5.9 6.6 5.9 2.7 0 4.6-1.6 4.6-4 0-2.2-1.7-3.6-3.8-3.6-1.7 0-2.9 1-3.2 2.4M6.4 10.6 5.3 8.7M6.4 10.6l2-.6"/><circle class="eye" cx="15.3" cy="11.7" r=".85"/></svg>`};

  const folded = (key, open) => key in folds ? !folds[key] : !open; // apps start open, projects closed
  function setFold(key, open) { folds[key] = open; try { localStorage.setItem(FOLDS, JSON.stringify(folds)); } catch (e) {} }
  function when(ms) {
    if (!ms) return '';
    const d = new Date(ms), now = new Date(), s = (now - d) / 1000;
    if (s < 60) return '刚刚';
    if (s < 3600) return Math.floor(s / 60) + '分钟';
    if (d.toDateString() === now.toDateString()) return hhmm(d);
    if (d.toDateString() === new Date(now - 86400000).toDateString()) return '昨天';
    return (d.getFullYear() === now.getFullYear() ? '' : String(d.getFullYear()).slice(2) + '-') + (d.getMonth() + 1) + '-' + d.getDate();
  }
  // One row: a div acting as a button (a label inside it gives the iPhone's tick, see navigation-ui.js tapLabel)
  function row(cls, level, act) {
    const r = el('div', 'tree-row ' + cls); r.setAttribute('role', 'treeitem'); r.setAttribute('aria-level', String(level)); r.tabIndex = 0;
    r.onclick = act; r.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); act(); } };
    window.navigationUI?.tapLabel?.(r);
    return r;
  }
  function chev() { const c = el('span', 'tree-chev'); c.innerHTML = CHEV; return c; }
  // A group: its head row, and its rows below in a box that grows open and shut. All rows are in the page from the
  // start, so opening only flips a class (and the head's label stays in the page to pass the tap on to the tick).
  function group(kind, key, openAtFirst, lead, label, level) {
    const g = el('div', 'tree-group'), open = !folded(key, openAtFirst); g.dataset.key = key; g.classList.toggle('open', open);
    const head = row('tree-' + kind, level, () => setOpen(g, !g.classList.contains('open')));
    head.setAttribute('aria-expanded', String(open)); head.insertAdjacentHTML('afterbegin', lead); head.append(el('span', 'tree-name', label), chev());
    const kids = el('div', 'tree-kids'), inner = el('div', 'tree-kids-in'); kids.inert = !open; kids.setAttribute('role', 'group');
    kids.append(inner); g.append(head, kids);
    return [g, head, inner];
  }
  function setOpen(g, open) {
    setFold(g.dataset.key, open); g.classList.toggle('open', open);
    g.firstElementChild.setAttribute('aria-expanded', String(open)); g.querySelector(':scope>.tree-kids').inert = !open;
  }
  // A project's ＋: the 新建对话 sheet with this app and this project filled in; 其他对话's ＋ makes a conversation in no
  // project (Codex: a new folder under Documents\Codex; Claude: No folder). Above the row's own label, so the tap is its.
  function plus(app, p) {
    const b = el('span', 'tree-add'); b.innerHTML = PLUS; b.setAttribute('role', 'button'); b.tabIndex = 0;
    b.setAttribute('aria-label', p.projectless ? '新建不在项目里的 ' + (app === 'codex' ? 'Codex' : 'Claude') + ' 对话' : '在「' + p.name + '」新建对话');
    // not the row's: no fold. A click keeps its default, which is the label passing the tap on to the tick switch.
    const go = e => { e.stopPropagation(); window.newChatUI?.open({app, folder: p.folder, projectless: !!p.projectless, name: p.name}); };
    b.onclick = go; b.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(e); } };
    window.navigationUI?.tapLabel?.(b);
    return b;
  }
  function item(c) {
    const r = row('tree-item', 3, () => openItem(c)), name = el('span', 'tree-name', c.title);
    r.dataset.id = c.app + ':' + c.id;
    if (c.place) name.append(el('small', '', c.place));
    if (c.status === 'running' || c.status === 'waiting') { const dot = el('span', 'tree-dot'); dot.setAttribute('aria-label', c.status==='waiting'?'等待你处理':'运行中');if(c.status==='waiting')dot.style.background='var(--amber)';r.append(dot); }
    r.append(name, el('span', 'tree-time', when(c.updated)));
    return r;
  }
  function openItem(c) {
    const conv = {app: c.app, id: c.id, title: c.title, folder: c.folder, cwd: c.cwd, status: c.status, updated: c.updated};
    if (window.navigationUI?.openFromDrawer) navigationUI.openFromDrawer(() => openConv(conv)); else openConv(conv);
  }

  function render() {
    const keep = links.scrollTop;
    box.replaceChildren();
    if (!data) { box.append(el('div', 'tree-note', failed ? '读不到项目：' + failed : '读取中…')); return; }
    data.apps.forEach((app, n) => {
      const [ag, , apps] = group('app', 'app:' + app.app, true, MARK[app.app] || '', app.name, 1);
      ag.style.setProperty('--n', n + 1);
      if (!app.projects.length) apps.append(el('div', 'tree-note', '没有对话'));
      app.projects.forEach((p, i) => {
        const pk = app.app + '|' + p.key, [pg, ph, rows] = group('proj', 'p:' + pk, false, p.projectless ? LOOSE : folder(), p.name, 2);
        pg.style.setProperty('--i', Math.min(i, 10));
        if (p.folder || p.projectless) ph.insertBefore(plus(app.app, p), ph.querySelector('.tree-chev'));
        const seen = new Set(), list = [...p.items, ...(extra.get(pk) || [])].filter(c => !seen.has(c.id) && seen.add(c.id));
        list.forEach((c, j) => { const r = item(c); r.style.setProperty('--i', Math.min(j, 10)); rows.append(r); });
        if (list.length < p.count) {
          const m = row('tree-more', 3, () => more(app.app, p, list.length, m));
          m.append(el('span', 'tree-name', '显示更多（还有 ' + (p.count - list.length) + ' 个）')); m.style.setProperty('--i', Math.min(list.length, 10));
          rows.append(m);
        }
        apps.append(pg);
      });
      box.append(ag);
    });
    links.scrollTop = keep;
  }
  async function more(app, p, have, rowNode) {
    if (rowNode.dataset.busy) return; rowNode.dataset.busy = '1'; rowNode.querySelector('.tree-name').textContent = '读取中…';
    try {
      const j = await api('/api/chat/projects?app=' + app + '&key=' + encodeURIComponent(p.key) + '&offset=' + have + '&limit=' + MORE);
      const pk = app + '|' + p.key; extra.set(pk, [...(extra.get(pk) || []), ...j.items]); p.count = j.count;
    } catch (e) { toast('没读到更多对话：' + e.message, true); }
    render();
  }
  // Drawn once the drawer stands still. The PC answers in about 0.6 s and the drawer opens in 0.36 s, so the answer used
  // to arrive just after it stopped: the whole tree was rebuilt and its entrance played a second time, which the user saw
  // as the end of the opening stuttering (10-14). An answer like the last one leaves the rows as they are.
  function whenStill(draw) {
    const sheetBox = drawer.querySelector('.box');
    if (!sheetBox || !sheetBox.classList.contains('lbr-entering')) { draw(); return; }
    const watch = new MutationObserver(() => { if (!sheetBox.classList.contains('lbr-entering')) { watch.disconnect(); draw(); } });
    watch.observe(sheetBox, {attributes: true, attributeFilter: ['class']});
  }
  // A full read; projects opened further with 显示更多 come back as long as they were
  function load(force) {
    if (loading || (!force && data && Date.now() - loadedAt < STALE)) return loading;
    const wanted = [...extra].filter(([, v]) => v.length).map(([k, v]) => { const i = k.indexOf('|'); return [k.slice(0, i), k.slice(i + 1), v.length]; });
    loading = (async () => {
      const shown = () => JSON.stringify([data && data.apps, failed, [...extra]]), before = shown();  // not data.now, the PC's clock
      try {
        data = await api('/api/chat/projects' + (wanted.length ? '?more=' + encodeURIComponent(JSON.stringify(wanted)) : ''));
        loadedAt = Date.now(); failed = ''; extra.clear();
      } catch (e) { failed = e.message; }
      if (shown() !== before) await new Promise(done => whenStill(() => { try { render(); } finally { done(); } }));
      loading = null;
    })();
    return loading;
  }
  // The conversation made last from the phone, lit up and in view the next time the drawer opens (its groups unfold)
  function showFresh() {
    const r = fresh && box.querySelector(`.tree-item[data-id="${CSS.escape(fresh)}"]`);
    if (!r) return;
    fresh = '';
    for (let g = r.closest('.tree-group'); g; g = g.parentElement && g.parentElement.closest('.tree-group')) if (!g.classList.contains('open')) setOpen(g, true);
    r.classList.remove('fresh'); void r.offsetWidth; r.classList.add('fresh');
    setTimeout(() => r.scrollIntoView({block: 'nearest'}), 380);
  }
  // Read when the drawer opens (class is-open comes with every way of opening it), and once soon after the page loads
  new MutationObserver(() => { if (drawer.classList.contains('is-open')) Promise.resolve(load(false)).then(showFresh); }).observe(drawer, {attributes: true, attributeFilter: ['class']});
  // the gear turns a quarter as the settings come up
  const gear = $('settingsBtn');
  if (gear) gear.addEventListener('click', () => { gear.classList.add('spin'); setTimeout(() => gear.classList.remove('spin'), 520); });
  render();
  if (document.readyState === 'complete') setTimeout(() => load(false), 1500); else addEventListener('load', () => setTimeout(() => load(false), 1500), {once: true});
  window.sidebarUI = {load, render, highlight(id) { fresh = id; }};
})();
