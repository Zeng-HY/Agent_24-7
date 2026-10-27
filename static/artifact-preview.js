/* Exact-reference adapter only. No filesystem paths are sent by this module. */
(() => {
  'use strict';
  const LIMIT = Object.freeze({text: 1<<20, binary: 16<<20, download: 64<<20, resources: 4<<20, pixels: 16000000, side:8192, nodes:20000});
  const TAGS='html head body title style p br div span main section article header footer nav aside h1 h2 h3 h4 h5 h6 ul ol li dl dt dd blockquote strong em b i u s small sub sup hr pre code table caption colgroup col thead tbody tfoot tr th td a img figure figcaption details summary'.split(' ');
  const ATTRS='class id style title alt src href rel width height colspan rowspan start open lang dir'.split(' ');
  const CSP="default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src 'none'; connect-src 'none'; media-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'";
  const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
  const fail=status=>new Error(({401:'登录已失效，请重新登录',403:'附件引用无效或不属于当前会话',404:'文件已移动或删除',409:'文件在读取时发生变化，请重试'})[status]||'文件读取失败（'+status+'）');
  function decode(bytes){
    const a=new Uint8Array(bytes);let encoding='utf-8';
    if(a[0]===255&&a[1]===254)encoding='utf-16le';else if(a[0]===254&&a[1]===255)encoding='utf-16be';
    let text;try{text=new TextDecoder(encoding,{fatal:true}).decode(a);}catch{throw Error('无法按 UTF-8 或 UTF-16 读取，请下载原文件');}
    if(/[\x00-\x08\x0e-\x1f]/.test(text))throw Error('内容不是可预览的文本，请下载原文件');
    return text;
  }
  function dimensions(a){
    const v=new DataView(a.buffer,a.byteOffset,a.byteLength);let w,h,mime;
    if(a.length>=24&&[137,80,78,71,13,10,26,10].every((x,i)=>a[i]===x)){w=v.getUint32(16);h=v.getUint32(20);mime='image/png';}
    else if(a.length>4&&a[0]===255&&a[1]===216){
      let i=2;while(i+8<a.length){if(a[i++]!==255)break;while(a[i]===255)i++;const marker=a[i++];if(marker===217||marker===218)break;
        const len=v.getUint16(i);if(len<2||i+len>a.length)break;
        if([192,193,194].includes(marker)){h=v.getUint16(i+3);w=v.getUint16(i+5);mime='image/jpeg';break;}i+=len;}
    }else if(a.length>=30&&String.fromCharCode(...a.slice(0,4))==='RIFF'&&String.fromCharCode(...a.slice(8,12))==='WEBP'){
      const type=String.fromCharCode(...a.slice(12,16));mime='image/webp';
      if(type==='VP8X'){if(a[20]&2)throw Error('动态图请下载查看');w=1+a[24]+a[25]*256+a[26]*65536;h=1+a[27]+a[28]*256+a[29]*65536;}
      else if(type==='VP8 '&&a[23]===157&&a[24]===1&&a[25]===42){w=v.getUint16(26,true)&16383;h=v.getUint16(28,true)&16383;}
      else if(type==='VP8L'&&a[20]===47){w=1+a[21]+((a[22]&63)<<8);h=1+(a[22]>>6)+(a[23]<<2)+((a[24]&15)<<10);}
    }
    if(!w||!h||w>LIMIT.side||h>LIMIT.side||w*h>LIMIT.pixels)throw Error('图片损坏、格式不支持或尺寸超过预览上限，请下载原文件');
    return {w,h,mime};
  }
  const css=s=> /[\\<]|url\s*\(|@import|@font-face|expression\s*\(|-moz-binding/i.test(s)?'':s;
  const relative=s=>!!s&&!/^[\\/]|:|[?#\x00-\x1f]/.test(s);
  const dataImage=bytes=>{const a=new Uint8Array(bytes),d=dimensions(a);let s='';for(let i=0;i<a.length;i+=8192)s+=String.fromCharCode(...a.subarray(i,i+8192));return 'data:'+d.mime+';base64,'+btoa(s);};
  async function cleanHTML(source,resource,signal){
    if(!window.DOMPurify)throw Error('预览组件未加载，请重试或下载原文件');
    // DOMPurify's inert template document is never inserted in the parent page.
    const doc=DOMPurify.sanitize(source,{ALLOWED_TAGS:[...TAGS,'link'],ALLOWED_ATTR:ATTRS,ALLOW_DATA_ATTR:false,ALLOW_ARIA_ATTR:false,WHOLE_DOCUMENT:true,RETURN_DOM:true});
    if(doc.querySelectorAll('*').length>LIMIT.nodes)throw Error('页面过于复杂，请下载查看');
    let missing=false,budget=LIMIT.resources,count=0;
    async function load(path){if(!relative(path)||!resource||++count>16)throw Error('unprovided');const b=await resource(path,signal,Math.min(budget,LIMIT.text));budget-=b.byteLength;if(budget<0)throw Error('limit');return b;}
    for(const node of doc.querySelectorAll('*')){
      if(signal?.aborted)throw new DOMException('Aborted','AbortError');
      if(node.hasAttribute('style')){const raw=node.getAttribute('style'),safe=css(raw);node.setAttribute('style',safe);if(raw&&!safe)missing=true;}
      if(node.tagName==='STYLE'){const raw=node.textContent;node.textContent=css(raw);if(raw&&!node.textContent)missing=true;}
      if(node.tagName==='LINK'){
        try{if(node.getAttribute('rel')!=='stylesheet')throw Error('link');const raw=decode(await load(node.getAttribute('href'))),safe=css(raw);if(raw&&!safe)throw Error('css');node.replaceWith(el('style','',safe));}catch(e){if(signal?.aborted)throw e;missing=true;node.remove();}continue;
      }
      if(node.tagName==='IMG'){
        const src=node.getAttribute('src')||'';node.removeAttribute('src');
        try{let bytes;if(/^data:image\/(png|jpeg|webp);base64,[a-z0-9+/=]+$/i.test(src)&&src.length<=LIMIT.text*1.4){const raw=atob(src.split(',')[1]);bytes=Uint8Array.from(raw,c=>c.charCodeAt(0));budget-=bytes.length;if(budget<0)throw Error('limit');}else bytes=await load(src);node.setAttribute('src',dataImage(bytes));}
        catch(e){if(signal?.aborted)throw e;missing=true;node.setAttribute('alt',(node.getAttribute('alt')||'图片')+'（资源未提供）');}
      }else node.removeAttribute('src');
      // Links are readable labels in a static preview, never navigation/download actions.
      node.removeAttribute('href');node.removeAttribute('rel');
    }
    const body=doc.querySelector('body')||doc,head=doc.querySelector('head');
    return {html:'<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="'+CSP+'"><meta name="viewport" content="width=device-width,initial-scale=1"><style>html{overflow-wrap:anywhere}img{max-width:100%;height:auto}body{margin:16px}pre,table{max-width:100%;overflow:auto}</style>'+(head?.innerHTML||'')+'</head>'+body.outerHTML+'</html>',missing};
  }
  // told: the computer's own words on a failure ({error}) are shown instead of the status's (the PDF of an Office file)
  async function request(url,parentSignal,limit,json=false,wait=60000,told=false){
    const controller=new AbortController(),signal=controller.signal;
    const abort=()=>controller.abort();parentSignal.addEventListener('abort',abort,{once:true});if(parentSignal.aborted)abort();
    const timeout=setTimeout(abort,wait);
    try{
    let r;try{r=await fetch(url,{credentials:'same-origin',cache:'no-store',signal,redirect:'error'});}catch(e){if(signal.aborted)throw e;throw Error('连接中断或电脑离线，请重试');}
    if(!r.ok){const said=told&&r.status!==401?await r.json().then(j=>String(j.error||''),()=>''):'';throw said?Error(said):fail(r.status);}
    if(Number(r.headers.get('Content-Length'))>limit){r.body?.cancel();throw Error('文件超过读取上限，请下载原文件');}
    const reader=r.body?.getReader();if(!reader)throw Error('浏览器不支持此读取方式');
    const parts=[];let size=0;try{while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>limit)throw Error('文件超过读取上限，请下载原文件');parts.push(value);}}catch(e){await reader.cancel().catch(()=>{});throw e;}finally{reader.releaseLock();}
    const bytes=new Uint8Array(size);let at=0;for(const p of parts){bytes.set(p,at);at+=p.length;}
    return json?JSON.parse(decode(bytes)):bytes;
    }catch(e){if(signal.aborted&&!parentSignal.aborted)throw Error('读取超时，请重试');throw e;}
    finally{clearTimeout(timeout);parentSignal.removeEventListener('abort',abort);}
  }
  function adapter(target,file){
    if(!target?.app||!target?.id||!file?.id)throw Error('缺少附件引用');
    const q=new URLSearchParams({app:target.app,id:target.id,file:file.id});
    const url='/api/file?'+q+'&download=1';
    return {meta:s=>request('/api/file/meta?'+q,s,65536,true),bytes:(s,l)=>request(url,s,l),url,
      pdf:(s,l)=>request('/api/file/pdf?'+q,s,l,false,120000,true),  // Office starts first: up to a minute
      resource:async(path,signal,limit)=>{
        if(!relative(path)||!file.path)throw Error('unprovided');
        // Match only server-listed exact files. Normalization grants no directory authority.
        const norm=p=>{const parts=[];for(const bit of p.replace(/\\/g,'/').split('/')){if(bit==='..')parts.pop();else if(bit&&bit!=='.')parts.push(bit);}return parts.join('/').toLowerCase();};
        const listing=await request('/api/chat/files?'+new URLSearchParams({app:target.app,id:target.id}),signal,1<<20,true);
        const base=file.path.replace(/\\/g,'/').replace(/[^/]+$/,'');
        const match=listing.items.find(x=>x.id&&x.path&&norm(x.path)===norm(base+decodeURIComponent(path)));
        if(!match)throw Error('unprovided');
        return request('/api/file?'+new URLSearchParams({app:target.app,id:target.id,file:match.id,download:'1'}),signal,limit);
      }};
  }
  let active=null;
  function close(){if(!active)return;const s=active;active=null;s.controller.abort();clearTimeout(s.timer);for(const u of s.urls)URL.revokeObjectURL(u);s.dialog.close();s.dialog.remove();s.focus?.focus({preventScroll:true});}
  async function open(target,file,options={}){
    close();const s={controller:new AbortController(),urls:new Set(),focus:document.activeElement};active=s;
    const valid=()=>active===s&&!s.controller.signal.aborted;
    const dialog=el('dialog','artifact-panel');s.dialog=dialog;dialog.setAttribute('aria-label','附件详情');
    const header=el('header','artifact-header'),back=el('button','tp-icon-button');back.type='button';back.setAttribute('aria-label','返回聊天');
    back.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="m14 6-6 6 6 6"/></svg>';back.onclick=close;
    const heading=el('div','tp-header-title');heading.append(el('strong','',file.name||'附件'));
    const tools=el('div','tp-toolbar'),save=el('button','tp-button','下载');tools.append(save);header.append(back,heading,tools);
    const info=el('div','artifact-info'),full=el('details'),summary=el('summary','','文件详情');full.append(summary,el('div','artifact-name',file.name||'附件'));info.append(full);
    const status=el('p','artifact-status','正在读取…');status.setAttribute('role','status');
    const tabs=el('div','theme-choices artifact-tabs');tabs.hidden=true;const body=el('div','artifact-body');
    dialog.append(header,info,status,tabs,body);document.body.append(dialog);dialog.showModal();back.focus();dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
    const a=options.adapter||adapter(target,file),signal=s.controller.signal;
    const object=blob=>{const u=URL.createObjectURL(blob);s.urls.add(u);return u;};
    const error=e=>{if(valid())status.textContent=e.message;};
    s.timer=setTimeout(()=>{if(valid()){status.textContent='读取超时，请重新打开或重试';s.controller.abort();}},60000);
    save.onclick=async()=>{
      save.disabled=true;try{
        if(s.downloadURL){URL.revokeObjectURL(s.downloadURL);s.urls.delete(s.downloadURL);s.downloadURL=null;}
        const m=await a.meta(signal);if(!valid())return;
        if(m.size>LIMIT.download){
          // Browser streams to disk; no large ArrayBuffer/DOM allocation. Errors cannot replace chat.
          const link=el('a');link.href=a.url;link.download=m.name||file.name;dialog.append(link);link.click();link.remove();
          status.textContent='已交给浏览器下载；请在下载列表查看结果。失败后可点下载重试。';return;
        }
        const bytes=await a.bytes(signal,LIMIT.download);if(!valid())return;
        const link=el('a');s.downloadURL=object(new Blob([bytes],{type:'application/octet-stream'}));link.href=s.downloadURL;link.download=m.name||file.name;dialog.append(link);link.click();link.remove();status.textContent='已准备原文件，请在浏览器下载或分享菜单中保存。';
      }catch(e){error(e);}finally{if(valid())save.disabled=false;}
    };
    try{
      const m=await a.meta(signal);if(!valid())return;
      const name=m.name||file.name||'',ext=name.toLowerCase().split('.').pop();
      heading.firstChild.textContent=name;full.lastChild.textContent=name+' · '+m.size+' 字节';
      status.textContent=(m.updated||m.state==='updated'||file.state==='updated'?'文件已更新 · ':'')+'当前文件';
      // Word, Excel and PowerPoint: this computer's Office turns them into a PDF to look at; 下载 keeps the original (10-27)
      const office=m.kind==='download'&&m.preview==='pdf'&&!!a.pdf&&!options.downloadOnly;
      const kind=office?'pdf':['html','htm'].includes(ext)?'html':['md','markdown'].includes(ext)?'markdown':['png','jpg','jpeg','webp'].includes(ext)?'image':ext==='pdf'?'pdf':m.kind==='text'||/^(txt|json|csv|tsv|py|js|css|ts|tsx|jsx|ps1|sh|yaml|yml|sql|xml|log|c|h|cpp|rs|go)$/.test(ext)?'text':'download';
      if(kind==='download'||options.downloadOnly){const card=el('p','artifact-file');card.innerHTML='<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M14 3H5v18h14V8zM14 3v5h5"/></svg>';card.append(document.createTextNode(' '+name));body.append(card,el('p','','此文件可下载后使用相应应用打开。'));return;}
      if(!office&&m.size>(['html','markdown','text'].includes(kind)?LIMIT.text:LIMIT.binary)){body.append(el('p','','文件超过预览上限，请下载原文件。'));return;}
      if(office){status.textContent+=' · 正在用电脑上的 Office 转成 PDF…';clearTimeout(s.timer);s.timer=setTimeout(()=>{if(valid()){status.textContent='转换超时，请下载原文件';s.controller.abort();}},125000);}
      const bytes=await (office?a.pdf(signal,LIMIT.binary):a.bytes(signal,['html','markdown','text'].includes(kind)?LIMIT.text:LIMIT.binary));if(!valid())return;
      if(office)status.textContent=status.textContent.replace('正在用电脑上的 Office 转成 PDF…','电脑上的 Office 转成的 PDF');
      if(!bytes.length){body.append(el('p','','这是一个空文件。'));return;}
      if(kind==='image'){
        const d=dimensions(new Uint8Array(bytes)),img=el('img','artifact-image');img.alt=name;img.width=d.w;img.height=d.h;img.src=object(new Blob([bytes],{type:d.mime}));img.onerror=()=>error(Error('图片无法显示，请下载原文件'));body.append(img);return;
      }
      if(kind==='pdf'){
        if(new TextDecoder().decode(bytes.slice(0,5))!=='%PDF-')throw Error('内容不是有效的 PDF，请下载原文件');
        body.append(el('p','','若此浏览器无法显示 PDF，请点下载，在“文件”中打开。'));
        const frame=el('iframe','artifact-frame');frame.title=name;frame.setAttribute('sandbox','');frame.src=object(new Blob([bytes],{type:'application/pdf'}));body.append(frame);return;
      }
      const source=decode(bytes);s.source=source;
      const pre=el('pre','artifact-source',source),copy=el('button','tp-button','复制源码');
      copy.onclick=async()=>{try{await navigator.clipboard.writeText(source);if(valid())status.textContent='已复制原文';}catch{error(Error('复制失败，可选中文本复制或下载'));}};
      const sourceView=()=>{body.replaceChildren(copy,pre);};
      if(kind==='text'){sourceView();return;}
      const rendered=kind==='markdown'?window.markdownit({html:false,linkify:false}).render(source):source;
      const safe=await cleanHTML(rendered,a.resource,signal);if(!valid())return;
      status.textContent+=(kind==='html'?' · 静态预览，不运行脚本':'')+(safe.missing?' · 部分资源未提供':'');
      const frame=el('iframe','artifact-frame');frame.title=name;frame.setAttribute('sandbox','');frame.referrerPolicy='no-referrer';frame.srcdoc=safe.html;
      const view=el('button','',kind==='html'?'查看页面':'阅读视图'),raw=el('button','','查看源码');
      for(const b of [view,raw]){b.type='button';b.setAttribute('aria-checked','false');}
      const select=sourceMode=>{view.setAttribute('aria-checked',String(!sourceMode));raw.setAttribute('aria-checked',String(sourceMode));if(sourceMode)sourceView();else body.replaceChildren(frame);};
      view.onclick=()=>select(false);raw.onclick=()=>select(true);tabs.addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();const next=e.target===view?raw:view;next.click();next.focus();}});
      tabs.append(view,raw);tabs.hidden=false;select(false);
    }catch(e){if(valid()){status.textContent=e.message;const retry=el('button','tp-button','重试');retry.onclick=()=>open(target,file,options);body.append(retry);}}
    finally{clearTimeout(s.timer);}
  }
  addEventListener('pagehide',close);
  window.artifactPreview={open,close,adapter,limits:LIMIT,decode,dimensions,cleanHTML};
})();
