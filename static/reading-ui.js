/* Paginated public history, files, copying and a single foreground event stream. */
(() => {
  let listKey='',listCursor=null,listHasMore=false,listBusy=false,query='',loadGeneration=0,listSig='';
  let me=null,loaded=[],cursor=null,hasMore=false,historyWindow=false,initialPage=null,fetching=null,source=null,streamActive=false,streamSeq=0,streamGeneration=0,retryTimer=null,bufferedEvent=null;
  const expanded=new Map();
  const css=el('style');css.textContent=`.history-tools{display:flex;justify-content:center;gap:8px;padding:4px 12px;flex:none}.history-tools button{font-size:12px;font-weight:400;min-height:36px;border:0;background:transparent;color:var(--blue);padding:6px 10px}.conversation-search{display:flex;gap:8px;margin:4px 0 12px}.conversation-search input{min-width:0;flex:1;font:inherit;font-size:16px;padding:10px 14px;border:1px solid var(--line);border-radius:16px;background:var(--bg)}.message-actions{display:flex;gap:8px;margin-top:8px}.message-actions button,.code-copy{font-size:12px;font-weight:400;min-height:36px;padding:6px 10px;border:0;background:var(--bg);border-radius:999px;color:var(--muted)}.code-wrap{position:relative}.code-copy{display:block;margin-left:auto}.search-hit{display:block;width:100%;text-align:left;border:0;border-bottom:1px solid var(--line);border-radius:0;font-size:14px;font-weight:400;padding:12px;background:transparent;white-space:pre-wrap}.search-hit small{display:block;color:var(--muted);font-size:12px}.file-row{padding:12px;border:1px solid var(--line);border-radius:16px;overflow-wrap:anywhere}.file-actions{display:flex;gap:8px;margin-top:8px}.file-actions button{font-size:13px;padding:8px 12px;border-radius:999px}.file-preview{width:100%;height:65dvh;border:0}.text-preview{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.6 ui-monospace,monospace;max-height:65dvh;overflow:auto}.template-row{display:flex;align-items:center;gap:4px}.template-row .insert{flex:1;text-align:left;overflow:hidden;text-overflow:ellipsis}.template-row button{font-size:13px;padding:8px;min-height:44px}.template-editor input,.template-editor textarea{box-sizing:border-box;width:100%;font:inherit;font-size:16px;padding:10px;border:1px solid var(--line);border-radius:12px;margin:4px 0}.template-editor textarea{min-height:140px}.list-more{display:block;margin:16px auto;font-size:14px;padding:10px 20px;border-radius:999px}.history-note{font-size:12px;text-align:center;color:var(--muted)}`;document.head.append(css);
  const searchLine=el('div','conversation-search'),listInput=el('input');listInput.type='search';listInput.placeholder='搜索对话标题或文件夹';listInput.setAttribute('aria-label','搜索对话');searchLine.append(listInput);document.querySelector('.conversation-home .chips').after(searchLine);
  const listMore=el('button','list-more','加载更多对话');listMore.hidden=true;listMore.onclick=()=>loadList(true);$('convList').after(listMore);
  let searchTimer;listInput.addEventListener('input',e=>{if(e.isComposing)return;clearTimeout(searchTimer);searchTimer=setTimeout(()=>{query=listInput.value.trim();loadList(false,true);},250);});listInput.addEventListener('compositionend',()=>{query=listInput.value.trim();loadList(false,true);});
  function sheet(id,title){const n=el('div','sheet');n.id=id;n.setAttribute('aria-label',title);n.innerHTML='<div class="box"><div class="sh-head"><b></b><button class="icon-btn" aria-label="关闭">'+icon('close')+'</button></div><div class="sh-body"></div></div>';n.querySelector('b').textContent=title;n.querySelector('button').onclick=()=>closeSheet(id);n.onclick=e=>{if(e.target===n)closeSheet(id);};document.body.append(n);return n.querySelector('.sh-body');}
  const searchBody=sheet('historySearch','查找消息'),fileBody=sheet('conversationFiles','对话文件'),previewBody=sheet('resultPreview','文件预览'),templateBody=sheet('promptLibrary','常用提示语');
  const toolbar=el('div','history-tools'),older=el('button','','加载更早消息'),latest=el('button','','回到最新');older.hidden=true;latest.hidden=true;older.onclick=loadOlder;latest.onclick=()=>loadConversation(true);toolbar.append(older,latest);document.querySelector('.message-region').before(toolbar);
  function menu(label,fn){const b=el('button','menu-row',label);b.onclick=()=>{dismissOverlays();fn();};$('convMenu').querySelector('.sh-body').append(b);}
  menu('查找消息',openSearch);menu('对话文件',openFiles);menu('常用提示语',openTemplates);
  function preserveList(render){const top=document.querySelector('header').getBoundingClientRect().bottom,row=[...document.querySelectorAll('.conv')].find(n=>n.getBoundingClientRect().bottom>top),key=row?.dataset.key,y=row?.getBoundingClientRect().top;render();if(scrollY>40&&key){const n=[...document.querySelectorAll('.conv')].find(n=>n.dataset.key===key);if(n)window.scrollBy(0,n.getBoundingClientRect().top-y);}}
  async function loadList(more=false,reset=false){
    if(listBusy||!window.workspaceUI?.canPoll())return;const key=convApp+'|'+query;if(key!==listKey){reset=true;listKey=key;}listBusy=true;listMore.disabled=true;
    try{const j=await api('/api/chats?app='+convApp+'&limit=40&query='+encodeURIComponent(query)+(more&&listCursor?'&cursor='+encodeURIComponent(listCursor):''));if(key!==convApp+'|'+query)return;
      const incoming=j.items||[];
      if(reset)convItems=incoming;else if(more){const ids=new Set(convItems.map(v=>v.app+':'+v.id));convItems.push(...incoming.filter(v=>!ids.has(v.app+':'+v.id)));}else{const fresh=new Map(incoming.map(v=>[v.app+':'+v.id,v]));const olderItems=convItems.filter(v=>!fresh.has(v.app+':'+v.id));convItems=[...incoming,...olderItems];}
      if(more||reset||!listCursor){listCursor=j.next_cursor;listHasMore=!!j.has_more;}
      // the list is read every 10 s; rebuilt only when it changed, or once a minute for its "x 分钟前" (10-14: a rebuild under
      // a finger made scrolling and tapping catch)
      const sig=JSON.stringify([convItems,Math.floor(Date.now()/60000)]);if(more||reset||sig!==listSig){listSig=sig;preserveList(renderConvs);}$('convHint').textContent=(query?'搜索结果':'按最近活动排序')+(j.total!=null?' · '+j.total+' 个对话':'');listMore.hidden=!listHasMore;
    }catch(e){$('convHint').textContent='读取失败：'+e.message;}finally{listBusy=false;listMore.disabled=false;if(key!==convApp+'|'+query)loadList(false,true);}
  }
  function merge(items,prepend=false){const map=new Map(loaded.map(m=>[m.id,m]));for(const m of items){if(m.streaming&&map.has(m.id)&&!map.get(m.id).streaming)continue;const full=expanded.get(m.id);map.set(m.id,full&&full.length>=(m.length||m.text.length)&&!m.streaming?{...m,text:full.text,truncated:false}:m);}
    const order=loaded.map(m=>m.id),known=new Set(order);
    if(prepend)order.unshift(...items.filter(m=>!known.has(m.id)).map(m=>m.id));
    else{let next=null;for(let i=items.length-1;i>=0;i--){const id=items[i].id;if(!known.has(id)){const at=next===null?-1:order.indexOf(next);if(at<0)order.push(id);else order.splice(at,0,id);known.add(id);}next=id;}}
    loaded=[...new Set(order)].map(id=>map.get(id));loaded.sort((a,b)=>Number.isFinite(a.order)&&Number.isFinite(b.order)?a.order-b.order:0);}
  function reconcileLive(ids){if(!Array.isArray(ids))return;const active=new Set(ids);loaded=loaded.filter(m=>!m.streaming||active.has(m.id));}
  function render(){if(!cur||!me||chatKey(cur)!==chatKey(me))return;renderMsgs(loaded);painted=true;older.hidden=!hasMore;latest.hidden=!historyWindow;}
  function applyMeta(j){if(!cur)return;chatReadError='';updateConnection();cur.status=j.status||cur.status;cur.title=j.title||cur.title;$('cvTitle').textContent=cur.title;$('cvMeta').textContent=(cur.app==='deepseek'?'DeepSeek':cur.app==='codex'?'Codex':'Claude')+(cur.folder?' · '+cur.folder:'')+' · '+(STATUS[cur.status]||'');if(j.runtime!==undefined)renderRuntime(j.runtime);}
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
  async function jump(mid){const target={...cur};const j=await api('/api/chat?app='+target.app+'&id='+encodeURIComponent(target.id)+'&n=60&around='+encodeURIComponent(mid));if(!cur||chatKey(cur)!==chatKey(target))return;loaded=j.messages;cursor=j.next_cursor;hasMore=!!j.has_more;historyWindow=!!j.has_newer;render();const n=[...$('cvMsgs').children].find(n=>n.dataset.key===mid);if(n){n.scrollIntoView({block:'center'});n.animate?.([{background:'#eef2ff'},{background:'transparent'}],{duration:900});}await expandMessage(mid);}
  async function expandMessage(mid){if(!cur)return;const target={...cur},j=await api('/api/chat/message?app='+target.app+'&id='+encodeURIComponent(target.id)+'&message='+encodeURIComponent(mid));if(!cur||chatKey(cur)!==chatKey(target))return;expanded.set(mid,j);merge([j]);render();}
  function publicText(text){let fence=false;return text.split('\n').filter(line=>{if(/^\s*```/.test(line)){fence=!fence;return true;}return fence||!/^::created-thread\{/.test(line.trim());}).join('\n').replace(/<\/?proposed_plan>/g,'').trim();}
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
  function execCopy(text){  // the old way, for a page not on https (no clipboard API there)
    const t=el('textarea');t.value=text;t.readOnly=true;t.style.cssText='position:fixed;left:0;top:0;width:1px;height:1px;opacity:0';
    (overlays.length?$(overlays.at(-1).id):$('convView')).append(t);let ok=false;try{t.select();t.setSelectionRange(0,text.length);ok=document.execCommand('copy');}catch(e){}t.remove();return ok;
  }
  function decorateMessage(node,m){
    const f=flows.get(node.dataset.key),running=!!f&&f.shown<f.text.length;if(f)f.node=node;
    if(pick?.b===node)node.classList.add('picked');  // redrawn while its menu is open
    if(m.role==='user'&&m.truncated){const actions=el('div','message-actions'),expand=el('button','','展开全文（'+m.length+' 字）');expand.onclick=()=>expandMessage(m.id).catch(e=>toast(e.message,true));actions.append(expand);node.append(actions);return;}
    if(m.role!=='assistant'||m.phase==='commentary')return;
    const actions=el('div','message-actions'),copy=el('button','','复制正文');copy.onclick=()=>copyText(m.truncated&&!m.streaming?api('/api/chat/message?app='+cur.app+'&id='+encodeURIComponent(cur.id)+'&message='+encodeURIComponent(m.id)).then(full=>publicText(full.text)):publicText(m.text));actions.append(copy);
    if(m.truncated){const expand=el('button','',m.streaming?'生成中，完成后可展开':'展开全文（'+m.length+' 字）');expand.disabled=!!m.streaming;expand.onclick=()=>expandMessage(m.id).catch(e=>toast(e.message,true));actions.append(expand);}
    node.append(actions);
    if(running)return;  // code blocks get their copy button once the reply has run out: its words are rewritten till then
    node.querySelectorAll('pre').forEach(pre=>{const code=pre.textContent,wrap=el('div','code-wrap'),b=el('button','code-copy','复制代码');b.onclick=()=>copyText(code);pre.before(wrap);wrap.append(b,pre);});
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
      const after=onScreen(f);if(after!==before){words.innerHTML=md(assistantMarkdown(after).markdown);moved=true;}
      if(f.shown<f.text.length)going=true;else{f.tick=0;if(!f.streaming)ended.push(f);}
    }
    if(moved&&atEnd)box.scrollTop=box.scrollHeight;
    // run out: drawn once more as a whole (copy buttons on code, the conversations it created)
    if(ended.length&&cur&&box.dataset.ready){for(const f of ended)delete f.node.dataset.sig;renderMsgs(currentMessages);}
    if(going)wake();
  }
  // Words being picked out of a message stay as they are till they are let go: a redraw (each update of a reply still being
  // written, each frame of its run-out) would drop them. renderMsgs asks before it redraws a message.
  let heldBack=false;
  function holding(n){const s=getSelection?.();if(!n||!s||s.isCollapsed||!s.rangeCount||!s.getRangeAt(0).intersectsNode(n))return false;heldBack=true;return true;}
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
    const c=b.cloneNode(true);c.querySelectorAll('.send-receipt,.outbox-state,.message-actions,.outbox-refs,.sent-images,.message-origin,.code-copy,.thread-link').forEach(n=>n.remove());return c.textContent.trim();
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
  async function checkFile(target,file){return api('/api/file/meta?app='+target.app+'&id='+encodeURIComponent(target.id)+'&file='+file.id);}
  async function download(target,file){try{await checkFile(target,file);workspaceUI?.saveScene();location.assign(fileUrl(target,file,'&download=1'));}catch(e){toast(e.message,true);}}
  async function preview(target,file){try{await checkFile(target,file);previewBody.innerHTML='';previewBody.append(el('div','hint',file.name));
      if(file.kind==='text'){const data=await api('/api/file/text?app='+target.app+'&id='+encodeURIComponent(target.id)+'&file='+file.id);previewBody.append(el('pre','text-preview',data.text));}
      else if(file.kind==='image'){const img=el('img');img.src=fileUrl(target,file);img.alt=file.name;img.style.maxWidth='100%';previewBody.append(img);}
      else{const iframe=el('iframe','file-preview');iframe.title=file.name;iframe.src=fileUrl(target,file);previewBody.append(iframe);}
      const b=el('button','','下载原文件');b.onclick=()=>download(target,file);previewBody.append(b);openSheet('resultPreview');
    }catch(e){toast(e.message,true);}}
  async function openFiles(){if(!cur)return;const target={...cur};fileBody.textContent='正在读取文件…';openSheet('conversationFiles');try{const j=await api('/api/chat/files?app='+target.app+'&id='+encodeURIComponent(target.id));fileBody.innerHTML='';for(const f of j.items){const row=el('div','file-row',f.name);row.append(el('div','hint',Math.ceil(f.size/1024)+' KB · '+stamp(f.modified)));const actions=el('div','file-actions');if(f.kind!=='download'){const b=el('button','','预览');b.onclick=()=>preview(target,f);actions.append(b);}const d=el('button','','下载');d.onclick=()=>download(target,f);actions.append(d);row.append(actions);fileBody.append(row);}if(!j.items.length)fileBody.append(el('div','hint','尚未找到允许目录内的本地文件链接。'));fileBody.append(el('div','hint',j.scope));}catch(e){fileBody.textContent='读取失败：'+e.message;}}
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
    if(source||!cur||document.hidden||window.workspaceUI?.paused)return;const target={...cur},generation=++streamGeneration;const s=new EventSource('/api/events?app='+target.app+'&id='+encodeURIComponent(target.id));source=s;streamSeq=0;
    s.addEventListener('update',e=>{if(generation!==streamGeneration||!cur||chatKey(cur)!==chatKey(target))return;try{const data=JSON.parse(e.data);if(data.protocol!==1)throw Error('protocol');if(data.type!=='snapshot'&&data.seq!==streamSeq+1)throw Error('sequence');streamSeq=data.seq;streamActive=true;if(window.workspaceUI?.composing){bufferedEvent=data;return;}applyEvent(data);}catch(err){pauseStream();retryTimer=setTimeout(()=>{loadConversation(false);resumeStream();},3000);}});
    s.onerror=()=>{if(generation!==streamGeneration)return;pauseStream();retryTimer=setTimeout(resumeStream,target.app==='deepseek'?1000:8000);};
  }
  $('cvText').addEventListener('compositionend',()=>{if(bufferedEvent){bufferedEvent=null;pauseStream();resumeStream();}});
  $('newMessages').onclick=()=>{if(historyWindow)loadConversation(true);else jumpToLatest();};
  // hidden: what was running out is shown whole; back on screen, what came meanwhile shows as it is
  document.addEventListener('visibilitychange',()=>{if(document.hidden){pauseStream();settleFlows();}else{quietUntil=performance.now()+2000;if(!window.workspaceUI?.paused)resumeStream();}});
  window.readingUI={loadList,onOpen,loadConversation,decorateMessage,decorateRows(){},flowText,holding,closeMenu,pauseStream,resumeStream,get streamActive(){return streamActive;},get historyWindow(){return historyWindow;}};
  if(cur){onOpen({},cur);loadConversation(true);}else loadList(false,true);
})();
