/* DeepSeek controls use the authenticated local bridge, never desktop focus.
   10-20: laid out as Codex's and Claude's are. The message box holds ＋ (pictures, conversations), the model and the
   permission (仅可查看 / 工作区内修改 / 完全权限, the Harness's own presets); 停止这一轮 sits in the title bar; while a turn
   runs, a line says ↑ adds to it, with 排队稍后发送 beside it, and the queue waits in a grey tray whose rows can be handed
   to the turn now or dropped; a question or an approval is one strip above the box that opens a sheet. Before, a row of
   bare words (图片 / 模型 / 排队发送 / 停止) stood over the box and approvals were two buttons stuck together. */
(() => {
  const active=me=>cur?.app==='deepseek'&&cur.id===me.id;
  const uid=()=>crypto.randomUUID();
  const questionDrafts=new Map();
  let state=null,busy=false,timer=null,askSig='',modelCatalog=null,asking=new Set();
  const css=el('style');css.textContent=`
    .ds-ask+.ds-ask{border-top:1px solid var(--line);margin-top:16px;padding-top:16px}
    .ds-ask h3{margin:0;font-size:16px;font-weight:600;line-height:1.5}.ds-ask .hint{margin:4px 0 0}
    .ds-tool{display:inline-block;margin-left:6px;padding:2px 8px;border-radius:999px;background:var(--bg);color:var(--muted);font-size:12px;font-weight:500;vertical-align:2px}
    .ds-reason{margin:10px 0 0;padding:10px 12px;border-radius:12px;background:var(--bg);font-size:14px;line-height:1.6;white-space:pre-wrap;overflow-wrap:anywhere;max-height:30dvh;overflow:auto}
    .ds-actions{display:flex;gap:10px;margin-top:16px}.ds-actions button{flex:1;min-height:48px;border-radius:14px;font-size:15px;font-weight:600}
    .ds-actions .ds-allow{background:var(--blue);border-color:var(--blue);color:#fff}.ds-actions .ds-reject{background:#fff;color:var(--red)}
    .ds-actions button:disabled{opacity:.5}.ds-ask textarea{box-sizing:border-box;width:100%;min-height:64px;margin-top:8px;padding:10px 12px;border:1px solid var(--line);border-radius:12px;font:inherit;font-size:16px}
    .ds-ask .option-card b{display:block;font-size:15px;font-weight:600}.ds-ask .big{margin-top:12px;width:100%}
    .composer-chip.is-full{color:#c2410c}#deepseekPermissions .option-card b{display:block;font-size:15px;font-weight:600}
    #deepseekModels .setting-heading:first-child{margin-top:0}`;document.head.append(css);
  // in the message box: ＋ (pictures and conversations), the model, the permission
  const tools=el('div','composer-tools');tools.id='deepseekComposerTools';tools.hidden=true;
  const add=el('button','icon-btn','＋'),model=el('button','composer-chip','模型'),perm=el('button','composer-chip','权限');
  add.id='deepseekAdd';model.id='deepseekModel';perm.id='deepseekPermission';
  add.setAttribute('aria-label','添加图片或引用对话');model.setAttribute('aria-label','选择 DeepSeek 模型与推理强度');perm.setAttribute('aria-label','选择 DeepSeek 权限');
  for(const b of [add,model,perm]){b.type='button';tools.append(b);}$('cvBtn').before(tools);
  add.onclick=()=>codexUI.openAttachments(add);model.onclick=()=>chooseModel();perm.onclick=()=>choosePermission();
  // the title bar: stop this turn
  const stop=el('button','stop-turn','停止这一轮');stop.id='deepseekStop';stop.type='button';stop.hidden=true;stop.setAttribute('aria-label','停止这一轮');
  document.querySelector('.cv-top .cv-title').after(stop);window.navigationUI?.tapTick?.(stop);
  // above the box while a turn runs: the queue, then what ↑ does and 排队稍后发送
  const tray=el('div','queue-strip'),runBar=el('div','run-bar'),runHint=el('span','run-hint','发送会立即补充给这一轮');
  const later=el('button','run-queue','排队稍后发送'),check=el('button','run-queue','核对待发送消息');
  tray.id='deepseekQueue';runBar.id='deepseekRun';later.id='deepseekQueueSend';later.type=check.type='button';tray.hidden=runBar.hidden=true;
  runBar.append(runHint,check,later);$('runtimeBar').before(tray,runBar);
  later.onclick=()=>send('queue');check.onclick=()=>checkPending(cur,true);
  // Subagents: the strip names how many a conversation opened; the cards in the transcript mark where.
  const subBar=el('button','run-queue');subBar.id='deepseekSubBar';subBar.type='button';subBar.hidden=true;$('runtimeBar').before(subBar);
  let subs=[];
  function panel(id,title){const n=el('div','sheet');n.id=id;n.setAttribute('aria-label',title);n.innerHTML='<div class="box"><div class="sh-head"><b></b><button class="icon-btn" aria-label="关闭">'+icon('close')+'</button></div><div class="sh-body"></div></div>';n.querySelector('b').textContent=title;n.querySelector('.sh-head button').onclick=()=>closeSheet(id);n.onclick=e=>{if(e.target===n)closeSheet(id);};document.body.append(n);return n.querySelector('.sh-body');}
  const models=panel('deepseekModels','模型与推理强度');
  const perms=panel('deepseekPermissions','权限');
  const askBody=panel('deepseekAskSheet','DeepSeek 在等你');
  const subsBody=panel('deepseekSubList','这个对话的子智能体');
  const askOpen=()=>overlays.some(o=>o.id==='deepseekAskSheet');
  stop.onclick=async()=>{const me=cur;if(!active(me)||busy)return;stop.disabled=true;stop.textContent='正在停止…';try{await api('/api/deepseek/stop',{id:me.id,expected_turn:state?.turn_id});toast('已请求停止，排队消息仍保留');}catch(e){toast(e.message,true);}finally{stop.disabled=false;stop.textContent='停止这一轮';await refresh(me);}};
  const EFFORT={off:'关',none:'关',minimal:'最低',low:'低',medium:'中',high:'高',xhigh:'很高',max:'最高'};
  const PERMISSION={'read-only':'仅可查看','workspace-write':'工作区内修改','danger-full-access':'完全权限',auto:'自动审查'};  // the Harness's own names
  function modelLabel(s){
    if(!s?.model)return '模型';let name=s.model,effort=s.reasoningEffort?EFFORT[s.reasoningEffort]||s.reasoningEffort:'';
    for(const g of modelCatalog?.groups||[])for(const m of g.models||[])if(m.id===s.model){name=m.name||m.id;effort=(m.reasoning?.efforts||[]).find(e=>e.id===s.reasoningEffort)?.name||effort;}
    return name+(effort?' · '+effort:'');
  }
  async function chooseModel(){
    const me=cur;if(!active(me))return;
    try{modelCatalog=await api('/api/deepseek/models');if(!active(me))return;models.replaceChildren();const now=state?.settings||{};
      for(const g of modelCatalog.groups||[])for(const m of g.models||[]){
        const head=el('div','setting-heading',m.name||m.id),row=el('div','effort-choices');row.setAttribute('role','radiogroup');row.setAttribute('aria-label',m.name||m.id);
        for(const effort of m.reasoning?.efforts||[{id:null,name:'默认'}]){
          const b=el('button','',effort.name);b.type='button';b.setAttribute('role','radio');
          b.setAttribute('aria-checked',String(now.model===m.id&&(effort.id==null||now.reasoningEffort===effort.id)));
          b.onclick=async()=>{for(const n of models.querySelectorAll('button'))n.disabled=true;
            try{await api('/api/deepseek/model',{id:me.id,settings:{provider:g.id,model:m.id,...(effort.id?{reasoningEffort:effort.id}:{})}});closeSheet('deepseekModels');toast('已换成 '+(m.name||m.id)+' · '+effort.name);await refresh(me);}
            catch(e){toast(e.message,true);}finally{for(const n of models.querySelectorAll('button'))n.disabled=false;}};
          row.append(b);}
        models.append(head,row);}
      models.append(el('p','settings-notice','换模型从下一步开始生效，电脑上的 DeepSeek 同步显示。'));
      openSheet('deepseekModels',model);
    }catch(e){toast(e.message,true);}
  }
  async function choosePermission(){
    const me=cur;if(!active(me))return;
    try{const j=await api('/api/deepseek/permissions?id='+encodeURIComponent(me.id));if(!active(me))return;perms.replaceChildren();
      const group=el('div');group.setAttribute('role','radiogroup');group.setAttribute('aria-label','权限');
      for(const o of j.options||[]){
        const b=el('button','option-card'),text=el('span');b.type='button';b.setAttribute('role','radio');b.setAttribute('aria-checked',String(o.value===j.current));
        text.append(el('b','',o.name));if(o.description)text.append(el('small','',o.description));b.append(el('span','choice-dot'),text);
        b.onclick=async()=>{if(o.value===j.current){closeSheet('deepseekPermissions');return;}
          if(o.confirm&&!(await askConfirm('「'+o.name+'」：'+(o.description||'DeepSeek 做事前不再问你')+'。确定换成它吗？')))return;
          for(const n of perms.querySelectorAll('button'))n.disabled=true;
          try{const r=await api('/api/deepseek/permission',{id:me.id,preset:o.value,confirmed:!!o.confirm});closeSheet('deepseekPermissions');toast(r.text||'已切换');await refresh(me);}
          catch(e){toast('切换结果待核对：'+e.message,true);await refresh(me);}finally{for(const n of perms.querySelectorAll('button'))n.disabled=false;}};
        group.append(b);}
      perms.append(group,el('p','settings-notice','只影响这个对话；电脑上的 DeepSeek 会同步显示。'));
      openSheet('deepseekPermissions',perm);
    }catch(e){toast(e.message,true);}
  }
  function drawSubs(){
    subBar.hidden=cur?.app!=='deepseek'||!subs.length;if(subBar.hidden)return;
    const running=subs.filter(v=>v.running).length;
    subBar.textContent='子智能体 '+subs.length+' 个'+(running?' · '+running+' 个运行中':' · 都已完成');
  }
  function paintSubs(){
    const map=new Map(subs.map(v=>[v.id,v]));
    document.querySelectorAll('.sub-card[data-subagent]').forEach(n=>{const v=map.get(n.dataset.subagent);if(!v)return;const st=v.running?'running':'done';if(n.dataset.status===st)return;n.dataset.status=st;n.classList.toggle('running',st==='running');const chip=n.querySelector('.sub-state');if(chip)chip.textContent=st==='running'?'运行中':'已完成';});
  }
  subBar.onclick=()=>{subsBody.replaceChildren();for(const v of subs){const row=el('div','codex-card');row.append(el('b','',v.label||'子智能体'));row.append(el('span','hint',v.running?'运行中':'已完成'));subsBody.append(row);}subsBody.append(el('p','hint','子智能体自己的过程记录只在电脑上能打开；这里显示的是这个对话开过哪些、现在什么状态。'));openSheet('deepseekSubList');};
  function pendingKey(me){return 'lbr_deepseek_pending_'+me.id;}
  function paintRun(me){
    const on=!!me&&active(me),running=on&&!!state?.running,pending=on&&!!localStorage.getItem(pendingKey(me));
    runBar.hidden=!(running||pending);runHint.hidden=later.hidden=!running;check.hidden=!pending;
    later.disabled=busy||sending||!state?.available||!!window.referencesUI?.pendingCount(me)||!($('cvText').value.trim()||codexUI.imageSnapshot(me).length||window.referencesUI?.fileCount(me));
    if(on)$('cvBtn').setAttribute('aria-label',running?'立即补充当前任务':'发送');
    const rows=on?state?.queued||[]:[];const sig=JSON.stringify([on&&me.id,rows,running]);
    if(tray.dataset.sig===sig)return;tray.dataset.sig=sig;  // rebuilt only when it changes: a tap on a row is not lost
    tray.replaceChildren();tray.hidden=!rows.length;if(rows.length)tray.append(el('div','queue-head','排队中 · 这一轮做完后依次发出'));
    for(const q of rows){const row=el('div','queue-row');row.append(el('p','',q.text));
      const now=el('button','','立即补充'),x=el('button','queue-x','×');now.type=x.type='button';
      now.disabled=!running;now.setAttribute('aria-label','把这条消息立即补充给这一轮');x.setAttribute('aria-label','取消排队');
      now.onclick=()=>queueAction(me,q,'steer');x.onclick=()=>queueAction(me,q,'remove');
      row.append(now,x);window.navigationUI?.tapTick?.(now);window.navigationUI?.tapTick?.(x);tray.append(row);}
  }
  async function queueAction(me,q,action){
    if(!active(me))return;for(const n of tray.querySelectorAll('button'))n.disabled=true;
    try{const r=await api('/api/deepseek/queue',{id:me.id,item_id:q.id,action});toast(r.text||'已处理');}catch(e){toast('结果待核对：'+e.message,true);}
    finally{tray.dataset.sig='';await refresh(me);}
  }
  function controls(){
    const on=cur?.app==='deepseek';tools.hidden=!on;subBar.hidden=!on||!subs.length;stop.hidden=!on||!state?.running;
    if(!on){tray.hidden=runBar.hidden=true;return;}
    model.textContent=modelLabel(state?.settings);perm.textContent=state?.permission_name||PERMISSION[state?.permission]||'权限';perm.classList.toggle('is-full',state?.permission==='danger-full-access');
    perm.hidden=state?.permission_available===false;  // no permission service in this session: the desktop hides it too
    for(const b of [add,model,perm])b.disabled=busy||!state?.available;stop.disabled=busy;paintRun(cur);
  }
  async function refresh(me=cur){
    clearTimeout(timer);if(!me||!active(me))return;
    try{const s=await api('/api/deepseek/state?id='+encodeURIComponent(me.id));if(!active(me))return;state=s;subs=s.subagents||[];renderAsk(me,s);drawSubs();paintSubs();controls();await checkPending(me,false);}
    catch(e){if(active(me)){state={available:false};controls();showNote(e.message,'warn');}}
    finally{if(active(me))timer=setTimeout(()=>{if(!document.hidden)refresh(me);else timer=setTimeout(()=>refresh(me),3000);},2500);}
  }
  // What DeepSeek waits on: its questions (from the session, or a live event) and its approval requests, newest last.
  function waits(me,s){
    const interactions=s.interactions||[],items=[];
    const questionEvents=new Map(interactions.filter(v=>v.event==='user-questions/request').map(v=>[v.request.callId||v.eventId,v]));
    const all=new Map((s.questions||[]).map(q=>[q.callId,q]));
    for(const e of questionEvents.values()){const key=e.request.callId||e.eventId;if(!all.has(key))all.set(key,{...e.request,_eventKey:key});}
    for(const q of all.values())items.push({kind:'question',key:'q:'+(q._eventKey||q.callId),q,event:questionEvents.get(q._eventKey||q.callId)});
    for(const event of interactions.filter(v=>v.event==='approval/request'))items.push({kind:'approval',key:'a:'+event.eventId,event});
    return items;
  }
  function askLine(item){
    if(item.kind==='approval'){const r=item.event.request||{};return '请求批准'+(r.toolName?'：'+r.toolName:'');}
    return (item.q.questions||[])[0]?.question||'DeepSeek 在问你';
  }
  function renderAsk(me,s){
    const items=waits(me,s),box=$('cvOpts'),sig=JSON.stringify([me.id,items.map(i=>i.key),s.questions,(s.interactions||[]).map(v=>v.eventId)]);
    if(!items.length){askSig='';if(box.dataset.owner==='deepseek'){box.replaceChildren();delete box.dataset.owner;}if(askOpen())closeSheet('deepseekAskSheet');return;}
    if(sig===askSig&&box.dataset.owner==='deepseek')return;askSig=sig;
    const pill=el('button','optbox ask-pill');pill.type='button';pill.setAttribute('aria-label','DeepSeek 在等你，打开处理');
    pill.append(el('span','ask-dot'),el('span','ask-text',askLine(items[0])+(items.length>1?'（共 '+items.length+' 项）':'')),el('span','ask-go','去处理 ›'));
    pill.onclick=()=>{paintAsk(me,items);if(!askOpen())openSheet('deepseekAskSheet');};
    box.replaceChildren(pill);box.dataset.owner='deepseek';if(askOpen())paintAsk(me,items);
  }
  function paintAsk(me,items){
    askBody.replaceChildren();
    for(const item of items)askBody.append(item.kind==='approval'?approvalPart(me,item.event):questionPart(me,item.q,item.event));
  }
  function approvalPart(me,event){
    const r=event.request||{},part=el('section','ds-ask'),head=el('h3','','批准这一步吗？');
    if(r.toolName)head.append(el('span','ds-tool',r.toolName));part.append(head);
    const reason=typeof r.reason==='string'?r.reason:(r.displayReason||(r.reason?JSON.stringify(r.reason):''));
    if(reason)part.append(el('pre','ds-reason',reason));
    const actions=el('div','ds-actions'),allow=el('button','ds-allow','仅允许本次'),reject=el('button','ds-reject','拒绝');
    allow.type=reject.type='button';actions.append(reject,allow);part.append(actions,el('p','hint','只放行这一次；以后同样的操作还会再问。'));
    const answer=async choice=>{allow.disabled=reject.disabled=true;asking.add(event.eventId);
      try{const result=await api('/api/deepseek/approval',{id:me.id,event_id:event.eventId,choice});toast(result.text);}
      catch(e){toast('处理结果待核对：'+e.message,true);}finally{asking.delete(event.eventId);askSig='';await refresh(me);}};
    allow.onclick=()=>answer('allowed-once');reject.onclick=()=>answer('rejected');
    window.navigationUI?.tapTick?.(allow);window.navigationUI?.tapTick?.(reject);
    return part;
  }
  function questionPart(me,q,event){
    const part=el('section','ds-ask'),answers=[],key=q._eventKey||q.callId;
    for(const question of q.questions||[]){
      part.append(el('h3','',question.question));if(question.detail)part.append(el('p','hint',question.detail));
      const savedKey=me.id+':'+key+':'+question.id,saved=questionDrafts.get(savedKey)||{selected:[],custom:''},group=el('div');
      group.setAttribute('role',question.multiSelect?'group':'radiogroup');group.setAttribute('aria-label',question.question);
      const cards=[];const save=()=>questionDrafts.set(savedKey,{selected:cards.filter(c=>c.getAttribute('aria-checked')==='true').map(c=>c.dataset.value),custom:custom.value});
      for(const option of question.options||[]){
        const card=el('button','option-card'),text=el('span');card.type='button';card.dataset.value=option.label;
        card.setAttribute('role',question.multiSelect?'checkbox':'radio');card.setAttribute('aria-checked',String(saved.selected.includes(option.label)));
        text.append(el('b','',option.label));if(option.description)text.append(el('small','',option.description));card.append(el('span','choice-dot'),text);
        card.onclick=()=>{const on=card.getAttribute('aria-checked')!=='true';if(!question.multiSelect)cards.forEach(c=>c.setAttribute('aria-checked','false'));card.setAttribute('aria-checked',String(on||!question.multiSelect));save();};
        cards.push(card);group.append(card);}
      const custom=el('textarea');custom.value=saved.custom;custom.placeholder='补充回答（可不填）';custom.setAttribute('aria-label',question.question+'：补充回答');custom.oninput=save;
      part.append(group,custom);
      answers.push(()=>({id:question.id,selected:cards.filter(c=>c.getAttribute('aria-checked')==='true').map(c=>c.dataset.value),...(custom.value.trim()?{custom:custom.value.trim()}:{})}));
    }
    const submit=el('button','big','提交答案');submit.type='button';
    submit.onclick=async()=>{const batch=answers.map(f=>f());if(batch.some(a=>!a.selected.length&&!a.custom)){toast('请回答每一个问题',true);return;}
      submit.disabled=true;try{const result=await api('/api/deepseek/answer',{id:me.id,call_id:q.callId,event_id:event?.eventId,answers:batch});toast(result.text||'答案已提交');}
      catch(e){toast('答案结果待核对：'+e.message,true);}finally{submit.disabled=false;askSig='';await refresh(me);}};
    part.append(submit);return part;
  }
  $('cvText').addEventListener('input',()=>{if(cur?.app==='deepseek')paintRun(cur);});
  async function send(intent='steer'){
    const me=cur;if(!me||!active(me)||busy||sending||window.workspaceUI?.composing)return;
    if(window.referencesUI?.pendingCount(me)){showNote('文件还在传到电脑，传完再发；没传上的点「重试」或去掉','warn');return;}
    if(codexUI.blocked())return;
    const text=$('cvText').value,images=codexUI.imageSnapshot(me);if(!text.trim()&&!images.length&&!window.referencesUI?.fileCount(me))return;  // files alone are a message
    const key=pendingKey(me);let previous;try{previous=JSON.parse(localStorage.getItem(key)||'null');}catch{}
    if(previous){await checkPending(me,true);return;}
    const body={id:me.id,request_id:uid(),text,attachments:images.map(v=>v.meta.id),references:window.referencesUI?.snapshot(me)||[],intent};
    try{localStorage.setItem(key,JSON.stringify(body));}catch{showNote('无法保存发送记录，请先释放手机存储空间','bad');return;}
    busy=true;sending=true;controls();updateSendButton();showNote(intent==='queue'?'正在排进 DeepSeek 的队列…':'正在发送给 DeepSeek…');
    try{const result=await api('/api/deepseek/send',body);localStorage.removeItem(key);codexUI.clearImages(me);window.referencesUI?.clear(me);if(active(me)&&$('cvText').value===text){$('cvText').value='';saveDraft();autoGrow();}if(active(me))showNote(result.text,'ok');}
    catch(e){if(active(me))showNote('发送结果待核对：'+e.message+'。草稿已保留。','warn');}
    finally{busy=false;sending=false;updateSendButton();controls();if(active(me)){await loadConv(true);await refresh(me);}}
  }
  async function checkPending(me,explicit){
    if(!me||!active(me)||busy)return;const key=pendingKey(me);let body;try{body=JSON.parse(localStorage.getItem(key)||'null');}catch{}if(!body)return;
    try{const receipt=await api('/api/deepseek/receipt?request_id='+encodeURIComponent(body.request_id));
      if(receipt.state==='accepted'&&receipt.id===me.id){localStorage.removeItem(key);codexUI.clearImages(me);window.referencesUI?.clear(me);if(active(me)&&$('cvText').value===body.text){$('cvText').value='';saveDraft();autoGrow();}if(active(me)){showNote('已按请求编号确认送达','ok');controls();updateSendButton();}return;}
      if(explicit&&receipt.state==='unknown'){busy=true;check.disabled=true;try{const result=await api('/api/deepseek/send',body);localStorage.removeItem(key);codexUI.clearImages(me);window.referencesUI?.clear(me);if(active(me)&&$('cvText').value===body.text){$('cvText').value='';saveDraft();autoGrow();}if(active(me))showNote(result.text,'ok');}finally{busy=false;check.disabled=false;controls();updateSendButton();}return;}
      if(explicit)showNote('仍未确认送达。已保留草稿和请求编号，请核对 DeepSeek 对话。','warn');
    }catch(e){if(explicit&&active(me))showNote(e.message,'warn');}
  }
  // A new DeepSeek conversation comes from the shared sheet (new-chat-ui.js) like the others: workspace, model and first
  // message in one go (10-20; there was a sheet here that made an empty conversation in a folder).
  function reset(){clearTimeout(timer);state=null;askSig='';subs=[];tray.dataset.sig='';tray.replaceChildren();tray.hidden=runBar.hidden=stop.hidden=subBar.hidden=true;if($('cvOpts').dataset.owner==='deepseek'){$('cvOpts').replaceChildren();delete $('cvOpts').dataset.owner;}}
  window.deepseekUI={send,refresh,onOpen(me){reset();controls();if(me.app==='deepseek'){if(!modelCatalog)api('/api/deepseek/models').then(v=>{modelCatalog=v;if(active(me))controls();}).catch(()=>{});refresh(me);}},onClose(){reset();tools.hidden=true;}};
  if(cur)deepseekUI.onOpen(cur);
})();
