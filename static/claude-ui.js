/* Claude controls read and operate the existing desktop session. */
(() => {
  let currentData=null,loading=false,menuTarget=null,actionSig='';const cache=new Map();
  const controls=el('div','composer-tools');controls.id='claudeComposerTools';controls.hidden=true;
  const model=el('button','composer-chip','读取模型'),effort=el('button','composer-chip','强度'),modeButton=el('button','composer-chip','模式');
  model.setAttribute('aria-label','选择 Claude 模型');effort.setAttribute('aria-label','选择 Claude 推理强度');modeButton.setAttribute('aria-label','选择 Claude 模式');controls.append(model,modeButton);$('cvBtn').before(controls);
  const sheet=el('div','sheet');sheet.id='claudeSettingSheet';sheet.setAttribute('aria-label','Claude 设置');sheet.innerHTML='<div class="box"><div class="sh-head"><b>Claude 设置</b><button class="icon-btn" aria-label="关闭">'+icon('close')+'</button></div><div class="sh-body"></div></div>';document.body.append(sheet);sheet.querySelector('button').onclick=()=>closeSheet(sheet.id);sheet.onclick=e=>{if(e.target===sheet)closeSheet(sheet.id);};
  const note=el('div','codex-control-note');note.id='claudeControlNote';note.hidden=true;const label=el('span'),open=el('button','','电脑上打开');note.append(label,open);$('runtimeBar').before(note);
  const active=me=>cur?.app==='claude'&&cur.id===me.id;
  const stop=el('button','stop-turn','停止这一轮');stop.hidden=true;document.querySelector('.cv-top .cv-title').after(stop);window.navigationUI?.tapTick?.(stop);
  // Like the desktop: a message sent while Claude is busy waits in Claude's queue, shown right above the
  // input box; the button next to it hands it to the running task at once.
  const queue=el('div','queue-strip');queue.id='claudeQueue';queue.hidden=true;document.querySelector('.cv-row').before(queue);
  const style=el('style');style.textContent='.queue-strip{display:flex;flex-direction:column;margin:0 0 8px;padding:4px 0;background:var(--bg);border-radius:18px}.queue-head{padding:4px 14px 2px;font-size:12px;color:var(--muted)}.queue-row{display:flex;align-items:center;gap:2px;min-height:44px;padding:4px 4px 4px 14px}.queue-row+.queue-row{border-top:1px solid var(--line)}.queue-row p{flex:1;min-width:0;margin:0 6px 0 0;font-size:14px;line-height:1.45;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;word-break:break-word}.queue-row.waiting p{color:var(--muted)}.queue-row button{flex:none;min-height:36px;padding:6px 10px;border:0;border-radius:999px;background:transparent;color:var(--blue);font-size:13px;font-weight:500}.queue-row button:active{background:#e8ecf7}.queue-row button:disabled{opacity:.4}.queue-row button.queue-x{min-width:36px;padding:4px 8px;color:var(--muted);font-size:20px;line-height:1;font-weight:400}.composer-chip.is-away{color:var(--blue)}.composer-chip.is-away::after{content:none}';document.head.append(style);
  // Claude asking (a question, a plan choice, a permission): a one-line strip above the message box; tapping it opens
  // a sheet with the question, each choice with its description, and the navigation. The user's pick (10-11): the
  // strip does not crowd the conversation or fight the keyboard. A tapped choice ticks at once (a see-through switch
  // over it) and says it is being clicked on the PC; the next question, or nothing, replaces it when that is done.
  const askCss=el('style');askCss.textContent='.ask-pill{display:flex;align-items:center;gap:8px;width:100%;min-height:44px;padding:8px 12px;border-radius:16px;text-align:left;color:var(--text);font-weight:500}.ask-pill .ask-dot{width:8px;height:8px;border-radius:50%;background:#f97316;flex:none;box-shadow:0 0 0 4px rgba(249,115,22,.15)}.ask-pill .ask-text{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px}.ask-pill .ask-go{flex:none;color:#c2410c;font-size:13px;font-weight:600}#claudeAskSheet .sh-head .ask-progress{font-size:13px;color:var(--muted);font-weight:500}#claudeAskSheet .sh-body{gap:10px}.ask-title{font-size:16px;font-weight:600;line-height:1.55;white-space:pre-wrap;max-height:30dvh;overflow:auto}.ask-choice{position:relative;margin:0;padding:14px;min-height:56px}.ask-caption{flex:1;min-width:0}.ask-choice b{display:block;font-size:15px;font-weight:600;line-height:1.45}.ask-choice small{display:block;margin-top:4px;font-size:13px;color:var(--muted);line-height:1.5;white-space:pre-wrap}.ask-choice.is-choosing,.ask-choice.is-choosing:disabled,.mode-choice.is-choosing,.mode-choice.is-choosing:disabled{border-color:var(--blue);background:#eef2ff;opacity:1}.ask-choice.is-choosing .choice-dot,.mode-choice.is-choosing .choice-dot{border:2px solid var(--blue);border-right-color:transparent;animation:askSpin .8s linear infinite}.ask-choice .ask-status,.mode-choice .ask-status{color:var(--blue);font-weight:500}.ask-nav{justify-content:flex-end;margin-top:4px}.ask-nav button{position:relative}@keyframes askSpin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.ask-choice.is-choosing .choice-dot,.mode-choice.is-choosing .choice-dot{animation:none}}';document.head.append(askCss);
  const askSheet=el('div','sheet');askSheet.id='claudeAskSheet';askSheet.setAttribute('aria-label','Claude 在等你选');
  askSheet.innerHTML='<div class="box"><div class="sh-head"><b>Claude 在等你选</b><span class="ask-progress"></span><button class="icon-btn" aria-label="关闭">'+icon('close')+'</button></div><div class="sh-body"></div></div>';
  document.body.append(askSheet);askSheet.querySelector('.sh-head button').onclick=()=>closeSheet(askSheet.id);askSheet.onclick=e=>{if(e.target===askSheet)closeSheet(askSheet.id);};
  let ask=null,choosing=false;const askOpen=()=>overlays.some(o=>o.id===askSheet.id);
  function askParts(data){ // the prompt as the PC lays it out, or (an older service) just its buttons
    const p=data.prompt;if(p&&(p.choices?.length||p.nav?.length))return p;const acts=data.actions||[];if(!acts.length)return null;
    return {title:'',progress:null,choices:acts.map(a=>({name:a.name,label:a.name,description:'',token:a.token})),nav:[],other:null};}
  function renderAsk(me,data){
    const p=askParts(data),box=$('cvOpts');
    if(!p){ask=null;box.replaceChildren();if(askOpen())closeSheet(askSheet.id);return;}
    ask={me,p,plan:data.settings?.mode==='plan',choosing:ask?.me===me?ask.choosing:null,error:''};
    const pill=el('button','optbox ask-pill');pill.type='button';pill.setAttribute('aria-label','Claude 在等你选，打开选项');
    const what=p.title?p.title.split('\n')[0]:(ask.plan?'计划与执行选项':'Claude 在等你选');
    pill.append(el('span','ask-dot'),el('span','ask-text',what+(p.progress?'（'+p.progress.replace(/\s+/g,'')+'）':'')),el('span','ask-go','去选择 ›'));
    pill.onclick=openAsk;box.replaceChildren(pill);if(askOpen())paintAsk();
  }
  function openAsk(){if(!ask)return;paintAsk();if(!askOpen())openSheet(askSheet.id);}
  function paintAsk(){
    const body=askSheet.querySelector('.sh-body'),p=ask?.p;askSheet.querySelector('.ask-progress').textContent=p?.progress?p.progress.replace(/\s+/g,''):'';
    askSheet.querySelector('.sh-head b').textContent=ask?.plan?'计划与执行选项':'Claude 在等你选';body.replaceChildren();if(!p)return;
    if(p.title)body.append(el('div','ask-title',p.title));
    for(const c of p.choices){
      const row=el('button','option-card ask-choice'),cap=el('span','ask-caption');row.type='button';cap.append(el('b','',c.label));if(c.description)cap.append(el('small','',c.description));
      row.append(el('span','choice-dot'),cap);if(c.pressed)row.setAttribute('aria-checked','true');
      if(ask.choosing){row.disabled=true;if(ask.choosing===c.name){row.classList.add('is-choosing');cap.append(el('small','ask-status','正在电脑上点选…'));}}
      if(!c.token)row.disabled=true;row.onclick=()=>pick(c,true);window.navigationUI?.tapTick?.(row);body.append(row);}
    if(p.other)body.append(el('p','hint','要自己写答案的话，请在电脑上点「Other」填写。'));
    if(ask.error)body.append(el('p','card-note error',ask.error));
    if(p.nav?.length){const bar=el('div','card-actions ask-nav');for(const n of p.nav){const b=el('button',n.name==='Next'||n.name==='Submit'?'big':'',ask.choosing===n.name?n.label+'…':n.label);b.type='button';b.disabled=!!ask.choosing||!n.token;b.onclick=()=>pick(n,false);window.navigationUI?.tapTick?.(b);bar.append(b);}body.append(bar);}
  }
  async function pick(part,isChoice){
    if(!ask||ask.choosing||!part.token)return;window.navigationUI?.haptic?.(); // Android; the iPhone ticks from the switch under the finger
    const me=ask.me;ask.choosing=part.name;ask.error='';paintAsk();choosing=true;
    let result=null,error=null;try{result=await api('/api/claude/choose',{id:me.id,token:part.token});}catch(e){error=e;}
    choosing=false;if(!active(me))return;if(ask){ask.choosing=null;paintAsk();}actionSig='';
    if(error){if(ask){ask.error=error.message;paintAsk();}refresh(me,true);return;}
    toast(isChoice?'已选：'+part.label:'已点「'+part.label+'」');if(result.state)paint(me,result.state);else refresh(me,true);
  }
  const showPendingBase=window.showPending; // the alert at the top opens the sheet too
  window.showPending=()=>{if(ask&&cur?.app==='claude')openAsk();else showPendingBase?.();};
  const norm=t=>String(t||'').replace(/\s+/g,' ').trim().slice(0,40);
  const sameText=(a,b)=>{a=norm(a);b=norm(b);return !!a&&!!b&&(a===b||a.startsWith(b)||b.startsWith(a));};
  function renderQueue(me=cur){
    if(!me||me.app!=='claude'||!active(me)){queue.hidden=true;queue.dataset.sig='';return;}
    const desk=(currentData?.queued||[]).map(q=>({text:q.text,q})),mine=window.workspaceUI?.queued?.(me)||[];
    const rows=[...desk,...mine.filter(m=>!desk.some(d=>sameText(d.text,m.text))).map(m=>({text:m.text,rid:m.rid}))];
    const sig=JSON.stringify(rows.map(r=>[r.text,r.q?.token||'',r.rid||'']));if(sig===queue.dataset.sig)return;queue.dataset.sig=sig;
    queue.replaceChildren();queue.hidden=!rows.length;if(rows.length)queue.append(el('div','queue-head','排队中 · 这一轮做完后依次发出'));
    for(const r of rows){const row=el('div','queue-row'+(r.q?'':' waiting'));row.append(el('p','',r.text));
      if(r.q){const now=el('button','','立即补充');now.setAttribute('aria-label','把这条消息立即交给正在进行的任务');now.onclick=()=>choose(me,r.q,now);window.navigationUI?.tapTick?.(now);row.append(now);}
      else if(r.rid){const x=el('button','queue-x','×');x.setAttribute('aria-label','移除这条记录');x.onclick=()=>window.workspaceUI?.dismissRid(r.rid);row.append(x);}
      queue.append(row);}
  }
  function paint(me,data){if(!active(me)||workspaceUI.composing)return;currentData=data;cache.set(me.id,data);window.codexUI?.setClaudeImages(me,data.images||[]);controls.hidden=false;
    // Model, effort and mode come from the conversation's own record and the lists kept from the PC, so they show while
    // the PC shows another conversation; a pick switches the PC there itself (10-12; the chip used to say 电脑上打开 and
    // needed a second tap). Only with nothing recorded does the chip open the conversation on the PC.
    const s=data.settings||{},away=!data.available&&!s.model;model.classList.toggle('is-away',away);modeButton.hidden=away;
    const name=data.model_label||data.recorded_label||(s.model?modelLabel(s.model):'');
    const plan=data.mode_label?/^plan/i.test(data.mode_label):s.mode==='plan';if(data.mode_options?.length)keepModes(data.mode_options); // the desktop's own mode button first
    model.textContent=away?'电脑上打开':name?name+' · '+(EFFORT[s.effort]||s.effort||data.effort_label||'默认'):'模型';effort.textContent=EFFORT[s.effort]||s.effort||'强度';modeButton.textContent=plan?'计划模式':modeShown(data,s);modeButton.classList.toggle('is-plan',plan);
    note.hidden=true;
    stop.hidden=!data.stop_token;stop.disabled=false;stop.onclick=()=>{stop.textContent='正在核对停止…';choose(me,{token:data.stop_token},stop);};if(!data.running)stop.textContent='停止这一轮';
    renderQueue(me);document.querySelectorAll('#cvMsgs .task-card').forEach(markTask);
    if(data.runtime)renderRuntime(data.runtime);
    const sig=JSON.stringify([data.action_revision,data.actions,data.prompt]);if(sig===actionSig)return;actionSig=sig;
    renderAsk(me,data);
  }
  // No polling while a choice is being clicked on the PC: a poll holds the service's Claude lock for ~1.4 s.
  // A fresh read asked for while another read is under way runs right after it, rather than being dropped: after 电脑上打开
  // the timed read already under way came back with the old state, and the chip needed a second tap (10-12).
  let again=false;
  async function refresh(me=cur,force=false){if(!me||window.newChatUI?.isPreview(me)||me.app!=='claude'||choosing||(!force&&!workspaceUI.canPoll()))return;if(loading){again=again||force;return;}loading=true;
    try{const data=await api('/api/claude/state?id='+encodeURIComponent(me.id)+(force?'&fresh=1':''),undefined,20000);cache.set(me.id,data);paint(me,data);}catch(e){if(active(me)){note.hidden=false;label.textContent='Claude 状态读取失败：'+e.message;}}finally{loading=false;if(again){again=false;refresh(cur,true);}}}
  async function choose(me,choice,button,value){if(!active(me))return;button.disabled=true;
    try{const result=await api('/api/claude/choose',{id:me.id,token:choice.token,...(value!==undefined?{value}: {})});if(active(me)){if(overlays.some(o=>o.id===sheet.id))closeSheet(sheet.id);if(result.state)paint(me,result.state);toast(result.text||'已操作，正在核对');if(!result.state)await refresh(me,true);}}
    catch(e){toast(e.message,true);button.disabled=true;button.textContent='结果未确认，请刷新选项';}
  }
  async function openMenu(kind){if(cur?.app!=='claude')return;const me={...cur};menuTarget=me;const body=sheet.querySelector('.sh-body');body.textContent='正在读取桌面选项…';sheet.querySelector('b').textContent={model:'Claude 模型',effort:'Claude 推理强度',mode:'Claude 模式'}[kind];openSheet(sheet.id);
    try{const data=await api('/api/claude/menu',{id:me.id,kind});if(kind==='mode')keepModes(data.items);if(!active(me)||menuTarget!==me)return;body.innerHTML='';
      for(const choice of data.items||[]){if(choice.range){const r=choice.range,slider=el('input'),current=el('div','hint','当前：'+r.label),apply=el('button','big','应用强度');slider.type='range';slider.min=r.min;slider.max=r.max;slider.step=r.step;slider.value=r.value;slider.setAttribute('aria-label','Claude 推理强度档位');slider.style.cssText='width:100%;min-height:44px;accent-color:var(--blue)';slider.oninput=()=>{current.textContent=Number(slider.value)===r.value?'当前：'+r.label:'待选第 '+(Math.round((Number(slider.value)-r.min)/r.step)+1)+' 档';};apply.onclick=()=>choose(me,choice,apply,Number(slider.value));body.append(current,slider,el('div','hint','左侧更快，右侧思考更深入；应用后读取桌面的实际档位名称。'),apply);continue;}
        const b=el('button','option-card',choice.name);b.setAttribute('role','radio');b.setAttribute('aria-checked',String(choice.selected));b.onclick=()=>choose(me,choice,b);body.append(b);}
      body.append(el('p','hint',data.notice||'选项直接读取自 Claude 桌面。'));if(!data.items?.length)body.append(el('div','hint','桌面没有返回可操作选项。'));
    }catch(e){if(active(me))body.textContent=e.message;}}
  const catalogs=new Map();let catalogVersion=0;
  function savedCatalog(me){if(catalogs.has(me.id))return catalogs.get(me.id);try{const own=JSON.parse(localStorage.getItem('lbr_claude_catalog_'+me.id));if(own)return own;const last=JSON.parse(localStorage.getItem('lbr_claude_catalog_last'));if(last?.model_id!==(cache.get(me.id)?.settings?.model))return null;for(const v of last.fast||[])v.selected=null;for(const v of last.effort||[])if(v.range)v.range.value=null;last.borrowed=true;return last;}catch(e){return null;}}
  function renderCatalog(me,data,busy=false){
    if(!active(me)||menuTarget!==me)return;const body=sheet.querySelector('.sh-body');body.replaceChildren();
    if(!data){body.append(el('p','hint','首次读取桌面模型目录…'));return;}
    const rows=el('div');rows.setAttribute('role','radiogroup');rows.setAttribute('aria-label','模型');
    async function change(kind,choice,value){if(busy)return;renderCatalog(me,data,true);try{const result=await api('/api/claude/setting',{id:me.id,kind,name:choice.name,value,expected_model:data.model_id});if(result.state)paint(me,result.state);if(result.catalog){catalogs.set(me.id,result.catalog);try{localStorage.setItem('lbr_claude_catalog_'+me.id,JSON.stringify(result.catalog));}catch(e){}renderCatalog(me,result.catalog);}else await loadCatalog(me,true);toast('已应用到此 Claude 会话');}catch(e){if(active(me)&&menuTarget===me){renderCatalog(me,data);body.prepend(el('p','hint',e.message));}}}
    for(const choice of data.model||[]){const b=el('button','model-list-row');b.setAttribute('role','radio');b.setAttribute('aria-checked',String(choice.selected));b.append(el('span','',choice.name));if(choice.selected){const mark=el('span');mark.innerHTML=icon('check');b.append(mark);}b.disabled=busy;b.onclick=()=>change('model',choice);rows.append(b);}body.append(rows,el('div','setting-heading','推理强度'));
    const efforts=el('div','effort-choices');efforts.setAttribute('role','radiogroup');efforts.setAttribute('aria-label','推理强度');
    for(const choice of data.effort||[]){if(choice.range){const r=choice.range;for(let v=r.min;r.step>0&&v<=r.max&&v<r.min+20*r.step;v+=r.step){const b=el('button','',r.labels?.[String(v)]||(v===r.value?r.label:'第 '+(Math.round((v-r.min)/r.step)+1)+' 档'));b.setAttribute('role','radio');b.setAttribute('aria-checked',String(v===r.value));b.disabled=busy;b.onclick=()=>change('effort',choice,v);efforts.append(b);}}else{const b=el('button','',choice.name);b.disabled=busy;b.setAttribute('role','radio');b.setAttribute('aria-checked',String(choice.selected));b.onclick=()=>change('effort',choice);efforts.append(b);}}
    body.append(efforts);if(!data.effort?.length)body.append(el('p','hint',data.effort_reason||'当前模型未提供推理强度设置。'));
    body.append(el('div','setting-heading','速度'));const speeds=el('div','effort-choices');speeds.setAttribute('role','radiogroup');speeds.setAttribute('aria-label','速度');
    const fast=data.fast?.[0];for(const [value,name] of [[false,'标准'],[true,'Fast']]){const b=el('button','',name);b.disabled=busy||!fast;b.setAttribute('role','radio');b.setAttribute('aria-checked',String(!!fast&&fast.selected===value));b.onclick=()=>change('fast',fast,value);speeds.append(b);}body.append(speeds,el('p','settings-notice',fast?'Fast 模式可能增加用量；推理强度独立设置。':'当前桌面未提供可操作的 Fast 开关。'));
    if(currentData&&!currentData.on_screen)body.append(el('p','settings-notice','电脑上现在开着别的对话；选了以后，电脑上的 Claude 会先切到这个对话再改。'));
    body.append(el('p','settings-notice',(data.borrowed?'已复用相同模型的桌面目录；本会话当前选项请点刷新核对。':'')+'目录更新时间：'+new Date(data.updated_at).toLocaleString()+'。选择后应用到此会话；正在运行的请求不保证立即改变。'));
    const refresh=el('button','','刷新桌面目录');refresh.disabled=busy;refresh.onclick=()=>loadCatalog(me,true);body.append(refresh);
  }
  async function loadCatalog(me,fresh=false){const version=++catalogVersion;try{const data=await api('/api/claude/catalog',{id:me.id,fresh});if(!active(me)||menuTarget!==me||version!==catalogVersion)return;catalogs.set(me.id,data);try{localStorage.setItem('lbr_claude_catalog_'+me.id,JSON.stringify(data));localStorage.setItem('lbr_claude_catalog_last',JSON.stringify(data));}catch(e){}renderCatalog(me,data);}catch(e){if(active(me)&&menuTarget===me){renderCatalog(me,savedCatalog(me));sheet.querySelector('.sh-body').prepend(el('p','hint',e.message));}}}
  const unknown=()=>currentData&&!currentData.available&&!currentData.settings?.model; // nothing recorded: read it on the PC
  function openModels(){if(cur?.app!=='claude')return;if(unknown()){open.onclick();return;}const me={...cur};menuTarget=me;sheet.querySelector('b').textContent='模型与推理强度';openSheet(sheet.id);renderCatalog(me,savedCatalog(me));loadCatalog(me);}
  // Modes (Plan / Ask…) list at once, like the models: the choices last read on the PC, the current one from the mode
  // button by Claude's message box. The desktop menu is opened only to apply a pick; it used to be read on every tap
  // (10-11). With nothing remembered yet, the menu is read from the desktop as before.
  // Auto can be picked too (10-12): the user's sessions run in it, and a pick of Plan on the phone could not be undone
  // there. Lists kept before that (lbr_claude_modes, without Auto) are dropped, and the chip names the mode in force:
  // Auto and Manual both read 普通执行, so the phone could not tell whether it was back in Auto.
  let modeBusy=null,modesKept='';const firstWord=s=>String(s||'').trim().split(/\s+/)[0].toLowerCase();
  try{localStorage.removeItem('lbr_claude_modes');}catch(e){}
  function modeList(){if(currentData?.mode_options?.length)return currentData.mode_options;try{const saved=JSON.parse(localStorage.getItem('lbr_claude_modes2'));if(saved?.length)return saved;}catch(e){}return null;}
  function keepModes(list){const value=JSON.stringify((list||[]).map(m=>({name:m.name})));if(!list?.length||value===modesKept)return;modesKept=value;try{localStorage.setItem('lbr_claude_modes2',value);}catch(e){}}
  function modeShown(data,s){if(data.mode_label)return data.mode_label;return {auto:'Auto',default:'Manual',acceptEdits:'Accept edits'}[s.mode]||'普通执行';}
  function modeNow(name){const live=currentData?.mode_label,m=currentData?.settings?.mode;if(live)return firstWord(name)===firstWord(live);return m==='plan'?/^plan/i.test(name):m==='default'?/^(ask|manual)/i.test(name):m==='auto'?/^auto/i.test(name):false;}
  function renderModes(me,error){
    if(!active(me)||menuTarget!==me)return;const body=sheet.querySelector('.sh-body'),list=modeList()||[],live=currentData?.mode_label;body.replaceChildren();
    if(live&&!list.some(m=>modeNow(m.name)))body.append(el('p','hint','电脑上现在是「'+live+'」。'));
    for(const m of list){ // the desktop names a mode 'Auto Recommended Claude handles permission decisions': the word in bold, what it does below
      const [word,...rest]=String(m.name||'').trim().split(/\s+/),about=rest.join(' ').replace(/^Recommended\s*/i,'');
      const row=el('button','option-card mode-choice'),cap=el('span','ask-caption');cap.append(el('b','',word));if(about)cap.append(el('small','',about));
      row.type='button';row.setAttribute('role','radio');row.setAttribute('aria-checked',String(modeNow(m.name)));row.disabled=!!modeBusy;
      if(modeBusy===m.name){row.classList.add('is-choosing');cap.append(el('small','ask-status','正在电脑上切换…'));}
      row.append(el('span','choice-dot'),cap);row.onclick=()=>pickMode(me,m);body.append(row);}
    if(error)body.append(el('p','card-note error',error));
    if(currentData&&!currentData.on_screen)body.append(el('p','hint','电脑上现在开着别的对话；选了以后，电脑上的 Claude 会先切到这个对话再改。'));
    body.append(el('p','hint','Plan 先出计划，确认后再改；Manual 每次改动前都先问你；Auto 自己做，遇到看起来不安全的操作才停下来问。'));
  }
  function openModes(){if(cur?.app!=='claude')return;if(unknown()){open.onclick();return;}
    if(!modeList())return openMenu('mode');const me={...cur};menuTarget=me;sheet.querySelector('b').textContent='Claude 模式';renderModes(me);openSheet(sheet.id);}
  async function pickMode(me,m){if(modeBusy)return;modeBusy=m.name;renderModes(me);
    try{const result=await api('/api/claude/setting',{id:me.id,kind:'mode',name:m.name});modeBusy=null;if(result.state)paint(me,result.state);if(active(me)&&menuTarget===me)closeSheet(sheet.id);toast('已切换到「'+m.name+'」');}
    catch(e){modeBusy=null;await refresh(me,true);renderModes(me,e.message);}}
  model.onclick=openModels;effort.onclick=openModels;modeButton.onclick=openModes;
  open.onclick=async()=>{const me=cur;try{await openOnPC();await refresh(me,true);}catch(e){toast(e.message,true);}};
  function onOpen(me){actionSig='';currentData=null;ask=null;controls.hidden=me.app!=='claude';note.hidden=true;stop.hidden=true;queue.hidden=true;queue.dataset.sig='';if(me.app==='claude'){paint(me,cache.get(me.id)||{settings:{},available:true});refresh(me,true);}}
  function closeMenu(){const target=menuTarget;menuTarget=null;if(target)api('/api/claude/close-menu',{id:target.id}).catch(()=>{});}
  // A button of Claude's next-step box (10-16), as if clicked on the PC: the same button pressed there, or, where the box
  // there takes no click, a reply's words sent as a message. Done, the buttons give way to what was done at once; the card
  // closes when the conversation shows the reply (10-16: it stayed as it was, and looked as if nothing had happened).
  let pressing=false;
  async function pressNext(m,index,row){
    const me=cur,a=m.actions[index];if(!me||me.app!=='claude'||pressing||!a)return;pressing=true;window.navigationUI?.haptic?.();
    const buttons=[...row.querySelectorAll('button')];buttons.forEach((b,i)=>{b.disabled=true;if(i===index)b.textContent=a.label+'…';});
    try{const result=await api('/api/claude/next',{id:me.id,tool_id:m.tool_id,index,label:a.label},65000);
      if(active(me)){row.replaceWith(el('div','next-status',result.text||'已在电脑上点了「'+a.label+'」'));toast(result.text||'已操作');refresh(me,true);loadConv(true);}}
    catch(e){if(active(me))toast(e.message,true);}
    finally{pressing=false;buttons.forEach((b,i)=>{b.disabled=false;b.textContent=m.actions[i].label;});}
  }
  // A task card Claude proposed (10-16): Start, Do it here or the cross, pressed on the PC's card with the same title.
  async function pressTask(m,kind,label,row){
    const me=cur;if(!me||me.app!=='claude'||pressing)return;
    if(kind==='dismiss'&&!(await askConfirm('不要这个任务了？电脑上的这张卡片也会关掉，任务不会开始。')))return;
    pressing=true;window.navigationUI?.haptic?.();const buttons=[...row.querySelectorAll('button')];
    buttons.forEach(b=>{b.disabled=true;if(b.textContent===label)b.textContent=label+'…';});
    try{const result=await api('/api/claude/task',{id:me.id,title:m.title,button:kind},65000);if(active(me)){toast(result.text||'已在电脑上操作');refresh(me,true);loadConv(true);}}
    catch(e){if(active(me))toast(e.message,true);}
    finally{pressing=false;buttons.forEach(b=>{b.disabled=false;b.textContent=b.textContent.replace(/…$/,'');});}
  }
  // Whether a task card still waits on the PC: only known while the PC shows the conversation (the state's tasks).
  function markTask(node){
    if(!node.querySelector('.next-actions'))return;const data=currentData;
    const settled=!!data?.on_screen&&Array.isArray(data.tasks)&&!data.tasks.includes(node.dataset.title);
    node.classList.toggle('settled',settled);node.querySelector('.task-note').textContent=settled?'电脑上已经处理过了：开始了、在这里做了，或者关掉了。':'';
  }
  window.claudeUI={onOpen,refresh,pressNext,pressTask,markTask,turnAnchor(){return currentData?.on_screen&&currentData?.running?currentData.turn_anchor:null;},onSheetClose(id){if(id===sheet.id)closeMenu();},onClose(){controls.hidden=true;note.hidden=true;stop.hidden=true;queue.hidden=true;queue.dataset.sig='';closeMenu();ask=null;if(askOpen())closeSheet(askSheet.id);},renderQueue(){renderQueue();},
    runtimeFor(value){const data=cur?.app==='claude'?cache.get(cur.id):null;return data?.runtime?.source==='desktop'&&Date.now()-data.observed_at<15000?data.runtime:value;}};
  setInterval(()=>refresh(),5000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
  if(cur)onOpen(cur);
})();
