/* Injected by the authenticated relay only. Device scope is fixed per tab. */
(()=>{'use strict';const match=location.pathname.match(/^\/d\/([0-9a-f]{32})(?:\/|$)/);if(!match)return;
const base='/d/'+match[1];window.RELAY_BASE=base;
try{localStorage.setItem('ar-last-device',match[1]);}catch{}
// Pointer taps and programmatic dialog focus must not leave keyboard rings on iOS.
if(!window.arFocusModality){window.arFocusModality=true;document.documentElement.dataset.input='pointer';
for(const event of ['pointerdown','touchstart'])document.addEventListener(event,()=>{document.documentElement.dataset.input='pointer';},{capture:true,passive:true});
document.addEventListener('keydown',event=>{if(event.key==='Tab')document.documentElement.dataset.input='keyboard';},true);}
const focusStyle=document.createElement('style');focusStyle.textContent='html[data-input="pointer"] button:focus,html[data-input="pointer"] [tabindex]:focus,html[data-input="pointer"] dialog:focus{outline:none!important}html[data-input="pointer"] .tree-row:focus,html[data-input="pointer"] .tree-add:focus{box-shadow:none!important}\n';document.head.append(focusStyle);
function scoped(value){if(typeof value!=='string')return value;try{const u=new URL(value,location.href);if(u.origin!==location.origin||/^\/(?:d\/|account(?:\/|$)|device-auth\/)/.test(u.pathname))return value;u.pathname=base+u.pathname;return u.href;}catch{return value;}}
const fetch0=window.fetch.bind(window);window.fetch=(input,init)=>fetch0(input instanceof Request?new Request(scoped(input.url),input):scoped(String(input)),init);
const ES=window.EventSource;window.EventSource=class extends ES{constructor(url,options){super(scoped(String(url)),options)}};
const open0=window.open.bind(window);window.open=(url,...args)=>open0(scoped(String(url)),...args);
const attr=Element.prototype.setAttribute;Element.prototype.setAttribute=function(name,value){return attr.call(this,name,['src','href','action','poster'].includes(name)?scoped(String(value)):value);};
for(const [prototype,key] of [[HTMLImageElement.prototype,'src'],[HTMLAnchorElement.prototype,'href'],[HTMLMediaElement.prototype,'src'],[HTMLScriptElement.prototype,'src'],[HTMLLinkElement.prototype,'href'],[HTMLIFrameElement.prototype,'src']]){const desc=Object.getOwnPropertyDescriptor(prototype,key);if(desc?.set)Object.defineProperty(prototype,key,{...desc,set(value){desc.set.call(this,scoped(String(value)))}});}
const xhr=XMLHttpRequest.prototype.open;XMLHttpRequest.prototype.open=function(method,url,...args){return xhr.call(this,method,scoped(String(url)),...args)};
const html=value=>String(value).replace(/((?:src|href|action|poster)=["'])\/(?!\/|d\/|account(?:\/|["']))/g,'$1'+base+'/');
const inner=Object.getOwnPropertyDescriptor(Element.prototype,'innerHTML');if(inner?.set)Object.defineProperty(Element.prototype,'innerHTML',{...inner,set(value){inner.set.call(this,html(value))}});
const adjacent=Element.prototype.insertAdjacentHTML;Element.prototype.insertAdjacentHTML=function(where,value){return adjacent.call(this,where,html(value))};
function connectionSettings(trigger){
  if(document.querySelector('.ar-connection[open]'))return;
  if(!document.getElementById('ar-connection-style')){
    const style=document.createElement('style');style.id='ar-connection-style';style.textContent=`
    dialog.ar-connection{box-sizing:border-box;position:fixed;inset:0;margin:auto;width:min(400px,calc(100vw - 32px));height:fit-content;max-height:80dvh;overflow:auto;padding:24px;border:1px solid #e8e8ec;border-radius:26px;background:#fff;color:#111113;box-shadow:0 24px 64px #11111326,0 4px 16px #1111130a;font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
    dialog.ar-connection::backdrop{background:rgba(17,17,19,.22)}
    .ar-connection .ar-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:20px}
    .ar-connection .ar-head h2{margin:0;font-size:22px;font-weight:650;color:#111113;line-height:1.3}
    .ar-connection button{font:inherit;cursor:pointer;border:0;min-height:44px}
    .ar-connection .ar-close{display:grid;place-items:center;width:44px;flex:none;padding:0;border-radius:50%;background:#f4f4f6;color:#62626b}
    .ar-connection .ar-close svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round}
    .ar-connection .ar-address{padding:16px;border-radius:16px;background:#f4f4f6}
    .ar-connection .ar-label{font-size:12px;color:#72727b;margin-bottom:6px}
    .ar-connection .ar-url{font-size:16px;overflow-wrap:anywhere;user-select:text;-webkit-user-select:text}
    .ar-connection .ar-done{width:100%;margin-top:24px;border-radius:16px;background:#111113;color:#fff;height:50px;font-weight:600}
    .ar-connection button:focus-visible{outline:2px solid #62626b;outline-offset:3px}
    @media(max-width:600px){dialog.ar-connection{inset:auto 0 max(16px,env(safe-area-inset-bottom));margin:0 auto}}
    `;document.head.append(style);
  }
  const d=document.createElement('dialog');d.className='ar-connection';d.setAttribute('aria-labelledby','ar-connection-title');
  const head=document.createElement('div');head.className='ar-head';
  const title=document.createElement('h2');title.id='ar-connection-title';title.textContent='连接设置';
  const close=document.createElement('button');close.className='ar-close';close.setAttribute('aria-label','关闭连接设置');
  close.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>';
  const address=document.createElement('div');address.className='ar-address';
  const label=document.createElement('div');label.className='ar-label';label.textContent='服务器地址';
  const url=document.createElement('div');url.className='ar-url';url.textContent=location.origin;
  const done=document.createElement('button');done.className='ar-done';done.textContent='完成';
  close.onclick=done.onclick=()=>d.close();head.append(title,close);address.append(label,url);d.append(head,address,done);
  d.addEventListener('click',e=>{const r=d.getBoundingClientRect();if(e.target===d&&(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom))d.close();});
  d.addEventListener('close',()=>{d.remove();trigger?.focus();});document.body.append(d);d.showModal();
}
document.addEventListener('DOMContentLoaded',()=>{document.title='Teleply';let appTitle=document.querySelector('meta[name="apple-mobile-web-app-title"]');if(!appTitle){appTitle=document.createElement('meta');appTitle.name='apple-mobile-web-app-title';document.head.append(appTitle);}appTitle.content='Teleply';const nav=document.querySelector('#navSheet .box');if(nav){const section=document.createElement('div');section.className='relay-menu';for(const [label,action] of [['账号与电脑',()=>location.assign('/account?choose=1')],['刷新',()=>location.reload()],['连接设置',event=>connectionSettings(event.currentTarget)]]){const b=document.createElement('button');b.className='menu-row';b.textContent=label;b.onclick=action;section.append(b);}nav.append(section);}const subtitle=document.getElementById('appSubtitle');if(subtitle){subtitle.disabled=false;subtitle.onclick=()=>location.assign('/account?choose=1');} });
})();
