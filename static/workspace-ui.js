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
    const values=[...outbox.values()],done=values.filter(v=>v.state==='delivered').sort((a,b)=>b.started-a.started).slice(0,60),open=values.filter(v=>v.state!=='delivered');
    localStorage.setItem(outboxKey,JSON.stringify([...done,...open]));
  }
  const css=el('style');css.textContent=`.bub.user.outbox .outbox-state{display:block;margin-top:4px;font-size:12px;opacity:.8}.bub.user.outbox .outbox-refs{font-size:12px;opacity:.8;margin-top:4px}.bub.user.outbox.problem{background:#fff;color:var(--text);border:1px solid #fca5a5}.bub.user.outbox.problem button.outbox-state{border:0;background:transparent;padding:0;min-height:28px;color:var(--red);font-size:13px;font-weight:500;opacity:1;text-align:left}.bub.user.outbox .message-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}.bub.user.outbox.problem .message-actions button{border:0;border-radius:999px;background:var(--bg);color:var(--text);padding:6px 14px;min-height:36px;font-size:13px;font-weight:500}.bub.user.outbox.problem .message-actions button.outbox-replace{background:#eef2ff;color:var(--blue)}.bub.user.outbox .outbox-why{flex-basis:100%;font-size:12px;line-height:1.5;color:var(--muted);white-space:normal}.input-test-bar{padding:8px 12px;font-size:12px;background:#fff7ed;color:#92400e}.input-test-bar a{color:inherit}.diagnostic-events{max-height:50dvh;overflow:auto;font:12px/1.5 ui-monospace,monospace;white-space:pre-wrap}`;document.head.append(css);
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
    const item={rid,app:me.app,id:me.id,started:ticket.started,state:'sending',note:ticket.note,text:ticket.text,originalText:extra.originalText??input.value,transport:extra.transport||'legacy',body:extra.body||null,images:extra.images||[],settings:extra.settings||null,base:extra.base||null,references:extra.references||[]};
    outbox.set(rid,item);try{saveOutbox();}catch(e){outbox.delete(rid);throw Error('无法保存发送副本，未发送。请释放浏览器存储空间后重试');}
    if(!extra.plan){input.value='';editVersion++;writeDraft(me,'');window.referencesUI?.clear(me);autoGrow();updateSendButton();}
    saveScene();return item;
  }
  function update(me,ticket){const rid=ticket.request_id||ticket.rid,item=outbox.get(rid);if(!item)return;Object.assign(item,{state:ticket.state,note:ticket.note,offset:ticket.offset,check_text:ticket.check_text,draft:ticket.draft||null});try{saveOutbox();}catch(e){}if(cur&&chatKey(cur)===chatKey(me)){renderMsgs(currentMessages);window.claudeUI?.renderQueue?.();}}
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
    if(['codex','claude'].includes(item.app))await codexUI.restoreSubmission(item);
    updateSendButton();input.focus();
  }
  function decorateRows(rows){
    if(!cur)return;
    for(let i=rows.length-1;i>=0;i--)if(rows[i].key?.startsWith('pending:'))rows.splice(i,1);
    for(const item of outbox.values()){
      if(item.app!==cur.app||item.id!==cur.id)continue;
      const matched=rows.some(r=>r.message?.client_request_id===item.rid || (item.app!=='codex'&&item.transport==='legacy'&&r.message?.role==='user'&&r.message.text?.trim()===(item.check_text||item.text)?.trim()&&Math.abs(new Date(r.message.time).getTime()-item.started)<120000));
      if(matched){if(item.state!=='delivered'){item.state='delivered';item.note='已确认送达';try{saveOutbox();}catch(e){}}continue;}
      // delivered: the conversation itself shows it; queued: shown above the input box (claude-ui.js)
      if(item.state==='delivered'||item.state==='queued'&&item.app!=='codex')continue;
      rows.push({key:'outbox:'+item.rid,workspace:{...item,body:undefined},created:item.started/1000});
    }
  }
  // A message sent from the phone looks like any other message: faded while it is on its way. Only a
  // problem adds a line, and tapping that line shows what can be done about it.
  function renderOutbox(node,item){
    const waiting=['sending','pressed'].includes(item.state),problem=!waiting;
    node.className='bub user outbox'+(waiting?' pending':' problem');node.replaceChildren();
    node.append(document.createTextNode(item.originalText||item.text||''));
    if(item.images?.length)codexUI?.renderImages(node,item.images.map(v=>v.meta).filter(Boolean));
    if(item.references?.length)node.append(el('div','outbox-refs',item.references.map(v=>(v.kind==='skill'?'$':'@')+(v.name||v.title)).join(' · ')));
    if(waiting){node.append(el('span','outbox-state','发送中…'));return;}
    const state=el('button','outbox-state',item.app==='codex'?(item.transport==='legacy'?'旧记录待核对 ›':({rejected:'未提交 ›',queued:'已排队 ›',cancelled:'已取消 ›'}[item.state]||'结果待核对 ›')):(item.state==='rejected'?'没发出去 ›':'没确认送达 ›')),actions=el('div','message-actions');actions.hidden=true;
    state.setAttribute('aria-expanded','false');state.onclick=()=>{actions.hidden=!actions.hidden;state.setAttribute('aria-expanded',String(!actions.hidden));};
    if(!['rejected','cancelled'].includes(item.state)){const check=el('button','','重新核对');check.onclick=async()=>{check.disabled=true;const result=await pollReceipts(item.rid);const latest=outbox.get(item.rid);if(!latest)return;toast(latest.state==='delivered'?'已送达':result?.errors?'暂时连不上电脑':latest.state==='queued'?'还在排队':'还没确认；不会自动重发',!!result?.errors);if(check.isConnected)check.disabled=false;};actions.append(check);}
    else if(item.note)actions.append(el('div','outbox-why',item.note)); // why it was not sent: the toast is gone by the time one looks
    if(item.state==='rejected'&&item.draft){const shown=item.draft.length>8?item.draft.slice(0,8)+'…':item.draft,swap=el('button','outbox-replace','换掉电脑上的「'+shown+'」再发');swap.onclick=()=>resendReplacing(outbox.get(item.rid));actions.append(swap);}
    if(item.note)actions.append(el('div','outbox-why',item.note));
    const back=el('button','','恢复草稿');back.onclick=()=>{const latest=outbox.get(item.rid);if(latest)restore(latest);};
    const remove=el('button','','移除');remove.onclick=()=>dismiss(outbox.get(item.rid));
    actions.append(back,remove);node.append(state,actions);
  }
  function queued(me){return [...outbox.values()].filter(v=>v.app===me?.app&&v.id===me?.id&&v.state==='queued').map(v=>({rid:v.rid,text:v.originalText||v.text||''}));}
  async function pollReceipts(onlyRid=null){
    if(pollingOutbox||document.hidden||composing||testMode==='pause'||!cur)return;pollingOutbox=true;const me={...cur};
    let errors=0;try{for(const item of [...outbox.values()].filter(v=>v.id===me.id&&v.app===me.app&&(!onlyRid||v.rid===onlyRid)&&['unconfirmed','pressed','queued'].includes(v.state)).slice(-8)){
      try{let delivered=false;
        if(item.transport==='codex'){const r=await api('/api/codex/receipt?id='+encodeURIComponent(item.id)+'&request_id='+item.rid);delivered=r.state==='accepted';if(['queued','cancelled','rejected'].includes(r.state)){item.state=r.state;item.note=r.result?.text||r.state;}}
        else if(item.app!=='codex'&&item.offset!=null){const r=await api('/api/chat/check',{app:item.app,id:item.id,offset:item.offset,text:item.check_text||item.text});delivered=r.delivered;if(r.queued){item.state='queued';item.note='已进入 Claude 队列，等待读取';}}
        if(delivered){item.state='delivered';item.note=item.app==='codex'?'已交给 Codex':'已确认送达';const ticket=pendingSends.get(item.app+':'+item.id);if((ticket?.request_id||ticket?.rid)===item.rid){ticket.state='delivered';ticket.note=item.note;persistPending();}}
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
  window.workspaceUI={get composing(){return composing;},get version(){return editVersion;},capture,update,decorateRows,renderOutbox,pollReceipts,saveScene,diagnostics,queued,dismissRid(rid){return dismiss(outbox.get(rid));},
    canPoll(){return !document.hidden&&!composing&&testMode!=='pause';},get paused(){return testMode==='pause';}};
  // Migrate the previous single pending entry without inventing delivery success.
  for(const [key,ticket] of pendingSends){const [app,...parts]=key.split(':'),id=parts.join(':'),rid=ticket.request_id||ticket.rid;if(dismissed.has(rid)){pendingSends.delete(key);continue;}if(rid&&!outbox.has(rid)&&ticket.state!=='delivered')outbox.set(rid,{...ticket,rid,app,id,transport:ticket.request_id?'codex':'legacy',images:[],body:ticket.submission||null});}persistPending();
  try{saveOutbox();}catch(e){}if(document.readyState==='complete')restoreScene();else window.addEventListener('load',restoreScene,{once:true});
  setInterval(pollReceipts,4000);
})();
