// Voice input for the message box. While recording, the box itself becomes the recorder: what you say
// shows up in it as you talk (recognised on the PC by voice_local.py), with ✕ to drop it and ✓ to keep
// it. The words are then put in the box, and with 录音后自动整理 on (设置, the gear in the drawer) the cloud
// model (voice.py) rewrites them in place a moment later. Nothing is ever sent by itself.
//   tap the microphone: talk as long as you like, then tap ✓
//   hold the microphone: talk, let go to keep the words, slide up and let go to drop them
// Browsers allow the microphone only on secure pages (https).
(() => {
  // "voice": false in this computer's remote_config.json (window.MACHINE, 10-13): no microphone and no voice settings
  if (window.MACHINE && window.MACHINE.voice === false) { window.voiceUI = {recording: false, busy: false, finish() {}, cancel() {}, openTerms() {}}; return; }
  const input = document.getElementById('cvText');
  const row = input && input.closest('.cv-row');
  const bottom = row && row.closest('.cv-bottom');
  if (!row || !bottom) return;
  const RATE = 16000, PIECE = 4000, MAX_SECONDS = 300, HOLD_MS = 350, CANCEL_PX = 70;
  // 录音后自动整理, set in 设置; on unless turned off there. The 整理 button the recording bar had until 10-12 kept its
  // choice under lbr_voice_tidy, and the user's phone had it off; the setting starts again from on.
  const TIDY_KEY = 'lbr_setting_voice_tidy';
  let tidy = true;
  try { tidy = localStorage.getItem(TIDY_KEY) !== '0'; localStorage.removeItem('lbr_voice_tidy'); } catch (e) {}
  let rec = null;   // the recording in progress
  let press = null; // the finger (or mouse) on the button
  let busy = false; // finishing: last pieces, recognition
  let pillTimer = 0;

  const style = document.createElement('style');
  style.textContent = `
    .cv-bottom{position:relative}
    .cv-row.has-mic .composer-tools{right:104px}
    .mic-btn{position:absolute;right:54px;bottom:8px;z-index:2;width:40px;height:40px;min-height:40px;padding:9px;border:0;border-radius:50%;background:transparent;color:var(--muted);touch-action:none;user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;transition:background .15s,color .15s}
    .mic-btn svg{width:22px;height:22px;pointer-events:none}
    .cv-row.is-recording #cvText,.cv-row.is-recording .composer-tools,.cv-row.is-recording .attachment-previews,.cv-row.is-recording .attachment-errors,.cv-row.is-recording #cvBtn{display:none!important}
    .cv-row.is-recording .mic-btn{right:8px;background:var(--text);color:#fff}
    .cv-row.is-recording.is-holding .mic-btn{right:54px;background:var(--red)}
    .cv-row.is-finishing .mic-btn svg{animation:lbrSpin .8s linear infinite}
    @keyframes lbrSpin{to{transform:rotate(360deg)}}
    .rec-panel{display:none}
    .cv-row.is-recording .rec-panel{display:block}
    .rec-text{min-height:28px;max-height:7.5em;overflow-y:auto;padding:4px 6px;font-size:16px;line-height:1.5;white-space:pre-wrap;word-break:break-word;overscroll-behavior:contain}
    .rec-text .p{color:var(--muted)}
    .rec-text:empty::before{content:'正在听…';color:var(--muted)}
    .rec-bar{position:absolute;left:8px;right:56px;bottom:8px;height:40px;display:none;align-items:center;gap:6px}
    .cv-row.is-recording .rec-bar{display:flex}
    .cv-row.is-holding .rec-bar{right:104px}
    .rec-x{width:40px;height:40px;min-height:40px;padding:10px;border:0;border-radius:50%;background:transparent;color:var(--text);flex:none}
    .rec-x svg{width:20px;height:20px;display:block}
    .rec-wave{flex:1;min-width:0;height:28px;display:block;color:var(--text)}
    .rec-time{flex:none;font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums}
    .rec-hint{display:none;flex:none;font-size:12px;color:var(--muted)}
    .cv-row.is-holding .rec-x,.cv-row.is-finishing .rec-x{display:none}
    .cv-row.is-holding .rec-hint{display:inline}
    .cv-row.is-cancel .rec-hint{color:var(--red);font-weight:600}
    .cv-row.is-cancel .rec-wave,.cv-row.is-finishing .rec-wave{opacity:.35}
    .voice-pill{position:absolute;left:50%;bottom:calc(100% + 8px);transform:translateX(-50%);z-index:5;display:flex;align-items:center;gap:12px;max-width:calc(100% - 32px);padding:8px 16px;border-radius:999px;background:var(--text);color:#fff;font-size:13px;line-height:1.5;white-space:nowrap;box-shadow:var(--shadow);opacity:0;pointer-events:none;transition:opacity .15s}
    .voice-pill.show{opacity:1;pointer-events:auto}
    .voice-pill.wrap{white-space:normal;border-radius:16px;width:max-content}
    .voice-pill.error{background:#b91c1c}
    .voice-pill button{border:0;background:transparent;color:#bfdbfe;padding:0;min-height:28px;font-size:13px;font-weight:600;flex:none}
    .voice-pill .dots::after{content:'';animation:lbrDots 1.2s steps(4) infinite}
    @keyframes lbrDots{0%{content:''}25%{content:'.'}50%{content:'..'}75%{content:'...'}}
    #voiceTermsText{width:100%;min-height:46dvh;font:15px/1.6 ui-monospace,Consolas,monospace;padding:10px 12px;border:1px solid var(--line);border-radius:14px;resize:vertical}
    @media(prefers-reduced-motion:reduce){.cv-row.is-finishing .mic-btn svg{animation:none}}`;
  document.head.append(style);

  const ICON_MIC = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3"/></svg>';
  const ICON_OK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
  const ICON_X = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';
  const ICON_WAIT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M12 3a9 9 0 1 0 9 9"/></svg>';

  const button = document.createElement('button');
  button.type = 'button'; button.className = 'mic-btn'; button.innerHTML = ICON_MIC;
  button.setAttribute('aria-label', '语音输入');
  const panel = document.createElement('div'); panel.className = 'rec-panel';
  const live = document.createElement('div'); live.className = 'rec-text'; live.setAttribute('aria-live', 'polite');
  const bar = document.createElement('div'); bar.className = 'rec-bar';
  const xButton = document.createElement('button'); xButton.type = 'button'; xButton.className = 'rec-x'; xButton.innerHTML = ICON_X; xButton.setAttribute('aria-label', '不要这段录音');
  const wave = document.createElement('canvas'); wave.className = 'rec-wave'; wave.setAttribute('aria-hidden', 'true');
  const time = document.createElement('span'); time.className = 'rec-time'; time.textContent = '0:00';
  const hint = document.createElement('span'); hint.className = 'rec-hint';
  bar.append(xButton, wave, time, hint);
  panel.append(live);
  row.prepend(panel); row.append(bar, button); row.classList.add('has-mic');
  const pill = document.createElement('div'); pill.className = 'voice-pill'; pill.setAttribute('role', 'status');
  bottom.append(pill);

  xButton.addEventListener('click', () => cancel());

  // ---------------------------------------------------------------- small helpers
  // idle; press: finger just went down (tap or hold not known yet); hold: talking while holding;
  // rec: tapped, talking until ✓; finish: waiting for the last words
  function setMode(m) {
    const holding = m === 'press' || m === 'hold';
    row.classList.toggle('is-recording', m !== 'idle');
    row.classList.toggle('is-holding', holding);
    row.classList.toggle('is-finishing', m === 'finish');
    if (m !== 'hold') row.classList.remove('is-cancel');
    button.innerHTML = m === 'rec' ? ICON_OK : m === 'finish' ? ICON_WAIT : ICON_MIC;
    button.setAttribute('aria-label', m === 'idle' ? '语音输入' : m === 'rec' ? '完成，把文字放进输入框' : m === 'finish' ? '正在出字' : '松开放进输入框');
    hint.textContent = m === 'hold' ? '松开放入 · 上滑取消' : '';
    if (m === 'idle') { live.textContent = ''; levels.length = 0; }
  }
  function showPill(parts, opts = {}) {
    clearTimeout(pillTimer);
    pill.replaceChildren();
    for (const p of parts) pill.append(p);
    pill.className = 'voice-pill show' + (opts.error ? ' error' : '') + (opts.wrap ? ' wrap' : '');
    if (opts.hideAfter) pillTimer = setTimeout(hidePill, opts.hideAfter);
  }
  function hidePill() { clearTimeout(pillTimer); pill.classList.remove('show'); }
  function words(text, cls) { const s = document.createElement('span'); if (cls) s.className = cls; s.textContent = text; return s; }
  function action(label, fn) { const b = document.createElement('button'); b.type = 'button'; b.textContent = label; b.onclick = () => { hidePill(); fn(); }; return b; }
  function showLive(finalText, partial) {
    live.textContent = finalText || '';
    if (partial) live.append(words(partial, 'p'));
    live.scrollTop = live.scrollHeight;
  }
  function currentChat() { return typeof cur !== 'undefined' && cur ? {...cur} : null; }
  function sameChat(chat) { const now = currentChat(); return !chat || !now || (chat.app === now.app && chat.id === now.id); }
  async function post(url, body, type) {
    const r = await fetch(url, {method: 'POST', headers: type ? {'Content-Type': type} : {}, body});
    let j = null; try { j = await r.json(); } catch (e) {}
    if (!r.ok || !j) throw new Error((j && j.error) || ('HTTP ' + r.status));
    return j;
  }
  function downsampler(inRate) { // average over each 1/16000 s: enough filtering for speech
    const ratio = inRate / RATE; let acc = 0, n = 0, next = ratio, seen = 0;
    return input => {
      const out = [];
      for (let i = 0; i < input.length; i++) {
        acc += input[i]; n++; seen++;
        if (seen >= next) { out.push(acc / n); acc = 0; n = 0; next += ratio; }
      }
      const pcm = new Int16Array(out.length);
      for (let i = 0; i < out.length; i++) pcm[i] = Math.max(-1, Math.min(1, out[i])) * 0x7fff;
      return pcm;
    };
  }
  function join(chunks) { let n = 0; for (const c of chunks) n += c.length; const all = new Int16Array(n); let at = 0; for (const c of chunks) { all.set(c, at); at += c.length; } return all; }
  function wav(pcm) {
    const buf = new ArrayBuffer(44 + pcm.length * 2), dv = new DataView(buf);
    const put = (off, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(off + i, s.charCodeAt(i)); };
    put(0, 'RIFF'); dv.setUint32(4, 36 + pcm.length * 2, true); put(8, 'WAVE'); put(12, 'fmt ');
    dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true); dv.setUint32(24, RATE, true);
    dv.setUint32(28, RATE * 2, true); dv.setUint16(32, 2, true); dv.setUint16(34, 16, true); put(36, 'data');
    dv.setUint32(40, pcm.length * 2, true); new Int16Array(buf, 44).set(pcm);
    return new Blob([buf], {type: 'audio/wav'});
  }

  // ---------------------------------------------------------------- the sound wave
  const levels = []; let waveFrame = 0;
  function pushLevel(samples) {
    let sum = 0; for (let i = 0; i < samples.length; i += 4) sum += samples[i] * samples[i];
    const db = 10 * Math.log10(sum / Math.ceil(samples.length / 4) + 1e-9);
    levels.push(Math.max(0, Math.min(1, (db + 55) / 40)));
    if (levels.length > 160) levels.splice(0, levels.length - 160);
    if (!waveFrame) waveFrame = requestAnimationFrame(drawWave);
  }
  function drawWave() {
    waveFrame = 0;
    const w = wave.clientWidth, h = wave.clientHeight, dpr = window.devicePixelRatio || 1;
    if (!w || !h) return;
    if (wave.width !== Math.round(w * dpr) || wave.height !== Math.round(h * dpr)) { wave.width = Math.round(w * dpr); wave.height = Math.round(h * dpr); }
    const g = wave.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
    g.fillStyle = getComputedStyle(wave).color;
    const step = 5, count = Math.floor(w / step), from = Math.max(0, levels.length - count);
    for (let i = from, x = w - (levels.length - from) * step; i < levels.length; i++, x += step) {
      const bh = Math.max(3, levels[i] * h);
      g.globalAlpha = 0.35 + 0.65 * Math.min(1, levels[i] * 1.6);
      g.beginPath(); (g.roundRect ? g.roundRect(x, (h - bh) / 2, 3, bh, 1.5) : g.rect(x, (h - bh) / 2, 3, bh)); g.fill();
    }
    for (let x = w - (levels.length - from) * step - step; x >= 0; x -= step) { g.globalAlpha = 0.25; g.fillRect(x, h / 2 - 1, 3, 2); }
  }

  // ---------------------------------------------------------------- the button
  button.addEventListener('pointerdown', e => {
    e.preventDefault();
    if (busy) return;
    if (rec) { press = {id: e.pointerId, endTap: true}; return; } // the ✓ of a tapped recording
    if (!window.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { httpsHint(); return; }
    const focused = document.activeElement === input;
    const selection = focused ? [input.selectionStart, input.selectionEnd] : null;
    if (focused) input.blur(); // the keyboard goes away while you talk
    press = {id: e.pointerId, y: e.clientY, t: Date.now(), cancel: false};
    try { button.setPointerCapture(e.pointerId); } catch (x) {}
    begin(selection);
    press.holdTimer = setTimeout(() => { if (press && !press.endTap && rec && rec.mode === 'hold?') setMode('hold'); }, HOLD_MS);
  });
  button.addEventListener('pointermove', e => {
    if (!press || press.endTap || e.pointerId !== press.id || !rec || rec.mode !== 'hold?') return;
    const cancelNow = press.y - e.clientY > CANCEL_PX;
    if (cancelNow !== press.cancel) {
      press.cancel = cancelNow; row.classList.toggle('is-cancel', cancelNow);
      hint.textContent = cancelNow ? '松开取消' : '松开放入 · 上滑取消';
    }
  });
  button.addEventListener('pointerup', e => {
    const p = press; press = null;
    if (!p || e.pointerId !== p.id) return;
    clearTimeout(p.holdTimer);
    if (p.endTap) { finish(); return; }
    if (!rec) return;
    if (Date.now() - p.t < HOLD_MS || !rec.running) { rec.mode = 'tap'; setMode('rec'); return; } // a tap: keep listening
    if (p.cancel) cancel(); else finish();
  });
  button.addEventListener('pointercancel', () => { const p = press; press = null; if (p) clearTimeout(p.holdTimer); if (p && !p.endTap && rec && rec.mode === 'hold?') finish(); });
  button.addEventListener('contextmenu', e => e.preventDefault());

  async function httpsHint() {
    let url = '';
    try { const r = await fetch('/api/voice/https-link'); url = (await r.json()).url || ''; } catch (e) {}
    showPill([words('话筒要在 https 地址下才能用'), ...(url ? [action('换过去', () => { location.href = url; })] : [])], {hideAfter: 10000});
  }
  // The microphone was refused: where this phone turns it back on. Chrome on Android asks per site, and the phone
  // itself may not let Chrome use the microphone at all.
  function deniedHint() {
    const system = phoneSystem();
    if (system === 'iphone') return '没有麦克风权限：iPhone 设置 → App → Safari → 麦克风，改成允许';
    if (system === 'android') return '没有麦克风权限：Chrome 右上角 ⋮ → 设置 → 网站设置 → 麦克风，把这个网址改成允许；还不行，到手机设置里给 Chrome 打开麦克风权限';
    return '没有麦克风权限：在浏览器的网站设置里允许这个网址用麦克风';
  }

  // ---------------------------------------------------------------- recording
  function begin(selection) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) { showPill([words('这个浏览器不能录音')], {error: true, hideAfter: 5000}); return; }
    let ctx;
    try { ctx = new AC(); if (ctx.resume) ctx.resume(); } catch (x) { showPill([words('录音没能开始：' + x.message)], {error: true, wrap: true, hideAfter: 6000}); return; }
    // made inside the press: iPhone Safari only lets sound start from a touch
    const r = rec = {ctx, mode: 'hold?', running: false, started: Date.now(), queue: [], queued: 0, all: [], total: 0,
      sid: null, local: true, sending: false, stopping: false, chat: currentChat(), selection, finalText: '', partial: ''};
    window.navigationUI?.haptic?.(); // still inside the press; a tick later (after the microphone answers) would not reach an iPhone
    hidePill(); setMode('press'); time.textContent = '0:00'; requestAnimationFrame(drawWave);
    post('/api/voice/stream/start?tidy=' + (tidy ? '1' : '0'), null).then(j => { r.sid = j.sid; pump(r); })
      .catch(() => { r.local = false; }); // no recognition on the PC: the cloud gets the whole recording at the end
    navigator.mediaDevices.getUserMedia({audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true}})
      .then(stream => {
        if (rec !== r) { stream.getTracks().forEach(t => t.stop()); return; }
        if (ctx.state === 'suspended') ctx.resume().catch(() => {});
        const source = ctx.createMediaStreamSource(stream), node = ctx.createScriptProcessor(2048, 1, 1), down = downsampler(ctx.sampleRate);
        node.onaudioprocess = ev => {
          if (r.stopping) return;
          const raw = ev.inputBuffer.getChannelData(0);
          pushLevel(raw);
          const pcm = down(raw);
          if (!pcm.length) return;
          r.queue.push(pcm); r.queued += pcm.length; r.all.push(pcm); r.total += pcm.length;
          if (r.total >= MAX_SECONDS * RATE) { finish(); return; }
          pump(r);
        };
        source.connect(node); node.connect(ctx.destination); // nothing is written to the output, so nothing is heard
        Object.assign(r, {stream, source, node, running: true});
        r.timer = setInterval(() => { if (rec === r) time.textContent = clock(r); }, 250);
      })
      .catch(err => {
        if (rec !== r) return;
        stopCapture(r); rec = null; setMode('idle');
        if (r.sid) post('/api/voice/stream/cancel?sid=' + r.sid, null).catch(() => {});
        const denied = err && (err.name === 'NotAllowedError' || err.name === 'SecurityError');
        showPill([words(denied ? deniedHint() : '没拿到麦克风：' + (err && err.message || err))], {error: true, wrap: true, hideAfter: 9000});
      });
  }
  function clock(r) { const s = Math.floor((r.total || 0) / RATE); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }
  function stopCapture(r) {
    r.stopping = true; clearInterval(r.timer);
    try { r.node && r.node.disconnect(); r.source && r.source.disconnect(); } catch (x) {}
    if (r.stream) r.stream.getTracks().forEach(t => t.stop());
    try { r.ctx.close(); } catch (x) {}
  }
  function cancel() {
    const r = rec; if (!r) return;
    stopCapture(r); rec = null; setMode('idle');
    if (r.sid) post('/api/voice/stream/cancel?sid=' + r.sid, null).catch(() => {});
  }

  // pieces of audio go to the PC one request at a time; whatever piles up meanwhile goes in the next one
  async function pump(r) {
    if (!r.local || !r.sid || r.sending) return;
    if (r.queued < PIECE && !(r.stopping && r.queued)) { if (r.stopping && !r.queued && r.done) r.done(); return; }
    const piece = join(r.queue); r.queue = []; r.queued = 0; r.sending = true;
    try {
      const j = await post('/api/voice/stream/chunk?sid=' + r.sid, piece.buffer, 'application/octet-stream');
      r.finalText = j.final || ''; r.partial = j.partial || '';
      if (rec === r || (r.stopping && busy)) showLive(r.finalText, r.partial);
    } catch (e) {
      r.local = false; // the PC lost this recording: fall back to the cloud with everything recorded
    } finally {
      r.sending = false;
      if (!r.local) { if (r.done) r.done(); } else pump(r);
    }
  }

  async function finish() {
    const r = rec; if (!r) return;
    window.navigationUI?.haptic?.();
    stopCapture(r); rec = null; busy = true;
    r.stopAt = performance.now();
    if (r.total < RATE * 0.5) {
      if (r.sid) post('/api/voice/stream/cancel?sid=' + r.sid, null).catch(() => {});
      busy = false; setMode('idle'); showPill([words('太短了，没听到')], {hideAfter: 2000}); return;
    }
    setMode('finish');
    try {
      let text = '', source = 'local';
      if (r.local && r.sid) await new Promise(resolve => { r.done = resolve; pump(r); });  // the last pieces reach the PC
      if (r.local && r.sid) {
        const j = await post('/api/voice/stream/end?sid=' + r.sid, null);
        text = (j.text || '').trim();
      } else {
        source = 'cloud';
        const j = await post('/api/voice?' + chatQuery(r.chat), wav(join(r.all)), 'audio/wav');
        text = (j.text || '').trim(); r.cloudRaw = (j.raw || '').trim(); r.cloudTidied = !!j.tidied;
      }
      setMode('idle'); busy = false;
      if (!text) { showPill([words('没听清'), ...(source === 'local' ? [action('换云端识别', () => cloudAgain(r))] : [])], {hideAfter: 7000}); return; }
      if (!sameChat(r.chat)) { showPill([words('对话已经换了'), action('填到这里', () => insert(text, r, null))], {hideAfter: 12000}); return; }
      const placed = insert(text, r, r.selection);
      if (source === 'cloud') { if (r.cloudTidied && r.cloudRaw) { placed.raw = r.cloudRaw; placed.tidied = text; tidiedPill(placed); } return; }
      if (tidy) await tidyIn(placed, r);
    } catch (e) {
      setMode('idle');
      showPill([words('没转成文字'), ...(r.all.length ? [action('换云端识别', () => cloudAgain(r))] : [])], {error: true, hideAfter: 10000});
    } finally {
      busy = false; if (!rec && row.classList.contains('is-finishing')) setMode('idle'); // a new recording may already be running
    }
  }
  function chatQuery(chat) {
    chat = chat || {};
    return new URLSearchParams({tidy: tidy ? '1' : '0', app: chat.app || '', title: (chat.title || '').slice(0, 120), folder: (chat.folder || '').slice(0, 120)});
  }

  // ---------------------------------------------------------------- putting text in the box
  function insert(text, r, selection) {
    const v = input.value;
    const [s, e] = selection && selection[0] != null ? [Math.min(selection[0], v.length), Math.min(selection[1], v.length)] : [v.length, v.length];
    const before = v.slice(0, s), after = v.slice(e);
    let sep = '';
    if (before && !/\s$/.test(before)) sep = text.includes('\n') ? '\n' : (/[　-鿿＀-￯]$/.test(before) ? '' : ' ');
    input.value = before + sep + text + after;
    input.dispatchEvent(new Event('input', {bubbles: true})); // drafts, the send button and the box height follow
    return {at: before.length + sep.length, text, raw: text, r};
  }
  function intact(p) { return input.value.substr(p.at, p.text.length) === p.text; }
  function swap(p, text) {
    input.value = input.value.slice(0, p.at) + text + input.value.slice(p.at + p.text.length);
    input.dispatchEvent(new Event('input', {bubbles: true}));
    p.text = text;
  }
  async function tidyIn(p, r) {
    const chat = r.chat || {};
    showPill([words('整理中', 'dots')]);
    try {
      const j = await post('/api/voice/tidy', JSON.stringify({text: p.raw, app: chat.app || '', title: chat.title || '', folder: chat.folder || '', existing: input.value.slice(Math.max(0, p.at - 400), p.at)}), 'application/json');
      const text = (j.text || '').trim();
      if (rec) return; // a new recording is on screen; leave this text as it is
      if (!text || text === p.text || !intact(p)) { hidePill(); return; } // unchanged, or you are already editing it
      swap(p, text); p.tidied = text;
      tidiedPill(p);
    } catch (e) {
      if (!rec) showPill([words('整理没成功，保留原话')], {error: true, hideAfter: 3500});
    }
  }
  function tidiedPill(p) {
    showPill([words('已整理'), action('撤销', () => { if (!intact(p)) return; swap(p, p.raw); })], {hideAfter: 5000});
  }
  async function cloudAgain(r) {
    if (!r.all.length || busy || rec) return;
    busy = true; showPill([words('云端识别中', 'dots')]);
    try {
      const j = await post('/api/voice?' + chatQuery(r.chat), wav(join(r.all)), 'audio/wav'); // the phone still has the recording
      const text = (j.text || '').trim();
      if (!text) { showPill([words('云端也没听清')], {hideAfter: 4000}); return; }
      const placed = insert(text, r, null); placed.raw = (j.raw || text).trim();
      if (j.tidied && placed.raw !== text) { placed.tidied = text; tidiedPill(placed); } else hidePill();
    } catch (e) {
      showPill([words('云端识别没成功')], {error: true, hideAfter: 5000});
    } finally { busy = false; }
  }

  // ---------------------------------------------------------------- the voice dictionary
  const sheet = document.createElement('div'); sheet.id = 'voiceTermsSheet'; sheet.className = 'sheet'; sheet.setAttribute('aria-label', '语音词典');
  sheet.innerHTML = '<div class="box"><div class="sh-head"><b>语音词典</b><button class="icon-btn" aria-label="关闭">' + ICON_X + '</button></div><div class="sh-body"><textarea id="voiceTermsText" spellcheck="false" autocapitalize="off" autocomplete="off"></textarea><button class="big" id="voiceTermsSave">保存</button></div></div>';
  document.body.append(sheet);
  sheet.addEventListener('click', e => { if (e.target === sheet) closeSheet(sheet.id); });
  sheet.querySelector('.icon-btn').onclick = () => closeSheet(sheet.id);
  const termsText = sheet.querySelector('#voiceTermsText'), termsSave = sheet.querySelector('#voiceTermsSave');
  async function openTerms() {
    termsText.value = ''; termsText.placeholder = '读取中…'; openSheet(sheet.id);
    try { const r = await fetch('/api/voice/terms'); const j = await r.json(); if (!r.ok) throw new Error(j.error || r.status); termsText.value = j.text || ''; termsText.placeholder = '每行一个词'; }
    catch (e) { termsText.placeholder = '没读到词典：' + e.message; }
  }
  termsSave.onclick = async () => {
    termsSave.disabled = true;
    try { const j = await post('/api/voice/terms', JSON.stringify({text: termsText.value}), 'application/json'); closeSheet(sheet.id); if (typeof toast === 'function') toast('已保存，' + j.count + ' 个词'); }
    catch (e) { if (typeof toast === 'function') toast(e.message, true); }
    finally { termsSave.disabled = false; }
  };

  // ---------------------------------------------------------------- 设置 (the gear at the bottom of the drawer)
  // 录音后自动整理 is a real switch: on the iPhone a finger on it ticks by itself (navigation-ui.js); Android gets
  // navigator.vibrate. Safari draws the switch; other browsers get one drawn in remote.html's styles.
  const settings = document.getElementById('settingsBody');
  if (settings) {
    const title = words('语音输入', 'setting-title');
    const group = document.createElement('div'); group.className = 'setting-group';
    const tidyRow = document.createElement('label'); tidyRow.className = 'setting-row';
    const tidySwitch = document.createElement('input'); tidySwitch.type = 'checkbox'; tidySwitch.setAttribute('switch', '');
    tidySwitch.className = 'setting-switch' + ('switch' in HTMLInputElement.prototype ? '' : ' drawn'); tidySwitch.id = 'voiceTidySwitch';
    tidySwitch.checked = tidy;
    tidySwitch.addEventListener('change', () => {
      tidy = tidySwitch.checked; try { localStorage.setItem(TIDY_KEY, tidy ? '1' : '0'); } catch (e) {}
      window.navigationUI?.haptic?.();
    });
    tidyRow.append(words('录音后自动整理'), tidySwitch);
    const termsRow = document.createElement('button'); termsRow.type = 'button'; termsRow.className = 'menu-row setting-row';
    termsRow.append(words('语音词典'), words('›', 'go'));
    termsRow.onclick = openTerms;
    group.append(tidyRow, termsRow);
    settings.append(title, group);
  }

  // leaving the page or the app ends the recording and keeps what was said so far
  document.addEventListener('visibilitychange', () => { if (document.hidden && rec) finish(); });
  window.voiceUI = {get recording() { return !!rec; }, get busy() { return busy; }, finish, cancel, openTerms};
})();
