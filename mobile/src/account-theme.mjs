import css from './account.css';

// Progressive presentation only. Keep the server's fields, handlers and requests.
export function enhanceAccount(document) {
  const $ = id => document.getElementById(id);
  const required = ['name', 'password', 'code', 'login', 'register', 'reset', 'signed', 'devices', 'message', 'logout', 'bind', 'old', 'new', 'change'];
  if (document.documentElement.dataset.padTheme || required.some(id => !$(id))) return false;
  const auth = $('name').closest('fieldset');
  if (!auth || !$('old').closest('fieldset') || !['password', 'code', 'login', 'register', 'reset'].every(id => auth.contains($(id)))
      || !$('login').onclick || !$('register').onclick || !$('reset').onclick) return false;
  const create = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text) node.textContent = text; return node; };
  const style = create('style'); style.textContent = css; document.head.append(style);
  const body = document.body;
  const header = create('header', 'pad-brand');
  const mark = create('span', 'pad-mark'); mark.setAttribute('aria-hidden', 'true'); mark.append(create('i'));
  header.append(mark, create('span', '', 'Pocket Agent Desk'));
  const top = create('div', 'pad-intro');
  top.append(create('p', 'pad-eyebrow', 'YOUR PERSONAL WORKSPACE'));
  const title = create('h1', '', '欢迎回来');
  const subtitle = create('p', 'pad-subtitle', '登录后，继续自己电脑上的工作。');
  top.append(title, subtitle);
  const shell = create('main', 'pad-shell');
  const oldTitle = body.querySelector(':scope > h1');
  const oldIntro = oldTitle?.nextElementSibling;
  if (oldTitle) oldTitle.hidden = true;
  if (oldIntro?.tagName === 'P') oldIntro.hidden = true;
  const legend = auth.querySelector('legend'); if (legend) legend.hidden = true;
  auth.classList.add('pad-card');
  auth.setAttribute('aria-label', '账号登录');
  const modes = create('div', 'pad-modes'); modes.setAttribute('role', 'group'); modes.setAttribute('aria-label', '账号操作');
  const tabs = {};
  for (const [mode, label] of [['login', '登录'], ['register', '受邀注册']]) {
    const button = create('button', '', label); button.type = 'button'; button.id = 'pad-mode-' + mode;
    modes.append(button); tabs[mode] = button;
  }
  auth.prepend(modes);
  const fields = {};
  function labelField(id, label) {
    const input = $(id); const wrapper = create('div', 'pad-field');
    const caption = create('label', '', label); caption.htmlFor = id;
    input.before(wrapper); wrapper.append(caption, input); fields[id] = wrapper;
  }
  labelField('name', '账号'); labelField('password', '密码'); labelField('code', '邀请码');
  $('name').placeholder = '输入你的账号'; $('password').placeholder = '输入密码';
  $('name').setAttribute('autocapitalize', 'none'); $('name').spellcheck = false;
  const actions = create('div', 'pad-actions');
  auth.append(actions);
  for (const id of ['login', 'register', 'reset']) {
    $(id).classList.add('pad-primary'); actions.append($(id));
  }
  $('login').textContent = '登录'; $('register').textContent = '创建账号'; $('reset').textContent = '重置密码';
  const recovery = create('button', 'pad-recovery', '忘记密码？'); recovery.type = 'button'; recovery.id = 'pad-recovery';
  const helper = create('p', 'pad-helper', '仅限受邀用户。没有账号？向管理员获取邀请。');
  auth.append(actions, recovery, helper);
  let mode = 'login';
  function setMode(value) {
    mode = value;
    for (const id of ['login', 'register', 'reset']) $(id).hidden = id !== mode;
    fields.code.hidden = mode === 'login';
    fields.code.querySelector('label').textContent = mode === 'reset' ? '重置码' : '邀请码';
    $('code').placeholder = mode === 'reset' ? '管理员提供的一次性重置码' : '管理员提供的一次性邀请码';
    $('password').autocomplete = mode === 'login' ? 'current-password' : 'new-password';
    $('password').placeholder = mode === 'login' ? '输入密码' : '设置至少 12 个字符的密码';
    for (const [key, tab] of Object.entries(tabs)) { tab.classList.toggle('is-active', mode === key); tab.setAttribute('aria-pressed', String(mode === key)); }
    recovery.textContent = mode === 'reset' ? '返回登录' : '忘记密码？';
    helper.textContent = mode === 'reset' ? '向管理员获取重置码。重置后请使用新密码登录。' : mode === 'register' ? '使用自己的账号和密码。注册后，请返回登录。' : '仅限受邀用户。没有账号？向管理员获取邀请。';
    updateView();
  }
  tabs.login.onclick = () => setMode('login'); tabs.register.onclick = () => setMode('register');
  recovery.onclick = () => setMode(mode === 'reset' ? 'login' : 'reset');
  auth.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.isComposing && event.target.tagName === 'INPUT') {
      event.preventDefault(); $(mode).click();
    }
  });
  // Preserve original callbacks while preventing duplicate submissions.
  for (const id of ['login', 'register', 'reset', 'logout', 'bind', 'change']) {
    const button = $(id), original = button.onclick;
    if (typeof original !== 'function') continue;
    button.onclick = async function(event) {
      if (button.disabled) return;
      button.disabled = true;
      try { return await original.call(this, event); }
      finally { button.disabled = false; }
    };
  }
  const devices = $('signed'); devices.classList.add('pad-device-area');
  const empty = create('p', 'pad-empty', '还没有绑定电脑。请在自己的电脑上完成账号登录与设备绑定，再回到这里。');
  $('devices').after(empty);
  labelField('old', '当前密码'); labelField('new', '新密码');
  const passwordFieldset = $('old').closest('fieldset');
  const security = create('details', 'pad-security'); const summary = create('summary', '', '账号安全 · 修改密码');
  passwordFieldset.before(security); security.append(summary, passwordFieldset);
  $('message').classList.add('pad-message'); $('message').setAttribute('aria-live', 'polite');
  const footer = create('p', 'pad-footer', '每个账号仅能访问自己绑定的电脑。');
  shell.append(top, auth, devices, $('message'), footer);
  body.prepend(header, shell);
  function updateView() {
    const signed = !devices.hidden;
    auth.hidden = signed;
    title.textContent = signed ? '你的电脑' : mode === 'register' ? '创建你的账号' : mode === 'reset' ? '重新设置密码' : '欢迎回来';
    subtitle.textContent = signed ? '选择一台电脑，继续桌面上的工作。' : mode === 'register' ? '受邀加入，连接自己的工作空间。' : mode === 'reset' ? '使用管理员提供的重置码恢复访问。' : '登录后，继续自己电脑上的工作。';
    empty.hidden = $('devices').children.length > 0;
  }
  new MutationObserver(updateView).observe(devices, { attributes: true, attributeFilter: ['hidden'] });
  new MutationObserver(updateView).observe($('devices'), { childList: true });
  document.documentElement.dataset.padTheme = '3';
  setMode('login');
  return true;
}
if (typeof document !== 'undefined' && location.pathname === '/account') enhanceAccount(document);
