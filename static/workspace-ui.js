/* Input sessions and durable outbox. Network callbacks never edit the composer. */
(() => {
  const INPUT_VERSION='0.9.0',input=$('cvText');
  let composing=false,editVersion=0,pollingOutbox=false,restoring=false;
  const testMode=new URLSearchParams(location.search).get('input_test');
  const outboxKey='lbr_outbox_v1',sceneKey='lbr_scene_v1',dismissedKey='lbr_outbox_dismissed_v1';
  function read(key,def){try{return JSON.parse(localStorage.getItem(key))??def;}catch(e){return def;}}
  const dismissed=new Set(read(dismissedKey,[])||[]);
  const outbox=new Map((read(outboxKey,[])||[]).filter(v=>!dismissed.has(v.rid)).map(v=>[v.rid,v]));
  for(const item of outbox.values())if(item.state==='sending'||item.state==='pressed'){item.state='unconfirmed';item.note='正在核对上次发送结果';}
  function saveOutbox(){
    localStorage.setItem(outboxKey,JSON.stringify([...outbox.values()]));
  }
  const css=el('style');css.textContent=`.bub.user.outbox{transform-origin:100% 100%}.bub.user.outbox .outbox-refs{font-size:12px;opacity:.8;margin-top:4px}.bub.user.has-receipt{position:relative;margin-bottom:38px}.bub.user .send-receipt{position:absolute;right:6px;top:100%;margin-top:5px;font-size:12px;line-height:16px;font-weight:400;color:var(--muted);white-space:nowrap;pointer-events:none;-webkit-user-select:none;user-select:none}.bub.user .send-receipt.sending{animation:sendPulse 1.4s ease-in-out infinite}.bub.user .send-receipt.done::before{content:'✓ '}@keyframes sendPulse{50%{opacity:.35}}.bub.user.outbox.problem{position:relative}.bub.user.outbox.problem::before{content:'!';position:absolute;left:-30px;top:50%;margin-top:-10px;width:20px;height:20px;border-radius:50%;background:var(--red);color:#fff;font:700 13px/20px -apple-system,sans-serif;text-align:center}.bub.user.outbox.problem button.outbox-state{display:block;border:0;background:transparent;padding:0;margin-top:6px;min-height:28px;color:inherit;font-size:13px;font-weight:600;text-align:left}.bub.user.outbox .message-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}.bub.user.outbox.problem .message-actions button{border:0;border-radius:999px;background:rgba(255,255,255,.22);color:#fff;padding:6px 14px;min-height:36px;font-size:13px;font-weight:500}.bub.user.outbox.problem .message-actions button.outbox-replace{background:#fff;color:var(--blue)}.bub.user.outbox .outbox-why{flex-basis:100%;font-size:12px;line-height:1.5;opacity:.85;white-space:normal}.input-test-bar{padding:8px 12px;font-size:12px;background:#fff7ed;color:#92400e}.input-test-bar a{color:inherit}.diagnostic-events{max-height:50dvh;overflow:auto;font:12px/1.5 ui-monospace,monospace;white-space:pre-wrap}`;document.head.append(css);
  const events=[];
  function logEvent(e){if(!testMode)return;const vv=window.visualViewport;events.push({time:Math.round(performance.now()),event:e.type,inputType:e.inputType||null,composing,version:editVersion,focused:document.activeElement?.id||document.activeElement?.tagName,length:input.value.length,selection:[input.selectionStart,input.selectionEnd],visible:document.visibilityState,viewport:vv?{height:vv.height,top:vv.offsetTop,scale:vv.scale}:null});if(events.length>300)events.shift();}
  function saveScene(){
    if(restoring)return;
    clearTimeout(input._d);saveDraft();window.codexUI?.saveCurrentDraft();
    const box=$('cvMsgs'),top=box.getBoundingClientRect().top,anchor=[...box.children].find(n=>n.getBoundingClientRect().bottom>top);
    const scene={version:1,mode,conv:cur?{app:cur.app,id:cur.id,title:cur.title,folder:cur.folder,status:cur.status}:null,
      pageScroll:scrollY,scroll:box.scrollTop,anchor:anchor?.dataset.key||null,anchorOffset:anchor?anchor.getBoundingClientRect().top-top:0,selection:[input.selectionStart,input.selectionEnd],saved:Date.now()};
    try{localStorage.setItem(sceneKey,JSON.stringify(scene));saveOutbox();}catch(e){}
  }
  input.addEventListener('compositionstart',e=>{composing=true;editVersion++;logEvent(e);updateSendButton();});
  input.addEventListener('compositionend',e=>{composing=false;editVersion++;saveDraft();logEvent(e);updateSendButton();});
  input.addEventListener('beforeinput',e=>{editVersion++;logEvent(e);});
  input.addEventListener('input',e=>{editVersion++;clearTimeout(input._d);saveDraft();logEvent(e);});
  input.addEventListener('focus',logEvent);input.addEventListener('blur',e=>{composing=false;saveDraft();logEvent(e);updateSendButton();});
  ['pagehide','pageshow','blur','focus'].forEach(name=>window.addEventListener(name,e=>{logEvent(e);if(name==='pagehide')saveScene();else if(name==='pageshow'){fitView();fitOverlays();}}));
  document.addEventListener('visibilitychange',e=>{logEvent(e);if(document.hidden){saveScene();window.readingUI?.pauseStream();}else{fitView();fitOverlays();if(!composing&&!testMode){window.readingUI?.resumeStream();pollReceipts();}}});
  if(window.visualViewport){visualViewport.addEventListener('resize',logEvent);visualViewport.addEventListener('scroll',logEvent);}
  let sceneTimer; $('cvMsgs').addEventListener('scroll',()=>{clearTimeout(sceneTimer);sceneTimer=setTimeout(saveScene,200);},{passive:true});
  function capture(me,ticket,extra={}){
    if(composing)throw Error('请先完成当前输入');
    const rid=ticket.request_id||ticket.rid||('legacy-'+Date.now()+'-'+Math.random().toString(36).slice(2));ticket.rid=rid;
    const item={position_version:2,rid,app:me.app,id:me.id,started:ticket.started,state:'sending',note:ticket.note,text:ticket.text,originalText:extra.originalText??input.value,transport:extra.transport||'legacy',body:extra.body||null,images:extra.images||[],settings:extra.settings||null,base:extra.base||null,references:extra.references||[]};
    const tail=[...$('cvMsgs').children].filter(n=>!['empty','notice'].includes(n.dataset.key)).at(-1);item.predecessor=tail?._activity?.items.at(-1)?.id||tail?.dataset.key||currentMessages.at(-1)?.id||null;
    outbox.set(rid,item);try{saveOutbox();}catch(e){outbox.delete(rid);throw Error('无法保存发送副本，未发送。请释放浏览器存储空间后重试');}
    if(!extra.plan){input.value='';editVersion++;writeDraft(me,'');window.referencesUI?.clear(me);autoGrow();updateSendButton();}
    // The caller draws the bubble next: it springs up out of the send button's corner while the list glides up to it,
    // as WhatsApp's and iMessage's do (10-22). The list used to jump.
    // (a microtask: it runs once the caller has drawn the bubble, before the frame is painted)
    justSent.set(rid,performance.now());const box=$('cvMsgs'),from=box.scrollTop;
    queueMicrotask(()=>{if(cur&&chatKey(cur)===chatKey(me))glide(box,from);});
    saveScene();return item;
  }
  const justSent=new Map(),still=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
  function pop(node){if(still()||!node.animate)return;node.animate([{opacity:0,transform:'translateY(24px) scale(.78)'},{opacity:1,offset:.3},{opacity:1,transform:'none'}],{duration:460,easing:'cubic-bezier(.2,1.3,.32,1)'});}
  let gliding=0;$('cvMsgs').addEventListener('touchstart',()=>{gliding=0;},{passive:true});  // a finger takes over
  function glide(box,from){
    const end=()=>box.scrollHeight-box.clientHeight;
    if(still()||end()-from>box.clientHeight*1.5||end()<=from+1){jumpToLatest();return;}  // from far up: straight there
    const id=++gliding,start=performance.now();box.scrollTop=from;
    const step=now=>{if(gliding!==id)return;const t=Math.min(1,Math.max(0,now-start)/320);
      box.scrollTop=Math.max(box.scrollTop,Math.round(from+(end()-from)*(1-Math.pow(1-t,3))));  // never back up: a redraw may be at the end already
      if(t<1)requestAnimationFrame(step);else{gliding=0;jumpToLatest();}};
    requestAnimationFrame(step);
  }
  // receivedAt: when the PC confirmed it; the bubble stands in until the conversation's own copy of it comes
  function received(item){if(item.state==='delivered'&&!item.receivedAt){item.receivedAt=Date.now();if(item.body?.intent==='queue')item.predecessor=currentMessages.at(-1)?.id||item.predecessor;}}
  function update(me,ticket){const rid=ticket.request_id||ticket.rid,item=outbox.get(rid);if(!item)return;Object.assign(item,{state:ticket.state,note:ticket.note,offset:ticket.offset,check_text:ticket.check_text,draft:ticket.draft||null});received(item);try{saveOutbox();}catch(e){}if(cur&&chatKey(cur)===chatKey(me)){renderMsgs(currentMessages);window.claudeUI?.renderQueue?.();}}
  // Text sitting in Claude's box on the PC turned this message away (10-12: an "e" typed there). Send it again, replacing
  // exactly that text: the card goes, the message comes back as it was (text, pictures, references) and is sent at once.
  async function resendReplacing(item){
    if(!item?.draft||composing)return;
    await restore(item);
    if(!cur||chatKey(cur)!==item.app+':'+item.id||input.value!==(item.originalText??item.text??''))return; // a newer draft was there
    dismissed.add(item.rid);try{localStorage.setItem(dismissedKey,JSON.stringify([...dismissed]));}catch(e){}
    outbox.delete(item.rid);try{saveOutbox();}catch(e){}
    const key=item.app+':'+item.id,ticket=pendingSends.get(key);if((ticket?.request_id||ticket?.rid)===item.rid){pendingSends.delete(key);persistPending();}
    sendReplacing(cur,item.draft);
  }
  async function dismiss(item){
    if(!item||item.state==='sending')return;
    const accepted=await askConfirm('移除这条记录？电脑上已经收到的消息不受影响。');if(!accepted)return;
    dismissed.add(item.rid);try{localStorage.setItem(dismissedKey,JSON.stringify([...dismissed]));}catch(e){dismissed.delete(item.rid);toast('保存失败，记录未移除',true);return;}
    outbox.delete(item.rid);try{saveOutbox();}catch(e){}
    const key=item.app+':'+item.id,ticket=pendingSends.get(key);if((ticket?.request_id||ticket?.rid)===item.rid){pendingSends.delete(key);persistPending();if(cur&&chatKey(cur)===key)hideNote();}
    if(cur&&chatKey(cur)===key){renderMsgs(currentMessages);window.claudeUI?.renderQueue?.();}toast('已移除');
  }
  async function restore(item){
    if(composing){toast('请先完成当前输入',true);return;}
    if(!cur||chatKey(cur)!==item.app+':'+item.id){const c=await api('/api/chat?app='+item.app+'&id='+encodeURIComponent(item.id));openConv(c);}
    const hasText=!!input.value.trim(),hasImages=window.codexUI?.attachmentCount()>0;
    if(hasText||hasImages||window.referencesUI?.count()){toast('当前有新草稿，请先处理；发送副本仍保留在卡片中',true);return;}
    input.value=item.originalText??item.text??'';editVersion++;saveDraft();autoGrow();
    if(item.references?.length)referencesUI.restore(cur,item.references);
    if(['codex','claude','deepseek'].includes(item.app))await codexUI.restoreSubmission(item);
    updateSendButton();input.focus();
  }
  // Only transport/source identity maps an outbox entry to a transcript row.
  function sameMessage(m,item){return window.messageProjection.matches(m,item);}
  // What the line under the bubble says; null: a problem, said in the bubble with what can be done about it (10-22).
  // Every message sent from here is the blue bubble at once and only this line changes. Before, it was pale on its way,
  // turned into a white box framed in red when the PC had not confirmed it within 25 s or the page had reloaded meanwhile,
  // and once confirmed it went until the conversation's own copy came: a gap, as if it appeared only when the PC had it.
  const GRACE=120000,LONG_QUEUE=1800000;  // still unconfirmed, or queued, this long after it was sent: it needs a look
  function line(item){
    if(item.state==='delivered')return {k:'done',text:'电脑已接收'};
    if(item.state==='queued'&&Date.now()-item.started<LONG_QUEUE)return {k:'queued',text:'已排队，这一轮结束后发出'};
    if(item.state==='sending'||item.state==='pressed')return {k:'sending',text:'发送中…'};
    if(item.state==='unconfirmed'&&Date.now()-item.started<GRACE)return {k:'sending',text:'确认中…'};
    return null;
  }
  function observations(){return [...outbox.values()].filter(v=>v.app===cur?.app&&v.id===cur?.id).sort((a,b)=>a.started-b.started).map(v=>({...v,line:line(v)}));}
  function acceptSource(rid,message){const item=outbox.get(rid);if(!item)return;if(item.recorded&&item.source_id===message.id)return;item.recorded=true;item.source_id=message.id;item.state='delivered';received(item);try{saveOutbox();}catch{}}
  let resolving=false,lastResolution=0;
  async function resolveLocations(){
    if(resolving||!cur||composing||document.hidden)return;const me={...cur};const pending=observations().filter(v=>!v.recorded&&!['rejected','cancelled'].includes(v.state));if(!pending.length)return;
    resolving=true;try{for(let start=0;start<pending.length;start+=100){const result=await api('/api/chat/resolve',{app:me.app,id:me.id,request_ids:pending.slice(start,start+100).map(v=>v.rid)});
      for(const match of result.items||[]){const item=outbox.get(match.request_id);if(!item||item.id!==me.id||item.app!==me.app)continue;item.resolution=match;if(match.status==='recorded'){item.recorded=true;item.source_id=match.message_id;item.state='delivered';received(item);}}
    }saveOutbox();if(cur&&chatKey(cur)===chatKey(me))renderMsgs(currentMessages);
    }catch{}finally{resolving=false;lastResolution=Date.now();}
  }
  let unresolved=[];
  const unresolvedButton=el('button','menu-row','待核对发送记录');unresolvedButton.hidden=true;
  $('convMenu').querySelector('.sh-body').append(unresolvedButton);
  function setUnresolved(items){unresolved=items;unresolvedButton.hidden=!items.length;unresolvedButton.textContent='待核对发送记录（'+items.length+'）';if(Date.now()-lastResolution>4000)queueMicrotask(resolveLocations);}
  unresolvedButton.onclick=()=>{dismissOverlays();let sheet=$('unresolvedSends');if(!sheet){sheet=el('div','sheet');sheet.id='unresolvedSends';sheet.innerHTML='<div class="box"><div class="sh-head"><b>待核对发送记录</b><button class="tp-icon-button" aria-label="关闭">'+icon('close')+'</button></div><div class="sh-body"></div></div>';sheet.querySelector('button').onclick=()=>closeSheet(sheet.id);document.body.append(sheet);}const body=sheet.querySelector('.sh-body');body.replaceChildren(el('p','hint','这些记录缺少可靠的来源位置，暂不插入对话。原内容和草稿仍保留，不会自动重发。'));for(const item of unresolved){const row=el('div','unresolved-send');row.append(el('p','',item.originalText||item.text||'图片或引用消息'));const check=el('button','tp-button','重新核对');check.onclick=async()=>{await resolveLocations();if(!unresolved.some(v=>v.rid===item.rid))row.remove();};const back=el('button','tp-button','恢复草稿');back.onclick=()=>restore(outbox.get(item.rid));row.append(check,back);body.append(row);}openSheet(sheet.id);};
  function paintReceipt(node,said){node.classList.add('has-receipt');node.append(el('span','send-receipt '+said.k,said.text));}
  function renderOutbox(node,item){
    const sent=justSent.get(item.rid);justSent.delete(item.rid);if(performance.now()-sent<1500)queueMicrotask(()=>pop(node));  // drawn for the first time, just sent (and by then in the page)
    node.className='bub user outbox'+(item.line?'':' problem');node.replaceChildren();
    node.append(document.createTextNode(item.originalText||item.text||''));
    if(item.images?.length)codexUI?.renderImages(node,item.images.map(v=>v.meta).filter(Boolean));
    if(item.references?.length)node.append(el('div','outbox-refs',item.references.map(v=>window.filesUI?.isFile(v)?filesUI.label(v):(v.kind==='skill'?'$':'@')+(v.name||v.title)).join(' · ')));
    if(item.line){paintReceipt(node,item.line);return;}
    // a problem: the bubble says it, and tapping that shows what can be done about it
    const state=el('button','outbox-state',item.app==='codex'?(item.transport==='legacy'?'旧记录待核对 ›':({rejected:'未提交 ›',queued:'已排队 ›',cancelled:'已取消 ›'}[item.state]||'结果待核对 ›')):({rejected:'没发出去 ›',queued:'已排队 ›'}[item.state]||'没确认送达 ›')),actions=el('div','message-actions');actions.hidden=true;
    state.setAttribute('aria-expanded','false');state.onclick=()=>{actions.hidden=!actions.hidden;state.setAttribute('aria-expanded',String(!actions.hidden));};
    const why=()=>{if(item.note)actions.append(el('div','outbox-why',item.note));};  // the toast is gone by the time one looks
    if(!['rejected','cancelled'].includes(item.state)){const check=el('button','','重新核对');check.onclick=async()=>{check.disabled=true;const result=await pollReceipts(item.rid);const latest=outbox.get(item.rid);if(!latest)return;toast(latest.state==='delivered'?'已送达':result?.errors?'暂时连不上电脑':latest.state==='queued'?'还在排队':'还没确认；不会自动重发',!!result?.errors);if(check.isConnected)check.disabled=false;};actions.append(check);why();}
    else{why();if(item.state==='rejected'&&item.draft){const shown=item.draft.length>8?item.draft.slice(0,8)+'…':item.draft,swap=el('button','outbox-replace','换掉电脑上的「'+shown+'」再发');swap.onclick=()=>resendReplacing(outbox.get(item.rid));actions.append(swap);}}
    const back=el('button','','恢复草稿');back.onclick=()=>{const latest=outbox.get(item.rid);if(latest)restore(latest);};
    const remove=el('button','','移除');remove.onclick=()=>dismiss(outbox.get(item.rid));
    actions.append(back,remove);node.append(state,actions);
  }
  function pendingQueue(me){return [...outbox.values()].filter(v=>v.app===me?.app&&v.id===me?.id&&v.body?.intent==='queue'&&['sending','queued','unconfirmed'].includes(v.state)).map(v=>({id:v.rid,text:v.originalText||v.text||'',status:v.state,local:true}));}
  function editableQueue(me,id){const item=outbox.get(id);return !!item&&item.app===me?.app&&item.id===me?.id&&!!item.body;}
  function draftOccupied(){return composing||!!input.value.trim()||!!window.codexUI?.attachmentCount()||!!window.referencesUI?.count();}
  async function editQueued(me,id,cancel){
    const item=outbox.get(id);if(!editableQueue(me,id)){toast('这条消息没有完整的手机草稿，请在电脑端编辑',true);return;}
    if(draftOccupied()){toast('输入框已有草稿，请先处理；排队消息未改变',true);return;}
    const version=editVersion;
    if(!await cancel())return;
    item.state='cancelled';item.note='已移出队列';
    if(!cur||chatKey(cur)!==chatKey(me)||editVersion!==version||draftOccupied()){
      item.state='rejected';item.note='已移出队列；输入框有新内容，原稿保留在此，可恢复草稿';
    }else{await restore(item);}
    try{saveOutbox();}catch(e){}if(cur&&chatKey(cur)===chatKey(me))renderMsgs(currentMessages);
  }
  function queueMenu(me,q,cancel){
    let panel=$('queueActionsSheet');if(!panel){panel=el('div','sheet dialog-sheet');panel.id='queueActionsSheet';panel.innerHTML='<div class="box"><div class="sh-head"><b>待发送消息</b><button class="icon-btn" aria-label="关闭">×</button></div><div class="sh-body"></div></div>';panel.querySelector('button').onclick=()=>closeSheet(panel.id);document.body.append(panel);}
    const body=panel.querySelector('.sh-body');body.replaceChildren();
    const edit=el('button','menu-row','编辑草稿'),remove=el('button','menu-row danger','删除');edit.type=remove.type='button';
    edit.disabled=!editableQueue(me,q.id);if(edit.disabled)edit.title='这条消息没有完整的手机草稿，请在电脑端编辑';
    edit.onclick=()=>{closeSheet(panel.id);editQueued(me,q.id,cancel);};remove.onclick=()=>{closeSheet(panel.id);cancel();};body.append(edit,remove);openSheet(panel.id);
  }
  function queued(me){return [...outbox.values()].filter(v=>v.app===me?.app&&v.id===me?.id&&v.state==='queued').map(v=>({rid:v.rid,text:v.originalText||v.text||''}));}
  async function pollReceipts(onlyRid=null){
    if(pollingOutbox||document.hidden||composing||testMode==='pause'||!cur)return;pollingOutbox=true;const me={...cur};
    // DeepSeek's queued ones are settled by the conversation's copy, as its receipt says accepted all the while
    let errors=0;try{for(const item of [...outbox.values()].filter(v=>v.id===me.id&&v.app===me.app&&(!onlyRid||v.rid===onlyRid)&&['unconfirmed','pressed','queued'].includes(v.state)&&!(v.transport==='deepseek'&&v.state==='queued')).slice(-8)){
      try{let delivered=false;
        if(item.transport==='codex'){const r=await api('/api/codex/receipt?id='+encodeURIComponent(item.id)+'&request_id='+item.rid);delivered=r.state==='accepted';item.client_id=r.result?.client_id||item.client_id;item.source_id=r.result?.evidence?.message_id||item.source_id;if(['queued','cancelled','rejected'].includes(r.state)){item.state=r.state;item.note=r.result?.text||r.state;}}
        else if(item.transport==='deepseek'){const r=await api('/api/deepseek/receipt?request_id='+encodeURIComponent(item.rid));if(r.state==='accepted'){if(item.body?.intent!=='queue')delivered=true;else{item.state='queued';item.note='已排队';}}}
        else if(item.app!=='codex'&&item.offset!=null){const r=await api('/api/chat/check',{app:item.app,id:item.id,offset:item.offset,text:item.check_text||item.text});delivered=r.delivered;if(r.queued){item.state='queued';item.note='已进入 Claude 队列，等待读取';}}
        if(delivered){item.state='delivered';item.note=item.app==='codex'?'已交给 Codex':'已确认送达';received(item);const ticket=pendingSends.get(item.app+':'+item.id);if((ticket?.request_id||ticket?.rid)===item.rid){ticket.state='delivered';ticket.note=item.note;persistPending();}}
      }catch(e){errors++;}
    }saveOutbox();if(cur&&chatKey(cur)===chatKey(me)&&!composing){renderMsgs(currentMessages);window.claudeUI?.renderQueue?.();}return {errors};}finally{pollingOutbox=false;}
  }
  function diagnostics(){
    let panel=$('inputDiagnosticSheet');if(!panel){panel=el('div','sheet');panel.id='inputDiagnosticSheet';panel.innerHTML='<div class="box"><div class="sh-head"><b>输入诊断</b><button class="small">关闭</button></div><div class="sh-body"><p class="hint">不记录语音和正文，仅记录输入与页面事件。</p><a href="/input-diagnostics">原生输入框测试</a><a href="/?input_test=pause">聊天页 · 暂停刷新测试</a><a href="/?input_test=trace">聊天页 · 正常刷新测试</a><a href="/">退出诊断模式</a><pre class="diagnostic-events"></pre></div></div>';panel.querySelector('button').onclick=()=>closeSheet(panel.id);panel.onclick=e=>{if(e.target===panel)closeSheet(panel.id);};document.body.append(panel);}
    panel.querySelector('pre').textContent=JSON.stringify({version:INPUT_VERSION,standalone:!!navigator.standalone||matchMedia('(display-mode: standalone)').matches,userAgent:navigator.userAgent,events},null,2);openSheet(panel.id);
  }
  if(testMode){const bar=el('div','input-test-bar');bar.innerHTML=(testMode==='pause'?'输入诊断：已暂停刷新':'输入诊断：正常刷新')+' · <a href="/">退出</a>';document.querySelector('.cv-top').after(bar);}
  async function restoreScene(){
    const saved=read(sceneKey,null);if(!saved||cur)return;restoring=true;
    try{if(saved.mode==='chat')setMode(saved.mode);
      if(!saved.conv){replaceUIState();requestAnimationFrame(()=>window.scrollTo(0,saved.pageScroll||0));return;}
      if(window.newChatUI?.isPreview(saved.conv)){openConv(saved.conv,true);replaceUIState();return;}
      const c=await api('/api/chat?app='+saved.conv.app+'&id='+encodeURIComponent(saved.conv.id)+'&n=60'+(saved.anchor?'&around='+encodeURIComponent(saved.anchor):''));if(cur)return;
      scrollPositions.set(chatKey(c),saved.scroll||0);replaceUIState();openConv(c,false);await loadConv(true);
      if(cur?.id!==c.id)return;const node=[...$('cvMsgs').children].find(n=>n.dataset.key===saved.anchor);if(node)$('cvMsgs').scrollTop+=node.getBoundingClientRect().top-$('cvMsgs').getBoundingClientRect().top-(saved.anchorOffset||0);
      if(saved.selection)input.setSelectionRange(Math.min(saved.selection[0],input.value.length),Math.min(saved.selection[1],input.value.length));
    }catch(e){}finally{restoring=false;}}
  window.workspaceUI={get composing(){return composing;},get version(){return editVersion;},capture,update,observations,acceptSource,setUnresolved,resolveLocations,renderOutbox,paintReceipt,pollReceipts,saveScene,diagnostics,queued,pendingQueue,queueMenu,editQueued,editableQueue,dismissRid(rid){return dismiss(outbox.get(rid));},
    delivered(rid){return outbox.get(rid)?.state==='delivered';},
    has(rid){return outbox.has(rid)||dismissed.has(rid);},  // a send this page keeps (deepseek-ui.js: its draft has left the box)
    canPoll(){return !document.hidden&&!composing&&testMode!=='pause';},get paused(){return testMode==='pause';}};
  // Migrate the previous single pending entry without inventing delivery success.
  for(const [key,ticket] of pendingSends){const [app,...parts]=key.split(':'),id=parts.join(':'),rid=ticket.request_id||ticket.rid;if(dismissed.has(rid)){pendingSends.delete(key);continue;}if(rid&&!outbox.has(rid)&&ticket.state!=='delivered')outbox.set(rid,{...ticket,rid,app,id,transport:ticket.request_id?'codex':'legacy',images:[],body:ticket.submission||null});}persistPending();
  try{saveOutbox();}catch(e){}if(document.readyState==='complete')restoreScene();else window.addEventListener('load',restoreScene,{once:true});
  setInterval(()=>{pollReceipts();resolveLocations();},4000);
})();
