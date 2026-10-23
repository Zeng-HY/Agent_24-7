/* Shared theme controller. Loaded before page paint; no network or account data. */
(() => {
  const KEY = 'teleply.theme.v1', valid = v => ['system','light','dark'].includes(v);
  const root = document.documentElement, media = matchMedia('(prefers-color-scheme: dark)');
  const script = document.currentScript;
  const asset = name => new URL(name + (script?.src ? new URL(script.src).search : ''), script?.src || location.href).href;
  let mode = 'system';
  try { const saved = localStorage.getItem(KEY); if (valid(saved)) mode = saved; } catch {}
  function apply() {
    const dark = mode === 'dark' || (mode === 'system' && media.matches);
    root.dataset.theme = dark ? 'dark' : 'light'; root.dataset.themeMode = mode;
    const metas=[...document.querySelectorAll('meta[name="theme-color"]')];
    let meta=metas.shift();if(!meta){meta=document.createElement('meta');meta.name='theme-color';document.head.append(meta);}
    for(const duplicate of metas)duplicate.remove();
    meta.content=dark?'#000000':'#ffffff';
    let icon = document.querySelector('link[rel="icon"]');
    if (!icon) { icon = document.createElement('link'); icon.rel = 'icon'; document.head.append(icon); }
    icon.type = 'image/svg+xml'; icon.href = asset(dark ? 'favicon-dark.svg' : 'favicon.svg');
    document.querySelectorAll('[data-theme-choice]').forEach(b => b.setAttribute('aria-checked', String(b.dataset.themeChoice === mode)));
    const detail={mode,resolved:root.dataset.theme};
    dispatchEvent(new CustomEvent('teleply-theme-change',{detail}));
    try{if(window.__teleplyAppearanceDocument)window.TeleplyAppearance?.postMessage(JSON.stringify({...detail,document:window.__teleplyAppearanceDocument}));}catch{}
  }
  function set(value) { if (!valid(value)) return false; mode=value; try {localStorage.setItem(KEY,value);} catch {} apply(); return true; }
  window.TeleplyTheme = {set, get:()=>mode};
  media.addEventListener('change',()=>{if(mode==='system')apply();});
  addEventListener('storage',e=>{if(e.key===KEY || e.key===null){mode=valid(e.newValue)?e.newValue:'system';apply();}});
  addEventListener('pageshow',apply);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)apply();});
  apply();
  function choices(container) {
    const title=document.createElement('h2');title.className='theme-title';title.textContent='外观';
    const group=document.createElement('div');group.className='theme-choices';group.setAttribute('role','radiogroup');group.setAttribute('aria-label','外观');
    for(const [value,label] of [['system','跟随系统'],['light','浅色'],['dark','深色']]) {
      const b=document.createElement('button');b.type='button';b.dataset.themeChoice=value;b.setAttribute('role','radio');
      b.textContent=label;b.onclick=()=>set(value);
      b.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const buttons=[...group.children],i=buttons.indexOf(b),next=e.key==='Home'?0:e.key==='End'?2:(i+(e.key==='ArrowLeft'?2:1))%3;buttons[next].focus();set(buttons[next].dataset.themeChoice);};
      group.append(b);
    }
    container.prepend(title,group);
  }
  document.addEventListener('DOMContentLoaded',()=>{
    const settings=document.getElementById('settingsBody');
    if(settings) choices(settings);
    else {
      const details=document.createElement('details');details.className='theme-settings';
      const summary=document.createElement('summary');summary.textContent='设置';details.append(summary);
      const panel=document.createElement('div');panel.className='theme-settings-panel';choices(panel);details.append(panel);
      const main=document.querySelector('main') || document.body;main.prepend(details);
    }
    apply();
  });
})();
