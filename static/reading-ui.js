/* Paginated public history, files, copying and a single foreground event stream. */
(() => {
  let listKey='',listCursor=null,listHasMore=false,listBusy=false,query='',loadGeneration=0,listSig='';
  let me=null,loaded=[],cursor=null,hasMore=false,historyWindow=false,initialPage=null,fetching=null,source=null,streamActive=false,streamSeq=0,streamGeneration=0,retryTimer=null,bufferedEvent=null;
  const expanded=new Map();
  const css=el('style');css.textContent=`.history-tools{display:flex;justify-content:center;gap:8px;padding:4px 12px;flex:none}.history-tools button{font-size:12px;font-weight:400;min-height:36px;border:0;background:transparent;color:var(--blue);padding:6px 10px}.conversation-search{display:flex;gap:8px;margin:4px 0 12px}.conversation-search input{min-width:0;flex:1;font:inherit;font-size:16px;padding:10px 14px;border:1px solid var(--line);border-radius:16px;background:var(--bg)}.message-actions{display:flex;gap:8px;margin-top:8px}.message-actions button{font-size:12px;font-weight:400;min-height:36px;padding:6px 10px;border:0;background:var(--bg);border-radius:999px;color:var(--muted)}.bub .inline-copy{display:inline-flex;align-items:center;gap:5px;vertical-align:baseline;min-height:28px;margin:0 2px;padding:2px 5px;border:0;border-radius:5px;background:#f3f4f6;color:inherit;font:inherit;max-width:100%;text-align:left}.inline-copy svg{width:13px;height:13px;flex:none;opacity:.55}.bub .inline-copy code{padding:0;background:none;overflow-wrap:anywhere}.search-hit{display:block;width:100%;text-align:left;border:0;border-bottom:1px solid var(--line);border-radius:0;font-size:14px;font-weight:400;padding:12px;background:transparent;white-space:pre-wrap}.search-hit small{display:block;color:var(--muted);font-size:12px}.file-row{padding:12px;border:1px solid var(--line);border-radius:16px;overflow-wrap:anywhere}.file-actions{display:flex;gap:8px;margin-top:8px}.file-actions button{font-size:13px;padding:8px 12px;border-radius:999px}.file-preview{width:100%;height:65dvh;border:0}.text-preview{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.6 ui-monospace,monospace;max-height:65dvh;overflow:auto}.template-row{display:flex;align-items:center;gap:4px}.template-row .insert{flex:1;text-align:left;overflow:hidden;text-overflow:ellipsis}.template-row button{font-size:13px;padding:8px;min-height:44px}.template-editor input,.template-editor textarea{box-sizing:border-box;width:100%;font:inherit;font-size:16px;padding:10px;border:1px solid var(--line);border-radius:12px;margin:4px 0}.template-editor textarea{min-height:140px}.list-more{display:block;margin:16px auto;font-size:14px;padding:10px 20px;border-radius:999px}.history-note{font-size:12px;text-align:center;color:var(--muted)}`;document.head.append(css);
  // ---- answer files in a message (docs/handoff-file-preview.md §5.1, §6.1, §6.4)
  const answerCss=el('style');answerCss.textContent=`
.msg-image{display:block;position:relative;width:100%;max-height:360px;margin:10px 0;border-radius:12px;overflow:hidden;background:#eef0f3;aspect-ratio:4 / 3}
.msg-image img{display:block;width:100%;height:100%;object-fit:contain;max-width:100%}
.msg-image.loaded{background:transparent}.msg-image.failed{background:#f6f7f9}
.msg-image-state{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;gap:8px;padding:12px;text-align:center;font-size:12px;line-height:1.4;color:var(--muted);overflow-wrap:anywhere}
.msg-image-retry{font-size:12px;min-height:32px;padding:4px 10px;border-radius:999px}
.msg-file-card{display:flex;flex-direction:row;align-items:center;gap:8px;width:100%;margin:10px 0;padding:10px 12px;text-align:left;border:1px solid var(--line);border-radius:12px;background:var(--card,#fff);white-space:normal}
.answer-files{display:flex;gap:8px;overflow-x:auto;padding:8px 0 2px;margin-top:4px;white-space:normal;overscroll-behavior-x:contain}
.answer-file{display:flex;flex-direction:column;align-items:flex-start;gap:4px;flex:none;width:132px;min-height:96px;padding:8px;border:1px solid var(--line);border-radius:12px;background:var(--card,#fff);color:var(--text);text-align:left;white-space:normal;overflow:hidden;font:inherit}
.answer-file.missing .answer-file-name{text-decoration:line-through;color:var(--muted)}
.answer-file-thumb{display:block;width:100%;height:64px;object-fit:cover;border-radius:8px;background:#eef0f3}
.answer-file-icon{display:block;width:28px;height:28px;color:var(--muted)}.answer-file-icon svg{width:28px;height:28px;display:block}
.answer-file-name{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:12px;line-height:1.35;overflow-wrap:anywhere;color:var(--text)}
.answer-file-meta{font-size:11px;line-height:1.3;color:var(--muted)}
.answer-more{flex:none;align-self:stretch;min-height:96px;width:96px;border:1px dashed var(--line);border-radius:12px;background:transparent;color:var(--blue);font-size:12px;padding:8px;white-space:normal}
.inline-file{color:inherit;text-decoration:underline;text-decoration-style:dotted;text-underline-offset:2px;cursor:pointer}
.inline-file code{color:inherit}
.file-note-short{color:var(--muted);font-size:12px;margin-left:2px;cursor:pointer;white-space:nowrap}
.web-local-note{cursor:default}
.answer-dialog{width:min(440px,calc(100vw - 32px));max-height:80vh;border:0;border-radius:18px;padding:0;background:var(--card,#fff);color:var(--text);box-shadow:0 24px 64px rgba(15,23,42,.25)}
.answer-dialog::backdrop{background:rgba(15,23,42,.38)}
.answer-dialog-head{display:flex;align-items:center;gap:8px;padding:14px 16px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--card,#fff);z-index:1}
.answer-dialog-head b{flex:1;font-size:15px}.answer-dialog-close{min-height:36px;padding:6px 12px;font-size:13px}
.answer-dialog-body{padding:14px 16px 18px;overflow:auto;display:flex;flex-direction:column;gap:10px}
.answer-dialog-body p{margin:0;font-size:14px;line-height:1.65;overflow-wrap:anywhere}
.answer-dialog-body .answer-reason-short{color:var(--muted);font-size:12px}
.answer-file-list{display:flex;flex-direction:column;gap:8px}.answer-file-list .answer-file{width:100%;flex-direction:row;align-items:center;min-height:56px}
:root[data-theme=dark] .msg-image,:root[data-theme=dark] .msg-image-state{background:#1c1c1c}
:root[data-theme=dark] .answer-file{background:#141414}
`;document.head.append(answerCss);
  const searchLine=el('div','conversation-search'),listInput=el('input');listInput.type='search';listInput.placeholder='搜索对话标题或文件夹';listInput.setAttribute('aria-label','搜索对话');searchLine.append(listInput);document.querySelector('.conversation-home .chips').after(searchLine);
  const listMore=el('button','list-more','加载更多对话');listMore.hidden=true;listMore.onclick=()=>loadList(true);$('convList').after(listMore);
  let searchTimer;listInput.addEventListener('input',e=>{if(e.isComposing)return;clearTimeout(searchTimer);searchTimer=setTimeout(()=>{query=listInput.value.trim();loadList(false,true);},250);});listInput.addEventListener('compositionend',()=>{query=listInput.value.trim();loadList(false,true);});
  function sheet(id,title){const n=el('div','sheet');n.id=id;n.setAttribute('aria-label',title);n.innerHTML='<div class="box"><div class="sh-head"><b></b><button class="icon-btn" aria-label="关闭">'+icon('close')+'</button></div><div class="sh-body"></div></div>';n.querySelector('b').textContent=title;n.querySelector('button').onclick=()=>closeSheet(id);n.onclick=e=>{if(e.target===n)closeSheet(id);};document.body.append(n);return n.querySelector('.sh-body');}
  const searchBody=sheet('historySearch','查找消息'),fileBody=sheet('conversationFiles','对话文件'),previewBody=sheet('resultPreview','文件预览'),templateBody=sheet('promptLibrary','常用提示语');
  const toolbar=el('div','history-tools'),older=el('button','','加载更早消息'),latest=el('button','','回到最新');older.hidden=true;latest.hidden=true;older.onclick=loadOlder;latest.onclick=()=>loadConversation(true);toolbar.append(older,latest);document.querySelector('.message-region').before(toolbar);
  function menu(label,fn){const b=el('button','menu-row',label);b.onclick=()=>{dismissOverlays();fn();};$('convMenu').querySelector('.sh-body').append(b);}
  menu('查找消息',openSearch);menu('对话文件',openFiles);menu('常用提示语',openTemplates);
  function preserveList(render){const top=document.querySelector('header').getBoundingClientRect().bottom,row=[...document.querySelectorAll('.conv')].find(n=>n.getBoundingClientRect().bottom>top),key=row?.dataset.key,y=row?.getBoundingClientRect().top;render();if(scrollY>40&&key){const n=[...document.querySelectorAll('.conv')].find(n=>n.dataset.key===key);if(n)window.scrollBy(0,n.getBoundingClientRect().top-y);}}
  // Whether row a comes after row b in the computer's order (chat_history.py sort_key): newest first, then app, then id.
  function sortsAfter(a,b,field){const newer=(Number(b[field])||0)-(Number(a[field])||0);return newer?newer>0:a.app+'\0'+a.id>b.app+'\0'+b.id;}
  async function loadList(more=false,reset=false){
    if(listBusy||!window.workspaceUI?.canPoll())return;const display=window.interactionUI?.query()||'';const key=convApp+'|'+query+display;if(key!==listKey){reset=true;listKey=key;}listBusy=true;listMore.disabled=true;
    // Reuse the request started by the inline shell, even if it finished before this module downloaded.
    const first=takeInitialConvPage(convApp);
    try{const j=await ((!more&&!query&&!display&&first)||api('/api/chats?app='+convApp+'&limit='+CONV_PAGE_SIZE+'&query='+encodeURIComponent(query)+display+(more&&listCursor?'&cursor='+encodeURIComponent(listCursor):'')));if(key!==convApp+'|'+query+(window.interactionUI?.query()||''))return;
      const incoming=j.items||[],oneState=display.includes('&status=');let kept=[];
      if(reset)convItems=incoming;else if(more){const ids=new Set(convItems.map(v=>v.app+':'+v.id));convItems.push(...incoming.filter(v=>!ids.has(v.app+':'+v.id)));}else{const fresh=new Map(incoming.map(v=>[v.app+':'+v.id,v]));
        // 11-02: in a list of one state the first page speaks for every row up to its last. One of those it leaves out has left
        // that state (运行中: it ended). Kept, nothing would read it again: it said 运行中 hours after the turn ended.
        const end=j.has_more?incoming.at(-1):null,field=display.includes('&sort=created')?'created':'updated';
        kept=convItems.filter(v=>!fresh.has(v.app+':'+v.id)&&(!oneState||(end&&sortsAfter(v,end,field))));convItems=[...incoming,...kept];}
      if(more||reset||!listCursor||(oneState&&!kept.length)){listCursor=j.next_cursor;listHasMore=!!j.has_more;}
      // the list is read every 10 s; rebuilt only when it changed, or once a minute for its "x 分钟前" (10-14: a rebuild under
      // a finger made scrolling and tapping catch)
      const sig=JSON.stringify([convItems,Math.floor(Date.now()/60000)]);if(more||reset||sig!==listSig){listSig=sig;preserveList(renderConvs);}$('convHint').textContent=(query?'搜索结果':window.interactionUI?.sortLabel()||'按最近活动排序')+(j.total!=null?' · '+j.total+' 个对话':'');listMore.hidden=!listHasMore;
    }catch(e){$('convHint').textContent='读取失败：'+e.message;}finally{listBusy=false;listMore.disabled=false;if(key!==convApp+'|'+query+(window.interactionUI?.query()||''))loadList(false,true);}
  }
  function merge(items,prepend=false){loaded=messageProjection.merge(loaded,items.map(m=>{const full=expanded.get(m.id);return full&&full.length>=(m.length||m.text.length)&&!m.streaming?{...m,text:full.text,truncated:false}:m;}),prepend);}
  function reconcileLive(ids){loaded=messageProjection.reconcileLive(loaded,ids);}
  function render(){if(!cur||!me||chatKey(cur)!==chatKey(me))return;renderMsgs(loaded);painted=true;older.hidden=!hasMore;latest.hidden=!historyWindow;}
  function applyMeta(j){if(!cur)return;window.interactionUI?.meta(j);chatReadError='';updateConnection();cur.status=j.status||cur.status;cur.title=j.title||cur.title;$('cvTitle').textContent=cur.title;$('cvMeta').textContent=Agents.name(cur.app)+(cur.folder?' · '+cur.folder:'')+' · '+(STATUS[cur.status]||'');if(j.runtime!==undefined)renderRuntime(j.runtime);}
  function onOpen(original,current){closeMenu(true);pauseStream();loadGeneration++;fetching=null;me=current;loaded=[];expanded.clear();cursor=null;hasMore=false;historyWindow=!!original.has_newer;initialPage=Array.isArray(original.messages)?original:null;streamSeq=0;flows.clear();cancelAnimationFrame(frame);frame=0;keysSeen=null;painted=false;}
  async function loadConversation(force=false){
    if(window.newChatUI?.isPreview(cur))return;
    if(!cur)return;if(!me||chatKey(me)!==chatKey(cur))onOpen({},cur);
    if(fetching)return fetching;
    if(historyWindow&&!force){codexUI?.refresh(cur);return;}
    if(force)pauseStream();const target={...cur},generation=loadGeneration,startedStream=streamGeneration,startedSeq=streamSeq;
    fetching=(async()=>{try{await Promise.resolve();if(generation!==loadGeneration)return;
      const initial=initialPage;initialPage=null;const j=initial||await api('/api/chat?app='+target.app+'&id='+encodeURIComponent(target.id)+'&n=60');if(generation!==loadGeneration||!cur||chatKey(cur)!==chatKey(target))return;
      // A reply still being written is not in the record yet: kept through a fresh read (one follows every send), it does not
      // blink out until the stream brings it back (10-22). Over when the record says the turn is.
      const writing=force&&!initial?loaded.filter(m=>m.streaming):[];
      if(initial||force){loaded=[];historyWindow=!!j.has_newer;cursor=j.next_cursor;hasMore=!!j.has_more;}
      else if(!loaded.length){cursor=j.next_cursor;hasMore=!!j.has_more;}
      merge(j.messages||[]);if(writing.length)merge(writing);if(!streamActive||(startedStream===streamGeneration&&startedSeq===streamSeq)){applyMeta(j);if(j.status==='idle')reconcileLive([]);}render();codexUI?.refresh(cur);workspaceUI?.pollReceipts();
      if(force&&!initial){historyWindow=false;latest.hidden=true;jumpToLatest();}
      resumeStream();
    }catch(e){if(generation===loadGeneration&&cur&&chatKey(cur)===chatKey(target)){chatReadError='读取对话失败：'+e.message;updateConnection();}}finally{if(generation===loadGeneration)fetching=null;}})();return fetching;
  }
  async function loadOlder(){if(!cur||!cursor||older.disabled)return;const target={...cur};older.disabled=true;try{const j=await api('/api/chat?app='+target.app+'&id='+encodeURIComponent(target.id)+'&n=60&before='+encodeURIComponent(cursor));if(!cur||chatKey(cur)!==chatKey(target))return;if(j.reset){toast('记录位置已变化，请回到最新位置再试',true);return;}cursor=j.next_cursor;hasMore=!!j.has_more;merge(j.messages||[],true);render();}catch(e){toast(e.message,true);}finally{older.disabled=false;}}
  async function jump(mid){const target={...cur};const j=await api('/api/chat?app='+target.app+'&id='+encodeURIComponent(target.id)+'&n=60&around='+encodeURIComponent(mid));if(!cur||chatKey(cur)!==chatKey(target))return;loaded=j.messages;cursor=j.next_cursor;hasMore=!!j.has_more;historyWindow=!!j.has_newer;render();const n=[...$('cvMsgs').querySelectorAll('[data-key],[data-message-id]')].find(n=>n.dataset.key===mid||n.dataset.messageId===mid);if(n){const group=n.closest('.activity-group');if(group?.querySelector('.activity-body').hidden)group.querySelector('.activity-heading').click();if(n.tagName==='DETAILS')n.open=true;n.scrollIntoView({block:'center'});n.animate?.([{background:'#eef2ff'},{background:'transparent'}],{duration:900});}await expandMessage(mid);}
  async function expandMessage(mid){if(!cur)return;const target={...cur},j=await api('/api/chat/message?app='+target.app+'&id='+encodeURIComponent(target.id)+'&message='+encodeURIComponent(mid));if(!cur||chatKey(cur)!==chatKey(target))return;expanded.set(mid,j);merge([j]);render();}
  function publicText(text){return assistantMarkdown(text).markdown;}

  // The clipboard is written in the tap itself, as Safari wants it: words still to be read from the computer (a long
  // message shown in part) go as a promise of them, which Safari and Chrome both take. Where that fails, the words are
  // shown to pick from (选择文字), with 复制全部.
  function copyText(text){
    const done=()=>toast('已复制'),c=navigator.clipboard,secure=!!c&&window.isSecureContext;
    const fail=()=>Promise.resolve(text).then(t=>openReader(t,'没能直接复制。长按文字选出要的部分，或点「复制全部」。'),e=>toast(e.message,true));
    try{
      if(typeof text==='string'){if(secure&&c.writeText)c.writeText(text).then(done,()=>execCopy(text)?done():fail());else if(execCopy(text))done();else fail();return;}
      if(secure&&c.write&&window.ClipboardItem)c.write([new ClipboardItem({'text/plain':text.then(t=>new Blob([t],{type:'text/plain'}))})]).then(done,()=>text.then(t=>c.writeText(t)).then(done,fail));
      else text.then(t=>secure?c.writeText(t):Promise.reject(new Error('no clipboard'))).then(done,fail);
    }catch(e){fail();}
  }
  let copyPress=null;
  document.addEventListener('pointerdown',event=>{const button=event.target.closest?.('[data-copy-fragment]');if(button)copyPress={node:button.closest('.bub'),at:performance.now()};},true);
  for(const name of ['pointerup','pointercancel'])document.addEventListener(name,()=>{if(copyPress)setTimeout(()=>{copyPress=null;wake();},100);},true);
  document.addEventListener('click',event=>{const button=event.target.closest?.('[data-copy-fragment]');if(!button)return;event.preventDefault();event.stopPropagation();copyText(JSON.parse(button.dataset.copyFragment));},true);
  function execCopy(text){  // the old way, for a page not on https (no clipboard API there)
    const t=el('textarea');t.value=text;t.readOnly=true;t.style.cssText='position:fixed;left:0;top:0;width:1px;height:1px;opacity:0';
    (overlays.length?$(overlays.at(-1).id):$('convView')).append(t);let ok=false;try{t.select();t.setSelectionRange(0,text.length);ok=document.execCommand('copy');}catch(e){}t.remove();return ok;
  }
  // ---- answer files: the files a new computer lists on a reply, and the reasons for the ones it cannot give
  const answerMessageFiles=new WeakMap();
  const ANSWER_VIA=new Set(['link','citation','presented','tool']);
  const ANSWER_REASONS={
    missing:['文件已删除','文件已移动或删除'],
    changed:['文件刚改过','文件刚改过，重新打开就是新的'],
    not_found:['找不到文件','电脑上没找到这个文件（回答写的是相对位置，在对话文件夹里没找到）'],
    not_local:['网络位置','文件在网络位置或别的电脑上，遥应只读这台电脑自己的磁盘'],
    denied:['不开放','出于安全，遥应不让手机读这个文件（可能含密钥或登录信息）'],
    folder:['文件夹','这是文件夹，可以在「电脑上的文件」里看'],
    too_large:['文件太大','文件有 N MB，超过手机上直接看的上限；可以保存或用其他应用打开'],
    unsupported:['不能显示','这种文件手机上不能直接显示；可以保存或用其他应用打开'],
    decode:['编码读不出','读不出这个文件的文字编码；可以保存后用其他应用打开'],
    offline:['电脑离线','电脑离线，连上后再试'],
    old_pc:['电脑端较旧','电脑端版本较旧，更新到 dev.55 或以后才能看'],
    local_web:['本机网址','这是电脑本机的网址，手机打不开']
  };
  const ANSWER_ICONS={
    file:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M14 3H5v18h14V8zM14 3v5h5"/></svg>',
    pdf:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M14 3H5v18h14V8zM14 3v5h5"/><path d="M8 13h2.2a1.8 1.8 0 0 1 0 3.6H8zM8 16.6V19M13.5 13h1.2a2.6 2.6 0 0 1 0 5.2h-1.2zM13.5 13v5.2M17.2 13H20M17.2 16h2"/></svg>',
    image:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="9" r="1.5"/><path d="m4 17 5-5 4 4 3-3 4 4"/></svg>',
    code:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="m9 8-5 4 5 4M15 8l5 4-5 4M13 5l-2 14"/></svg>',
    text:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M14 3H5v18h14V8zM14 3v5h5M8 12h8M8 16h8M8 8h3"/></svg>',
    table:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M3 14h18M9 9v11M15 9v11"/></svg>'
  };
  function answerHref(value){const raw=String(value??'');try{return decodeURIComponent(raw);}catch{return raw;}}
  function answerPath(value){let s=answerHref(value).replace(/\\/g,'/').trim();
    s=s.replace(/#L\d+(?:C\d+)?(?:-L?\d+)?$/i,'').replace(/(?::\d+){1,2}(?:-\d+)?$/,'');
    return s.replace(/\/{2,}/g,'/').toLowerCase();}
  function answerFileFor(files,href){const key=answerPath(href);return key?(files||[]).find(f=>f&&f.id&&answerPath(f.path)===key)||null:null;}
  function answerNoteFor(notes,href){const key=answerHref(href);return (notes||[]).find(n=>n&&n.href!=null&&answerHref(n.href)===key)||null;}
  function answerReasonInfo(reason,text){const got=ANSWER_REASONS[reason];
    return {short:got?got[0]:'打不开',full:(reason==='too_large'&&text?text:got?got[1]:'')||text||'这个文件打不开'};}
  function answerSize(size){const n=Number(size);if(!Number.isFinite(n)||n<0)return '';
    if(n>=1<<20)return (n/(1<<20)).toFixed(n>=10<<20?0:1)+' MB';if(n>=1024)return Math.ceil(n/1024)+' KB';return n+' B';}
  function answerState(file){return file.state==='missing'?'已删除':file.state==='updated'?'已更新':'';}
  function answerFileUrl(target,file){const p=new URLSearchParams({app:target.app,id:target.id,file:file.id});
    if(file.v)p.set('v',file.v);return '/api/file?'+p.toString();}
  function answerThumbUrl(target,file,w){const p=new URLSearchParams({app:target.app,id:target.id,file:file.id,w:String(w)});
    if(file.v)p.set('v',file.v);return '/api/file/thumb?'+p.toString();}
  function answerImageUrl(target,file,w){return file.thumb?answerThumbUrl(target,file,w):answerFileUrl(target,file);}
  function answerImageWidth(){const px=Math.min(window.innerWidth||390,900)*(window.devicePixelRatio||1);return px>640?1280:640;}
  function answerIcon(file){const ext=String(file.ext||'').toLowerCase();
    const kind=file.view==='office'||['xlsx','xls','csv','tsv','ods'].includes(ext)?'table':file.kind==='pdf'||ext==='pdf'?'pdf':
      file.view==='image'||file.view==='svg'||file.kind==='image'?'image':file.view==='code'||file.kind==='text'?'code':'file';
    const span=el('span','answer-file-icon');span.innerHTML=ANSWER_ICONS[kind]||ANSWER_ICONS.file;return span;}
  let answerDialog=null;
  function answerDialogNode(){
    if(answerDialog)return answerDialog;
    const d=el('dialog','answer-dialog');d.setAttribute('aria-label','文件说明');
    const head=el('div','answer-dialog-head'),title=el('b'),close=el('button','answer-dialog-close','关闭');
    close.type='button';close.onclick=()=>d.close();head.append(title,close);
    const body=el('div','answer-dialog-body');d.append(head,body);
    d.addEventListener('click',e=>{if(e.target===d)d.close();});
    d._title=title;d._body=body;document.body.append(d);answerDialog=d;return d;
  }
  function showAnswerDialog(title,nodes){const d=answerDialogNode();d._title.textContent=title;d._body.replaceChildren(...nodes);if(!d.open)d.showModal();}
  function openAnswerReason(note){const info=answerReasonInfo(note?.reason,note?.text);
    showAnswerDialog('文件打不开',[el('p','answer-reason-short',info.short),el('p','answer-reason-full',info.full)]);}
  function openAnswerFile(file){if(!cur||!file||!file.id)return;const target={...cur};
    if(file.state==='missing'){openAnswerReason({reason:'missing',text:'文件已移动或删除'});return;}
    if(file.kind==='download'&&file.preview!=='pdf')download(target,file);else preview(target,file);}
  function answerCard(file,{thumb=false}={}){
    const card=el('button','answer-file'+(file.state==='missing'?' missing':''));
    card.type='button';card.dataset.fileId=file.id||'';
    card.setAttribute('aria-label',(file.name||'文件')+(file.state==='missing'?'，文件已移动或删除':'，打开文件'));
    let media=null;
    if(thumb&&file.view==='image'&&file.state!=='missing'){
      media=el('img','answer-file-thumb');media.alt='';media.loading='lazy';
      media.onerror=()=>{media.remove();card.prepend(answerIcon(file));};
      media.src=answerImageUrl(cur?{...cur}:{},file,320);
    }
    if(media)card.append(media);else card.append(answerIcon(file));
    card.append(el('span','answer-file-name',file.name||'文件'));
    const bits=[answerSize(file.size),answerState(file)].filter(Boolean);
    card.append(el('span','answer-file-meta',bits.join(' · ')));
    card._answerFile=file;
    card.onclick=e=>{e.preventDefault();e.stopPropagation();if(answerDialog?.open)answerDialog.close();openAnswerFile(file);};
    return card;
  }
  function answerNoteChip(note){const info=answerReasonInfo(note.reason,note.text);
    const chip=el('span','file-note-short','（'+info.short+'）');
    chip.dataset.noteReason=note.reason||'unsupported';if(note.text)chip.dataset.noteText=note.text;
    chip.setAttribute('role','button');chip.tabIndex=0;
    chip.onclick=e=>{e.preventDefault();e.stopPropagation();openAnswerReason(note);};
    return chip;}
  function answerNoteBlock(text,note){const span=el('span','answer-note-block');
    if(text)span.append(document.createTextNode(text));span.append(answerNoteChip(note));return span;}
  function answerPlaceholderText(ph,key){const alt=ph.querySelector('img')?.getAttribute('alt')||'';
    return alt||String(key||'').split(/[\\/]/).pop()||'图片';}
  function answerInlineImage(file,key,index){
    const target=cur?{...cur}:null;
    const fig=el('figure','local-image msg-image loading');
    fig.dataset.observed='1';fig.dataset.answerRendered='1';fig.dataset.fileId=file.id||'';fig.dataset.resultKey=key;fig.dataset.resultIndex=index||'';
    fig.style.aspectRatio=Number(file.w)>0&&Number(file.h)>0?file.w+' / '+file.h:'4 / 3';
    const img=el('img');img.alt=file.name||'';img.loading='lazy';img.decoding='async';
    const state=el('span','msg-image-state',file.name||'图片');fig.append(img,state);
    img.onload=()=>{fig.classList.remove('loading');fig.classList.add('loaded');state.hidden=true;};
    img.onerror=()=>{fig.classList.remove('loading','loaded');fig.classList.add('failed');state.hidden=false;
      const retry=el('button','msg-image-retry','重试');retry.type='button';
      retry.onclick=e=>{e.preventDefault();e.stopPropagation();fig.classList.add('loading');fig.classList.remove('failed');state.hidden=true;
        img.src=answerImageUrl(target,file,answerImageWidth())+'&retry='+(++fig._retries||1);};
      state.replaceChildren(el('span','','图片读取失败'),retry);};
    fig.onclick=e=>{if(e.target.closest('button'))return;e.preventDefault();e.stopPropagation();openAnswerFile(file);};
    img.src=answerImageUrl(target,file,answerImageWidth());
    return fig;
  }
  function answerInlineCard(file,key,index){const card=answerCard(file);
    card.classList.add('local-image','msg-file-card');
    card.dataset.observed='1';card.dataset.answerRendered='1';card.dataset.resultKey=key;card.dataset.resultIndex=index||'';
    return card;}
  function answerStrip(node,files,rendered){
    const seen=new Set(),eligible=[];
    for(const f of files||[]){
      if(!f||!f.id||seen.has(f.id))continue;seen.add(f.id);
      if(rendered.has(f.id))continue;
      const via=Array.isArray(f.via)?f.via:[];
      if(!via.some(v=>ANSWER_VIA.has(v)))continue;
      eligible.push(f);
    }
    if(!eligible.length)return;
    const strip=el('div','answer-files');strip.setAttribute('aria-label','这条消息的文件');
    for(const f of eligible.slice(0,8))strip.append(answerCard(f,{thumb:true}));
    if(eligible.length>8){
      const more=el('button','answer-more','还有 '+(eligible.length-8)+' 个');more.type='button';
      more.onclick=e=>{e.preventDefault();e.stopPropagation();openAnswerMessageFiles(files);};
      strip.append(more);
    }
    node.append(strip);
  }
  function openAnswerMessageFiles(files){
    const list=el('div','answer-file-list');
    for(const f of files||[])if(f&&f.id)list.append(answerCard(f));
    if(!list.children.length)list.append(el('p','','这条消息没有文件'));
    showAnswerDialog('这条消息的文件',[list]);
  }
  function decorateWebLinks(node){
    for(const a of node.querySelectorAll('a[href]')){
      let url;try{url=new URL(a.getAttribute('href'),location.href);}catch{continue;}
      const host=url.hostname.replace(/^\[|\]$/g,'').toLowerCase();
      if(!/^https?:$/.test(url.protocol)||!['localhost','127.0.0.1','::1'].includes(host))continue;
      const next=a.nextElementSibling;
      if(next&&next.classList.contains('web-local-note'))continue;
      a.after(el('span','file-note-short web-local-note','（电脑本机网址，手机打不开）'));
    }
  }
  function answerTextNodes(root){
    const out=[],walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,{acceptNode(n){
      if(!n.data.trim())return NodeFilter.FILTER_REJECT;
      const p=n.parentElement;if(!p)return NodeFilter.FILTER_REJECT;
      if(p.closest('a,code,pre,script,style,textarea,button,.code-wrap,.msg-image,.answer-file,.file-note-short'))return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    }});
    while(walker.nextNode())out.push(walker.currentNode);return out;
  }
  function decorateTextFiles(node,files){
    const pairs=[];
    for(const f of files||[]){if(!f||!f.id||!Array.isArray(f.texts))continue;
      for(const text of f.texts)if(typeof text==='string'&&text.length)pairs.push({text,file:f});}
    if(!pairs.length)return;
    pairs.sort((a,b)=>b.text.length-a.text.length);
    for(const pair of pairs){
      for(const code of [...node.querySelectorAll('code')]){
        if(code.closest('.code-wrap')||code.closest('a')||code.dataset.answerText)continue;
        if(code.textContent!==pair.text)continue;
        const a=el('a','inline-file');a.href='#';a.dataset.fileId=pair.file.id;a._answerFile=pair.file;
        code.replaceWith(a);a.append(code);code.dataset.answerText='1';
      }
    }
    for(const pair of pairs){
      if(pair.text.length<2)continue;
      for(const original of answerTextNodes(node)){
        if(!original.parentNode||original.parentElement?.closest('a'))continue;
        let current=original;
        while(current&&current.parentNode){
          const at=current.data.indexOf(pair.text);if(at<0)break;
          const before=current.splitText(at),after=before.splitText(pair.text.length);
          const a=el('a','inline-file');a.href='#';a.dataset.fileId=pair.file.id;a._answerFile=pair.file;a.textContent=pair.text;
          before.parentNode.insertBefore(a,before);a.append(before);
          current=after;
        }
      }
    }
  }
  function decorateAnswerFiles(node,m,{strip=false}={}){
    node.querySelectorAll('.answer-files').forEach(n=>n.remove());
    const files=Array.isArray(m.files)?m.files:null;
    if(!files){answerMessageFiles.delete(node);return;}
    const notes=Array.isArray(m.file_notes)?m.file_notes:[];
    answerMessageFiles.set(node,{files,notes});
    const rendered=new Set();
    for(const ph of [...node.querySelectorAll('.local-image')]){
      ph.dataset.observed='1';
      if(ph.dataset.answerRendered==='1'){if(ph.dataset.fileId)rendered.add(ph.dataset.fileId);continue;}
      const key=ph.dataset.resultKey||'',file=answerFileFor(files,key);
      if(file&&(file.view==='image'||file.view==='svg')){
        if(file.view==='image'&&file.state!=='missing'&&(file.thumb||!file.size||Number(file.size)<=16<<20)){
          ph.replaceWith(answerInlineImage(file,key,ph.dataset.resultIndex));rendered.add(file.id);continue;
        }
        ph.replaceWith(answerInlineCard(file,key,ph.dataset.resultIndex));rendered.add(file.id);continue;
      }
      const note=answerNoteFor(notes,key);
      if(note){ph.replaceWith(answerNoteBlock(answerPlaceholderText(ph,key),note));continue;}
      ph.replaceWith(document.createTextNode(answerPlaceholderText(ph,key)));
    }
    for(const a of node.querySelectorAll('a[data-file-href]'))a.setAttribute('href','#');  // a new computer only: an old one keeps its plain words
    for(const a of node.querySelectorAll('a[data-file-href],a[data-result-key]')){
      const href=a.dataset.resultKey||a.dataset.fileHref||'';
      if(!href||a.dataset.noteReason)continue;
      if(answerFileFor(files,href))continue;
      const note=answerNoteFor(notes,href);if(!note)continue;
      a.dataset.noteReason=note.reason||'unsupported';if(note.text)a.dataset.noteText=note.text;
      a.after(answerNoteChip(note));
    }
    decorateTextFiles(node,files);
    if(strip)answerStrip(node,files,rendered);
  }
  function decorateMessage(node,m){
    const f=flows.get(node.dataset.key);if(f)f.node=node;
    if(pick?.b===node)node.classList.add('picked');  // redrawn while its menu is open
    if(m.role==='user'&&m.truncated){const actions=el('div','message-actions'),expand=el('button','','展开全文（'+m.length+' 字）');expand.onclick=()=>expandMessage(m.id).catch(e=>toast(e.message,true));actions.append(expand);node.append(actions);return;}
    if(m.role!=='assistant')return;
    decorateWebLinks(node);
    if(m.phase==='commentary'){decorateAnswerFiles(node,m);return;}
    const actions=el('div','message-actions'),copy=el('button','','复制正文');copy.onclick=()=>copyText(m.truncated&&!m.streaming?api('/api/chat/message?app='+cur.app+'&id='+encodeURIComponent(cur.id)+'&message='+encodeURIComponent(m.id)).then(full=>publicText(full.text)):publicText(m.text));actions.append(copy);
    if(m.truncated){const expand=el('button','',m.streaming?'生成中，完成后可展开':'展开全文（'+m.length+' 字）');expand.disabled=!!m.streaming;expand.onclick=()=>expandMessage(m.id).catch(e=>toast(e.message,true));actions.append(expand);}
    node.append(actions);
    decorateAnswerFiles(node,m,{strip:true});
  }
  // ---- a reply runs out smoothly (10-22)
  // Text used to land in lumps: Codex's stream reads its log once a second, DeepSeek's sends up to five updates a second,
  // and Claude writes a reply a whole block at a time. What has arrived now runs out at about the pace it comes in, at most
  // about a second behind, and a block that lands whole runs out within a second (renderMsgs asks flowText how much of a
  // reply to draw; step rewrites only its words, .reply-text, a frame at a time). The first paint of a conversation, older
  // pages, a pile of rows at once, the page just back on screen and Reduce Motion show the text as it is.
  const flows=new Map();  // row key → {text, shown (characters out), pace (out a second), gap (between updates), at, node, …}
  let frame=0,quietUntil=0,keysSeen=null,touching=0;  // touching: when a finger, still down, last went down on or moved the messages
  // painted: this conversation's own messages are on screen. Not just the box having been drawn: the Codex state can draw it
  // empty before the conversation is read, and the first paint then ran out like a new reply.
  let painted=false;
  const MIN_CPS=40;
  const calm=()=>document.hidden||performance.now()<quietUntil||matchMedia('(prefers-reduced-motion: reduce)').matches;
  // What is not out yet goes at one steady pace: while it streams, spread over a little more than the time till the next
  // update is due (so the words keep moving), and once it has all come, within a second.
  function pace(f){const left=f.text.length-f.shown;f.pace=Math.max(MIN_CPS,left/(f.streaming?Math.min(1.2,Math.max(.2,(f.gap||1)*1.15)):Math.min(1,Math.max(.3,left/400))));}
  function upTo(f){  // the part out by now, never half of a character pair
    let n=Math.floor(f.shown);if(n>=f.text.length)return f.text;
    const c=f.text.charCodeAt(n-1);if(c>=0xD800&&c<0xDC00)n++;
    return f.text.slice(0,n);
  }
  // A half-typed mark shows as what it will be, not as its marks: a line that may turn into a code fence, a table row, a
  // heading or a ::directive waits till it is whole, a [link](…) till it is closed, and **bold** and `code` are bold and
  // code already (inside a code block the words are left as they are).
  function partial(s){
    const at=s.lastIndexOf('\n')+1;let tail=s.slice(at);
    if(/^\s*(::|\||[`~]{1,2}$|```|~~~|#{1,6}$)/.test(tail))return s.slice(0,at);
    if((s.slice(0,at).match(/^\s*```/gm)||[]).length%2)return s;
    const open=tail.lastIndexOf('['),rest=open<0?'':tail.slice(open);
    if(open>=0&&!/\]\([^)\s]*\)/.test(rest)&&(rest.includes('](')||rest.length<120))tail=tail.slice(0,open);
    tail=tail.replace(/[*`]+$/,'');
    if((tail.match(/`/g)||[]).length%2)tail+='`';
    else if((tail.replace(/`[^`]*`/g,'').match(/\*\*/g)||[]).length%2)tail+='**';
    return s.slice(0,at)+tail;
  }
  const onScreen=f=>f.shown>=f.text.length?f.text:partial(upTo(f));
  function flowText(key,m,fresh,keys){
    if(m.role!=='assistant'||typeof m.text!=='string')return m.text;
    const now=performance.now(),text=m.text,still=calm();
    if(keys!==keysSeen){keysSeen=keys;for(const [k,o] of flows)if(!keys.has(k)){if(!o.gone){o.gone=now;o.goneIn=keys;}else if(now-o.gone>3000)flows.delete(k);}}
    let f=flows.get(key);
    if(!f){
      // DeepSeek hands a streamed reply over to its saved copy, which has another name: carry on where the stream had got
      // to. A stream replaced by other words shows them at once.
      const gone=[...flows].filter(([,o])=>o.gone&&!!o.thinking===!!m.thinking),from=gone.find(([,o])=>text.startsWith(upTo(o)));
      if(from){f={...from[1],gone:0,goneIn:null};flows.delete(from[0]);}
      else if(fresh&&painted&&!still&&!gone.some(([,o])=>o.goneIn===keys))f={text:'',shown:0,gap:0,at:0};
      else if(m.streaming)f={text,shown:text.length,gap:0,at:now};  // what is on screen, for the words still to come
      else return text;
      flows.set(key,f);
    }
    f.gone=0;f.goneIn=null;
    const was=f.streaming;f.streaming=!!m.streaming;f.thinking=!!m.thinking;
    if(text!==f.text){
      const kept=text.startsWith(upTo(f))&&!(f.truncated&&!m.truncated);  // 展开全文 shows it all at once
      if(kept&&f.at&&text.length>f.text.length){const gap=Math.min(3,(now-f.at)/1000);f.gap=f.gap?f.gap*.6+gap*.4:gap;}
      if(!kept||still)f.shown=text.length;
      f.text=text;f.at=now;pace(f);if(!f.tick)f.tick=now;  // the next frame already moves it
    }else if(was&&!f.streaming)pace(f);  // it has all come: the rest at the finishing pace
    f.truncated=!!m.truncated;
    if(f.shown<f.text.length)wake();else if(!f.streaming)flows.delete(key);
    return onScreen(f);
  }
  function wake(){if(!frame)frame=requestAnimationFrame(step);}
  function step(now){
    frame=0;if(window.workspaceUI?.composing){setTimeout(wake,250);return;}  // nothing moves under the IME (workspace-ui.js)
    // follow the words down only from the very end, and not under a finger (one left still for 3 s counts as gone)
    if(touching&&now-touching>=3000)touching=0;
    const box=$('cvMsgs'),atEnd=!touching&&box.scrollHeight-box.scrollTop-box.clientHeight<=24,ended=[];let moved=false,going=false;
    for(const [key,f] of flows){
      if(f.shown>=f.text.length)continue;
      const words=f.node?.isConnected&&f.node.querySelector('.reply-text');if(!words){flows.delete(key);continue;}
      if(holding(f.node)){f.tick=0;continue;}  // words being picked out of it: it waits till they are let go
      const dt=f.tick?Math.max(0,Math.min(.1,(now-f.tick)/1000)):0;f.tick=now;
      const before=onScreen(f);f.shown=Math.min(f.text.length,f.shown+f.pace*dt);
      const after=onScreen(f);if(after!==before){window.updateMarkdown(words,assistantMarkdown(after).markdown,true);moved=true;}
      if(f.shown<f.text.length)going=true;else{f.tick=0;if(!f.streaming)ended.push(f);}
    }
    if(moved&&atEnd)box.scrollTop=box.scrollHeight;
    // Run out: redraw the whole reply and its created-conversation links.
    if(ended.length&&cur&&box.dataset.ready){for(const f of ended)delete f.node.dataset.sig;renderMsgs(currentMessages);}
    if(going)wake();
  }
  // Words being picked out of a message stay as they are till they are let go: a redraw (each update of a reply still being
  // written, each frame of its run-out) would drop them. renderMsgs asks before it redraws a message.
  let heldBack=false;
  function holding(n){if(copyPress?.node===n&&performance.now()-copyPress.at<2000)return true;const s=getSelection?.();if(!n||!s||s.isCollapsed||!s.rangeCount||!s.getRangeAt(0).intersectsNode(n))return false;heldBack=true;return true;}
  document.addEventListener('selectionchange',()=>{if(!heldBack||!getSelection().isCollapsed)return;heldBack=false;if(cur&&$('cvMsgs').dataset.ready)renderMsgs(currentMessages);wake();});
  function settleFlows(){let any=false;for(const f of flows.values())if(f.shown<f.text.length){f.shown=f.text.length;if(f.node?.isConnected){delete f.node.dataset.sig;any=true;}}if(any&&cur&&$('cvMsgs').dataset.ready)renderMsgs(currentMessages);}
  // The release is listened for on what the finger went down on: when the words under it are rewritten, that node leaves the
  // page and its touchend no longer reaches #cvMsgs or the document, but still reaches the node itself.
  $('cvMsgs').addEventListener('touchstart',e=>{touching=performance.now();const off=()=>{touching=0;};for(const name of ['touchend','touchcancel'])e.target.addEventListener(name,off,{once:true,passive:true});},{passive:true});
  $('cvMsgs').addEventListener('scroll',()=>{if(touching)touching=performance.now();},{passive:true});
  for(const name of ['touchend','touchcancel'])document.addEventListener(name,()=>{touching=0;},{passive:true});

  // ---- a message tapped: what can be done with it (10-22)
  // Held, a message's words are picked out the phone's own way, with its handles and its 拷贝. (0.25.0 lifted a held message
  // out over a blurred page instead: its menu covered the words, none could be picked out, and the blur was too much; the
  // user, 10-22.) Tapped, or right-clicked on a computer, a message comes up a little and a small menu shows by it:
  // 复制 · 选择文字 · 分享. Nothing is dimmed and nothing is in the way: a tap anywhere else, a scroll or a panel puts it
  // away, and that tap does nothing else among the messages. A tap that puts the keyboard away, or clears words picked out,
  // opens nothing. 选择文字 shows the words large, to pick from with the phone's handles, with 复制全部 under them.
  Object.assign(ICONS,{copy:'M8 8h11v11H8zM5 16V5h11',select:'M5 7V5h14v2M12 5v14M9 19h6',share:'M12 15V4m-4 4 4-4 4 4M6 11v8h12v-8'});
  const menuCss=el('style');menuCss.textContent=`#cvMsgs .bub.user{transition:transform .2s ease,box-shadow .2s ease}
    #cvMsgs .bub.user.picked{transform:scale(1.035);box-shadow:0 8px 22px rgba(37,99,235,.28);transition:transform .34s cubic-bezier(.3,1.6,.5,1),box-shadow .25s ease}
    #cvMsgs .bub.assistant{transition:background-color .2s ease,box-shadow .2s ease}
    #cvMsgs .bub.assistant.picked{background:#f1f3f6;box-shadow:0 0 0 8px #f1f3f6;border-radius:6px}
    .msg-menu{position:absolute;z-index:30;display:flex;padding:4px;border-radius:16px;background:#fff;box-shadow:0 10px 30px rgba(15,23,42,.16),0 1px 3px rgba(15,23,42,.08),0 0 0 .5px rgba(15,23,42,.08)}
    .msg-menu[hidden]{display:none}.msg-menu.closing{pointer-events:none}
    .msg-menu button{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;min-width:64px;min-height:56px;margin:0;padding:7px 10px 6px;border:0;border-radius:12px;background:transparent;color:var(--text);font-size:12px;font-weight:500;line-height:1.2}
    .msg-menu button:active{background:#eef0f4;transform:none}.msg-menu .icon{width:21px;height:21px}
    #readerSheet .reader-text{font-size:17px;line-height:1.75;white-space:pre-wrap;word-break:break-word;color:var(--text);-webkit-user-select:text;user-select:text;-webkit-touch-callout:default}
    #readerSheet .reader-text pre{white-space:pre-wrap;word-break:break-all;background:#f3f4f6;padding:10px 12px;border-radius:8px;font:14px/1.6 ui-monospace,Consolas,monospace;margin:6px 0}
    #readerSheet .reader-text code{background:#f3f4f6;padding:0 3px;border-radius:4px;font-size:15px}
    #readerSheet .reader-text table{border-collapse:collapse;display:block;overflow-x:auto;white-space:normal;font-size:15px;margin:8px 0}#readerSheet .reader-text td{border:1px solid var(--line);padding:6px 10px;vertical-align:top}
    #readerSheet .hint{margin:0}#readerSheet .reader-foot{flex:none;padding:10px 16px 12px;border-top:1px solid var(--line)}#readerSheet .reader-foot button{width:100%}
    @media (prefers-reduced-motion:reduce){#cvMsgs .bub.user.picked{transform:none}#cvMsgs .bub.user,#cvMsgs .bub.assistant{transition:none}}`;document.head.append(menuCss);
  function textOf(b,m){
    if(m&&typeof m.text==='string')return m.role==='assistant'?publicText(m.text):m.text;
    const c=b.cloneNode(true);c.querySelectorAll('.send-receipt,.outbox-state,.message-actions,.outbox-refs,.sent-images,.message-origin,.code-head,.thread-link').forEach(n=>n.remove());return c.textContent.trim();
  }
  async function fullText(b,m){return textOf(b,m?.truncated&&!m.streaming?await api('/api/chat/message?app='+cur.app+'&id='+encodeURIComponent(cur.id)+'&message='+encodeURIComponent(m.id)):m);}
  // 选择文字: the words as they read in the conversation, large, with nothing else that a finger could catch
  const readerBody=sheet('readerSheet','选择文字'),readerFoot=el('div','reader-foot'),readerCopy=el('button','big','复制全部');
  readerFoot.append(readerCopy);$('readerSheet').querySelector('.box').append(readerFoot);
  let readerWords='';readerCopy.onclick=()=>copyText(readerWords);
  function openReader(text,hint='长按文字选出要的部分，拖动两端调整。'){
    readerWords=text;const words=el('div','reader-text');words.innerHTML=md(text);readerBody.replaceChildren(el('div','hint',hint),words);
    openSheet('readerSheet');readerBody.scrollTop=0;
  }
  const msgMenu=el('div','msg-menu');msgMenu.setAttribute('role','menu');msgMenu.setAttribute('aria-label','消息');msgMenu.hidden=true;$('convView').append(msgMenu);
  // pick: the message the menu is for, where on it the finger was, and (a long one shown in part) its whole words
  let pick=null,down=null,dismissed=-1e9,opening=0;
  const reduced=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
  const picking=()=>{const s=getSelection?.();return !!s&&!s.isCollapsed&&String(s).trim()!=='';};
  const tappable=t=>{const b=t?.closest?.('#cvMsgs .bub');return b&&!b.classList.contains('note')&&!b.onclick&&!t.closest('button,a,input,textarea,select,summary,label,img,video,.message-actions,.outbox-refs,.sent-images')?b:null;};
  function openMenu(b,x,y){
    closeMenu(true);if(!cur||!b.isConnected)return;
    const m=loaded.find(v=>v.id===b.dataset.key),r=b.getBoundingClientRect();
    const p=pick={b,m,x:x-r.left,y:y-r.top,full:null,words:null};
    if(m?.truncated&&!m.streaming){p.full=fullText(b,m);p.full.then(t=>{p.words=t;},()=>{});}  // read now, there by the time 复制 is tapped
    msgMenu.replaceChildren();
    const item=(label,name,act)=>{const btn=el('button');btn.type='button';btn.setAttribute('role','menuitem');btn.innerHTML=icon(name);btn.append(el('span','',label));
      btn.onclick=()=>{closeMenu();act();};msgMenu.append(btn);window.navigationUI?.tapTick?.(btn);};
    // in the tap itself (Safari writes the clipboard nowhere else): the words, or the promise of them
    item('复制','copy',()=>copyText(p.words??p.full??textOf(b,m)));
    item('选择文字','select',()=>Promise.resolve(p.words??p.full??textOf(b,m)).then(t=>openReader(t),e=>toast(e.message,true)));
    if(navigator.share)item('分享','share',async()=>{try{await navigator.share({text:p.words??await(p.full??textOf(b,m))});}catch(e){if(e.name!=='AbortError')toast(e.message,true);}});
    msgMenu.getAnimations().forEach(a=>a.cancel());msgMenu.classList.remove('closing');msgMenu.hidden=false;b.classList.add('picked');
    if(!place())return;
    if(!reduced())msgMenu.animate([{opacity:0,transform:'scale(.9)'},{opacity:1,transform:'none'}],{duration:200,easing:'cubic-bezier(.2,1.25,.4,1)'});
    window.navigationUI?.haptic?.();
  }
  // Over one of yours, or under it when there is no room; by the finger on a reply (often taller than the screen), over the
  // line tapped or under it. Kept on the screen and clear of the back-swipe strip on the left.
  function place(){
    const p=pick;if(!p)return false;const b=p.b,r=b.getBoundingClientRect(),area=$('cvMsgs').getBoundingClientRect(),host=$('convView').getBoundingClientRect();
    const lo=Math.max(area.top,0)+8,hi=Math.min(area.bottom,viewportBox().height)-8,mw=msgMenu.offsetWidth,mh=msgMenu.offsetHeight,mine=b.classList.contains('user');
    const ax=mine?r.left+r.width/2:r.left+p.x,ay=r.top+p.y;
    if(!b.isConnected||(mine?r.bottom<lo||r.top>hi:ay<lo||ay>hi)){closeMenu();return false;}
    let top,below;
    if(mine&&r.top-10-mh>=lo){top=r.top-10-mh;below=false;}else if(mine&&r.bottom+10+mh<=hi){top=r.bottom+10;below=true;}
    else if(ay-16-mh>=lo){top=ay-16-mh;below=false;}else{top=Math.min(hi-mh,ay+24);below=true;}
    const left=Math.max(20,Math.min(innerWidth-12-mw,ax-mw/2));
    msgMenu.style.left=(left-host.left)+'px';msgMenu.style.top=(top-host.top)+'px';msgMenu.style.transformOrigin=Math.round(ax-left)+'px '+(below?'0':'100%');
    return true;
  }
  function closeMenu(now=false){
    clearTimeout(opening);if(!pick)return;pick.b.classList.remove('picked');pick=null;
    if(now||reduced()||msgMenu.hidden){msgMenu.hidden=true;return;}
    msgMenu.classList.add('closing');msgMenu.animate([{opacity:1},{opacity:0}],{duration:120,easing:'ease-in'}).onfinish=()=>{if(!pick){msgMenu.hidden=true;msgMenu.classList.remove('closing');}};
  }
  document.addEventListener('pointerdown',e=>{
    clearTimeout(opening);
    down={x:e.clientX,y:e.clientY,t:performance.now(),type:e.pointerType,busy:e.pointerType!=='mouse'&&typingField()||!!window.workspaceUI?.composing||picking()};  // a tap that puts the keyboard away
    if(pick&&!msgMenu.contains(e.target)){closeMenu();if($('cvMsgs').contains(e.target))dismissed=performance.now();}
  },true);
  $('cvMsgs').addEventListener('click',e=>{
    const b=tappable(e.target),d=down;down=null;
    // not a press held (the phone's own selection), nor one that moved
    if(!b||!d||d.busy||e.defaultPrevented||e.detail>1||overlays.length||picking()||performance.now()-dismissed<600||performance.now()-d.t>500||Math.hypot(e.clientX-d.x,e.clientY-d.y)>12)return;
    if(d.type==='mouse')opening=setTimeout(()=>openMenu(b,e.clientX,e.clientY),240);  // a double click picks a word instead
    else openMenu(b,e.clientX,e.clientY);
  });
  // a right-click; a long press on a phone (Android sends one too) is left to the phone's own selection
  $('cvMsgs').addEventListener('contextmenu',e=>{
    if((e.pointerType||down?.type)!=='mouse'||picking()||overlays.length)return;const b=tappable(e.target);if(!b)return;
    e.preventDefault();openMenu(b,e.clientX,e.clientY);
  });
  $('cvMsgs').addEventListener('scroll',()=>{if(pick)place();},{passive:true});  // moved under it by new words: it follows
  addEventListener('wheel',e=>{if(pick&&!msgMenu.contains(e.target))closeMenu();},{passive:true});
  addEventListener('resize',()=>closeMenu(true));
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&pick)closeMenu();});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)closeMenu(true);});
  new MutationObserver(()=>{if($('convView').inert||$('convView').style.display==='none')closeMenu(true);}).observe($('convView'),{attributes:true,attributeFilter:['inert','style']});
  function openSearch(){if(!cur)return;const target={...cur};searchBody.innerHTML='';const input=el('input');input.type='search';input.placeholder='查找这段对话的完整内容';input.setAttribute('aria-label','查找消息关键词');const go=el('button','big','查找'),results=el('div'),more=el('button','','更多结果');more.hidden=true;let next=null,version=0;
    async function search(append=false){const q=input.value.trim();if(!q)return;const v=++version;go.disabled=true;try{const j=await api('/api/chat/search?app='+target.app+'&id='+encodeURIComponent(target.id)+'&query='+encodeURIComponent(q)+(append&&next?'&cursor='+encodeURIComponent(next):''));if(v!==version)return;if(!append)results.innerHTML='';for(const hit of j.items){const b=el('button','search-hit',hit.snippet);b.append(el('small','',(hit.origin==='other_chat'?'来自其他对话':hit.role==='user'?'你':'助手')+' · '+stamp(hit.time)));b.onclick=()=>{dismissOverlays();jump(hit.id).catch(e=>toast(e.message,true));};results.append(b);}if(!j.items.length&&!append)results.append(el('div','hint','没有找到匹配消息'));next=j.next_cursor;more.hidden=!j.has_more;}catch(e){toast(e.message,true);}finally{go.disabled=false;}}
    go.onclick=()=>search();more.onclick=()=>search(true);input.onkeydown=e=>{if(e.key==='Enter'&&!e.isComposing)search();};searchBody.append(input,go,results,more);openSheet('historySearch');}
  function fileUrl(target,file,extra=''){return '/api/file?app='+target.app+'&id='+encodeURIComponent(target.id)+'&file='+file.id+extra;}
  function messageId(node){return node.closest('[data-message-id]')?.dataset.messageId||node.closest('#cvMsgs>[data-key]')?.dataset.key;}
  async function referencedFile(target,link){
    const mid=messageId(link);if(!mid)throw Error('找不到这条消息的文件引用');
    const result=await api('/api/chat/files?app='+target.app+'&id='+encodeURIComponent(target.id)+'&message='+encodeURIComponent(mid));
    const file=result.items.find(f=>f.index===Number(link.dataset.resultIndex||0));
    if(!file)throw Error('文件引用无效');if(file.state==='missing')throw Error('文件已移动或删除');return file;
  }
  document.addEventListener('click',async e=>{
    const inline=e.target.closest?.('[data-file-id]');
    if(inline&&inline._answerFile){e.preventDefault();openAnswerFile(inline._answerFile);return;}
    const note=e.target.closest?.('[data-note-reason]');
    if(note){e.preventDefault();openAnswerReason({reason:note.dataset.noteReason,text:note.dataset.noteText||''});return;}
    const link=e.target.closest?.('a[data-result-index],a[data-result-path],a[data-result-key],a[data-file-href]');if(!link)return;
    const bub=link.closest('[data-message-id]'),answer=bub?answerMessageFiles.get(bub):null;
    if(answer){  // a new computer lists the files itself: no whole-conversation list, no index lookup
      e.preventDefault();
      const href=link.dataset.resultKey||link.dataset.fileHref||'';
      const file=answerFileFor(answer.files,href);if(file){openAnswerFile(file);return;}
      const missing=answerNoteFor(answer.notes,href);if(missing)openAnswerReason(missing);
      return;
    }
    if(link.dataset.fileHref){e.preventDefault();return;}  // an old computer showed these as plain words
    e.preventDefault();if(!cur)return;const target={...cur};
    try{const file=await referencedFile(target,link);if(cur?.app!==target.app||cur?.id!==target.id)return;
      if(file.kind==='download'&&file.preview!=='pdf')await download(target,file);else await preview(target,file);  // Office: shown as PDF
    }catch(error){toast(error.message,true);}
  });
  document.addEventListener('keydown',e=>{
    if(e.key!=='Enter'&&e.key!==' ')return;
    const chip=e.target.closest?.('.file-note-short[data-note-reason]');if(!chip)return;
    e.preventDefault();openAnswerReason({reason:chip.dataset.noteReason,text:chip.dataset.noteText||''});
  });
  const images=new IntersectionObserver(entries=>{for(const entry of entries){if(!entry.isIntersecting)continue;const link=entry.target;images.unobserve(link);if(!cur)continue;const target={...cur};referencedFile(target,link).then(file=>{if(!link.isConnected||cur?.id!==target.id)return;const img=link.querySelector('img');img.onload=()=>{link.querySelector('span').textContent=file.state==='updated'?'文件已更新':'当前文件';};img.onerror=()=>{link.querySelector('span').textContent='图片读取失败，点击重试或下载';};img.src=fileUrl(target,file);}).catch(error=>{link.querySelector('span').textContent=error.message+'，点击重试';});}}, {root:$('cvMsgs'),rootMargin:'200px'});
  new MutationObserver(()=>{for(const link of $('cvMsgs').querySelectorAll('.local-image:not([data-observed])')){link.dataset.observed='true';images.observe(link);}}).observe($('cvMsgs'),{childList:true,subtree:true});
  async function checkFile(target,file){return api('/api/file/meta?app='+target.app+'&id='+encodeURIComponent(target.id)+'&file='+file.id);}
  async function prepareFile(target,file,previewing){
    if(!window.artifactPreview){toast('附件预览组件未加载，请刷新后重试',true);return;}
    return artifactPreview.open(target,file,{downloadOnly:!previewing});
  }
  async function download(target,file){workspaceUI?.saveScene();return prepareFile(target,file,false);}
  async function preview(target,file){return prepareFile(target,file,true);}
  async function openFiles(){if(!cur)return;const target={...cur};fileBody.textContent='正在读取文件…';openSheet('conversationFiles');try{const j=await api('/api/chat/files?app='+target.app+'&id='+encodeURIComponent(target.id));fileBody.innerHTML='';for(const f of j.items){const row=el('div','file-row',f.name);row.append(el('div','hint',Math.ceil(f.size/1024)+' KB · '+stamp(f.modified)));const actions=el('div','file-actions');if(f.kind!=='download'||f.preview==='pdf'){const b=el('button','','预览');b.onclick=()=>preview(target,f);actions.append(b);}const d=el('button','','下载');d.onclick=()=>download(target,f);actions.append(d);row.append(actions);fileBody.append(row);}if(!j.items.length)fileBody.append(el('div','hint','尚未找到允许目录内的本地文件链接。'));fileBody.append(el('div','hint',j.scope));}catch(e){fileBody.textContent='读取失败：'+e.message;}}
  function openTemplates(){const target=cur?{...cur}:null;let entries=[];try{entries=JSON.parse(localStorage.getItem('lbr_prompt_library')||'[]');}catch(e){}
    function save(){localStorage.setItem('lbr_prompt_library',JSON.stringify(entries));}
    function editor(item=null){templateBody.innerHTML='';const form=el('div','template-editor'),name=el('input'),text=el('textarea'),saveButton=el('button','big','保存'),back=el('button','','返回');name.placeholder='名称';name.setAttribute('aria-label','提示语名称');name.maxLength=40;text.placeholder='提示语内容';text.setAttribute('aria-label','提示语内容');text.maxLength=20000;name.value=item?.name||'';text.value=item?.text||'';form.append(name,text,saveButton,back);templateBody.append(form);back.onclick=draw;saveButton.onclick=()=>{if(!name.value.trim()||!text.value.trim()){toast('请填写名称和内容',true);return;}const value={id:item?.id||Date.now().toString(36),name:name.value.trim(),text:text.value};entries=item?entries.map(v=>v.id===item.id?value:v):[...entries,value];try{save();draw();}catch(e){toast('保存失败，浏览器存储空间不足',true);}};}
    function draw(){templateBody.innerHTML='';for(const p of entries){const row=el('div','template-row'),insert=el('button','insert',p.name),edit=el('button','','编辑'),remove=el('button','danger','删除');insert.onclick=()=>{if(!cur||chatKey(cur)!==chatKey(target)||workspaceUI.composing){toast('请先返回目标对话并结束当前输入',true);return;}const input=$('cvText');input.setRangeText(p.text,input.selectionStart,input.selectionEnd,'end');input.dispatchEvent(new Event('input',{bubbles:true}));dismissOverlays();input.focus();};edit.onclick=()=>editor(p);remove.onclick=()=>{entries=entries.filter(v=>v.id!==p.id);save();draw();};row.append(insert,edit,remove);templateBody.append(row);}const add=el('button','big','新建提示语');add.onclick=()=>editor();templateBody.append(add,el('div','hint','点击名称只插入输入框，不会自动发送。'));}draw();openSheet('promptLibrary');}
  function pauseStream(){streamGeneration++;if(source){source.close();source=null;}streamActive=false;clearTimeout(retryTimer);bufferedEvent=null;}
  function applyEvent(data){if(!cur||!me||data.id!==cur.id||data.app!==cur.app)return;
    if(data.type==='snapshot'){applyMeta(data.chat);if(!historyWindow){if(!loaded.length){cursor=data.chat.next_cursor;hasMore=!!data.chat.has_more;}merge(data.chat.messages||[]);reconcileLive(data.streaming_ids);render();}}
    else{applyMeta(data.meta||{});if(!historyWindow){merge(data.messages||[]);reconcileLive(data.streaming_ids);render();}else if(data.messages?.length)$('newMessages').hidden=false;}if(data.control)codexUI?.applyState(cur,data.control);}
  function resumeStream(){
    if(window.newChatUI?.isPreview(cur))return;
    if(source||!cur||document.hidden||window.workspaceUI?.paused)return;const target={...cur},generation=++streamGeneration;const s=new EventSource('/api/events?app='+encodeURIComponent(target.app)+'&id='+encodeURIComponent(target.id)+'&protocol=2');source=s;streamSeq=0;
    s.addEventListener('update',e=>{if(generation!==streamGeneration||!cur||chatKey(cur)!==chatKey(target))return;try{const data=JSON.parse(e.data);if(data.protocol!==1)throw Error('protocol');if(data.type!=='snapshot'&&data.seq!==streamSeq+1)throw Error('sequence');streamSeq=data.seq;streamActive=true;if(window.workspaceUI?.composing){bufferedEvent=data;return;}applyEvent(data);}catch(err){pauseStream();retryTimer=setTimeout(()=>{loadConversation(false);resumeStream();},3000);}});
    s.onerror=()=>{if(generation!==streamGeneration)return;pauseStream();retryTimer=setTimeout(resumeStream,Agents.cardLayout(target.app)==='deepseek.v1'?1000:8000);};
  }
  $('cvText').addEventListener('compositionend',()=>{if(bufferedEvent){bufferedEvent=null;pauseStream();resumeStream();}});
  $('newMessages').onclick=()=>{if(historyWindow)loadConversation(true);else jumpToLatest();};
  // hidden: what was running out is shown whole; back on screen, what came meanwhile shows as it is
  document.addEventListener('visibilitychange',()=>{if(document.hidden){pauseStream();settleFlows();}else{quietUntil=performance.now()+2000;if(!window.workspaceUI?.paused)resumeStream();}});
  window.readingUI={loadList,onOpen,loadConversation,decorateMessage,decorateRows(){},flowText,holding,closeMenu,pauseStream,resumeStream,get streamActive(){return streamActive;},get historyWindow(){return historyWindow;}};
  if(cur){onOpen({},cur);loadConversation(true);}else loadList(false,true);
})();
