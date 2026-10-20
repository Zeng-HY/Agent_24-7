/* Full first-message composer. Every first message sent becomes a creation job of its own (10-16): the sheet is free
   again at once, whatever becomes of the job, and a job that went wrong can be checked, restored or removed. */
(() => {
  const key='lbr_new_chat_v1',jobsKey='lbr_new_jobs_v1';
  // settings: per app, the model and effort picked for the next new conversation ({model, modelLabel, effort, effortLabel});
  // none: the desktop's own (10-14, the sheet had no way to pick them)
  const empty=()=>({app:'codex',folder:'',projectless:false,label:'',text:'',references:[],images:[],request_id:null,settings:{}});
  // DeepSeek is one of the three like the others since 10-20 (it had a sheet of its own: a folder and an empty conversation)
  const APP_NAME={codex:'Codex',claude:'Claude',deepseek:'DeepSeek'},APP_ID={codex:'newCodex',claude:'newClaude',deepseek:'newDeepseek'};
  const SPARK='<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3.5l1.8 4.7 4.7 1.8-4.7 1.8-1.8 4.7-1.8-4.7-4.7-1.8 4.7-1.8z"/><path d="M18.5 15.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z"/></svg>';
  let d;try{d={...empty(),...JSON.parse(localStorage.getItem(key)||'{}')};}catch{d=empty();}
  // jobs: the first messages sent, oldest first, each {request_id, preview_id, app, folder, projectless, label, text,
  // references, images, body (what was submitted), pending (the service's latest word), clientTiming, created}
  let jobs;try{jobs=JSON.parse(localStorage.getItem(jobsKey)||'[]');if(!Array.isArray(jobs))jobs=[];}catch{jobs=[];}
  // Before 10-16 the draft itself carried the request under way (d.pending) and the sheet stayed locked until it was
  // accepted: one left unconfirmed (10-15 19:09) locked it for good. Such a request becomes a job; the draft starts afresh.
  if(d.pending){jobs.push(jobOf(d,d.pending));d=fresh(d);save();saveJobs();}
  let folders=[],composing=false,uploading=0,opening=null,searchSeq=0,pickerKind='',offset=0,trigger=null;
  let starting=false,lastTiming=null,handoff=null,modelOptions={},sheetJob=null,dockSig='';
  // per request id, on this page only: the next look, a look or a send under way, when the send started, a note
  const timers={},checking=new Set(),sending=new Set(),clocks={},notes={};
  try{handoff=JSON.parse(localStorage.getItem('lbr_new_handoff_v1')||'null');}catch{}
  try{lastTiming=JSON.parse(localStorage.getItem('lbr_new_timing_v1')||'null');}catch{}
  const sheet=$('newSheet'),box=sheet.querySelector('.sh-body');
  sheet.querySelector('b').textContent='新建对话';sheet.setAttribute('aria-label','新建对话');
  box.innerHTML=`<div class="new-apps" role="radiogroup" aria-label="客户端"><button id="newCodex" role="radio">Codex</button><button id="newClaude" role="radio">Claude</button><button id="newDeepseek" role="radio">DeepSeek</button></div>
    <p class="hint new-caption" id="newCaption">第一句话就能附照片、使用技能或引用其他对话。</p>
    <div class="new-composer"><div id="newImages" class="attachment-previews" hidden></div><div id="newRefs" class="reference-chips" hidden></div>
    <textarea id="newText" rows="4" placeholder="想做什么？输入 @ 找对话，$ 找技能" aria-label="首条消息"></textarea>
    <div id="newSuggestions" class="new-suggestions" hidden></div><div class="new-composer-bar"><button id="newAdd" class="icon-btn" aria-label="添加照片、技能或对话">＋</button><span class="hint">首条消息</span><button id="newBtn" class="icon-btn new-send" aria-label="创建并发送">${icon('send')}</button></div></div>
    <button id="newFolderChoice" class="new-folder"><span>${icon('folder')}</span><span><strong id="newFolderName">选择项目文件夹</strong><small id="newFolderPath">读取电脑上的项目…</small></span><span>⌄</span></button>
    <button id="newModelChoice" class="new-folder"><span>${SPARK}</span><span><strong id="newModelName">默认模型</strong><small id="newModelDetail">跟电脑当前设置走；点这里选</small></span><span>⌄</span></button>
    <p class="hint new-caption" id="newStatus" role="status" aria-live="polite"></p>`;
  // Only the desktop apps this computer has (MACHINE.apps, looked at again each time the page opens); paint() hides the row
  // when one button is left (10-20; it used to look only for Claude).
  const hasNew=app=>!Array.isArray(window.MACHINE?.apps)||MACHINE.apps.includes(app);
  for(const app in APP_ID)$(APP_ID[app]).hidden=!hasNew(app);
  if(!hasNew(d.app))d.app=Object.keys(APP_ID).find(hasNew)||d.app;
  if(d.app==='deepseek')d.projectless=false;  // a DeepSeek conversation lives in one of its workspaces
  const dock=el('div');dock.id='newJobDock';dock.hidden=true;$('convList').before(dock);  // one row per job not on screen
  const css=el('style');css.textContent=`
    #newSheet .box{max-height:calc(var(--overlay-height,100dvh) - 16px)}#newSheet .sh-body{gap:16px;padding-bottom:calc(16px + env(safe-area-inset-bottom))}
    #newSheet [hidden],#newJobSheet [hidden],#newJobDock[hidden]{display:none!important}
    #convView.new-provisional .composer-tools,#convView.new-provisional .history-tools,#convView.new-provisional .stop-turn,#convView.new-provisional #runtimeBar,#convView.new-provisional .codex-control-note,#convView.new-provisional .attachment-previews,#convView.new-provisional .reference-chips{display:none!important}
    #convView.new-provisional .cv-top [onclick*="convMenu"]{visibility:hidden}
    .new-first-message{display:flex;flex-direction:column;align-items:flex-end}.new-inline-status{display:block;color:#9ca3af;font-size:12px;font-weight:400;line-height:1.6;margin:0 12px 0;background:none;border:0;padding:0;min-height:0;text-align:right}.new-inline-status.problem{cursor:pointer;text-decoration:underline;text-underline-offset:3px}
    .new-job-dock{position:static;display:block;width:100%;min-height:44px;background:var(--card);color:var(--muted);border:1px solid var(--line);border-radius:14px;padding:10px 14px;margin:8px 0;font-size:13px;text-align:left;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .new-apps{display:flex;border-radius:999px;background:var(--bg);padding:4px;gap:4px}.new-apps button{border:0;flex:1;border-radius:999px;min-height:44px;background:transparent;font-size:16px;font-weight:500}.new-apps button[aria-checked=true]{background:#fff;color:var(--blue);box-shadow:0 1px 5px #1d23300d}
    .new-caption{margin:0;line-height:1.6}.new-composer{padding:12px;border:1px solid var(--line);background:var(--bg);border-radius:24px;min-width:0}.new-composer textarea{font:inherit;font-size:16px;background:transparent;border:0;resize:none;display:block;min-height:112px;max-height:28dvh;width:100%;padding:8px 4px;line-height:1.6;outline:none}.new-composer:focus-within{border-color:#9db8f8}
    .new-composer-bar{display:flex;align-items:center;gap:8px}.new-composer-bar .hint{flex:1}.new-send{background:var(--blue);color:white!important;border-radius:50%;padding:10px!important}.new-send svg{width:24px;height:24px}.new-send:disabled{opacity:.45}
    .new-folder{display:flex;align-items:center;gap:12px;width:100%;border:0;background:transparent;text-align:left;border-radius:16px;padding:12px 4px;min-height:60px}.new-folder>span:nth-child(2){min-width:0;flex:1}.new-folder strong{display:block;font-size:15px;font-weight:500}.new-folder small{display:block;color:var(--muted);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:100%;margin-top:4px}.new-folder svg{width:22px;height:22px}.new-result-actions{display:flex;flex-wrap:wrap;gap:8px}.new-result-actions button{font-size:14px;border-radius:999px;min-height:44px}
    #newJobSheet .sh-body{gap:12px;padding-bottom:calc(16px + env(safe-area-inset-bottom))}.new-job-status{margin:0;line-height:1.6;overflow-wrap:anywhere}
    #newPicker .new-search{position:sticky;top:0;background:white;padding-bottom:8px}#newPickerResults{max-height:48dvh;overflow:auto;overscroll-behavior:contain}.new-pick-row{width:100%;text-align:left;background:transparent;border:0;border-radius:14px;padding:12px;min-height:60px;font-size:15px;display:block;font-weight:500}.new-pick-row small{display:block;font-size:12px;color:var(--muted);font-weight:400;white-space:normal;overflow-wrap:anywhere;margin-top:4px;line-height:1.5}.new-pick-row[aria-selected=true]{color:var(--blue);background:#eef2ff}.new-pick-row:active{background:var(--bg)}
    .new-suggestions{border-top:1px solid var(--line);max-height:180px;overflow:auto;overscroll-behavior:contain}.new-suggestions button{font-size:14px}.new-upload-error{font-size:12px;color:var(--red);overflow-wrap:anywhere}.new-composer .reference-chips{display:flex;flex-wrap:wrap;gap:6px;padding:4px}.new-composer .reference-chip{max-width:100%;background:white}.new-composer .reference-chip span{overflow:hidden;text-overflow:ellipsis}
    #newSheet .new-folder+.new-folder{margin-top:-12px}#newModelSheet .sh-body{gap:12px}#newModelRows{display:flex;flex-direction:column;gap:2px}
    #newModelSheet .model-list-row small{display:block;margin-top:2px;font-size:12px;font-weight:400;color:var(--muted)}#newModelSheet .model-list-row[aria-checked=true] small{color:inherit;opacity:.75}
    @media(max-height:520px){#newSheet .sh-body{gap:8px}.new-composer textarea{min-height:60px}.new-caption{font-size:12px}}
  `;document.head.append(css);
  function panel(id,title,content,popover=false){const n=el('div','sheet'+(popover?' popover':''));n.id=id;n.setAttribute('aria-label',title);n.innerHTML='<div class="box"><div class="sh-head"><b>'+title+'</b><button class="icon-btn" aria-label="关闭">'+icon('close')+'</button></div><div class="sh-body">'+content+'</div></div>';n.querySelector('button').onclick=()=>closeSheet(id);n.onclick=e=>{if(e.target===n)closeSheet(id);};document.body.append(n);return n;}
  panel('newAddMenu','添加','<button class="menu-row" id="newCamera">拍照</button><button class="menu-row" id="newPhoto">从相册选择</button><button class="menu-row" id="newChatRef">引用对话</button><button class="menu-row" id="newSkillRef">使用技能</button>',true);
  panel('newModelSheet','模型与推理强度','<div id="newModelRows" role="radiogroup" aria-label="模型"></div><div class="setting-heading" id="newEffortHead">推理强度</div><div id="newEffortRows" class="effort-choices" role="radiogroup" aria-label="推理强度"></div><p id="newModelNote" class="settings-notice"></p><button class="big" id="newModelDone">好了</button>');
  panel('newPicker','选择','<div class="new-search"><input id="newSearch" class="field" type="search" placeholder="搜索" aria-label="搜索选项"></div><div id="newPickerResults" role="listbox"></div><button id="newMore" hidden>加载更多</button>');
  panel('newJobSheet','新建对话的结果','<p class="hint new-caption" id="newJobTitle"></p><p class="new-job-status" id="newJobStatus" role="status" aria-live="polite"></p><div class="new-result-actions"><button id="newCheck">核对结果</button><button id="newRetry" hidden>继续发送</button><button id="newOpen" hidden>打开对话</button><button id="newRestore" hidden>恢复草稿</button><button id="newDismiss">移除</button></div>');
  const photo=el('input'),camera=el('input');for(const n of [photo,camera]){n.type='file';n.accept='image/*';n.hidden=true;n.onchange=()=>{addFiles([...n.files]);n.value='';};document.body.append(n);}photo.multiple=true;camera.setAttribute('capture','environment');
  let dbPromise;function filesDB(){return dbPromise ||=new Promise((resolve,reject)=>{const r=indexedDB.open('agent-remote-image-drafts',1);r.onupgradeneeded=()=>r.result.createObjectStore('files');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
  async function fileStore(op,id,value){const db=await filesDB();return new Promise((resolve,reject)=>{const tx=db.transaction('files',op==='get'?'readonly':'readwrite'),store=tx.objectStore('files'),req=op==='put'?store.put(value,id):store[op](id);let result;req.onsuccess=()=>result=req.result;tx.oncomplete=()=>resolve(result);tx.onerror=()=>reject(tx.error);});}
  function save(){localStorage.setItem(key,JSON.stringify({...d,images:d.images.map(({file,url,...v})=>v)}));}
  function saveJobs(){localStorage.setItem(jobsKey,JSON.stringify(jobs));}
  function hex(){return [...crypto.getRandomValues(new Uint8Array(16))].map(v=>v.toString(16).padStart(2,'0')).join('');}
  function fresh(v){return {...empty(),app:v.app,folder:v.folder,projectless:!!v.projectless,label:v.label||'',settings:v.settings||{}};}  // same place and picks, nothing written
  function jobOf(v,pending){
    const pick=(v.settings||{})[v.app],j={request_id:v.request_id,preview_id:v.preview_id||'new:'+(v.request_id||hex()),app:v.app,folder:v.folder,projectless:!!v.projectless,label:v.label||'',
      text:v.text||'',references:v.references||[],images:(v.images||[]).map(({file,url,...i})=>i),pending,clientTiming:v.clientTiming||{},timingReported:!!v.timingReported,created:Date.now()};
    j.body={request_id:j.request_id,app:j.app,folder:j.projectless?'':j.folder,...(j.projectless?{projectless:true}:{}),...(pick?{settings:{model:pick.model,effort:pick.effort??null}}:{}),text:j.text,attachments:j.images.map(i=>i.meta?.id).filter(Boolean),references:j.references};
    return j;
  }
  function grow(){const n=$('newText');n.style.height='auto';n.style.height=Math.min(n.scrollHeight,window.innerHeight*.28)+'px';}
  // ---- the new conversation's model and effort (10-14)
  function chosen(){return (d.settings||{})[d.app]||null;}
  function setPick(v){d.settings={...(d.settings||{}),[d.app]:v};save();paintModels();paint();}
  async function openModels(){
    openSheet('newModelSheet');paintModels();const app=d.app;
    try{modelOptions[app]=await api('/api/chat/new/options?app='+app);}catch(e){modelOptions[app]={models:[],note:'读不到模型列表：'+e.message};}
    if(app===d.app)paintModels();
  }
  function paintModels(){
    const opts=modelOptions[d.app],pick=chosen(),rows=$('newModelRows'),efforts=$('newEffortRows');rows.replaceChildren();efforts.replaceChildren();
    const row=(label,sub,on,pickIt)=>{const b=el('button','model-list-row'),text=el('span','',label);b.type='button';b.setAttribute('role','radio');b.setAttribute('aria-checked',String(on));if(sub)text.append(el('small','',sub));b.append(text);b.onclick=pickIt;return b;};
    rows.append(row('默认',{claude:'Claude 桌面端当前的模型和强度',deepseek:'DeepSeek 的默认模型和强度'}[d.app]||'Codex 当前的默认设置',!pick,()=>setPick(null)));
    const models=opts?.models||[],model=models.find(m=>m.id===pick?.model);
    for(const m of models)rows.append(row(m.label,'',pick?.model===m.id,()=>{if(pick?.model!==m.id)setPick({model:m.id,modelLabel:m.label,effort:null,effortLabel:''});}));
    if(!opts)rows.append(el('p','hint','读取电脑上的模型列表…'));
    else if(pick&&!model&&models.length)rows.append(el('p','hint','之前选的「'+pick.modelLabel+'」不在电脑现在的模型列表里，请重新选。'));
    $('newEffortHead').hidden=efforts.hidden=!model?.efforts?.length;
    for(const e of model?.efforts||[]){const label=d.app==='codex'?(EFFORT[e.id]||e.label):e.label,b=el('button','',label);b.type='button';b.setAttribute('role','radio');b.setAttribute('aria-checked',String(pick.effort===e.id));
      b.onclick=()=>setPick({...pick,effort:pick.effort===e.id?null:e.id,effortLabel:pick.effort===e.id?'':label});efforts.append(b);}
    $('newModelNote').textContent=opts?.note||(model&&pick.effort==null&&model.efforts?.length?'推理强度不选，就用'+({codex:'电脑上的档位（这个模型没有时用它的默认档）',deepseek:'这个模型的默认档'}[d.app]||'Claude 新建页当前的档位')+'。':'');
  }
  function shown(id){return overlays.some(v=>v.id===id);}
  function progressText(p){
    if(!p)return '';
    if(p.state==='accepted')return '首条消息已送达';
    if(p.state==='failed')return '创建未完成';
    if(p.state==='unconfirmed')return '正在核对发送结果';
    const stage=p.timing?.active?.name||'';
    if(stage==='claude_record'||stage==='receipt'||stage==='send_ack'||stage==='late_receipt')return '正在确认首条消息';
    if(stage.startsWith('send_')||['claude_fill','claude_images','claude_verify','claude_invoke'].includes(stage))return '正在发送首条消息';
    if(stage.startsWith('desktop_'))return '正在连接电脑端';
    return '正在创建对话';
  }
  // ---- jobs: where each first message sent stands
  function isPreview(c=cur){return !!c?.id?.startsWith('new:');}
  function currentJob(){return isPreview(cur)?jobs.find(j=>j.preview_id===cur.id)||null:null;}
  function oneLine(text){return String(text||'').replace(/\s+/g,' ').trim();}
  function problem(j){return ['failed','unconfirmed'].includes(j?.pending?.state);}
  function retryable(p){return !!(p?.can_submit||(p?.state==='failed'&&p.not_submitted&&p.can_retry!==false));}
  function stateText(j){const s=j.pending?.state;return s==='accepted'?'新对话已就绪':s==='failed'?'没发出去':s==='unconfirmed'?'尚未确认发送':s==='dispatching'?'发送中…':'对话创建中…';}
  function inlineText(j){const s=j.pending?.state;return s==='failed'?'没发出去 · 点击处理':s==='unconfirmed'?'尚未确认发送 · 点击核对':s==='accepted'?'':stateText(j);}
  function dockText(j){return (APP_NAME[j.app]||'Codex')+' · '+stateText(j)+' · '+(oneLine(j.text).slice(0,60)||'新对话');}
  function renderProgress(){
    const now=currentJob(),rows=jobs.filter(j=>j!==now),sig=rows.map(j=>j.request_id+' '+dockText(j)).join('\n');dock.hidden=!rows.length;
    if(sig!==dockSig){dockSig=sig;dock.replaceChildren(...rows.map(j=>{const b=el('button','new-job-dock',dockText(j));b.type='button';b.onclick=()=>openJob(j);return b;}));}
    const note=$('newInlineStatus');if(note&&now){note.textContent=inlineText(now);note.classList.toggle('problem',problem(now));}
    if(sheetJob&&shown('newJobSheet'))paintJob();
  }
  function openJob(j){if(j.pending?.state==='accepted'&&j.pending.id)finish(j);else if(problem(j))openJobSheet(j);else openPreview(j);}
  function openJobSheet(j){sheetJob=j;openSheet('newJobSheet');paintJob();}
  function paintJob(){
    const j=sheetJob;if(!j)return;const p=j.pending||{},gone=!jobs.includes(j),place=j.projectless?'无项目':j.label||String(j.folder||'').split(/[\\/]/).pop();
    $('newJobTitle').textContent=[APP_NAME[j.app]||'Codex',place,oneLine(j.text).slice(0,40)||'只有图片或引用'].filter(Boolean).join(' · ');
    $('newJobStatus').textContent=gone?'这一条已经处理过了。':notes[j.request_id]||(problem(j)?p.message||stateText(j):progressText(p));
    $('newCheck').hidden=gone||p.state==='accepted';$('newRetry').hidden=gone||!retryable(p);$('newOpen').hidden=gone||!p.id;$('newRestore').hidden=gone||p.state!=='failed';$('newDismiss').hidden=gone;
  }
  function drop(j,keepFiles=false){  // keepFiles: its photos go back into the draft
    jobs=jobs.filter(v=>v!==j);const rid=j.request_id;clearTimeout(timers[rid]);delete timers[rid];delete clocks[rid];delete notes[rid];saveJobs();
    if(!keepFiles)for(const v of j.images||[])fileStore('delete',v.localId).catch(()=>{});
  }
  function openPreview(j,fromHistory=false){
    if(!j)return;if(j.pending?.state==='accepted'&&j.pending.id){finish(j);return;}
    if(cur){saveDraft();rememberScroll();}window.codexUI?.onClose();window.claudeUI?.onClose();window.referencesUI?.onClose();window.readingUI?.pauseStream();clearTimeout(convTimer);dismissOverlays();
    cur={app:j.app,id:j.preview_id,title:j.text.slice(0,50)||'新对话',folder:j.projectless?'':j.label||j.folder,status:'creating'};
    curSig='';optsSig='';chatReadError='';lastRuntime=null;currentMessages=[];
    $('convView').classList.add('new-provisional');$('convView').style.display='flex';$('cvTitle').textContent=cur.title;$('cvMeta').textContent=APP_NAME[j.app]||'Codex';
    $('cvOpts').replaceChildren();$('cvMsgs').replaceChildren();delete $('cvMsgs').dataset.ready;$('newMessages').hidden=true;hideNote();renderRuntime(null);updateConnection();
    $('cvText').value=readDraft(cur);$('cvText').placeholder='可以先写下一条，创建完成后发送';autoGrow();updateSendButton();
    window.readingUI?.onOpen(cur,cur);renderMsgs([]);if(window.navigationUI?.openFromDrawer)navigationUI.openFromDrawer(()=>navigationUI.onOpen());else window.navigationUI?.onOpen();fitView();syncInert();if(!fromHistory)pushUIState();window.workspaceUI?.saveScene();renderProgress();
  }
  function decorateRows(rows){
    const job=currentJob(),delivered=!job&&handoff&&cur?.id===handoff.id&&cur?.app===handoff.app;
    if(!job&&!delivered)return;
    if(delivered&&rows.some(v=>v.message?.role==='user'))return;
    for(let i=rows.length-1;i>=0;i--)if(rows[i].key==='empty')rows.splice(i,1);
    const item=job||handoff;
    rows.unshift({key:'new-first:'+item.request_id,newCreation:{text:item.text||'',images:(item.images||[]).map(v=>v.meta).filter(Boolean),references:item.references||[],status:job?inlineText(job):'',problem:problem(job)}});
  }
  function renderFirst(node,item){
    node.className='new-first-message';node.replaceChildren();const bubble=el('div','bub user');bubble.innerHTML=md(item.text||'请查看这些图片或引用。');
    if(item.images.length)window.codexUI?.renderImages(bubble,item.images);
    if(item.references.length)bubble.append(el('small','',item.references.map(r=>(r.kind==='skill'?'$':'@')+(r.name||r.title)).join(' · ')));
    node.append(bubble);if(item.status){const note=el('button','new-inline-status'+(item.problem?' problem':''),item.status);note.id='newInlineStatus';note.onclick=()=>{const j=currentJob();if(problem(j))openJobSheet(j);};node.append(note);}
  }
  function rememberTiming(j,r){
    const rid=j.request_id;if(!j.clientTiming?.observed_ms&&clocks[rid]!=null)j.clientTiming={...j.clientTiming,observed_ms:performance.now()-clocks[rid]};
    lastTiming={app:j.app,server:r.timing,client:j.clientTiming};localStorage.setItem('lbr_new_timing_v1',JSON.stringify(lastTiming));saveJobs();
    if(rid&&!j.timingReported){j.timingReported=true;saveJobs();api('/api/chat/new/timing',{request_id:rid,timing:j.clientTiming||{}}).catch(()=>{j.timingReported=false;saveJobs();});}
  }
  async function ensureDraft(){if(d.request_id)return d.request_id;if(!opening)opening=api('/api/chat/new/draft',{}).then(v=>{d.request_id=v.request_id;save();return v.request_id;}).finally(()=>opening=null);return opening;}
  function paint(){
    for(const app in APP_ID)$(APP_ID[app]).setAttribute('aria-checked',String(d.app===app));
    const apps=box.querySelector('.new-apps');apps.hidden=[...apps.children].filter(b=>!b.hidden).length<2;  // one app: nothing to pick
    const skills=d.app!=='deepseek';  // DeepSeek takes conversations as references, not skills: nothing on the sheet offers them
    $('newSkillRef').style.display=skills?'':'none';
    $('newCaption').textContent=skills?'第一句话就能附照片、使用技能或引用其他对话。':'第一句话就能附照片或引用其他对话。';
    $('newText').placeholder=skills?'想做什么？输入 @ 找对话，$ 找技能':'想做什么？输入 @ 找对话';
    $('newAdd').setAttribute('aria-label',skills?'添加照片、技能或对话':'添加照片或对话');
    const folder=folders.find(v=>v.path===d.folder);$('newFolderName').textContent=d.projectless?'无项目':d.label||folder?.name||(d.folder?d.folder.split(/[\\/]/).pop():'选择项目文件夹');$('newFolderPath').textContent=d.projectless?'不放进任何项目':d.folder||'电脑端的项目与对话目录';
    const pick=chosen();$('newModelName').textContent=pick?pick.modelLabel+(pick.effortLabel?' · '+pick.effortLabel:''):'默认模型';
    $('newModelDetail').textContent=pick?'新对话用这个模型；点这里换':'跟电脑当前设置走；点这里选';
    $('newBtn').disabled=starting||composing||uploading>0||d.images.some(v=>!v.meta)||!(d.folder||d.projectless)||(!d.text.trim()&&!d.images.length&&!d.references.length);
    $('newRefs').replaceChildren();$('newRefs').hidden=!d.references.length;
    for(const r of d.references){const chip=el('div','reference-chip'),b=el('button','','×');b.type='button';b.setAttribute('aria-label','移除 '+(r.name||r.title));b.onclick=()=>{d.references=d.references.filter(v=>v!==r);save();paint();};chip.append(el('span','',(r.kind==='skill'?'$':'@')+(r.name||r.title)),b);$('newRefs').append(chip);}
    $('newImages').replaceChildren();$('newImages').hidden=!d.images.length;
    for(const v of d.images){const tile=el('div','attachment-tile'),img=el('img'),remove=el('button','remove-image');img.src=v.meta?.thumbnail||v.url||'';img.alt=v.name;remove.innerHTML='<span>×</span>';remove.setAttribute('aria-label','移除 '+v.name);remove.onclick=()=>{d.images=d.images.filter(i=>i!==v);fileStore('delete',v.localId).catch(()=>{});if(v.url)URL.revokeObjectURL(v.url);save();paint();};tile.append(img,remove,el('small','',v.meta?'待发送':v.uploading?'上传中…':'未上传'));
      if(v.error){const err=el('div','new-upload-error',v.error),retry=el('button','retry-image','重试上传');retry.onclick=()=>upload(v);tile.append(err,retry);} $('newImages').append(tile);}
    $('newStatus').textContent=d.app==='claude'?(pick?'':'使用 Claude 桌面端当前设置。')+'新文件夹可能需要在电脑上确认信任。':pick?'创建后还可以在输入区调整。':'使用 '+(APP_NAME[d.app]||'Codex')+' 当前默认设置；创建后可在输入区调整。';
    renderProgress();
  }
  async function upload(v){if(v.uploading)return;v.uploading=true;v.error='';uploading++;paint();try{const rid=await ensureDraft(),file=v.file||await fileStore('get',v.localId);if(!file)throw Error('原图已不在浏览器中，请移除后重新选择');const res=await fetch('/api/codex/upload?draft='+rid+'&name='+encodeURIComponent(v.name),{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file});const out=await res.json();if(!res.ok||out.error)throw Error(out.error||'上传失败');v.meta=out;}catch(e){v.error=e.message;}finally{v.uploading=false;uploading--;save();paint();}}
  async function addFiles(files){for(const file of files){if(d.images.length>=5){toast('最多添加 5 张图片',true);break;}if(file.size>20*1024*1024){toast('单张图片不能超过 20 MB',true);continue;}if(d.images.reduce((n,v)=>n+v.size,0)+file.size>50*1024*1024){toast('图片合计不能超过 50 MB',true);break;}const v={localId:'new-'+hex(),name:file.name,size:file.size,file,url:URL.createObjectURL(file)};try{await fileStore('put',v.localId,file);d.images.push(v);save();upload(v);}catch(e){toast('图片草稿未能保存：'+e.message,true);}}paint();}
  function chooseRef(ref){if(composing)return;const id=v=>v.kind+':'+v.app+':'+v.id;if(d.references.some(v=>id(v)===id(ref))){toast('已经选过这一项');return;}if(d.references.length>=8||(ref.kind==='chat'&&d.references.filter(v=>v.kind==='chat').length>=3)){toast('最多引用 8 项，其中对话最多 3 段',true);return;}d.references.push(ref);if(trigger){const n=$('newText');if(n.value.slice(trigger.start,trigger.end)===trigger.text){n.setRangeText('',trigger.start,trigger.end,'end');d.text=n.value;}trigger=null;}$('newSuggestions').hidden=true;save();paint();}
  function pickRow(v,kind){const b=el('button','new-pick-row',kind==='folder'?v.name:(v.kind==='skill'?'$':'@')+(v.name||v.title));b.setAttribute('role','option');b.setAttribute('aria-selected',String(kind==='folder'?d.folder===v.path:d.references.some(r=>r.id===v.id&&r.app===v.app)));b.append(el('small','',kind==='folder'?v.path+' · '+v.sources.join(' / '):v.kind==='skill'?v.scope+' · '+v.description:(APP_NAME[v.app]||v.app)+' · '+v.folder+' · '+v.id.slice(-6)));b.onclick=()=>{if(kind==='folder'){if(d.folder!==v.path||d.projectless){d.folder=v.path;d.projectless=false;d.label='';searchSeq++;$('newSuggestions').hidden=true;d.references=d.references.filter(v=>v.kind!=='skill');save();paint();}}else chooseRef(v);closeSheet('newPicker');};return b;}
  function noProjectRow(){const b=el('button','new-pick-row','无项目');b.setAttribute('role','option');b.setAttribute('aria-selected',String(!!d.projectless));b.append(el('small','',d.app==='claude'?'Claude 不选文件夹，电脑上显示 No folder':'在「文档\\Codex」下新建一个文件夹'));b.onclick=()=>{if(!d.projectless){d.projectless=true;d.folder='';d.label='';searchSeq++;$('newSuggestions').hidden=true;d.references=d.references.filter(v=>v.kind!=='skill');save();paint();}closeSheet('newPicker');};return b;}
  async function loadPicker(more=false){const seq=++searchSeq,kind=pickerKind,q=$('newSearch').value.trim(),results=$('newPickerResults');if(!more)results.textContent='读取中…';$('newMore').hidden=true;
    try{if(kind==='folder'){const hits=folders.filter(v=>(v.name+' '+v.path+' '+v.sources.join(' ')).toLowerCase().includes(q.toLowerCase()));results.replaceChildren(...(d.app!=='deepseek'&&('无项目'.includes(q)||!q)?[noProjectRow()]:[]),...hits.map(v=>pickRow(v,'folder')));if(!hits.length&&q)results.append(el('p','hint','没有匹配的项目文件夹'));return;}
      const result=await api('/api/chat/new/references?'+new URLSearchParams({app:d.app,folder:d.folder,projectless:d.projectless?'1':'',kind,query:q,offset:more?offset:0}));if(seq!==searchSeq)return;if(!more)results.replaceChildren();for(const v of result.items)results.append(pickRow(v,kind));if(!result.items.length&&!more)results.append(el('p','hint','没有匹配项，试试部分名称或中文关键词'));offset=result.next_offset;$('newMore').hidden=!result.has_more;
    }catch(e){if(seq===searchSeq)results.textContent=e.message;}}
  function openPicker(kind){if(kind!=='folder'&&!d.folder&&!d.projectless){toast('先选择项目文件夹',true);kind='folder';}trigger=null;pickerKind=kind;offset=0;$('newPicker').querySelector('b').textContent=kind==='folder'?'项目文件夹':kind==='skill'?'使用技能':'引用对话';$('newSearch').value='';openSheet('newPicker');loadPicker();}
  let debounce;async function suggestions(){if(composing)return;const n=$('newText'),end=n.selectionStart,m=n.value.slice(0,end).match(/(?:^|\s)([@$])([^\s@$\n]{0,60})$/u),seq=++searchSeq;if(!m||end!==n.selectionEnd||!(d.folder||d.projectless)||(m[1]==='$'&&d.app==='deepseek')){$('newSuggestions').hidden=true;trigger=null;return;}const token={start:end-m[1].length-m[2].length,end,text:m[1]+m[2]};try{const r=await api('/api/chat/new/references?'+new URLSearchParams({app:d.app,folder:d.folder,projectless:d.projectless?'1':'',kind:m[1]==='@'?'chat':'skill',query:m[2]}));if(seq!==searchSeq||composing)return;trigger=token;const list=$('newSuggestions');list.replaceChildren();for(const v of r.items.slice(0,8)){const b=pickRow(v,v.kind);b.onpointerdown=e=>e.preventDefault();b.onclick=()=>chooseRef(v);list.append(b);}list.hidden=false;if(!r.items.length)list.textContent='没有匹配项';}catch(e){if(seq===searchSeq){$('newSuggestions').textContent=e.message;$('newSuggestions').hidden=false;}}}
  $('newText').value=d.text;$('newText').addEventListener('input',e=>{d.text=e.target.value;save();grow();paint();clearTimeout(debounce);if(!e.isComposing)debounce=setTimeout(suggestions,180);});$('newText').addEventListener('compositionstart',()=>{composing=true;searchSeq++;$('newSuggestions').hidden=true;paint();});$('newText').addEventListener('compositionend',()=>{composing=false;d.text=$('newText').value;save();paint();suggestions();});$('newText').addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'&&!e.isComposing&&!composing){e.preventDefault();send();}});
  for(const app in APP_ID)$(APP_ID[app]).onclick=()=>{if(d.app===app)return;const was=d.app;d.app=app;d.references=d.references.filter(v=>v.kind!=='skill');if(app==='deepseek')d.projectless=false;searchSeq++;$('newSuggestions').hidden=true;save();paint();
    if((was==='deepseek')!==(app==='deepseek'))loadFolders();};  // DeepSeek picks from its workspaces, the others from their projects
  async function loadFolders(){
    const app=d.app;
    try{const r=await api('/api/chat/folders'+(app==='deepseek'?'?app=deepseek':''));if(app!==d.app)return;folders=r.items||r.folders.map(path=>({path,name:path.split(/[\\/]/).pop(),sources:[]}));
      if(!d.projectless&&!folders.some(v=>v.path===d.folder)){let previous='';try{previous=localStorage.getItem('lbr_new_folder')||'';}catch{}d.folder=folders.find(v=>v.path===previous)?.path||folders[0]?.path||'';d.label='';save();}
      paint();grow();}catch(e){$('newStatus').textContent='文件夹读取失败：'+e.message;}}
  $('newAdd').onclick=()=>openSheet('newAddMenu',$('newAdd'));$('newCamera').onclick=()=>{closeSheet('newAddMenu');camera.click();};$('newPhoto').onclick=()=>{closeSheet('newAddMenu');photo.click();};$('newChatRef').onclick=()=>{closeSheet('newAddMenu');openPicker('chat');};$('newSkillRef').onclick=()=>{closeSheet('newAddMenu');openPicker('skill');};$('newFolderChoice').onclick=()=>openPicker('folder');$('newModelChoice').onclick=openModels;$('newModelDone').onclick=()=>closeSheet('newModelSheet');$('newSearch').oninput=e=>{if(!e.isComposing){clearTimeout(debounce);debounce=setTimeout(()=>loadPicker(),180);}};$('newSearch').oncompositionend=()=>loadPicker();$('newMore').onclick=()=>loadPicker(true);
  async function check(j){
    if(!j?.request_id||checking.has(j.request_id)||sending.has(j.request_id)||!jobs.includes(j))return;
    const rid=j.request_id;clearTimeout(timers[rid]);checking.add(rid);let delay=500;
    try{const started=performance.now(),r=await api('/api/chat/new/state?request_id='+rid);if(!jobs.includes(j))return;
      j.clientTiming={...j.clientTiming,status_roundtrip_ms:performance.now()-started};delete notes[rid];
      j.pending=r.state==='draft'?{...r,state:'unconfirmed',can_submit:true,message:'服务器尚无提交记录。可继续发送同一请求，不会重复创建。'}:r;saveJobs();renderProgress();
      if(r.state==='accepted'){rememberTiming(j,r);if(!settle())window.sidebarUI?.load(true);return;}
      if(r.state==='failed'){rememberTiming(j,r);return;}
      if(r.state==='unconfirmed')delay=Date.now()-(j.created||0)<120000?6000:30000;else if(currentJob()!==j)delay=1500;
    }catch(e){notes[rid]='暂时无法核对，内容还在手机上；恢复连接后继续核对';renderProgress();delay=5000;}
    finally{checking.delete(rid);if(jobs.includes(j)&&j.pending&&!['accepted','failed'].includes(j.pending.state)&&!document.hidden)timers[rid]=setTimeout(()=>check(j),delay);}
  }
  function settle(){  // an accepted job on screen becomes its conversation, unless something is open over it or being typed
    const j=currentJob();if(j?.pending?.state!=='accepted'||!j.pending.id||overlays.length||window.workspaceUI?.composing)return false;finish(j);return true;
  }
  function finish(j){
    const r=j.pending||{},wasPreview=currentJob()===j;if(!r.id||wasPreview&&window.workspaceUI?.composing)return;
    const next={app:r.app||j.app,id:r.id,title:r.title,folder:r.folder,status:'running',keepPreview:wasPreview};
    const input=$('cvText'),focused=wasPreview&&document.activeElement===input,selection=[input.selectionStart,input.selectionEnd];
    if(wasPreview)saveDraft();const following=readDraft({app:j.app,id:j.preview_id});if(following)writeDraft(next,following);
    handoff={...next,preview_id:j.preview_id,request_id:j.request_id,text:j.text,images:j.images,references:j.references};localStorage.setItem('lbr_new_handoff_v1',JSON.stringify(handoff));
    drop(j);if(sheetJob===j)sheetJob=null;
    $('newInlineStatus')?.remove();dismissOverlays();openConv(next,wasPreview);if(wasPreview)replaceUIState();if(focused){input.focus({preventScroll:true});input.setSelectionRange(...selection);}window.workspaceUI?.saveScene();window.sidebarUI?.highlight?.(next.app+':'+next.id);window.sidebarUI?.load(true);renderProgress();
  }
  async function send(){
    if(composing||starting||$('newBtn').disabled)return;
    const clock=performance.now();starting=true;paint();let rid;
    try{rid=await ensureDraft();}catch(e){starting=false;paint();$('newStatus').textContent='还没发出，草稿还在：'+e.message;return;}
    starting=false;
    // the draft becomes a job, and the sheet takes a fresh draft at once (10-16)
    const j=jobOf(d,{state:'creating',message:'正在创建对话…'});j.clientTiming={draft_ms:performance.now()-clock};clocks[rid]=clock;jobs.push(j);saveJobs();
    for(const v of d.images)if(v.url)URL.revokeObjectURL(v.url);  // the files stay in the browser's store, the job's now
    d=fresh(d);save();$('newText').value='';$('newSuggestions').hidden=true;trigger=null;searchSeq++;grow();
    document.activeElement?.blur();openPreview(j);paint();
    sending.add(rid);const sent=performance.now();
    try{j.pending=await api('/api/chat/new',j.body);}catch(e){j.pending={state:e.notSubmitted?'failed':'unconfirmed',message:e.message||'提交结果未确认，请核对'};}
    finally{sending.delete(rid);j.clientTiming.submit_roundtrip_ms=performance.now()-sent;saveJobs();renderProgress();if(jobs.includes(j)&&j.pending.state!=='failed')check(j);}
  }
  async function retry(j){
    const previous=j.pending,rid=j.request_id;if(!rid||sending.has(rid)||checking.has(rid)||!retryable(previous))return;
    sending.add(rid);clocks[rid]=performance.now();j.clientTiming={};j.timingReported=false;j.pending={...previous,state:'creating',message:'正在继续原请求…'};saveJobs();renderProgress();
    try{j.pending=previous.can_submit?await api('/api/chat/new',j.body):await api('/api/chat/new/retry',{request_id:rid});}
    catch(e){j.pending={...previous,state:'unconfirmed',can_submit:false,not_submitted:false,message:'继续发送的结果尚未确认，请核对结果'};toast(e.message,true);}
    finally{sending.delete(rid);j.clientTiming.submit_roundtrip_ms=performance.now()-clocks[rid];saveJobs();renderProgress();check(j);}
  }
  async function restore(j){  // a first message that was not sent goes back into the sheet, to change and send again
    if(j.pending?.state!=='failed')return;
    if((d.text.trim()||d.images.length||d.references.length)&&!(await askConfirm('新建窗口里有一份还没发的草稿。换成这条没发出去的内容吗？')))return;
    for(const v of d.images){fileStore('delete',v.localId).catch(()=>{});if(v.url)URL.revokeObjectURL(v.url);}
    const wasPreview=currentJob()===j;drop(j,true);if(sheetJob===j)sheetJob=null;
    d={...fresh(j),settings:d.settings||{},text:j.text,references:j.references,images:j.images.map(v=>({...v,meta:null,uploading:false,error:''}))};save();$('newText').value=d.text;
    closeSheet('newJobSheet');if(wasPreview)closeConv(true);
    openSheet('newSheet');paint();grow();for(const v of d.images)await upload(v);
  }
  async function remove(j){  // the phone stops following it; nothing on the computer changes
    const s=j.pending?.state;
    if(!(await askConfirm(s==='failed'?'这条首条消息没发出去。移除后手机上不再留着它的内容。移除吗？':s==='accepted'?'对话已经建好，在对话列表里能找到。移除这条提示吗？':'移除只是手机不再跟踪这一条，不会重复发送。电脑上如果已经建好对话，会照常出现在对话列表里。移除吗？')))return;
    const wasPreview=currentJob()===j;drop(j);if(sheetJob===j)sheetJob=null;closeSheet('newJobSheet');if(wasPreview)closeConv();renderProgress();
  }
  $('newBtn').onclick=send;
  $('newCheck').onclick=()=>{const j=sheetJob;if(j){delete notes[j.request_id];check(j);}};
  $('newRetry').onclick=()=>{if(sheetJob)retry(sheetJob);};
  $('newOpen').onclick=()=>{const j=sheetJob,p=j?.pending;if(!p?.id)return;if(p.state==='accepted'){finish(j);return;}closeSheet('newJobSheet');openConv({app:j.app,id:p.id,title:p.title||j.text.slice(0,50)||'新对话',folder:p.folder||'',status:'idle'});};
  $('newRestore').onclick=()=>{if(sheetJob)restore(sheetJob);};
  $('newDismiss').onclick=()=>{if(sheetJob)remove(sheetJob);};
  window.openNewSheet=async function(place){
    // place {app, folder, projectless, name}: a project's ＋ in the sidebar. A job under way no longer holds the sheet (10-16).
    if(!Object.keys(APP_ID).some(hasNew)){toast('这台电脑上没找到 Codex、Claude 或 DeepSeek Harness 桌面版',true);return;}
    if(place){const folder=place.projectless?'':place.folder||'';if(d.app!==place.app||d.folder!==folder||d.projectless!==!!place.projectless){d.references=d.references.filter(v=>v.kind!=='skill');searchSeq++;$('newSuggestions').hidden=true;}
      d.app=place.app;d.folder=folder;d.projectless=!!place.projectless&&place.app!=='deepseek';d.label=d.projectless?'':place.name||'';save();}
    openSheet('newSheet');paint();
    ensureDraft().catch(()=>{});
    await loadFolders();};
  for(const id of ['newPickerResults','newSuggestions'])$(id).addEventListener('keydown',e=>{if(!['ArrowDown','ArrowUp','Home','End'].includes(e.key))return;const rows=[...$(id).querySelectorAll('button')];if(!rows.length)return;e.preventDefault();const index=rows.indexOf(document.activeElement);rows[e.key==='Home'?0:e.key==='End'?rows.length-1:(index+(e.key==='ArrowDown'?1:-1)+rows.length)%rows.length].focus();});
  window.sendNew=send;window.newChatUI={open:window.openNewSheet,sync:renderProgress,isPreview,openPreview:()=>openPreview(jobs.at(-1)),decorateRows,renderFirst,route(c,fromHistory){
    if(!isPreview(c)){const done=jobs.find(j=>j.pending?.state==='accepted'&&j.pending.id===c.id&&j.app===c.app);if(done){drop(done);renderProgress();}return false;}  // opened from the list
    const j=jobs.find(v=>v.preview_id===c.id);if(j)openPreview(j,fromHistory);else if(handoff?.preview_id===c.id)openConv(handoff,fromHistory);else toast('这个创建请求已处理，请从对话列表打开');return true;}};
  $('cvText').addEventListener('compositionend',()=>setTimeout(settle,0));
  document.addEventListener('visibilitychange',()=>{const open=jobs.filter(j=>!['accepted','failed'].includes(j.pending?.state));if(document.hidden){for(const j of open){clearTimeout(timers[j.request_id]);j.clientTiming={...j.clientTiming,backgrounded:true};}saveJobs();}else for(const j of open)check(j);});
  setInterval(()=>{if(!document.hidden&&jobs.length){renderProgress();settle();}},500);
  for(const j of jobs.filter(j=>j.pending?.state==='accepted'&&Date.now()-(j.created||0)>86400000))drop(j);  // a day on, its conversation is in the list
  for(const v of d.images){v.uploading=false;if(!v.meta)v.error='图片尚未上传，请重试';}paint();
  for(const j of jobs)if(!['accepted','failed'].includes(j.pending?.state))check(j);
})();
