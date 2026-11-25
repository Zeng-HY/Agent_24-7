/* Exact-reference adapter only. No filesystem paths are sent by this module. */
(() => {
  'use strict';
  const LIMIT = Object.freeze({text: 1<<20, binary: 16<<20, download: 64<<20, resources: 4<<20, pixels: 16000000, side:8192, nodes:20000});
  const TAGS='html head body title style p br div span main section article header footer nav aside h1 h2 h3 h4 h5 h6 ul ol li dl dt dd blockquote strong em b i u s small sub sup hr pre code table caption colgroup col thead tbody tfoot tr th td a img figure figcaption details summary'.split(' ');
  const ATTRS='class id style title alt src href rel width height colspan rowspan start open lang dir'.split(' ');
  const CSP="default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; media-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'";
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
  const css=s=> /[\\<]|@import|expression\s*\(|-moz-binding/i.test(s)?'':s.replace(/url\(\s*(?:"([^"]*)"|'([^']*)'|([^)]*))\s*\)/gi,(m,a,b,c)=>/^(?:data:|#)/i.test((a??b??c??'').trim())?m:'none');
  const relative=s=>!!s&&!/^[\\/]|:|[?#\x00-\x1f]/.test(s);
  const dataImage=bytes=>{const a=new Uint8Array(bytes),d=dimensions(a);let s='';for(let i=0;i<a.length;i+=8192)s+=String.fromCharCode(...a.subarray(i,i+8192));return 'data:'+d.mime+';base64,'+btoa(s);};
  const RES_MIME={png:'image/png',jpg:'image/jpeg',jpeg:'image/jpeg',webp:'image/webp',gif:'image/gif',bmp:'image/bmp',
    tif:'image/tiff',tiff:'image/tiff',heic:'image/heic',heif:'image/heic',avif:'image/avif',svg:'image/svg+xml',
    woff:'font/woff',woff2:'font/woff2',ttf:'font/ttf',otf:'font/otf',eot:'application/vnd.ms-fontobject'};
  const b64=bytes=>{const a=new Uint8Array(bytes);let s='';for(let i=0;i<a.length;i+=8192)s+=String.fromCharCode(...a.subarray(i,i+8192));return btoa(s);};
  async function cleanHTML(source,resource,signal){
    if(!window.DOMPurify)throw Error('预览组件未加载，请重试或下载原文件');
    // DOMPurify's inert template document is never inserted in the parent page.
    const doc=DOMPurify.sanitize(source,{ALLOWED_TAGS:[...TAGS,'link'],ALLOWED_ATTR:ATTRS,ALLOW_DATA_ATTR:false,ALLOW_ARIA_ATTR:false,WHOLE_DOCUMENT:true,RETURN_DOM:true});
    if(doc.querySelectorAll('*').length>LIMIT.nodes)throw Error('页面过于复杂，请下载查看');
    let missing=false,budget=LIMIT.resources,count=0;
    async function load(path){if(!relative(path)||!resource||++count>64)throw Error('unprovided');const b=await resource(path,signal,Math.min(budget,LIMIT.text));budget-=b.byteLength;if(budget<0)throw Error('limit');return b;}
    async function inlineCSS(raw){
      const jobs=[];
      let text=String(raw).replace(/url\(\s*(?:"([^"]*)"|'([^']*)'|([^)]*))\s*\)/gi,(match,a,b,c)=>{
        const ref=(a??b??c??'').trim(),token='__teleply_resource_'+jobs.length+'__';
        if(/^(?:data:|#)/i.test(ref))return match;
        jobs.push({token,ref});return token;
      });
      for(const job of jobs){
        try{const bytes=await load(job.ref);const ext=(job.ref.split(/[?#]/)[0].split('.').pop()||'').toLowerCase();
          text=text.replace(job.token,'url("data:'+(RES_MIME[ext]||'application/octet-stream')+';base64,'+b64(bytes)+'")');}
        catch(error){if(signal?.aborted)throw error;missing=true;text=text.replace(job.token,'none');}
      }
      return css(text);
    }
    for(const node of doc.querySelectorAll('*')){
      if(signal?.aborted)throw new DOMException('Aborted','AbortError');
      if(node.hasAttribute('style')){const raw=node.getAttribute('style'),safe=await inlineCSS(raw);node.setAttribute('style',safe);if(raw&&!safe)missing=true;}
      if(node.tagName==='STYLE'){const raw=node.textContent;node.textContent=await inlineCSS(raw);if(raw&&!node.textContent)missing=true;}
      if(node.tagName==='LINK'){
        try{if(node.getAttribute('rel')!=='stylesheet')throw Error('link');const raw=decode(await load(node.getAttribute('href'))),safe=await inlineCSS(raw);if(raw&&!safe)throw Error('css');node.replaceWith(el('style','',safe));}catch(e){if(signal?.aborted)throw e;missing=true;node.remove();}continue;
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
      text:s=>request('/api/file/text?'+q,s,8<<20,true),
      pdf:(s,l)=>request('/api/file/pdf?'+q,s,l,false,120000,true),  // Office starts first: up to a minute
      zip:s=>request('/api/file/zip?'+q+(file.v?'&v='+encodeURIComponent(file.v):''),s,4<<20,true,60000,true),
      resource:async(path,signal,limit)=>{
        if(!relative(path)||!file.path)throw Error('unprovided');
        return request('/api/file/resource?'+new URLSearchParams({app:target.app,id:target.id,file:file.id,path}),signal,limit);
      }};
  }
  // ---- code and table pages (docs/handoff-file-preview.md §6.2)
  const HLJS_VERSION='11.12.0';
  const CODE_HIGHLIGHT_LIMIT=200<<10;
  let highlightPromise=null,codeThemeLink=null;
  function loadScript(src){
    return new Promise((resolve,reject)=>{const script=document.createElement('script');script.src=src;script.async=false;
      script.onload=resolve;script.onerror=reject;document.head.append(script);});
  }
  function ensureHighlight(){
    if(window.hljs)return Promise.resolve(window.hljs);
    if(highlightPromise)return highlightPromise;
    const base='/highlight/';
    highlightPromise=loadScript(base+'highlight.min.js?v='+HLJS_VERSION)
      .then(()=>Promise.all(['highlight.r.min.js','highlight.powershell.min.js','highlight.latex.min.js','highlight.dockerfile.min.js']
        .map(name=>loadScript(base+name+'?v='+HLJS_VERSION).catch(()=>null))))
      .then(()=>window.hljs||null).catch(()=>null);
    return highlightPromise;
  }
  function ensureCodeTheme(){
    if(!codeThemeLink){codeThemeLink=document.createElement('link');codeThemeLink.rel='stylesheet';codeThemeLink.id='code-theme';document.head.append(codeThemeLink);}
    const href='/highlight/code-'+(document.documentElement.dataset.theme==='dark'?'dark':'light')+'.css?v='+HLJS_VERSION;
    if(codeThemeLink.getAttribute('href')!==href)codeThemeLink.href=href;
  }
  addEventListener('teleply-theme-change',ensureCodeTheme);
  const CODE_LANG={r:'r',py:'python',js:'javascript',mjs:'javascript',ts:'typescript',tsx:'typescript',jsx:'javascript',
    json:'json',yaml:'yaml',yml:'yaml',xml:'xml',sql:'sql',sh:'bash',bash:'bash',ps1:'powershell',kt:'kotlin',kts:'kotlin',
    swift:'swift',java:'java',c:'c',h:'c',cpp:'cpp',hpp:'cpp',cs:'csharp',go:'go',rs:'rust',css:'css',scss:'css',less:'css',
    md:'markdown',markdown:'markdown',ini:'ini',cfg:'ini',conf:'ini',toml:'ini',diff:'diff',patch:'diff',tex:'latex',
    dockerfile:'dockerfile'};
  const codeLang=(ext,lang)=>lang||CODE_LANG[String(ext||'').toLowerCase()]||null;
  const fileMb=n=>{const v=Number(n)/(1<<20);return (v>=10?Math.round(v):Math.round(v*10)/10)+' MB';};
  function copyPlain(text){
    return (async()=>{
      try{await navigator.clipboard.writeText(text);return true;}catch{}
      const area=el('textarea');area.value=text;area.readOnly=true;area.style.cssText='position:fixed;left:0;top:0;width:1px;height:1px;opacity:0';
      document.body.append(area);let ok=false;try{area.select();area.setSelectionRange(0,text.length);ok=document.execCommand('copy');}catch{}
      area.remove();return ok;
    })();
  }
  function highlightedFragments(value,text,lines){
    const holder=document.createElement('div');holder.innerHTML=value;
    const map=[];let total=0,walker=document.createTreeWalker(holder,NodeFilter.SHOW_TEXT);
    while(walker.nextNode()){const node=walker.currentNode;map.push({node,start:total,end:total+node.data.length});total+=node.data.length;}
    const at=offset=>{
      for(const item of map)if(offset<=item.end)return [item.node,Math.max(0,offset-item.start)];
      const last=map.at(-1);return last?[last.node,last.data.length]:[holder,holder.childNodes.length];
    };
    const fragments=[];let offset=0;
    for(const line of lines){
      const start=offset,end=offset+line.length,range=document.createRange();
      try{const [sn,so]=at(start),[en,eo]=at(end);range.setStart(sn,so);range.setEnd(en,eo);fragments.push(range.cloneContents());}
      catch{fragments.push(document.createTextNode(line));}
      offset=end+1;
    }
    return fragments;
  }
  async function buildCodePage(body,made,name,ext,m,signal){
    ensureCodeTheme();
    const text=made.text||'',lines=text.split('\n'),language=codeLang(ext,made.lang||m.lang);
    const large=new Blob([text]).size>CODE_HIGHLIGHT_LIMIT;
    const wrap=el('button','code-tool','自动换行');wrap.type='button';wrap.setAttribute('aria-pressed','false');
    const find=el('input','code-find');find.type='search';find.placeholder='在代码里查找';find.setAttribute('aria-label','在代码里查找');
    const prev=el('button','code-tool','上一个');prev.type='button';const next=el('button','code-tool','下一个');next.type='button';
    const hits=el('span','code-hits','');const copy=el('button','code-tool','复制全部');copy.type='button';
    const toolbar=el('div','code-toolbar');toolbar.append(wrap,find,prev,next,hits,copy);
    const notes=el('div','code-notes');
    if(made.truncated)notes.append(el('p','','只显示了开头 '+fileMb(new Blob([text]).size)+'（文件共 '+fileMb(made.total_size)+'）'));
    if(large)notes.append(el('p','','文件超过 200 KB，没有语法高亮'));
    const scroll=el('div','code-scroll'),pre=el('pre','code-view');scroll.append(pre);
    body.replaceChildren(toolbar,notes,scroll);
    let rows=[];
    const render=fragments=>{
      const fragment=document.createDocumentFragment();rows=[];
      lines.forEach((line,index)=>{
        const row=el('span','code-line');row.dataset.line=String(index+1);
        const number=el('span','ln',String(index+1)),content=el('span','code-body');
        if(fragments)content.append(fragments[index]);else content.textContent=line;
        row.append(number,content);rows.push(row);fragment.append(row);
      });
      pre.replaceChildren(fragment);pre.classList.toggle('wrap',wrap.getAttribute('aria-pressed')==='true');
    };
    render(null);
    let fragments=null;
    if(!large&&language){
      const hljs=await ensureHighlight();
      if(signal.aborted)return;
      if(hljs&&hljs.getLanguage(language)){
        try{fragments=highlightedFragments(hljs.highlight(text,{language,ignoreIllegals:true}).value,text,lines);render(fragments);}catch{}
      }
    }
    const goLine=number=>{const row=rows[Math.max(0,Math.min(rows.length-1,number-1))];if(!row)return;
      row.classList.add('jump');scrollRow(row);};
    const scrollRow=row=>{const box=scroll.getBoundingClientRect(),line=row.getBoundingClientRect();
      scroll.scrollTop+=line.top-box.top-scroll.clientHeight/2+line.height/2;};
    if(made.line)goLine(Number(made.line));
    wrap.onclick=()=>{const on=wrap.getAttribute('aria-pressed')!=='true';wrap.setAttribute('aria-pressed',String(on));pre.classList.toggle('wrap',on);};
    copy.onclick=async()=>{const ok=await copyPlain(text);copy.textContent=ok?'已复制':'复制失败';setTimeout(()=>{copy.textContent='复制全部';},1500);};
    let matches=[],current=-1;
    const starts=[];let offset=0;for(const line of lines){starts.push(offset);offset+=line.length+1;}
    const lineAt=position=>{let low=0,high=starts.length-1;while(low<high){const middle=(low+high+1)>>1;if(starts[middle]<=position)low=middle;else high=middle-1;}return low;};
    const show=index=>{
      rows.forEach(row=>row.classList.remove('find-hit'));
      if(!matches.length){current=-1;hits.textContent=find.value?'没有找到':'';return;}
      current=(index+matches.length)%matches.length;const row=rows[lineAt(matches[current])];if(row)row.classList.add('find-hit');
      if(row)scrollRow(row);
      hits.textContent=(current+1)+' / '+matches.length;
    };
    const search=()=>{
      const query=find.value;matches=[];current=-1;
      if(query){const haystack=text.toLowerCase(),needle=query.toLowerCase();let at=haystack.indexOf(needle);
        while(at>=0&&matches.length<5000){matches.push(at);at=haystack.indexOf(needle,at+Math.max(1,needle.length));}}
      show(0);
    };
    find.addEventListener('input',search);find.addEventListener('keydown',event=>{
      if(event.key!=='Enter')return;event.preventDefault();if(matches.length)show(current+(event.shiftKey?-1:1));
    });
    prev.onclick=()=>show(current-1);next.onclick=()=>show(current+1);
  }
  function parseDelimited(text,delimiter){
    const rows=[];let row=[],field='',quoted=false;
    if(text.charCodeAt(0)===0xFEFF)text=text.slice(1);
    for(let i=0;i<text.length;i++){
      const char=text[i];
      if(quoted){
        if(char==='"'){if(text[i+1]==='"'){field+='"';i++;}else quoted=false;}
        else field+=char;
      }else if(char==='"')quoted=true;
      else if(char===delimiter){row.push(field);field='';}
      else if(char==='\n'||char==='\r'){
        if(char==='\r'&&text[i+1]==='\n')i++;
        row.push(field);rows.push(row);row=[];field='';
      }else field+=char;
    }
    if(field.length||row.length){row.push(field);rows.push(row);}
    return rows;
  }
  function buildTablePage(body,made,name,ext,m){
    const text=made.text||'',tsv=ext==='tsv';
    const rows=parseDelimited(text,tsv?'\t':','),header=rows[0]||[],all=rows.slice(1);
    const shown=all.slice(0,5000);
    const raw=el('button','code-tool','查看原文');raw.type='button';raw.setAttribute('aria-pressed','false');
    const toolbar=el('div','code-toolbar');toolbar.append(raw);
    const notes=el('div','code-notes');
    if(all.length>5000)notes.append(el('p','','只显示了前 5000 行（共 '+all.length+' 行）'));
    if(made.truncated)notes.append(el('p','','只显示了开头 '+fileMb(new Blob([text]).size)+'（文件共 '+fileMb(made.total_size)+'）'));
    const wrap=el('div','table-scroll'),table=el('table','table-view');
    const head=el('thead'),headRow=el('tr');
    for(const cell of header)headRow.append(el('th','',cell));
    head.append(headRow);table.append(head);
    const tbody=el('tbody');
    for(const values of shown){const tr=el('tr');for(let i=0;i<header.length;i++)tr.append(el('td','',values[i]??''));tbody.append(tr);}
    table.append(tbody);wrap.append(table);
    const source=el('pre','artifact-source',text);source.hidden=true;
    body.replaceChildren(toolbar,notes,wrap,source);
    if(!header.length)body.append(el('p','','这个表格是空的'));
    raw.onclick=()=>{const on=raw.getAttribute('aria-pressed')!=='true';raw.setAttribute('aria-pressed',String(on));
      wrap.hidden=on;source.hidden=!on;raw.textContent=on?'查看表格':'查看原文';};
  }

  function downloadCard(body,name,reason){
    const card=el('p','artifact-file');
    card.innerHTML='<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M14 3H5v18h14V8zM14 3v5h5"/></svg>';
    card.append(document.createTextNode(' '+name));body.append(card);
    body.append(el('p','',reason||'此文件可下载后使用相应应用打开。'));
  }
  const humanSize=n=>{const v=Number(n)||0;if(v>=1<<30)return (v/(1<<30)).toFixed(v>=10<<30?0:1)+' GB';
    if(v>=1<<20)return (v/(1<<20)).toFixed(v>=10<<20?0:1)+' MB';if(v>=1024)return Math.ceil(v/1024)+' KB';return v+' B';};
  const zipTime=ms=>{if(!ms)return '';const d=new Date(Number(ms));if(Number.isNaN(d.getTime()))return '';
    const pad=n=>String(n).padStart(2,'0');return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+' '+pad(d.getHours())+':'+pad(d.getMinutes());};
  const ZIP_FOLDER='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3 7V5h6l2 2h10v13H3z"/></svg>';
  const ZIP_FILE='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M14 3H5v18h14V8zM14 3v5h5"/></svg>';
  function buildZipPage(body,data){
    const entries=[...(data.entries||[])].sort((a,b)=>a.dir===b.dir?a.name.localeCompare(b.name,'zh-CN',{numeric:true}):a.dir?-1:1);
    const total=Number(data.total)||entries.length;
    const unpacked=entries.reduce((sum,entry)=>sum+(entry.dir?0:Number(entry.size)||0),0);
    body.replaceChildren(el('p','zip-summary','共 '+total+' 项，解压后 '+humanSize(unpacked)));
    if(data.truncated)body.append(el('p','code-notes','只列了前 2000 项'));
    const list=el('div','zip-list');
    for(const entry of entries){
      const row=el('div','zip-row'+(entry.dir?' dir':''));
      const mark=el('span','zip-icon');mark.innerHTML=entry.dir?ZIP_FOLDER:ZIP_FILE;
      row.append(mark,el('span','zip-name',entry.name),el('span','zip-size',entry.dir?'—':humanSize(entry.size)),
        el('span','zip-time',zipTime(entry.modified)));
      list.append(row);
    }
    body.append(list);
  }
  function mediaSource(target,file){const q=new URLSearchParams({app:target.app,id:target.id,file:file.id});if(file.v)q.set('v',file.v);return '/api/file?'+q.toString();}
  function stopMedia(s){if(!s?.media)return;try{s.media.pause();}catch{}s.media.removeAttribute('src');try{s.media.load();}catch{}s.media=null;}

  function previewState(kind){
    const base=history.state||{};
    const current=(typeof cur!=='undefined'&&cur)?{app:cur.app,id:cur.id,title:cur.title,folder:cur.folder,status:cur.status}:null;
    return {...base,remoteUI:base.remoteUI||{mode:'chat',conv:current,overlays:[],parent:!!current},filePreview:kind};
  }
  function rememberPreview(kind,replace){
    if(replace||history.state?.filePreview===kind)history.replaceState(previewState(kind),'');
    else history.pushState(previewState(kind),'');
  }
  addEventListener('popstate',()=>{
    if(imageViewerOpen&&history.state?.filePreview!=='image')closeImage(false);
    if(active&&history.state?.filePreview!=='file')close(false);
  });

  // ---- the full-screen picture viewer (§6.2 image/svg, §8)
  let imageViewerOpen=null;
  const VIEW_MAX=30<<20,SVG_MAX=10<<20;
  function imageQuery(target,file){return new URLSearchParams({app:target.app,id:target.id,file:file.id});}
  function imageOriginal(target,file){const q=imageQuery(target,file);if(file.v)q.set('v',file.v);return '/api/file?'+q.toString();}
  function imageThumb(target,file,width){const q=imageQuery(target,file);q.set('w',String(width));if(file.v)q.set('v',file.v);return '/api/file/thumb?'+q.toString();}
  function imageDownload(target,file){return imageOriginal(target,file)+'&download=1';}
  function closeImage(user=false){if(!imageViewerOpen)return;const s=imageViewerOpen;imageViewerOpen=null;s.aborted=true;s.controller.abort();
    for(const url of s.urls)URL.revokeObjectURL(url);s.urls.clear();s.host.remove();removeEventListener('keydown',s.key,true);
    document.body.style.overflow=s.bodyOverflow;s.focus?.focus?.({preventScroll:true});
    if(user&&history.state?.filePreview==='image')history.back();}

  function openImage(target,files,index=0){
    const items=(files||[]).filter(f=>f&&f.id&&(f.view==='image'||f.view==='svg')&&f.state!=='missing');if(!items.length)return;
    closeImage(false);rememberPreview('image');
    const s=imageViewerOpen={target,items,index:Math.max(0,Math.min(Number(index)||0,items.length-1)),scale:1,tx:0,ty:0,
      pointers:new Map(),drag:null,pinch:null,lastTap:0,lastX:0,lastY:0,urls:new Set(),controller:new AbortController(),
      focus:document.activeElement,aborted:false,bodyOverflow:document.body.style.overflow,load:0};
    const host=el('div','image-viewer');host.setAttribute('role','dialog');host.setAttribute('aria-modal','true');host.setAttribute('aria-label','看图');
    const bar=el('header','viewer-bar');
    const shut=el('button','viewer-btn');shut.type='button';shut.setAttribute('aria-label','返回');
    shut.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m14 6-6 6 6 6"/></svg>';
    const count=el('span','viewer-count');const actions=el('div','viewer-actions');
    const save=el('a','viewer-btn');save.setAttribute('download','');save.setAttribute('aria-label','下载原文件');
    save.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 4v11m-4-4 4 4 4-4M5 19h14"/></svg>';
    const filePage=el('button','viewer-btn','文件页');filePage.type='button';
    actions.append(save,filePage);bar.append(shut,count,actions);
    const stage=el('div','viewer-stage'),picture=el('img','viewer-picture');picture.alt='';picture.draggable=false;
    const note=el('div','viewer-note');note.hidden=true;stage.append(picture,note);host.append(bar,stage);document.body.append(host);
    s.host=host;s.stage=stage;s.picture=picture;s.note=note;s.count=count;s.save=save;s.filePage=filePage;
    document.body.style.overflow='hidden';shut.focus({preventScroll:true});
    const file=()=>s.items[s.index];
    const setNote=(text,retry)=>{note.replaceChildren(document.createTextNode(text));note.hidden=false;
      if(retry){const button=el('button','viewer-retry','重试');button.type='button';button.onclick=()=>load();note.append(button);}};
    const apply=()=>{picture.style.transform='translate3d('+s.tx+'px,'+s.ty+'px,0) scale('+s.scale+')';};
    const reset=()=>{s.scale=1;s.tx=0;s.ty=0;apply();};
    const clamp=()=>{
      if(s.scale<=1){s.tx=0;s.ty=0;return;}
      const rect=stage.getBoundingClientRect(),width=picture.offsetWidth*s.scale,height=picture.offsetHeight*s.scale;
      const maxX=Math.max(0,(width-rect.width)/2),maxY=Math.max(0,(height-rect.height)/2);
      s.tx=Math.max(-maxX,Math.min(maxX,s.tx));s.ty=Math.max(-maxY,Math.min(maxY,s.ty));
    };
    const zoomAt=(clientX,clientY,factor)=>{
      const rect=stage.getBoundingClientRect(),cx=clientX-rect.left-rect.width/2,cy=clientY-rect.top-rect.height/2;
      const next=Math.max(1,Math.min(8,s.scale*factor));if(Math.abs(next-s.scale)<.001)return;
      s.tx=cx-(cx-s.tx)*(next/s.scale);s.ty=cy-(cy-s.ty)*(next/s.scale);s.scale=next;clamp();apply();
    };
    const toggleZoom=(clientX,clientY)=>{if(s.scale>1)reset();else zoomAt(clientX,clientY,2.5);};
    const revoke=(url)=>{if(!url)return;URL.revokeObjectURL(url);s.urls.delete(url);};
    const probe=(src,ok,bad)=>{const image=new Image();s.probe=image;image.onload=()=>ok(src);image.onerror=()=>bad();image.src=src;};
    const show=src=>{picture.src=src;};
    const done=()=>{note.hidden=true;};
    const fail=(message,retry=true)=>setNote(message,retry);
    const load=()=>{
      const token=++s.load,current=file();if(!current)return;
      revoke(s.detailBlob);s.detailBlob=null;reset();note.hidden=false;note.replaceChildren(document.createTextNode('正在读取…'));
      count.textContent=(s.index+1)+'/'+s.items.length;save.href=imageDownload(target,current);
      picture.alt=current.name||'';
      const original=imageOriginal(target,current),thumb=w=>imageThumb(target,current,w);
      const afterThumb=()=>{
        if(current.view==='svg')return loadSvg(token,current,original);
        const ext=String(current.ext||'').toLowerCase(),small=Number(current.size)<=VIEW_MAX||ext==='gif';
        const next=small?original:thumb(2048);
        probe(next,src=>{if(token!==s.load)return;show(src);done();},()=>fail('原图读取失败，点重试',true));
      };
      picture.onload=()=>{if(token===s.load)done();};
      picture.onerror=()=>{if(token===s.load)fail('图片读取失败，点重试',true);};
      if(current.thumb){show(thumb(1280));probe(thumb(1280),()=>{if(token===s.load)afterThumb();},()=>afterThumb());}
      else afterThumb();
    };
    const loadSvg=(token,current,original)=>{
      if(Number(current.size)>SVG_MAX){setNote('SVG 超过 10 MB，请下载后在文件页查看',false);return;}
      request(original+'&download=1',s.controller.signal,SVG_MAX,false).then(bytes=>{
        if(token!==s.load||s.aborted)return;
        const url=URL.createObjectURL(new Blob([bytes],{type:'image/svg+xml'}));s.urls.add(url);s.detailBlob=url;
        probe(url,src=>{if(token!==s.load)return;show(src);done();},()=>{revoke(url);fail('SVG 读取失败，点重试',true);});
      }).catch(error=>{if(token===s.load&&!s.aborted)fail(error.message||'SVG 读取失败，点重试',true);});
    };
    const go=delta=>{const next=s.index+delta;if(next<0||next>=s.items.length)return;s.index=next;load();};
    const key=event=>{
      if(event.key==='Escape'){event.preventDefault();closeImage(true);return;}
      if(event.key==='ArrowLeft'||event.key==='ArrowRight'){
        event.preventDefault();const delta=event.key==='ArrowRight'?1:-1;
        if(s.scale>1){s.tx+=delta*80;clamp();apply();}else go(delta);
      }
    };
    s.key=key;addEventListener('keydown',key,true);
    shut.onclick=()=>closeImage(true);host.addEventListener('click',event=>{if(event.target===host)closeImage(true);});
    filePage.onclick=()=>{const current=file();closeImage(false);open(target,current,{replaceHistory:true});};
    stage.addEventListener('wheel',event=>{if(!event.ctrlKey)return;event.preventDefault();zoomAt(event.clientX,event.clientY,Math.exp(-event.deltaY*.002));},{passive:false});
    stage.addEventListener('pointerdown',event=>{
      if(event.pointerType==='mouse'&&event.button!==0)return;
      stage.setPointerCapture?.(event.pointerId);s.pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});
      if(s.pointers.size===1){s.drag={x:event.clientX,y:event.clientY,tx:s.tx,ty:s.ty,time:performance.now(),moved:0};s.pinch=null;}
      else if(s.pointers.size===2){const [a,b]=[...s.pointers.values()];s.pinch={dist:Math.hypot(a.x-b.x,a.y-b.y),scale:s.scale};s.drag=null;}
    });
    stage.addEventListener('pointermove',event=>{
      if(!s.pointers.has(event.pointerId))return;s.pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});
      if(s.pointers.size>=2&&s.pinch){
        const [a,b]=[...s.pointers.values()],dist=Math.hypot(a.x-b.x,a.y-b.y);
        if(s.pinch.dist>0){const factor=(s.pinch.scale*dist/s.pinch.dist)/s.scale;zoomAt((a.x+b.x)/2,(a.y+b.y)/2,factor);}
        return;
      }
      if(!s.drag)return;const dx=event.clientX-s.drag.x,dy=event.clientY-s.drag.y;s.drag.moved=Math.max(s.drag.moved,Math.hypot(dx,dy));
      if(s.scale>1){s.tx=s.drag.tx+dx;s.ty=s.drag.ty+dy;clamp();apply();stage.classList.add('dragging');}
    });
    const finish=event=>{
      if(!s.pointers.has(event.pointerId))return;s.pointers.delete(event.pointerId);
      if(s.pointers.size<2)s.pinch=null;
      if(s.drag){
        const drag=s.drag;s.drag=null;stage.classList.remove('dragging');
        const dx=event.clientX-drag.x,dy=event.clientY-drag.y,elapsed=performance.now()-drag.time;
        if(drag.moved<8&&elapsed<350){
          if(performance.now()-s.lastTap<320&&Math.hypot(event.clientX-s.lastX,event.clientY-s.lastY)<30){toggleZoom(event.clientX,event.clientY);s.lastTap=0;}
          else{s.lastTap=performance.now();s.lastX=event.clientX;s.lastY=event.clientY;}
        }else if(s.scale===1&&elapsed<700&&Math.abs(dx)>50&&Math.abs(dx)>Math.abs(dy)*1.5)go(dx<0?1:-1);
      }
      if(s.pointers.size===0)s.drag=null;
    };
    stage.addEventListener('pointerup',finish);stage.addEventListener('pointercancel',finish);
    load();
  }
  window.imageViewer={open:openImage,close:closeImage};

  let active=null;
  function close(user=false){if(!active)return;const s=active;active=null;s.controller.abort();clearTimeout(s.timer);stopMedia(s);for(const u of s.urls)URL.revokeObjectURL(u);s.dialog.close();s.dialog.remove();s.focus?.focus({preventScroll:true});
    if(user&&history.state?.filePreview==='file')history.back();}
  async function open(target,file,options={}){
    close(false);const s={controller:new AbortController(),urls:new Set(),focus:document.activeElement};active=s;
    const valid=()=>active===s&&!s.controller.signal.aborted;
    const dialog=el('dialog','artifact-panel');s.dialog=dialog;dialog.setAttribute('aria-label','附件详情');
    const header=el('header','artifact-header'),back=el('button','tp-icon-button');back.type='button';back.setAttribute('aria-label','返回聊天');
    back.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="m14 6-6 6 6 6"/></svg>';back.onclick=()=>close(true);
    const heading=el('div','tp-header-title');heading.append(el('strong','',file.name||'附件'));
    const tools=el('div','tp-toolbar'),save=el('button','tp-button','下载');tools.append(save);header.append(back,heading,tools);
    const info=el('div','artifact-info'),full=el('details'),summary=el('summary','','文件详情');full.append(summary,el('div','artifact-name',file.name||'附件'));info.append(full);
    const status=el('p','artifact-status','正在读取…');status.setAttribute('role','status');
    const tabs=el('div','theme-choices artifact-tabs');tabs.hidden=true;const body=el('div','artifact-body');
    dialog.append(header,info,status,tabs,body);document.body.append(dialog);dialog.showModal();back.focus();dialog.addEventListener('cancel',e=>{e.preventDefault();close(true);});
    rememberPreview('file',!!options.replaceHistory);
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
      const table=!office&&(m.view==='table'||['csv','tsv'].includes(ext));
      const code=!office&&!table&&(m.view==='code'||m.view==='text'||
        (m.kind==='text'&&!['html','htm','md','markdown'].includes(ext)));
      const audio=!office&&(m.view==='audio'||['mp3','m4a','aac','wav','flac','ogg'].includes(ext));
      const video=!office&&(m.view==='video'||['mp4','m4v','mov','webm','mkv'].includes(ext));
      const archive=m.view==='archive';
      const kind=office?'pdf':archive?'archive':audio?'audio':video?'video':table?'table':code?'code':['html','htm'].includes(ext)?'html':['md','markdown'].includes(ext)?'markdown':['png','jpg','jpeg','webp'].includes(ext)?'image':ext==='pdf'?'pdf':'download';
      if(kind==='download'||options.downloadOnly){downloadCard(body,name);return;}
      if(kind==='archive'){
        if(ext!=='zip'){downloadCard(body,name,'这种压缩包只能下载');return;}
        if(!a.zip){downloadCard(body,name,'这个压缩包只能下载');return;}
        try{const listing=await a.zip(signal);if(!valid())return;buildZipPage(body,listing);}catch(e){if(!valid())return;downloadCard(body,name,e.message);}
        return;
      }
      if(kind==='audio'||kind==='video'){
        const media=el(kind==='video'?'video':'audio');media.controls=true;media.preload='metadata';
        if(kind==='video'){media.playsInline=true;media.setAttribute('playsinline','');}
        const unsupported=()=>{media.remove();stopMedia(s);downloadCard(body,name,'这个格式浏览器放不了，请下载后用其他应用打开');};
        if(!media.canPlayType(m.mime||'')){unsupported();return;}
        media.onerror=unsupported;media.src=mediaSource(target,file);s.media=media;body.append(media);media.load();return;
      }
      if(kind==='code'||kind==='table'){
        let made=null;
        if(a.text){try{made=await a.text(signal);}catch(error){if(!a.bytes)throw error;}}
        if(!made&&a.bytes){const bytes=await a.bytes(signal,3<<20);made={text:decode(bytes),encoding:'utf-8',truncated:false,total_size:bytes.length,lines:0,lang:m.lang,line:file.line};}
        if(!valid())return;
        if(!made||typeof made.text!=='string'){body.append(el('p','','这个文件不能当文本预览，请下载原文件。'));return;}
        if(!made.text){body.append(el('p','','这个文件是空的。'));return;}
        made.line=made.line||m.line||file.line;
        if(kind==='code')await buildCodePage(body,made,name,ext,m,signal);else buildTablePage(body,made,name,ext,m);
        return;
      }
      if(!office&&m.size>(['html','markdown'].includes(kind)?LIMIT.text:LIMIT.binary)){body.append(el('p','','文件超过预览上限，请下载原文件。'));return;}
      if(office){status.textContent+=' · 正在用电脑上的 Office 转成 PDF…';clearTimeout(s.timer);s.timer=setTimeout(()=>{if(valid()){status.textContent='转换超时，请下载原文件';s.controller.abort();}},125000);}
      const bytes=await (office?a.pdf(signal,LIMIT.binary):a.bytes(signal,['html','markdown'].includes(kind)?LIMIT.text:LIMIT.binary));if(!valid())return;
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
  addEventListener('pagehide',()=>close(false));
  addEventListener('pagehide',()=>closeImage(false));
  window.artifactPreview={open,close,adapter,limits:LIMIT,decode,dimensions,cleanHTML};
})();
