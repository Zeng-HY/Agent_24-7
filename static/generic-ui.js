/* 通用的批准 / 回答卡片（第二批设计第三节）。
 * 卡片布局不是 codex.v1 / claude.v1 / deepseek.v1 的助手，控制态（GET /api/agents/<id>/state）里的
 * questions 每一项画一张卡：批准卡（kind: approval）和提问卡（kind: question），答复走
 * POST /api/agents/<id>/answer。只画自己画的东西（#cvOpts 里 owner 为 generic 的节点），
 * 不碰三家画在同一处的卡片。样式复用 codex-ui.js 的 .codex-card / .card-title / .option-card /
 * .card-actions，颜色一律用现有变量，不新增颜色。已选、已填的答案只留在内存里。
 */
(() => {
  'use strict';

  const DETAIL_LINES = 12;       // detail 超过 12 行折叠
  const owned = [];              // 自己画进 #cvOpts 的节点
  const drafts = new Map();      // 对话 key -> {labels, text, busy, error}
  let painted = '';              // 上一次画的内容，没变就不重画（保住输入框焦点）
  let current = '';              // 上一次画的是哪个对话

  const uid = () => [...crypto.getRandomValues(new Uint8Array(16))].map(v => v.toString(16).padStart(2, '0')).join('');
  const chatKeyOf = me => me.app + ':' + me.id;

  function store(me) {
    const key = chatKeyOf(me);
    let st = drafts.get(key);
    if (!st) { st = { labels: {}, text: {}, busy: '', error: '' }; drafts.set(key, st); }
    return st;
  }

  // 卡片标题：title，没有就用第一题的 header，再没有就用「<助手名> 等你批准 / 有问题要问你」。
  function titleOf(me, card) {
    if (typeof card.title === 'string' && card.title.trim()) return card.title.trim();
    const first = (card.questions || [])[0] || {};
    if (typeof first.header === 'string' && first.header.trim()) return first.header.trim();
    return Agents.name(me.app) + (card.kind === 'approval' ? ' 等你批准' : ' 有问题要问你');
  }

  // 此刻能不能答：批准看 approve、提问看 answer；过时的卡片也灰掉。
  function whyBlocked(me, card, control) {
    const cap = card.kind === 'approval' ? 'approve' : 'answer';
    if (!Agents.canNow(me.app, cap, control)) return Agents.noteNow(me.app, cap, control) || '请在电脑上处理';
    const expires = Number(card.expires_at || 0);
    if (expires > 0 && Date.now() > expires) return '已过时，请在电脑上处理';
    return '';
  }

  // 一问的答案：点了选项就是选项文字，写了字就是写的字（写字会清掉已点的选项）。
  function answerOf(st, q) {
    const labels = st.labels[q.id] || [];
    if (labels.length) return labels.slice();
    const text = String(st.text[q.id] || '').trim();
    return text ? [text] : [];
  }

  function allAnswered(card, st) {
    return (card.questions || []).every(q => answerOf(st, q).length > 0);
  }

  function clear() {
    for (const node of owned.splice(0)) { try { node.remove(); } catch (e) {} }
    painted = '';
    current = '';
  }

  function detailBlock(card) {
    if (typeof card.detail !== 'string' || !card.detail) return null;
    const lines = card.detail.split('\n');
    const box = el('div', 'gc-detail');
    let open = false;
    const more = el('button', 'gc-more');
    more.type = 'button';
    const label = () => (open ? '收起' : '展开全部 ' + lines.length + ' 行');
    function draw() {
      box.textContent = open ? lines.join('\n') : lines.slice(0, DETAIL_LINES).join('\n');
      box.classList.toggle('gc-open', open);
      more.textContent = label();
    }
    if (lines.length <= DETAIL_LINES) { draw(); return { box, more: null }; }
    more.onclick = () => { open = !open; draw(); };
    draw();
    return { box, more };
  }

  async function submit(me, control, card, st) {
    if (st.busy || whyBlocked(me, card, control)) return;
    const answers = {};
    for (const q of card.questions || []) answers[String(q.id)] = answerOf(st, q);
    st.busy = '正在提交…';
    st.error = '';
    paint(me, control, true);
    const body = { id: me.id, request_id: uid(), question_id: card.id, answers };
    if (card.answer_revision) body.answer_revision = card.answer_revision;
    try {
      const result = await api('/api/agents/' + encodeURIComponent(me.app) + '/answer', body);
      st.busy = '';
      st.labels = {}; st.text = {};
      toast((result && result.text) || '已提交');
      paint(me, control, true);
      await window.genericAgentUI?.refresh(me, true);
    } catch (e) {
      // 失败：原因写在卡片下面，已选、已填的内容不动。
      st.busy = '';
      st.error = (e && e.message) || '没有提交成功';
      paint(me, control, true);
    }
  }

  function paintApproval(me, control, card, st) {
    const wrap = el('div', 'codex-card');
    const title = el('div', 'card-title', titleOf(me, card));
    title.append(el('span', 'card-state', '等你批准'));
    wrap.append(title);
    const detail = detailBlock(card);
    if (detail) { wrap.append(detail.box); if (detail.more) wrap.append(detail.more); }
    const q = (card.questions || [])[0] || {};
    if (q.question) wrap.append(el('div', 'gc-question', q.question));
    const why = whyBlocked(me, card, control);
    const busy = !!st.busy;
    const actions = el('div', 'card-actions');
    for (const option of q.options || []) {
      const label = String((option && option.label) || '');
      if (!label) continue;
      const b = el('button', '', busy ? '正在提交…' : label);
      b.type = 'button';
      b.disabled = busy || !!why;
      b.onclick = () => {
        st.labels[q.id] = [label];
        st.text[q.id] = '';
        submit(me, control, card, st);
      };
      actions.append(b);
    }
    wrap.append(actions);
    if (why) wrap.append(el('div', 'gc-note', why));
    if (st.error) wrap.append(el('div', 'gc-note gc-error', st.error));
    return wrap;
  }

  function paintQuestion(me, control, card, st, direct) {
    const wrap = el('div', 'codex-card');
    const heading = titleOf(me, card);
    const title = el('div', 'card-title', heading);
    title.append(el('span', 'card-state', '等你回答'));
    wrap.append(title);
    const detail = detailBlock(card);
    if (detail) { wrap.append(detail.box); if (detail.more) wrap.append(detail.more); }
    const why = whyBlocked(me, card, control);
    const busy = !!st.busy;
    for (const q of card.questions || []) {
      const block = el('div', 'gc-q');
      // 标题已经用了第一题的 header 时不再重复一遍。
      if (q.header && q.header !== q.question && q.header !== heading) block.append(el('div', 'gc-head', q.header));
      block.append(el('b', '', q.question || ''));
      const multiple = !!q.isMultiple;
      const chosen = st.labels[q.id] || [];
      const typed = String(st.text[q.id] || '');
      for (const option of q.options || []) {
        const label = String((option && option.label) || '');
        if (!label) continue;
        const row = el('button', 'option-card gc-choice');
        row.type = 'button';
        row.setAttribute('role', multiple ? 'checkbox' : 'radio');
        row.setAttribute('aria-checked', String(!typed && chosen.includes(label)));
        row.append(el('span', 'choice-dot'));
        const caption = el('span', '');
        caption.append(el('b', '', label));
        if (option.description) caption.append(el('small', '', String(option.description)));
        row.append(caption);
        row.disabled = busy || !!why;
        row.onclick = () => {
          if (direct) {
            // 只有一题、单选、没有手写、不是密码题时，点选项直接提交。
            st.labels[q.id] = [label];
            st.text[q.id] = '';
            submit(me, control, card, st);
            return;
          }
          const now = st.labels[q.id] || [];
          st.labels[q.id] = multiple ? (now.includes(label) ? now.filter(v => v !== label) : now.concat([label])) : [label];
          st.text[q.id] = '';
          paint(me, control, true);
        };
        block.append(row);
      }
      if (!direct && (q.isOther === true || q.isSecret === true)) {
        const field = el(q.isSecret ? 'input' : 'textarea', 'gc-other');
        if (q.isSecret) field.type = 'password';
        field.placeholder = q.isSecret ? '写下答案（只用于这一次提交）' : '也可以自己填写';
        field.setAttribute('aria-label', (q.question || '答案') + '：自己填写');
        field.value = typed;
        field.disabled = busy || !!why;
        field.addEventListener('input', () => {
          const value = field.value;
          if ((st.text[q.id] || '') === value) return;
          st.text[q.id] = value;
          if (value.trim()) st.labels[q.id] = [];
          // 只更新「提交」的可点状态，不重画整张卡（免得输入框丢焦点）。
          const go = wrap.querySelector('.gc-submit');
          if (go) go.disabled = busy || !!why || !allAnswered(card, st);
        });
        block.append(field);
      }
      if (!direct && !(q.isOther === true || q.isSecret === true) && !(q.options || []).length) {
        block.append(el('div', 'gc-note', '这一题没有可选的答案，请在电脑上回答。'));
      }
      wrap.append(block);
    }
    if (!direct) {
      const actions = el('div', 'card-actions');
      const go = el('button', 'big gc-submit', busy ? '提交中…' : '提交');
      go.type = 'button';
      go.disabled = busy || !!why || !allAnswered(card, st);
      go.onclick = () => submit(me, control, card, st);
      actions.append(go);
      wrap.append(actions);
    }
    if (why) wrap.append(el('div', 'gc-note', why));
    if (st.error) wrap.append(el('div', 'gc-note gc-error', st.error));
    return wrap;
  }

  function paint(me, control, force) {
    const box = $('cvOpts');
    if (!box || !me) return;
    if (!Agents.isGenericLayout(me.app)) { clear(); return; }
    const cards = (Array.isArray(control && control.questions) ? control.questions : [])
      .filter(c => c && c.status === 'pending' && Array.isArray(c.questions) && c.questions.length);
    if (!cards.length) { clear(); return; }
    const st = store(me);
    const sig = JSON.stringify([me.app, me.id, st.busy, st.error,
      cards.map(c => [c.id, c.kind, c.status, c.title, c.detail, c.expires_at, c.answer_revision, c.questions]),
      (control && control.capabilities_now) || null, (control && control.capability_notes) || null]);
    if (!force && painted === sig && current === chatKeyOf(me) && owned.length && owned.every(n => n.isConnected)) return;
    // 只清自己画的，别人的卡片留着。
    for (const node of owned.splice(0)) { try { node.remove(); } catch (e) {} }
    const wrap = el('div', 'gc-wrap');
    wrap.dataset.owner = 'generic';
    for (const card of cards) {
      const q = (card.questions || [])[0] || {};
      const single = (card.questions || []).length === 1;
      const direct = card.kind !== 'approval' && single && !q.isMultiple && q.isOther !== true && q.isSecret !== true;
      wrap.append(card.kind === 'approval'
        ? paintApproval(me, control, card, st)
        : paintQuestion(me, control, card, st, direct));
    }
    box.append(wrap);
    owned.push(wrap);
    painted = sig;
    current = chatKeyOf(me);
  }

  const css = el('style');
  css.id = 'genericCardsStyle';
  css.textContent = [
    '.gc-wrap{margin:6px 0}',
    '.gc-detail{font:13px/1.55 ui-monospace,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0;padding:8px 10px;border-radius:10px;background:var(--bg);max-height:240px;overflow:hidden}',
    '.gc-detail.gc-open{max-height:none}',
    '.gc-more{border:0;background:transparent;color:var(--blue);padding:6px 0;font-size:13px}',
    '.gc-question{font-size:15px;margin:8px 0}',
    '.gc-q{margin:12px 0 0}.gc-q>b{display:block;font-size:15px;font-weight:600;margin:0 0 6px}',
    '.gc-head{font-size:13px;color:var(--muted);margin:0 0 4px}',
    '.gc-other{width:100%;box-sizing:border-box;min-height:44px;padding:9px 12px;border:1px solid var(--line);border-radius:12px;font:inherit;font-size:15px;background:#fff;color:var(--text);resize:vertical}',
    '.gc-choice{gap:10px;align-items:flex-start}.gc-choice b{font-weight:500}',
    '.gc-note{font-size:13px;color:var(--muted);margin-top:8px}.gc-note.gc-error{color:var(--red)}',
  ].join('');
  document.head.append(css);

  window.genericCards = { paint, clear };
})();
