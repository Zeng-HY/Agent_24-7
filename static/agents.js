/* Assistant manifest registry for the web page (plan.md §5).
 * Reads window.MACHINE.agents injected by remote.py; falls back to the built-in
 * three legacy assistants when talking to an older computer without manifests.
 * Unknown assistants get neutral gray styling, a generic icon, and safe defaults.
 */
(function () {
  'use strict';

  const ID_RE = /^[a-z][a-z0-9_-]{0,31}$/;
  const NEUTRAL_COLOR = '#6b7280';
  const LEGACY_LAYOUTS = new Set(['codex.v1', 'claude.v1', 'deepseek.v1']);

  const DEFAULT_PARAMS = Object.freeze({
    state_timeout_s: 20,
    send_timeout_s: 60,
    open_timeout_s: 45,
    new_timeout_s: 60,
    refresh_ms: 2500,
    max_images: 5,
    max_image_bytes: 52428800,
    max_text: 20000,
  });

  // Brand paths: Simple Icons (CC0) for claude/deepseek; SVG Logos (CC0) for codex; neutral mark for generic/unknown.
  const BUILTIN_ICONS = Object.freeze({
    codex: `<svg class="mark codex" viewBox="-18 -18 292 292" aria-hidden="true"><path fill="currentColor" fill-rule="evenodd" d="M86.2469364,4.88643768 C96.5221627,0.663921528 107.706851,-0.859846559 118.737241,0.460056962 C132.955749,2.09195154 145.627607,8.13956084 156.752816,18.5922189 C157.057164,18.8804461 157.48589,18.9966367 157.894137,18.9015322 C172.912636,15.211104 187.355142,16.5123532 201.210987,22.8052801 L201.88298,23.1252594 L203.525628,23.9358737 C218.000133,31.4340559 228.378684,42.8146541 234.650614,58.0456701 C237.615914,65.2878689 239.109231,72.8500471 239.141231,80.7215386 C239.350466,86.5827763 238.703666,92.4431937 237.221252,98.117748 C237.072866,98.7055193 237.233619,99.3284034 237.647914,99.7709746 C246.033486,108.272015 251.865155,118.955447 254.479726,130.606316 C258.586347,150.882339 254.373061,169.163825 241.8612,185.429441 L239.919889,187.775956 C231.633662,197.264359 220.756459,204.126195 208.624238,207.51868 C208.086793,207.673526 207.657538,208.078912 207.472251,208.60661 C204.752281,216.456769 202.021645,223.155003 196.944368,229.853237 C184.155177,246.726815 165.350054,256.112875 144.16629,255.997702 C127.281145,255.910221 112.315979,249.73462 99.2601245,237.479412 C98.8576056,237.109834 98.2899259,236.980086 97.7668078,237.1381 C92.2415361,238.919319 86.6735983,239.175302 80.6576654,239.111307 C71.0465963,239.033687 61.5798805,236.764715 52.9779742,232.477068 C43.9742908,228.011254 36.1364944,221.506888 30.0875629,213.480962 C27.9222537,210.611814 25.7782777,207.913322 24.2102951,204.724194 C22.0477537,200.328397 20.2808011,195.748843 18.9303541,191.039745 C16.0949613,180.338452 16.0325553,169.091285 18.7490227,158.359189 C18.8368469,158.105946 18.8660244,157.836068 18.8343551,157.569908 C18.7815189,157.305134 18.642794,157.065191 18.4396929,156.887285 C11.8646164,150.236858 6.83846328,142.217294 3.71985709,133.400802 C1.65509014,127.972392 0.456475456,122.253182 0.167896716,116.452563 C-0.347931023,108.814478 0.328607591,101.142652 2.17320768,93.7126993 C6.97315412,77.8843885 16.1357186,65.4691905 29.660901,56.4564394 C32.6688674,54.4512357 35.5275022,52.8940029 38.2154722,51.7847413 C41.2661049,50.5048239 44.327404,49.4382262 47.3993698,48.5422841 C47.8457913,48.4099044 48.1949726,48.0607417 48.3273594,47.614344 C50.6568855,39.2412668 54.6631877,31.4286693 60.103228,24.6504942 C67.3564804,15.6270771 76.0710499,9.03550297 86.2469364,4.88643768 Z M77.671032,88.6143619 C75.1909329,84.2758933 69.6632037,82.7692797 65.3245032,85.2492462 C60.9858026,87.7292126 59.4791084,93.2566464 61.9592073,97.5951152 L80.0283391,129.219739 L62.0232066,159.596443 C59.7295443,163.873179 61.2152431,169.19768 65.3918751,171.669198 C69.5685071,174.140717 74.9511079,172.880527 77.5963662,168.811848 L98.2894687,133.912769 C99.9508985,131.110939 99.9794101,127.632712 98.3641345,124.804024 L77.671032,88.6143619 L77.671032,88.6143619 Z M135.761051,155.170062 C130.977069,155.454803 127.243231,159.417285 127.243231,164.209479 C127.243231,169.001672 130.977069,172.964154 135.761051,173.248895 L187.472474,173.248895 C192.297403,173.014518 196.088968,169.034507 196.088968,164.204145 C196.088968,159.373784 192.297403,155.393772 187.472474,155.159396 L135.761051,155.159396 L135.761051,155.170062 Z"/></svg>`,
    claude: `<svg class="mark claude" viewBox="0 0 24 24" aria-hidden="true"><path d="m4.7144 15.9555 4.7174-2.6471.079-.2307-.079-.1275h-.2307l-.7893-.0486-2.6956-.0729-2.3375-.0971-2.2646-.1214-.5707-.1215-.5343-.7042.0546-.3522.4797-.3218.686.0608 1.5179.1032 2.2767.1578 1.6514.0972 2.4468.255h.3886l.0546-.1579-.1336-.0971-.1032-.0972L6.973 9.8356l-2.55-1.6879-1.3356-.9714-.7225-.4918-.3643-.4614-.1578-1.0078.6557-.7225.8803.0607.2246.0607.8925.686 1.9064 1.4754 2.4893 1.8336.3643.3035.1457-.1032.0182-.0728-.164-.2733-1.3539-2.4467-1.445-2.4893-.6435-1.032-.17-.6194c-.0607-.255-.1032-.4674-.1032-.7285L6.287.1335 6.6997 0l.9957.1336.419.3642.6192 1.4147 1.0018 2.2282 1.5543 3.0296.4553.8985.2429.8318.091.255h.1579v-.1457l.1275-1.706.2368-2.0947.2307-2.6957.0789-.7589.3764-.9107.7468-.4918.5828.2793.4797.686-.0668.4433-.2853 1.8517-.5586 2.9021-.3643 1.9429h.2125l.2429-.2429.9835-1.3053 1.6514-2.0643.7286-.8196.85-.9046.5464-.4311h1.0321l.759 1.1293-.34 1.1657-1.0625 1.3478-.8804 1.1414-1.2628 1.7-.7893 1.36.0729.1093.1882-.0183 2.8535-.607 1.5421-.2794 1.8396-.3157.8318.3886.091.3946-.3278.8075-1.967.4857-2.3072.4614-3.4364.8136-.0425.0304.0486.0607 1.5482.1457.6618.0364h1.621l3.0175.2247.7892.522.4736.6376-.079.4857-1.2142.6193-1.6393-.3886-3.825-.9107-1.3113-.3279h-.1822v.1093l1.0929 1.0686 2.0035 1.8092 2.5075 2.3314.1275.5768-.3218.4554-.34-.0486-2.2039-1.6575-.85-.7468-1.9246-1.621h-.1275v.17l.4432.6496 2.3436 3.5214.1214 1.0807-.17.3521-.6071.2125-.6679-.1214-1.3721-1.9246L14.38 17.959l-1.1414-1.9428-.1397.079-.674 7.2552-.3156.3703-.7286.2793-.6071-.4614-.3218-.7468.3218-1.4753.3886-1.9246.3157-1.53.2853-1.9004.17-.6314-.0121-.0425-.1397.0182-1.4328 1.9672-2.1796 2.9446-1.7243 1.8456-.4128.164-.7164-.3704.0667-.6618.4008-.5889 2.386-3.0357 1.4389-1.882.929-1.0868-.0062-.1579h-.0546l-6.3385 4.1164-1.1293.1457-.4857-.4554.0608-.7467.2307-.2429 1.9064-1.3114Z"/></svg>`,
    deepseek: `<svg class="mark deepseek" viewBox="0 0 24 24" aria-hidden="true"><path d="M23.748 4.651c-.254-.124-.364.113-.512.233-.051.04-.094.09-.137.137-.372.397-.806.657-1.373.626-.829-.046-1.537.214-2.163.848-.133-.782-.575-1.248-1.247-1.548-.352-.155-.708-.311-.955-.65-.172-.24-.219-.509-.305-.774-.055-.16-.11-.323-.293-.35-.2-.031-.278.136-.356.276-.313.572-.434 1.202-.422 1.84.027 1.436.633 2.58 1.838 3.393.137.094.172.187.129.323-.082.28-.18.553-.266.833-.055.179-.137.218-.328.14a5.5 5.5 0 0 1-1.737-1.179c-.857-.828-1.631-1.743-2.597-2.46a12 12 0 0 0-.689-.47c-.985-.957.13-1.743.387-1.836.27-.098.094-.433-.778-.428-.872.003-1.67.295-2.687.685a3 3 0 0 1-.465.136 9.6 9.6 0 0 0-2.883-.101c-1.885.21-3.39 1.1-4.497 2.622C.082 8.776-.231 10.854.152 13.02c.403 2.284 1.568 4.175 3.36 5.653 1.857 1.533 3.997 2.284 6.438 2.14 1.482-.085 3.132-.284 4.994-1.86.47.234.962.328 1.78.398.629.058 1.235-.031 1.705-.129.735-.155.684-.836.418-.961-2.155-1.004-1.682-.595-2.112-.926 1.095-1.295 2.768-3.598 3.284-6.733.05-.346.115-.834.108-1.114-.004-.171.035-.238.23-.257a4.2 4.2 0 0 0 1.545-.475c1.397-.763 1.96-2.016 2.093-3.517.02-.23-.004-.467-.247-.588M11.58 18.168c-2.088-1.642-3.101-2.183-3.52-2.16-.39.024-.32.472-.234.763.09.288.207.487.371.74.114.167.192.416-.113.603-.673.416-1.842-.14-1.897-.168-1.361-.801-2.5-1.86-3.301-3.306-.775-1.393-1.225-2.888-1.299-4.482-.02-.385.094-.522.477-.592a4.7 4.7 0 0 1 1.53-.038c2.131.311 3.946 1.264 5.467 2.774.868.86 1.525 1.887 2.202 2.89.72 1.066 1.494 2.082 2.48 2.915.348.291.626.513.892.677-.802.09-2.14.109-3.055-.615zm1.001-6.44a.306.306 0 0 1 .415-.287.3.3 0 0 1 .113.074.3.3 0 0 1 .086.214c0 .17-.136.307-.308.307a.303.303 0 0 1-.306-.307m3.11 1.596c-.2.081-.4.151-.591.16a1.25 1.25 0 0 1-.798-.254c-.274-.23-.47-.358-.551-.758a1.7 1.7 0 0 1 .015-.588c.07-.327-.007-.537-.238-.727-.188-.156-.426-.199-.689-.199a.6.6 0 0 1-.254-.078.253.253 0 0 1-.114-.358 1 1 0 0 1 .192-.21c.356-.202.767-.136 1.146.016.352.144.618.408 1.001.782.392.451.462.576.685.915.176.264.336.536.446.848.066.194-.02.353-.25.45"/></svg>`,
  });

  function genericIcon(color) {
    const c = escapeAttr(color || NEUTRAL_COLOR);
    return `<svg class="mark generic" viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="5"/><circle cx="9.5" cy="11.5" r="1.2" fill="${c}" stroke="none"/><circle cx="14.5" cy="11.5" r="1.2" fill="${c}" stroke="none"/><path d="M9.5 15.2c1.4 1 3.6 1 5 0"/></svg>`;
  }

  function escapeAttr(value) {
    return String(value).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // Fallback manifests for older computers that do not inject window.MACHINE.agents yet.
  const FALLBACK_MANIFESTS = [
    {
      schema: 1, id: 'codex', name: {zh: 'Codex', en: 'Codex'}, order: 10,
      color: '#1E222A', color_dark: '#FFFFFF', icon: {kind: 'builtin', key: 'codex'},
      legacy: true, min_protocol: 1,
      capabilities: {
        list: true, read: true, search: true, open: true, stop: true, queue: true, steer: true,
        approve: true, answer: true, new: true, new_projectless: true, new_permission: false,
        archive: true, restore: true, delete: true, usage: true, waiting: true,
        attachments: true, slash_commands: true,
        settings: ['model', 'effort', 'mode'], send_modes: ['send', 'steer', 'queue'],
        statuses: ['running', 'waiting', 'idle', 'unknown'],
      },
      params: {...DEFAULT_PARAMS, state_timeout_s: 40, refresh_ms: 2500},
      ui: {card_layout: 'codex.v1', waiting_text: '等你处理'},
    },
    {
      schema: 1, id: 'claude', name: {zh: 'Claude', en: 'Claude'}, order: 20,
      color: '#D97757', color_dark: '#D97757', icon: {kind: 'builtin', key: 'claude'},
      legacy: true, min_protocol: 1,
      capabilities: {
        list: true, read: true, search: true, open: true, stop: true, queue: false, steer: true,
        approve: true, answer: true, new: true, new_projectless: true, new_permission: false,
        archive: true, restore: true, delete: false, usage: true, waiting: true,
        attachments: true, slash_commands: true,
        settings: ['model', 'effort', 'permission', 'mode'], send_modes: ['send', 'steer'],
        statuses: ['running', 'waiting', 'idle', 'unknown'],
      },
      params: {...DEFAULT_PARAMS, state_timeout_s: 20, new_timeout_s: 70, refresh_ms: 5000},
      ui: {card_layout: 'claude.v1', waiting_text: '等待你处理'},
    },
    {
      schema: 1, id: 'deepseek', name: {zh: 'DeepSeek', en: 'DeepSeek'}, order: 30,
      color: '#4D6BFE', color_dark: '#4D6BFE', icon: {kind: 'builtin', key: 'deepseek'},
      legacy: true, min_protocol: 1,
      capabilities: {
        list: true, read: true, search: true, open: true, stop: true, queue: true, steer: true,
        approve: true, answer: true, new: true, new_projectless: false, new_permission: true,
        archive: true, restore: true, delete: false, usage: false, waiting: true,
        attachments: true, slash_commands: true,
        settings: ['model', 'permission'], send_modes: ['send', 'steer', 'queue'],
        statuses: ['running', 'waiting', 'idle', 'unknown'],
      },
      params: {...DEFAULT_PARAMS, state_timeout_s: 40, refresh_ms: 2500},
      ui: {card_layout: 'deepseek.v1', waiting_text: '等待你处理'},
    },
  ];

  let ordered = [];
  let byId = new Map();
  let usedFallback = false;
  let machineRef = null;

  function loadFrom(machine) {
    machineRef = machine || window.MACHINE || {};
    const raw = Array.isArray(machineRef.agents) && machineRef.agents.length ? machineRef.agents : null;
    usedFallback = !raw;
    let items;
    if (raw) {
      items = raw.filter(a => a && typeof a.id === 'string' && a.id);
    } else {
      const apps = Array.isArray(machineRef.apps) ? machineRef.apps : null;
      items = FALLBACK_MANIFESTS.filter(a => !apps || apps.includes(a.id)).map(a => ({
        ...a,
        capabilities: {
          ...a.capabilities,
          ...(a.id === 'claude' ? {archive: !!machineRef.claude_archive, restore: !!machineRef.claude_archive} : {}),
        },
      }));
    }
    ordered = [...items].sort((a, b) => (Number(a.order ?? 999) - Number(b.order ?? 999)) || String(a.id).localeCompare(String(b.id)));
    byId = new Map(ordered.map(a => [a.id, a]));
  }

  function get(app) {
    return (typeof app === 'string' && byId.get(app)) || null;
  }

  function name(app) {
    const m = get(app);
    return m?.name?.zh || m?.name?.en || (app ? String(app) : '');
  }

  function color(app, dark = false) {
    const m = get(app);
    if (!m) return NEUTRAL_COLOR;
    return (dark ? (m.color_dark || m.color) : m.color) || NEUTRAL_COLOR;
  }

  function badgeColor(app) {
    const m = get(app);
    if (!m) return NEUTRAL_COLOR;
    // Keep exact CSS colors for the three legacy badges (.badge.codex / .claude / .deepseek).
    if (m.legacy && LEGACY_LAYOUTS.has(m.ui?.card_layout)) return null;
    return m.color || NEUTRAL_COLOR;
  }

  function icon(app) {
    const m = get(app);
    const spec = m?.icon;
    if (spec?.kind === 'builtin' && BUILTIN_ICONS[spec.key]) {
      return BUILTIN_ICONS[spec.key];
    }
    if (spec?.kind === 'url' && typeof spec.path === 'string' && spec.path.startsWith('/')) {
      const src = escapeAttr(spec.path + (spec.etag ? (spec.path.includes('?') ? '&' : '?') + 'v=' + encodeURIComponent(spec.etag) : ''));
      return `<img class="mark mark-img" src="${src}" alt="" aria-hidden="true">`;
    }
    return genericIcon(m?.color || NEUTRAL_COLOR);
  }

  function can(app, cap) {
    const m = get(app);
    if (!m || !m.capabilities) return false;
    return m.capabilities[cap] === true;
  }

  function modes(app) {
    const m = get(app);
    return Array.isArray(m?.capabilities?.send_modes) ? m.capabilities.send_modes : [];
  }

  function settings(app) {
    const m = get(app);
    return Array.isArray(m?.capabilities?.settings) ? m.capabilities.settings : [];
  }

  function capsNow(control) {
    const c = control?.capabilities_now;
    return c && typeof c === 'object' && !Array.isArray(c) ? c : null;
  }

  function canNow(app, cap, control) {
    const c = capsNow(control);
    if (c) return c[cap] === true;
    return can(app, cap);
  }

  function modesNow(app, control) {
    const c = capsNow(control);
    if (c) return Array.isArray(c.send_modes) ? c.send_modes : [];
    return modes(app);
  }

  function settingsNow(app, control) {
    const c = capsNow(control);
    if (c) return Array.isArray(c.settings) ? c.settings : [];
    return settings(app);
  }

  function noteNow(app, cap, control) {
    const n = control?.capability_notes;
    return n && typeof n === 'object' && typeof n[cap] === 'string' ? n[cap] : '';
  }

  function params(app) {
    const m = get(app);
    return {...DEFAULT_PARAMS, ...(m?.params || {})};
  }

  function cardLayout(app) {
    return get(app)?.ui?.card_layout || 'generic.v1';
  }

  function isGenericLayout(app) {
    return !LEGACY_LAYOUTS.has(cardLayout(app));
  }

  function has(app) {
    if (!app) return false;
    if (byId.has(app)) return true;
    return !Array.isArray(machineRef?.apps) && !Array.isArray(machineRef?.agents);
  }

  loadFrom(window.MACHINE);

  window.Agents = {
    list: () => ordered.slice(),
    ids: () => ordered.map(a => a.id),
    get,
    has,
    isLegacy: app => !!get(app)?.legacy,
    isFallback: () => usedFallback,
    name,
    color,
    badgeColor,
    icon,
    can,
    canNow,
    modes,
    modesNow,
    canSend: app => modes(app).length > 0,
    settings,
    settingsNow,
    noteNow,
    params,
    cardLayout,
    isGenericLayout,
    waitingText: app => get(app)?.ui?.waiting_text || '等待你处理',
    validId: app => typeof app === 'string' && ID_RE.test(app),
    reload: loadFrom,
  };
})();
