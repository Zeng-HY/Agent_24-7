/* The sidebar's conversations, grouped the way the desktop apps group them: Codex and Claude; under each, its projects,
   named as on the desktop (most recently used first, 其他对话 last); under each project, its conversations, newest first.
   Tap Codex, Claude or a project to fold or unfold it; the folds are kept on this phone. Tap a conversation to open it:
   the chat is put in place and the drawer slides away over it. 10 per project at first, 显示更多 adds 30 at a time.
   Each project's ＋ opens 新建对话 with that app and project filled in; 其他对话's ＋ starts a conversation in no project.
   Data: GET /api/chat/projects (remote.py, chat_projects.py), read when the drawer opens, at most every 15 s.

   Flat outline folders and brand-colour marks; reduced motion preserves static navigation. */
(() => {
  const drawer = $('navSheet'), links = drawer && drawer.querySelector('.nav-links');
  if (!links) return;
  const FOLDS = 'lbr_sidebar_folds', MORE = 30, STALE = 15000;
  let folds = {}; try { folds = JSON.parse(localStorage.getItem(FOLDS) || '{}') || {}; } catch (e) {}
  let data = null, loadedAt = 0, loading = null, failed = '', fresh = '';
  const extra = new Map(); // "app|key" -> conversations added with 显示更多 since the last full read
  const box = el('div', 'nav-tree'); box.setAttribute('role', 'tree'); box.setAttribute('aria-label', '按项目分组的对话');
  links.append(box);
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
.fd,.mark{width:24px;height:24px;flex:none;overflow:visible;filter:none}
.fd{color:#606975;fill:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
.mark.code-symbol{color:#1e222a}.mark.claude{fill:#d97757}.mark.deepseek{fill:#4d6bfe}
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
  const folder = () => '<svg class="fd" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 8V6.5A2.5 2.5 0 0 1 5.5 4H9l2.5 2.5h7A2.5 2.5 0 0 1 21 9v8.5a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5V8Zm0 1h18"/></svg>';
  const LOOSE = '<svg class="fd loose" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5h12a3 3 0 0 1 3 3v8a3 3 0 0 1-3 3H9l-5 3V8a3 3 0 0 1 2-3Z"/></svg>';
  // Brand paths: Simple Icons (CC0), github.com/simple-icons/simple-icons, icons/{claude,deepseek}.svg.
  const MARK = {
    codex: `<svg class="mark code-symbol" viewBox="0 0 24 24" aria-hidden="true"><path d="m8 6-6 6 6 6m8-12 6 6-6 6m-3-14-2 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    claude: `<svg class="mark claude" viewBox="0 0 24 24" aria-hidden="true"><path d="m4.7144 15.9555 4.7174-2.6471.079-.2307-.079-.1275h-.2307l-.7893-.0486-2.6956-.0729-2.3375-.0971-2.2646-.1214-.5707-.1215-.5343-.7042.0546-.3522.4797-.3218.686.0608 1.5179.1032 2.2767.1578 1.6514.0972 2.4468.255h.3886l.0546-.1579-.1336-.0971-.1032-.0972L6.973 9.8356l-2.55-1.6879-1.3356-.9714-.7225-.4918-.3643-.4614-.1578-1.0078.6557-.7225.8803.0607.2246.0607.8925.686 1.9064 1.4754 2.4893 1.8336.3643.3035.1457-.1032.0182-.0728-.164-.2733-1.3539-2.4467-1.445-2.4893-.6435-1.032-.17-.6194c-.0607-.255-.1032-.4674-.1032-.7285L6.287.1335 6.6997 0l.9957.1336.419.3642.6192 1.4147 1.0018 2.2282 1.5543 3.0296.4553.8985.2429.8318.091.255h.1579v-.1457l.1275-1.706.2368-2.0947.2307-2.6957.0789-.7589.3764-.9107.7468-.4918.5828.2793.4797.686-.0668.4433-.2853 1.8517-.5586 2.9021-.3643 1.9429h.2125l.2429-.2429.9835-1.3053 1.6514-2.0643.7286-.8196.85-.9046.5464-.4311h1.0321l.759 1.1293-.34 1.1657-1.0625 1.3478-.8804 1.1414-1.2628 1.7-.7893 1.36.0729.1093.1882-.0183 2.8535-.607 1.5421-.2794 1.8396-.3157.8318.3886.091.3946-.3278.8075-1.967.4857-2.3072.4614-3.4364.8136-.0425.0304.0486.0607 1.5482.1457.6618.0364h1.621l3.0175.2247.7892.522.4736.6376-.079.4857-1.2142.6193-1.6393-.3886-3.825-.9107-1.3113-.3279h-.1822v.1093l1.0929 1.0686 2.0035 1.8092 2.5075 2.3314.1275.5768-.3218.4554-.34-.0486-2.2039-1.6575-.85-.7468-1.9246-1.621h-.1275v.17l.4432.6496 2.3436 3.5214.1214 1.0807-.17.3521-.6071.2125-.6679-.1214-1.3721-1.9246L14.38 17.959l-1.1414-1.9428-.1397.079-.674 7.2552-.3156.3703-.7286.2793-.6071-.4614-.3218-.7468.3218-1.4753.3886-1.9246.3157-1.53.2853-1.9004.17-.6314-.0121-.0425-.1397.0182-1.4328 1.9672-2.1796 2.9446-1.7243 1.8456-.4128.164-.7164-.3704.0667-.6618.4008-.5889 2.386-3.0357 1.4389-1.882.929-1.0868-.0062-.1579h-.0546l-6.3385 4.1164-1.1293.1457-.4857-.4554.0608-.7467.2307-.2429 1.9064-1.3114Z"/></svg>`,
    deepseek: `<svg class="mark deepseek" viewBox="0 0 24 24" aria-hidden="true"><path d="M23.748 4.651c-.254-.124-.364.113-.512.233-.051.04-.094.09-.137.137-.372.397-.806.657-1.373.626-.829-.046-1.537.214-2.163.848-.133-.782-.575-1.248-1.247-1.548-.352-.155-.708-.311-.955-.65-.172-.24-.219-.509-.305-.774-.055-.16-.11-.323-.293-.35-.2-.031-.278.136-.356.276-.313.572-.434 1.202-.422 1.84.027 1.436.633 2.58 1.838 3.393.137.094.172.187.129.323-.082.28-.18.553-.266.833-.055.179-.137.218-.328.14a5.5 5.5 0 0 1-1.737-1.179c-.857-.828-1.631-1.743-2.597-2.46a12 12 0 0 0-.689-.47c-.985-.957.13-1.743.387-1.836.27-.098.094-.433-.778-.428-.872.003-1.67.295-2.687.685a3 3 0 0 1-.465.136 9.6 9.6 0 0 0-2.883-.101c-1.885.21-3.39 1.1-4.497 2.622C.082 8.776-.231 10.854.152 13.02c.403 2.284 1.568 4.175 3.36 5.653 1.857 1.533 3.997 2.284 6.438 2.14 1.482-.085 3.132-.284 4.994-1.86.47.234.962.328 1.78.398.629.058 1.235-.031 1.705-.129.735-.155.684-.836.418-.961-2.155-1.004-1.682-.595-2.112-.926 1.095-1.295 2.768-3.598 3.284-6.733.05-.346.115-.834.108-1.114-.004-.171.035-.238.23-.257a4.2 4.2 0 0 0 1.545-.475c1.397-.763 1.96-2.016 2.093-3.517.02-.23-.004-.467-.247-.588M11.58 18.168c-2.088-1.642-3.101-2.183-3.52-2.16-.39.024-.32.472-.234.763.09.288.207.487.371.74.114.167.192.416-.113.603-.673.416-1.842-.14-1.897-.168-1.361-.801-2.5-1.86-3.301-3.306-.775-1.393-1.225-2.888-1.299-4.482-.02-.385.094-.522.477-.592a4.7 4.7 0 0 1 1.53-.038c2.131.311 3.946 1.264 5.467 2.774.868.86 1.525 1.887 2.202 2.89.72 1.066 1.494 2.082 2.48 2.915.348.291.626.513.892.677-.802.09-2.14.109-3.055-.615zm1.001-6.44a.306.306 0 0 1 .415-.287.3.3 0 0 1 .113.074.3.3 0 0 1 .086.214c0 .17-.136.307-.308.307a.303.303 0 0 1-.306-.307m3.11 1.596c-.2.081-.4.151-.591.16a1.25 1.25 0 0 1-.798-.254c-.274-.23-.47-.358-.551-.758a1.7 1.7 0 0 1 .015-.588c.07-.327-.007-.537-.238-.727-.188-.156-.426-.199-.689-.199a.6.6 0 0 1-.254-.078.253.253 0 0 1-.114-.358 1 1 0 0 1 .192-.21c.356-.202.767-.136 1.146.016.352.144.618.408 1.001.782.392.451.462.576.685.915.176.264.336.536.446.848.066.194-.02.353-.25.45"/></svg>`};

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
