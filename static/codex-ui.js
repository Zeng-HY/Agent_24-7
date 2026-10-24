/* Codex composer controls. All effects go through authenticated, narrow endpoints. */
(() => {
  const drafts = new Map(), states = new Map(), requests = new Map();
  let modelEdit = null;
  const uid = () => [...crypto.getRandomValues(new Uint8Array(16))].map(v=>v.toString(16).padStart(2,'0')).join('');
  const same = (a,b) => JSON.stringify(a) === JSON.stringify(b);
  const canonicalSettings = value => value ? {...value,service_tier:(!value.service_tier||value.service_tier==='default')?null:value.service_tier==='fast'?'priority':value.service_tier} : null;
  const active = me => cur?.app === me.app && cur.id === me.id;
  const current = () => ['codex','claude','deepseek'].includes(cur?.app) ? cur : null;
  const storageKey = id => 'lbr_codex_draft_'+id;
  const localGet = (key,fallback) => { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch(e) { return fallback; } };
  function draft(id) {
    if (!drafts.has(id)) {
      const saved=localGet(storageKey(id),{});
      drafts.set(id,{settings:canonicalSettings(saved.settings),base:canonicalSettings(saved.base),images:(saved.images||[]).map(v=>({...v,status:v.meta?'ready':'failed',error:v.meta?'':'图片尚未上传，请重试'}))});
    }
    return drafts.get(id);
  }
  function save(id) {
    const d=draft(id);
    // pc: a picture picked on the computer (files-ui.js), read in again from there when its upload has to be redone
    try {localStorage.setItem(storageKey(id),JSON.stringify({settings:d.settings,base:d.base,images:d.images.map(v=>({localId:v.localId,name:v.name,size:v.size,meta:v.meta||null,...(v.pc?{pc:v.pc}:{})}))}));} catch(e) {toast('浏览器未能保存草稿，请保持页面打开',true);}
  }
  const css=document.createElement('style');
  css.textContent=`
    .cv-row{flex-direction:column;align-items:stretch}.composer-tools{position:absolute;left:8px;bottom:6px;right:58px;display:flex;gap:4px;align-items:center;height:44px}
    .composer-tools .icon-btn{display:flex;align-items:center;justify-content:center;flex:none;width:44px;height:44px;min-height:44px;padding:10px;line-height:1}
    .composer-chip{display:inline-flex;align-items:center;justify-content:center;gap:7px;height:44px;line-height:20px;border:0;background:transparent;border-radius:999px;padding:0 8px;min-height:44px;font-size:12px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:150px}
    .composer-label{display:block;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.composer-chip::after{content:'';flex:none;width:5px;height:5px;border:solid var(--muted);border-width:0 1.5px 1.5px 0;transform:translateY(-2px) rotate(45deg)}#modeChoice{flex-shrink:0}#modelChoice{min-width:0;flex-shrink:1}
    .composer-chip.is-plan{color:var(--blue);background:#eef2ff}.attachment-previews{display:flex;gap:12px;overflow-x:auto;padding:8px 4px;min-height:88px}
    .attachment-tile{position:relative;flex:none;width:76px;min-height:84px}.attachment-tile img{width:72px;height:64px;object-fit:cover;border-radius:12px;background:#fff;border:1px solid var(--line)}
    .attachment-tile .remove-image{position:absolute;top:-6px;right:-6px;min-width:44px;min-height:44px;border:0;background:transparent;padding:8px;color:var(--text)}
    .remove-image span{display:flex;align-items:center;justify-content:center;width:24px;height:24px;background:white;border:1px solid var(--line);border-radius:50%}
    .attachment-tile small{font-size:11px;color:var(--muted);display:block;max-width:76px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .attachment-tile .retry-image{font-size:11px;padding:2px 4px;min-height:28px;width:76px;color:var(--red)}.attachment-open{padding:0;border:0;background:transparent;min-height:64px}
    .codex-card{margin:20px 0;padding:16px;border:1px solid var(--line);border-radius:20px;background:#fff;box-shadow:0 2px 12px rgba(29,35,48,.025);font-size:15px;line-height:1.6}
    .card-title{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:16px;font-weight:600;margin:0 0 12px}.card-state{font-size:12px;color:var(--muted);font-weight:400}
    .option-card{display:flex;align-items:flex-start;gap:10px;width:100%;padding:12px;border:1px solid var(--line);border-radius:14px;text-align:left;font-weight:400;margin:8px 0;background:#fff;font-size:14px}
    .option-card[aria-checked=true]{border-color:var(--blue);background:#eef2ff}.option-card .choice-dot{width:18px;height:18px;border:1px solid var(--line);border-radius:50%;flex:none;margin-top:3px}
    .option-card[aria-checked=true] .choice-dot{border:5px solid var(--blue)}.option-card small{font-size:12px;color:var(--muted);display:block;margin-top:4px}
    .card-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}.card-actions button{font-size:14px;font-weight:500;padding:10px 16px;border-radius:999px}.card-note{font-size:13px;color:var(--muted);margin-top:8px;white-space:pre-wrap}.card-note.error{color:var(--red)}
    .plan-preview{max-height:240px;overflow:hidden;position:relative;font-size:14px;white-space:pre-wrap}.plan-preview.expanded{max-height:none}.plan-read{border:0;background:transparent;color:var(--blue);padding:8px 0;font-size:13px;font-weight:400}
    .plan-preview pre{overflow:auto;white-space:pre;font-size:12px;background:var(--bg);padding:8px;border-radius:8px}.sent-images{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}.sent-images button{padding:0;overflow:hidden;border:0;background:transparent;border-radius:14px}.sent-images img{display:block;width:110px;height:100px;object-fit:cover;border-radius:14px}.image-history{margin-left:auto;max-width:88%}.image-history .hint{text-align:right;font-size:11px}
    .codex-control-note{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--muted);padding:0 8px}.codex-control-note span{flex:1;max-height:40px;overflow:auto}.codex-control-note button{border:0;background:transparent;color:var(--blue);font-size:12px;padding:6px;flex:none}
    .model-list-row{display:flex;align-items:center;justify-content:space-between;gap:12px;width:100%;border:0;background:transparent;text-align:left;padding:12px;font-size:15px;font-weight:500;border-radius:14px}.model-list-row[aria-checked=true]{background:#eef2ff;color:var(--blue)}
    .effort-choices{display:flex;flex-wrap:wrap;gap:8px}.effort-choices button{font-size:13px;font-weight:400;padding:8px 12px;border-radius:999px}.effort-choices button[aria-checked=true]{background:#eef2ff;border-color:var(--blue);color:var(--blue)}
    #imagePreviewSheet .box{height:auto;background:#fff}#imagePreviewSheet img{width:100%;max-height:70dvh;object-fit:contain}.settings-notice{font-size:12px;color:var(--muted);line-height:1.6;margin:0}.setting-heading{font-size:14px;font-weight:600;margin:8px 0}
    .run-bar{display:flex;align-items:center;gap:8px;min-height:36px;padding:0 4px 4px 12px}.run-hint{flex:1;min-width:0;font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .run-queue{flex:none;min-height:36px;padding:6px 10px;border:0;border-radius:999px;background:transparent;color:var(--blue);font-size:13px;font-weight:500}.run-queue:active{background:#e8ecf7}.run-queue:disabled{color:var(--muted);opacity:.55}
    @media(max-width:370px){.composer-chip{font-size:11px;padding:8px 5px;max-width:135px}.composer-tools{gap:0}.codex-card{padding:12px}}
  `;
  document.head.append(css);
  const attachmentErrors=el('div','attachment-errors');attachmentErrors.id='attachmentErrors';attachmentErrors.hidden=true;attachmentErrors.setAttribute('role','status');attachmentErrors.setAttribute('aria-live','polite');$('attachmentPreviews').after(attachmentErrors);
  const errorStyle=el('style');errorStyle.textContent='.attachment-errors{font-size:13px;line-height:1.5;color:var(--red);white-space:pre-wrap;overflow-wrap:anywhere;max-height:120px;overflow-y:auto;padding:4px}.attachment-errors p{margin:4px 0}';document.head.append(errorStyle);
  const controlNote=el('div','codex-control-note');controlNote.id='codexControlNote';controlNote.hidden=true;controlNote.append(el('span',''));
  const connectButton=el('button','','电脑上打开');connectButton.onclick=async()=>{const me=current();if(!me)return;await openOnPC();if(active(me))await refresh(me,true);};controlNote.append(connectButton);$('runtimeBar').before(controlNote);
  function sheet(id,title,contents,popover=false) {
    const n=el('div','sheet'+(popover?' popover':''));n.id=id;n.setAttribute('aria-label',title);
    n.innerHTML='<div class="box"><div class="sh-head"><b></b><button class="icon-btn" aria-label="关闭">'+icon('close')+'</button></div><div class="sh-body"></div></div>';
    n.querySelector('b').textContent=title;n.querySelector('button').onclick=()=>closeSheet(id);n.querySelector('.sh-body').innerHTML=contents;
    n.addEventListener('click',e=>{if(e.target===n)closeSheet(id);});document.body.append(n);return n;
  }
  sheet('attachmentMenu','添加图片','<button class="menu-row" id="takePhoto">拍照</button><button class="menu-row" id="choosePhoto">从相册选择</button>',true);
  sheet('modelSheet','模型与推理强度','<div id="modelRows" role="radiogroup" aria-label="模型"></div><div class="setting-heading">推理强度</div><div id="effortRows" class="effort-choices" role="radiogroup" aria-label="推理强度"></div><div class="setting-heading">速度</div><div id="speedRows" class="effort-choices" role="radiogroup" aria-label="速度"></div><p id="speedNotice" class="settings-notice"></p><p id="modelNotice" class="settings-notice"></p><button class="big" id="applyModel">下条消息使用</button>');
  sheet('modeSheet','对话模式','<div id="modeRows" role="radiogroup"></div><p class="settings-notice">选择将在下条消息发送时生效，不会修改正在运行的任务。</p>');
  sheet('imagePreviewSheet','查看图片','<img id="fullImage" alt="图片预览">');
  const photo=el('input'),camera=el('input');
  for(const input of [photo,camera]){input.type='file';input.accept='image/*';input.hidden=true;document.body.append(input);input.addEventListener('change',()=>{addFiles([...input.files],input.targetConversation||current());input.value='';input.targetConversation=null;});}
  photo.multiple=true;camera.setAttribute('capture','environment');
  $('takePhoto').onclick=()=>{camera.targetConversation=current();closeSheet('attachmentMenu');camera.click();};
  $('choosePhoto').onclick=()=>{photo.targetConversation=current();closeSheet('attachmentMenu');photo.click();};
  // IndexedDB retains selected files across reloads, including interrupted uploads.
  let dbPromise=null;
  function filesDB(){return dbPromise ||= new Promise((resolve,reject)=>{const req=indexedDB.open('agent-remote-image-drafts',1);req.onupgradeneeded=()=>req.result.createObjectStore('files');req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);});}
  async function fileStore(op,key,value){const db=await filesDB();return new Promise((resolve,reject)=>{const tx=db.transaction('files',op==='get'?'readonly':'readwrite');const req=op==='put'?tx.objectStore('files').put(value,key):tx.objectStore('files')[op](key);let result;req.onsuccess=()=>{result=req.result;};tx.oncomplete=()=>resolve(result);tx.onerror=()=>reject(tx.error);});}
  function previewImage(meta){$('fullImage').src=meta.url;$('imagePreviewSheet').querySelector('b').textContent=meta.name||'查看图片';openSheet('imagePreviewSheet');}
  // The queue is visible only after sending; the ordinary send button queues during a running turn.
  const codexQueue=el('div','queue-strip');codexQueue.id='codexQueue';codexQueue.hidden=true;
  document.querySelector('.cv-row').before(codexQueue);
  const fileRefs=me=>window.referencesUI?.fileCount(me)||0,filesGoingUp=me=>window.referencesUI?.pendingCount(me)||0;
  async function queueAction(message,action){
    const me=current(),s=states.get(me?.id);if(me?.app!=='codex')return false;
    const key='lbr_queue_action_'+me.id+':'+message.id+':'+action;
    let body=localGet(key,null)||{id:me.id,message_id:message.id,action,expected_turn:s?.active_turn_id,request_id:uid()};
    try{localStorage.setItem(key,JSON.stringify(body));const result=await api('/api/codex/queue-action',body);toast(result.text||'已处理');await refresh(me,true);await workspaceUI.pollReceipts();return true;}
    catch(e){toast('结果待核对：'+e.message,true);await refresh(me,true);return false;}
  }
  function paintQueue(me,s){
    const codex=me?.app==='codex',native=codex?(s?.queued||[]).filter(q=>!window.workspaceUI?.delivered(q.id)):[],local=codex?window.workspaceUI?.pendingQueue(me)||[]:[],rows=[...native,...local.filter(q=>!native.some(n=>n.id===q.id))];
    if(codex)$('cvBtn').setAttribute('aria-label',s?.running?'发送并排队':'发送');
    // rebuilt only when it changes (this runs on every refresh): a tap on a button in it is not lost
    const sig=JSON.stringify([rows.map(q=>[q.id,q.text,q.status,!!q.local]),!!s?.running]);if(codexQueue.dataset.sig===sig)return;codexQueue.dataset.sig=sig;
    codexQueue.replaceChildren();codexQueue.hidden=!rows.length;
    for(const q of rows){const row=el('div','queue-row'+(q.status==='queued'?'':' waiting'));row.append(el('p','',q.text));
      const now=el('button','','立即补充'),x=el('button','queue-x','⋯');now.type=x.type='button';
      now.disabled=q.local||q.status!=='queued'||!s?.running;now.setAttribute('aria-label','把这条消息立即补充给这一轮');now.onclick=()=>queueAction(q,'promote');
      x.disabled=q.local||q.status!=='queued';x.setAttribute('aria-label','待发送消息操作');x.onclick=()=>workspaceUI.queueMenu(me,q,()=>queueAction(q,'cancel'));
      row.append(now,x);window.navigationUI?.tapTick?.(now);window.navigationUI?.tapTick?.(x);codexQueue.append(row);}
  }
  function paintComposer(){
    const me=current();$('codexComposerTools').hidden=me?.app!=='codex';$('attachmentPreviews').hidden=true;attachmentErrors.hidden=true;controlNote.hidden=true;
    paintQueue(me,states.get(me?.id));if(!me)return;
    const d=draft(me.id),s=states.get(me.id),settings=d.settings||s?.settings;
    const away=me.app==='codex' && !!s && !s.available;
    const modelName=s?.catalog?.models?.find(m=>m.id===settings?.model)?.name || modelLabel(settings?.model);
    $('modelChoice').querySelector('.composer-label').textContent=away ? '电脑上打开' : settings ? modelName + ' · '+(EFFORT[settings.effort]||settings.effort||'默认') : '模型';
    $('modelChoice').classList.toggle('is-away',away);$('modeChoice').hidden=away;
    $('modeChoice').querySelector('.composer-label').textContent=settings?.mode==='plan'?'计划模式':'普通执行';$('modeChoice').classList.toggle('is-plan',settings?.mode==='plan');
    $('modelChoice').disabled=sending || (!away && !s?.available);$('modeChoice').disabled=sending || !s?.available;$('addImageBtn').disabled=sending;
    $('cvText').placeholder=settings?.mode==='plan'?'说明需要规划或调整的内容…':'输入消息…';
    const box=$('attachmentPreviews');box.innerHTML='';box.hidden=!d.images.length;
    for(const image of d.images){
      const tile=el('div','attachment-tile'),open=el('button','attachment-open');open.type='button';open.setAttribute('aria-label','预览 '+image.name);
      const img=el('img');img.alt=image.name;img.src=image.meta?.thumbnail||image.localUrl||'';open.append(img);open.onclick=()=>previewImage(image.meta||{url:image.localUrl,name:image.name});tile.append(open);
      const remove=el('button','remove-image');remove.innerHTML='<span>×</span>';remove.setAttribute('aria-label','移除 '+image.name);remove.disabled=sending;remove.onclick=()=>removeImage(me,image.localId);tile.append(remove);
      tile.append(el('small','',image.status==='uploading'?'上传中…':image.status==='ready'?'待发送':image.error||'上传失败'));
      if(image.status==='failed'){const retry=el('button','retry-image','重试上传');retry.onclick=()=>uploadImage(me,image);tile.append(retry);}box.append(tile);
    }
    const failures=new Map();d.images.forEach((image,index)=>{if(image.status==='failed'){const text=image.error||'上传失败';if(!failures.has(text))failures.set(text,[]);failures.get(text).push(index+1);}});
    const errors=[...failures].map(([text,indices])=>'第 '+indices.join('、')+' 张：'+text),errorSig=JSON.stringify(errors);attachmentErrors.hidden=!errors.length;
    if(attachmentErrors.dataset.sig!==errorSig){attachmentErrors.replaceChildren(...errors.map(text=>el('p','',text)));attachmentErrors.dataset.sig=errorSig;}
    if(d.settings){$('runtimeScope').textContent='上次实际记录 · 已选择下轮设置';}
    updateSendButton();
  }
  async function addFiles(files,me){
    if(!me||sending)return;const d=draft(me.id);
    if(d.images.length+files.length>5){toast('每条消息最多 5 张图片',true);return;}
    if(files.some(f=>f.size>20*1024*1024)||d.images.reduce((n,v)=>n+v.size,0)+files.reduce((n,f)=>n+f.size,0)>50*1024*1024){toast('单张最多 20 MB，合计最多 50 MB',true);return;}
    for(const f of files){const image={localId:uid(),name:f.name||'照片',size:f.size,file:f,localUrl:URL.createObjectURL(f),status:'uploading'};d.images.push(image);save(me.id);paintComposer();try{await fileStore('put',image.localId,f);}catch(e){toast('图片草稿无法持久保存，请保持页面打开',true);}await uploadImage(me,image);}
  }
  async function uploadImage(me,image){
    if(image.inflight)return;image.inflight=true;image.status='uploading';if(active(me))paintComposer();
    try{
      if(image.pc&&!image.file){  // a picture on the computer: read in again from where it is
        const data=await api('/api/files/image',{ref:image.pc,app:me.app,id:me.id},30000);
        if(!draft(me.id).images.includes(image)){await api('/api/codex/remove-attachment',{id:me.id,attachment:data.id});return;}
        image.meta=data;image.status='ready';image.error='';return;
      }
      const file=image.file||await fileStore('get',image.localId);if(!file)throw Error('图片草稿不存在，请重新选择');
      image.file=file;if(!image.localUrl)image.localUrl=URL.createObjectURL(file);
      const response=await fetch('/api/codex/upload?app='+encodeURIComponent(me.app)+'&id='+encodeURIComponent(me.id)+'&name='+encodeURIComponent(image.name),{method:'POST',headers:{'Content-Type':file.type||'application/octet-stream'},body:file});
      const data=await response.json();if(!response.ok)throw Error(data.error||'上传失败');
      if(!draft(me.id).images.includes(image)){await api('/api/codex/remove-attachment',{id:me.id,attachment:data.id});return;}
      image.meta=data;image.status='ready';image.error='';
    }catch(e){image.status='failed';image.error=e.message;}
    finally{image.inflight=false;save(me.id);if(active(me))paintComposer();}
  }
  async function removeImage(me,id){const d=draft(me.id),image=d.images.find(v=>v.localId===id);d.images=d.images.filter(v=>v.localId!==id);save(me.id);paintComposer();if(image?.localUrl)URL.revokeObjectURL(image.localUrl);fileStore('delete',id).catch(()=>{});if(image?.meta)try{await api('/api/codex/remove-attachment',{id:me.id,attachment:image.meta.id});}catch(e){toast('已从草稿移除；电脑临时文件将过期清理',true);}}
  async function refresh(me,force=false){
    if(window.newChatUI?.isPreview(me))return;
    if(me.app!=='codex' || (!force && window.workspaceUI && !workspaceUI.canPoll()))return;if(requests.has(me.id)){if(!force)return requests.get(me.id);await requests.get(me.id);}
    const task=(async()=>{try{
      const data=await api('/api/codex/state?id='+encodeURIComponent(me.id)+(force?'&fresh=1':''));states.set(me.id,data);
      window.activityUI?.onControl(me,data);
      await applyState(me,data);}

      catch(e){states.set(me.id,{available:false,reason:e.message});if(active(me))paintComposer();}finally{requests.delete(me.id);}})();requests.set(me.id,task);return task;
  }
  async function applyState(me,data){
    if(me.app!=='codex'||!data)return;
    states.set(me.id,data);window.activityUI?.onControl(me,data);
      const pending=pendingSends.get(chatKey(me));
      if(pending?.request_id && pending.state==='unconfirmed'){
        try{const receipt=await api('/api/codex/receipt?id='+encodeURIComponent(me.id)+'&request_id='+encodeURIComponent(pending.request_id));if(receipt.state==='accepted')settleReceipt(me,pending,receipt.result);}catch(e){}
      }
      if(active(me) && !document.hidden && !window.workspaceUI?.composing && states.get(me.id)===data){
        if(data.available && typeof data.running==='boolean'){me.status=data.running?'running':'idle';$('cvMeta').textContent='Codex'+(me.folder?' · '+me.folder:'')+' · '+STATUS[me.status];}
        paintComposer();renderMsgs(currentMessages);renderAsk(me,data);
      }
  }
  function chooseSettings(me,values){const d=draft(me.id),s=states.get(me.id);if(!s?.available)return;d.base={...s.settings};d.settings={...(d.settings||s.settings),...values};save(me.id);paintComposer();hideNote();}
  function modelList(){return states.get(current()?.id)?.catalog?.models||[];}
  function renderModels(){
    const rows=$('modelRows');rows.innerHTML='';for(const m of modelList()){
      const b=el('button','model-list-row');b.setAttribute('role','radio');b.setAttribute('aria-checked',String(modelEdit.model===m.id));b.append(el('span','',m.name));if(modelEdit.model===m.id){const mark=el('span');mark.innerHTML=icon('check');b.append(mark);}
      b.onclick=()=>{modelEdit.model=m.id;if(!(m.service_tiers||[]).some(t=>t.id===modelEdit.service_tier))modelEdit.service_tier=null;if(!m.efforts.includes(modelEdit.effort))modelEdit.effort=m.default_effort||m.efforts[0];renderModels();};rows.append(b);
    }
    const efforts=$('effortRows');efforts.innerHTML='';const m=modelList().find(m=>m.id===modelEdit.model);
    for(const value of m?.efforts||[]){const b=el('button','',EFFORT[value]||value);b.setAttribute('role','radio');b.setAttribute('aria-checked',String(modelEdit.effort===value));b.onclick=()=>{modelEdit.effort=value;renderModels();};efforts.append(b);}
    const speeds=$('speedRows');speeds.replaceChildren();
    for(const tier of [{id:null,name:'标准'},...(m?.service_tiers||[])]){const b=el('button','',tier.name);b.setAttribute('role','radio');b.setAttribute('aria-checked',String((modelEdit.service_tier??null)===tier.id));b.onclick=()=>{modelEdit.service_tier=tier.id;renderModels();};speeds.append(b);}
    $('speedNotice').textContent=m?.service_tiers?.find(t=>t.id===modelEdit.service_tier)?.description||'速度与推理强度分别设置。Fast 模式可能增加用量。';
    $('applyModel').disabled=!m||!m.efforts.includes(modelEdit.effort);$('modelNotice').textContent='使用桌面最近的模型目录。目录更新时间：'+stamp(states.get(cur.id)?.catalog?.updated_at)+'。设置在下条消息发送时生效。';
  }
  $('applyModel').onclick=()=>{if(!current())return;chooseSettings(cur,modelEdit);closeSheet('modelSheet');toast('已选择下条消息的模型与推理强度');};
  async function openModels(){const me=current();if(!me)return;if(me.app==='codex'&&states.get(me.id)?.available===false){await openOnPC();if(active(me))await refresh(me,true);return;}await refresh(me,true);const s=states.get(me.id);if(!active(me)||!s?.available)return;modelEdit={...(draft(me.id).settings||s.settings)};renderModels();openSheet('modelSheet');}
  function openModes(){const me=current(),s=states.get(me?.id);if(!s?.available)return;const selected=draft(me.id).settings||s.settings,box=$('modeRows');box.innerHTML='';for(const [value,name,description] of [['default','普通执行','分析问题并完成你要求的操作。'],['plan','计划模式','先分析和制定计划，确认后再开始执行。']]){const b=el('button','option-card');b.setAttribute('role','radio');b.setAttribute('aria-checked',String(selected.mode===value));b.append(el('span','choice-dot'));const text=el('span','',name);text.append(el('small','',description));b.append(text);b.onclick=()=>{chooseSettings(me,{mode:value});closeSheet('modeSheet');toast('下条消息使用'+name);};box.append(b);}openSheet('modeSheet');}
  function hasChanges(me){const d=draft(me.id),s=states.get(me.id);return d.images.length>0||!!d.settings||!!window.referencesUI?.count();}
  function settleReceipt(me,ticket,result){
    ticket.state='delivered';ticket.note='已确认送达';persistPending();workspaceUI?.update(me,ticket);
    if(active(me)){if(ticket.state==='queued')hideNote();else showNote(ticket.note,'ok');}
  }
  async function send(planId=null,intent='auto'){
    const me=current();if(!me||sending||window.workspaceUI?.composing)return;const d=draft(me.id);
    const s=states.get(me.id);if(intent==='auto'&&s?.running&&!planId)intent='queue';if(!s?.available){showNote(s?.reason||'Codex 控制连接不可用','bad');return;}
    if(s.running&&intent!=='queue'&&d.settings){showNote('新模型设置需要排队；草稿已保留','warn');return;}
    if(d.images.some(v=>v.status!=='ready')){showNote('请先完成图片上传','warn');return;}
    if(!planId&&filesGoingUp(me)){showNote('文件还在传到电脑，传完再发；没传上的点「重试」或去掉','warn');return;}
    const originalText=$('cvText').value,text=planId?'请执行这份计划。':originalText.trim();if(!text&&!d.images.length&&!(!planId&&fileRefs(me)))return;saveDraft();
    const previous=pendingSends.get(chatKey(me));if(previous?.state==='unconfirmed' && !(await askConfirm('上一条消息的结果尚未确认，再次发送可能重复。仍要发送吗？')))return;
    const rid=uid(),settings={...(d.settings||s.settings)},base=d.base||s.settings;
    if(planId)settings.mode='default';
    const imageIds=d.images.map(v=>v.meta.id),ticket={text:text||(d.images.length?d.images.length+' 张图片':'附带的文件'),started:Date.now(),state:'sending',note:'正在发送给 Codex…',request_id:rid,originalText,draftSettings:d.settings?{...d.settings}:null};
    const sentImages=d.images.map(v=>({localId:v.localId,name:v.name,size:v.size,meta:v.meta,...(v.pc?{pc:v.pc}:{})}));
    const body={id:me.id,request_id:rid,text,attachments:imageIds,settings,expected_settings:base,intent,expected_turn:s.running?s.active_turn_id:null};if(planId)body.plan_id=planId;
    const references=planId?[]:window.referencesUI?.snapshot(me)||[];if(references.length)body.references=references;
    ticket.submission={text,attachments:imageIds,settings,plan_id:planId,references};
    try{workspaceUI.capture(me,ticket,{transport:'codex',body,images:sentImages,settings,base,originalText,plan:!!planId,references});}catch(e){toast(e.message,true);return;}
    d.images=[];d.settings=null;d.base=null;save(me.id);pendingSends.set(chatKey(me),ticket);persistPending();sending=true;paintComposer();if(intent!=='queue')showNote(ticket.note);else hideNote();renderMsgs(currentMessages);
    try{
      const result=await api('/api/codex/send',body);if(!result.accepted)throw Error(result.text||'Codex 尚未确认接收');
      ticket.state=result.delivery_state==='queued'?'queued':'delivered';ticket.note=result.text||'已交给 Codex';
      // Preserve the live composer. The accepted send is independent of its new draft.
      if(active(me)){if(ticket.state==='queued')hideNote();else showNote(ticket.note,'ok');}
    }catch(e){
      let receipt=null;try{receipt=await api('/api/codex/receipt?id='+encodeURIComponent(me.id)+'&request_id='+rid);}catch(ignore){}
      if(['accepted','queued','cancelled'].includes(receipt?.state)){
        ticket.state=receipt.state==='accepted'?'delivered':receipt.state;ticket.note=receipt.result?.text||'已交给 Codex';if(active(me)){if(ticket.state==='queued')hideNote();else showNote(ticket.note,'ok');}
      }else{ticket.state=e.notSubmitted||['unknown','rejected'].includes(receipt?.state)?'rejected':'unconfirmed';ticket.note=ticket.state==='rejected'?'未发送：'+e.message:'尚未确认送达；会继续按请求编号核对，不会自动重发。';if(active(me))showNote(ticket.note,ticket.state==='rejected'?'bad':'warn');}
    }finally{persistPending();window.workspaceUI?.update(me,ticket);sending=false;updateSendButton();if(active(me)){paintComposer();await loadConv(true);await refresh(me,true);schedulePoll();}}
  }
  const normalize = text => String(text||'').replace(/\s/g,'');
  function observations(){return states.get(current()?.id)||{};}
  function renderImages(node,images){const box=el('div','sent-images');for(const meta of images){const b=el('button');b.setAttribute('aria-label','查看 '+meta.name);const img=el('img');img.src=meta.thumbnail;img.alt=meta.name;img.loading='lazy';b.append(img);b.onclick=()=>previewImage(meta);box.append(b);}node.append(box);}
  const questionExpanded=new Map();
  function renderCard(node,custom){
    node.innerHTML='';node.className='codex-card';
    if(custom.type==='images'){node.className='image-history';renderImages(node,custom.post.images);node.append(el('div','hint',custom.post.status==='accepted'?'已发送图片':'图片发送结果待确认'));return;}
    if(custom.type==='answer'){
      const card=custom.card,key=chatKey(cur)+':'+card.id;const detail=el('details','question-history');detail.open=questionExpanded.get(key)||false;const questionTitle=card.questions[0]?.question||'问题';detail.append(el('summary','',(card.status==='answered'?'已答 · ':'待回答 · ')+questionTitle.slice(0,32)+(questionTitle.length>32?'…':'')));detail.addEventListener('toggle',()=>questionExpanded.set(key,detail.open));node.append(detail);node=detail;
      for(const q of card.questions){const a=card.answers?.[q.id];node.append(el('p','',q.question||''),el('b','',q.isSecret?'（已填写）':(Array.isArray(a)?a:a?.answers||[]).join('、')));}
      if(card.desktop_dismiss){const d=card.desktop_dismiss,reasons={unsubmitted_draft:'存在未提交修改',answer_not_rendered:'桌面答案尚未同步',editing:'正在编辑',window_not_visible:'窗口不可见',window_not_foreground:'目标窗口不在前台',no_matching_window:'目标对话当前不可见',disabled:'自动收起未启用',version_unverified:'桌面版本尚未验证',answer_superseded:'已有更新的答案',title_not_unique:'对话标题不唯一',unsupported_question:'此类问题不自动收起',draft_unreadable:'无法确认草稿状态',service_restarted:'服务已重启，未重复操作'};const text={pending:'桌面卡片：正在核对',closed:'桌面卡片已收起',not_present:'桌面卡片已不存在',unconfirmed:'桌面收起结果待核对'}[d.status]||'桌面卡片保留：'+(reasons[d.reason]||'未满足自动收起条件');node.append(el('div','card-note',text));}
      if(card.editable){const edit=el('button','','修改答案');edit.onclick=()=>{const me=current();if(!me)return;sentCards.delete(card.id);ask={me,card,sel:askLoad(me,card),page:0,busy:null,error:'',editing:true};for(const q of card.questions){const vals=card.answers?.[q.id]||[];ask.sel[q.id]={labels:vals,other:!vals.every(v=>(q.options||[]).some(o=>o.label===v)),text:vals.join('、')};}openAsk();};node.append(edit);}return;
    }
    if(custom.type==='plan'){
      if(!custom.plan.ready){
        const plan=custom.plan,key=chatKey(cur)+':plan:'+plan.id,detail=el('details','plan-history');detail.open=questionExpanded.get(key)||false;
        detail.append(el('summary','','历史计划'));const text=el('div','reply-text');text.innerHTML=md(plan.text,true);detail.append(text);detail.addEventListener('toggle',()=>questionExpanded.set(key,detail.open));node.className='historical-plan';node.append(detail);return;
      }
      const p=custom.plan;const title=el('div','card-title','计划');title.append(el('span','card-state',p.ready?'待确认':'历史计划'));node.append(title);
      const preview=el('div','plan-preview');preview.innerHTML=md(p.text);node.append(preview);const read=el('button','plan-read','展开完整计划');read.onclick=()=>{preview.classList.toggle('expanded');read.textContent=preview.classList.contains('expanded')?'收起计划':'展开完整计划';};node.append(read);
      const actions=el('div','card-actions'),run=el('button','big','执行计划'),edit=el('button','','继续修改');run.disabled=!p.ready||sending;edit.disabled=!p.ready||sending;
      run.onclick=()=>send(p.id);edit.onclick=()=>{const me=current();if(!me)return;chooseSettings(me,{mode:'plan'});$('cvText').focus();$('cvText').placeholder='写下需要调整的地方…';};actions.append(run,edit);node.append(actions);
      if(!p.ready)node.append(el('div','card-note','这份计划已进入后续对话，或当前任务尚未结束。'));return;
    }
  }
  // Codex asking (request_user_input) shows like Claude's (claude-ui.js; the user's pick, 10-11): a one-line strip above
  // the message box, and a sheet with one question at a time, each choice with its description. It used to be a form in
  // the conversation (10-12). Choices only update drafts; all answers require an explicit submit.
  // Picks are kept per question (lbr_question_…), secrets excepted.
  const askCss=el('style');askCss.textContent='#codexAskSheet .sh-body{gap:10px}.ask-head{font-size:13px;color:var(--muted);font-weight:500;margin-bottom:-4px}.ask-other{font:inherit;font-size:16px;width:100%;min-height:96px;padding:10px 12px;border:1px solid var(--line);border-radius:14px;resize:vertical;flex:none}.ask-review{display:flex;flex-direction:column;gap:8px}.ask-review button{display:block;width:100%;min-height:56px;margin:0;padding:12px 14px;border:1px solid var(--line);border-radius:14px;background:#fff;text-align:left;font-weight:400}.ask-review small{display:block;font-size:13px;color:var(--muted);margin-bottom:4px;line-height:1.5}.ask-review b{display:block;font-size:15px;font-weight:600;line-height:1.5;white-space:pre-wrap}';document.head.append(askCss);
  const askSheet=el('div','sheet');askSheet.id='codexAskSheet';askSheet.setAttribute('aria-label','Codex 在等你选');
  askSheet.innerHTML='<div class="box"><div class="sh-head"><b>Codex 在等你选</b><span class="ask-progress"></span><button class="icon-btn" aria-label="关闭">'+icon('close')+'</button></div><div class="sh-body"></div></div>';
  document.body.append(askSheet);askSheet.querySelector('.sh-head button').onclick=()=>closeSheet(askSheet.id);askSheet.onclick=e=>{if(e.target===askSheet)closeSheet(askSheet.id);};
  let ask=null;const sentCards=new Map(),askOpen=()=>overlays.some(o=>o.id===askSheet.id); // sentCards: answered here, still listed by Codex -> its conversation
  const askKey=(me,card)=>'lbr_question_'+me.id+':'+card.id;
  function askLoad(me,card){const saved=localGet(askKey(me,card),{}),sel={};for(const q of card.questions){const v=saved[q.id]||{};sel[q.id]={labels:Array.isArray(v.labels)?v.labels:[],other:!!v.other,text:q.isSecret?'':String(v.text||'')};}return sel;}
  function askSave(){if(!ask)return;const saved={};for(const q of ask.card.questions)if(!q.isSecret)saved[q.id]=ask.sel[q.id];try{localStorage.setItem(askKey(ask.me,ask.card),JSON.stringify(saved));}catch(e){}}
  function answerOf(q){const v=ask.sel[q.id];return v.other?(v.text.trim()?[v.text.trim()]:[]):v.labels;}
  const answered=q=>answerOf(q).length>0;
  function renderAsk(me,data){
    const box=$('cvOpts'),pending=(data?.questions||[]).filter(q=>q.status==='pending'&&q.questions?.length),card=pending[0];
    for(const [id,tid] of sentCards)if(tid===me.id&&!pending.some(q=>q.id===id))sentCards.delete(id);
    if(!card){if(ask?.editing&&ask.me.id===me.id){const latest=data?.questions?.find(q=>q.id===ask.card.id&&q.editable);if(latest){ask.card=latest;return;}}if(ask?.me.id===me.id){ask=null;if(askOpen())closeSheet(askSheet.id);}if(box.querySelector('.codex-ask'))box.replaceChildren();return;}
    const fresh=!ask||ask.me.id!==me.id||ask.card.id!==card.id,n=card.questions.length;
    if(ask?.editing&&askOpen())return;
    if(fresh){ask={me,card,sel:askLoad(me,card),page:0,busy:null,error:''};const first=card.questions.findIndex(q=>!answered(q));ask.page=first<0?(n>1?n:0):first;}
    const sent=sentCards.has(card.id),q=card.questions[0];
    const what=sent?'答案已提交，等 Codex 接着做':String(q.header||q.question||'Codex 在等你选').split('\n')[0]+(n>1?'（'+n+' 个问题）':'');
    const sig=JSON.stringify([me.id,card.id,what]);
    if(box.dataset.askSig!==sig||!box.querySelector('.codex-ask')){
      const pill=el('button','optbox ask-pill codex-ask');pill.type='button';pill.setAttribute('aria-label','Codex 在等你选，打开选项');
      pill.append(el('span','ask-dot'),el('span','ask-text',what),el('span','ask-go',sent?'刷新 ›':'去选择 ›'));
      pill.onclick=sent?()=>refresh(me,true):openAsk;box.dataset.askSig=sig;box.replaceChildren(pill);}
    if(fresh&&askOpen())paintAsk();
  }
  function openAsk(){if(!ask||sentCards.has(ask.card.id))return;paintAsk();if(!askOpen())openSheet(askSheet.id);}
  function paintAsk(){
    const body=askSheet.querySelector('.sh-body');body.replaceChildren();if(!ask)return;
    const qs=ask.card.questions,n=qs.length,busy=!!ask.busy;
    askSheet.querySelector('.ask-progress').textContent=n>1?(ask.page<n?(ask.page+1)+'/'+n:'核对'):'';
    if(ask.page>=n){paintReview(body);return;}
    const q=qs[ask.page],v=ask.sel[q.id],multi=!!q.isMultiple;
    if(q.header&&q.header!==q.question)body.append(el('div','ask-head',q.header));
    body.append(el('div','ask-title',q.question||''));
    const choice=(label,description,on,act,status)=>{
      const row=el('button','option-card ask-choice'),cap=el('span','ask-caption');row.type='button';row.setAttribute('role',multi?'checkbox':'radio');row.setAttribute('aria-checked',String(on));
      cap.append(el('b','',label));if(description)cap.append(el('small','',description));row.append(el('span','choice-dot'),cap);row.disabled=busy;
      if(status){row.classList.add('is-choosing');cap.append(el('small','ask-status',status));}
      row.onclick=act;window.navigationUI?.tapTick?.(row);body.append(row);};
    for(const o of q.options||[])choice(o.label,o.description,!v.other&&v.labels.includes(o.label),()=>pickChoice(q,o.label),ask.busy===o.label?'正在提交…':'');
    if(q.isOther!==false){
      choice('自行填写','',v.other,()=>{if(ask.busy)return;v.other=true;v.labels=[];askSave();paintAsk();askSheet.querySelector('.ask-other')?.focus();},'');
      if(v.other){const field=el(q.isSecret?'input':'textarea','ask-other');if(q.isSecret)field.type='password';field.placeholder='写下你的答案';field.setAttribute('aria-label',(q.question||'')+'：自行填写');field.value=v.text;field.disabled=busy;
        field.addEventListener('input',()=>{v.text=field.value;askSave();const next=askSheet.querySelector('.ask-next');if(next)next.disabled=!answered(q);});body.append(field);}
    }
    if(!(q.options||[]).length&&q.isOther===false)body.append(el('p','hint','这一题没有可选的答案，请在电脑上回答。'));
    if(ask.error)body.append(el('p','card-note error',ask.error));
    const bar=el('div','card-actions ask-nav');
    if(ask.page>0){const b=el('button','','上一题');b.type='button';b.disabled=busy;b.onclick=()=>{ask.page--;ask.error='';paintAsk();};window.navigationUI?.tapTick?.(b);bar.append(b);}
    {const b=el('button','big ask-next',n===1?(ask.busy?'提交中…':'提交答案'):ask.page===n-1?'完成':'下一题');b.type='button';b.disabled=busy||!answered(q);b.onclick=()=>advance(q);window.navigationUI?.tapTick?.(b);bar.append(b);}
    if(bar.children.length)body.append(bar);
  }
  function paintReview(body){
    const qs=ask.card.questions,busy=!!ask.busy;body.append(el('div','ask-title','核对一下答案，没问题就提交给 Codex。'));
    const list=el('div','ask-review');
    qs.forEach((q,i)=>{const b=el('button');b.type='button';b.disabled=busy;const v=ask.sel[q.id];
      b.append(el('small','',(i+1)+'. '+(q.header||q.question||'')),el('b','',q.isSecret&&v.other?'（已填写）':answerOf(q).join('、')||'还没回答'));
      b.onclick=()=>{ask.page=i;ask.error='';paintAsk();};list.append(b);});
    body.append(list);if(ask.error)body.append(el('p','card-note error',ask.error));
    const bar=el('div','card-actions ask-nav'),back=el('button','','上一题'),go=el('button','big',busy?'提交中…':'提交答案');back.type=go.type='button';back.disabled=busy;go.disabled=busy||!qs.every(answered);
    back.onclick=()=>{ask.page=qs.length-1;ask.error='';paintAsk();};go.onclick=()=>submit('submit');
    for(const b of [back,go])window.navigationUI?.tapTick?.(b);bar.append(back,go);body.append(bar);
  }
  function pickChoice(q,label){
    if(!ask||ask.busy)return;window.navigationUI?.haptic?.();const v=ask.sel[q.id];v.other=false; // Android; the iPhone ticks from the switch under the finger
    if(q.isMultiple){v.labels=v.labels.includes(label)?v.labels.filter(x=>x!==label):[...v.labels,label];askSave();paintAsk();return;}
    v.labels=[label];askSave();paintAsk();
  }
  function advance(q){
    if(!ask||ask.busy||!answered(q))return;const qs=ask.card.questions,n=qs.length;ask.error='';
    if(n===1){submit(q.isMultiple||ask.sel[q.id].other?'submit':ask.sel[q.id].labels[0]);return;}
    let next=qs.findIndex((x,i)=>i>ask.page&&!answered(x));if(next<0)next=qs.findIndex(x=>!answered(x));
    ask.page=next<0?n:next;paintAsk();
  }
  async function submit(marker){
    if(!ask||ask.busy)return;const {me,card}=ask,answers={};
    for(const [i,q] of card.questions.entries()){const vals=answerOf(q);if(!vals.length){ask.page=i;ask.error='这一题还没回答';paintAsk();return;}answers[String(q.id)]=vals;}
    ask.busy=marker;ask.error='';paintAsk();
    const attemptKey=askKey(me,card)+':attempt';let attempt=localGet(attemptKey,null),error=null;
    try{
      if(attempt){
        const receipt=await api('/api/codex/receipt?id='+encodeURIComponent(me.id)+'&request_id='+attempt.request_id);
        if(receipt.state==='accepted'){if(ask)ask.busy=null;localStorage.removeItem(attemptKey);sentCards.set(card.id,me.id);if(askOpen())closeSheet(askSheet.id);await refresh(me,true);return;}
        if(!['unknown','rejected'].includes(receipt.state))throw Error('上次答复仍待核对，请稍后核对；不会重复发送');
        if(receipt.state==='unknown'&&attempt.answers&&!same(attempt.answers,answers))throw Error('上次答复还未确认，请先核对原答复');
        if(receipt.state==='rejected')attempt=null;
      }
      attempt=attempt||{id:me.id,question_id:card.id,request_id:uid(),answers,answer_revision:card.answer_revision};
      if(!attempt.answers)attempt.answers=answers;
      const savedAttempt=card.questions.some(q=>q.isSecret)?{...attempt,answers:undefined}:attempt;
      localStorage.setItem(attemptKey,JSON.stringify(savedAttempt));
      const result=await api('/api/codex/answer',attempt);if(!result.ok)throw Error(result.text||'答复未提交');
      localStorage.removeItem(attemptKey);
    }catch(e){error=e;if(e.notSubmitted){localStorage.removeItem(attemptKey);const fresh=states.get(me.id)?.questions?.find(q=>q.id===card.id);if(fresh)card.answer_revision=fresh.answer_revision;}}
    if(ask?.card.id!==card.id)return;ask.busy=null;
    if(error){ask.error='提交结果未确认：'+error.message+'。请先刷新查看，不会重复提交。';paintAsk();if(active(me))refresh(me,true);return;}
    sentCards.set(card.id,me.id);try{localStorage.removeItem(askKey(me,card));}catch(e){}
    const only=card.questions.length===1&&!card.questions[0].isSecret;toast(only?'已选：'+answers[String(card.questions[0].id)].join('、'):'答案已提交给 Codex');
    if(askOpen())closeSheet(askSheet.id);if(active(me)){renderAsk(me,states.get(me.id));await refresh(me,true);}
  }
  const showPendingBase=window.showPending; // the bar under the title opens the sheet too
  window.showPending=()=>{if(ask&&cur?.app==='codex'&&cur.id===ask.me.id)openAsk();else showPendingBase?.();};
  async function onOpen(me){
    if(ask&&ask.me.id!==me.id){ask=null;if(askOpen())closeSheet(askSheet.id);}
    $('codexComposerTools').hidden=me.app!=='codex';$('attachmentPreviews').hidden=true;attachmentErrors.hidden=true;controlNote.hidden=true;if(!['codex','claude','deepseek'].includes(me.app))return;
    const d=draft(me.id);paintComposer();
    for(const image of d.images)if(!image.meta)try{const f=await fileStore('get',image.localId);if(f){image.file=f;image.localUrl=URL.createObjectURL(f);}}catch(e){}
    const ready=d.images.filter(v=>v.meta);if(ready.length)try{const data=await api('/api/codex/attachments?id='+encodeURIComponent(me.id)+'&ids='+ready.map(v=>v.meta.id).join(','));const valid=new Map(data.items.map(v=>[v.id,v]));for(const image of ready)if(!valid.has(image.meta.id)){image.meta=null;image.status='failed';image.error='图片已过期，请重试或重新选择';}save(me.id);}catch(e){}
    if(active(me))paintComposer();await refresh(me,true);
  }
  window.codexUI={onOpen,applyState,setClaudeImages(me,images){states.set(me.id,{images});},saveCurrentDraft(){if(current())save(cur.id);},
    async restoreSubmission(item){const d=draft(item.id);d.images=(item.images||[]).map(v=>({...v,status:'ready'}));d.settings=canonicalSettings(item.settings);d.base=canonicalSettings(item.base);save(item.id);if(current()?.id===item.id)await onOpen(cur);},
    onClose(){if(current())save(cur.id);ask=null;if(askOpen())closeSheet(askSheet.id);},refresh,observations,renderCard,renderImages,openModels,openModes,
    openAttachments(anchor){if(current())openSheet('attachmentMenu',anchor);},
    imageSnapshot(me=cur){return draft(me.id).images.map(v=>({localId:v.localId,name:v.name,size:v.size,meta:v.meta,...(v.pc?{pc:v.pc}:{})}));},
    clearImages(me){draft(me.id).images=[];save(me.id);if(active(me))paintComposer();},
    // pictures and attached files (files-ui.js): either is enough to send
    attachmentCount(){return current()?draft(cur.id).images.length+fileRefs(cur):0;},
    // A running thread's images/settings cannot be submitted, but let Send explain why instead of looking frozen.
    blocked(){if(!current())return false;return draft(cur.id).images.some(v=>v.status!=='ready')||filesGoingUp(cur)>0;},
    shouldSendEnhanced(){return current()?.app==='codex';},send,
    // files-ui.js: photos among the files picked on the phone; a picture on the computer the service read in (pc: where it is)
    addPhotos(me,files){return addFiles(files,me);},photoRoom(me){return 5-draft(me.id).images.length;},
    addImported(me,meta,pc){const d=draft(me.id);if(d.images.length>=5)return false;d.images.push({localId:uid(),name:meta.name||pc.name,size:meta.original_size||pc.size||0,meta,pc,status:'ready',error:''});save(me.id);if(active(me))paintComposer();updateSendButton();return true;}};
  // Match keyboard navigation used by existing sheet controls.
  document.addEventListener('keydown',e=>{const top=overlays.at(-1)?.id;if(!['modelSheet','modeSheet','claudeSettingSheet'].includes(top)||!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key))return;const group=document.activeElement.closest('[role=radiogroup]');if(!group)return;const rows=[...group.querySelectorAll('[role=radio]:not(:disabled)')],i=rows.indexOf(document.activeElement);if(i<0)return;e.preventDefault();rows[(i+(['ArrowDown','ArrowRight'].includes(e.key)?1:-1)+rows.length)%rows.length].focus();});
  updateSendButton();
})();
