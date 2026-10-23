/* Shared browser/WebView activity, read-only diffs and anchored display menu. */
(() => {
  const saved=(key,fallback)=>{try{return JSON.parse(localStorage.getItem(key))??fallback;}catch{return fallback;}};
  const persist=(key,value)=>{try{localStorage.setItem(key,JSON.stringify(value));}catch{}};
  const preferences=saved('teleply-list-display',{}),expanded=saved('teleply-activity-expanded',{});
  const toolExpanded=new Map();
  const turns=new Map(),activeTurns=new Map(),unreliableTimes=saved('teleply-activity-clock-unknown',{});let pendingTurn=null;
  const button=(text,action)=>{const b=el('button','tp-button',text);b.type='button';b.onclick=action;return b;};
  const iconButton=(name,label,action)=>{const b=button('',action);b.className='tp-icon-button';b.innerHTML=icon(name);b.setAttribute('aria-label',label);b.title=label;return b;};
  function meta(data){if(!cur)return;const key=chatKey(cur);turns.set(key,{...(turns.get(key)||{}),...(data.activity_turns||{})});if(data.activity_current)activeTurns.set(key,data.activity_current);}
  function control(me,data){if(cur&&chatKey(cur)===chatKey(me)){const question=(data.questions||[]).find(q=>q.status==='pending');pendingTurn=question?(question.turn_id||data.active_turn_id):null;tick();}}
  function decorate(rows){
    const result=[],groups=new Map();let fallback='history';
    for(const row of rows){
      const m=row.message;
      if(m?.role==='user')fallback=m.id||row.key;
      const items=row.items||((m?.role==='assistant'&&(m.thinking||m.phase==='commentary'))?[m]:[]);
      if(!items.length){result.push(row);continue;}
      for(const item of items){
        const id=item.activity_turn||item.turn_id||fallback;
        let group=groups.get(id);
        if(!group){group={key:'activity:'+id,activity:{id,items:[],last:false}};groups.set(id,group);result.push(group);}
        group.activity.items.push(item);
      }
    }
    const current=activeTurns.get(chatKey(cur));
    if(current&&cur?.status==='running'&&!window.readingUI?.historyWindow&&!groups.has(current)){
      const group={key:'activity:'+current,activity:{id:current,items:[],last:true}};groups.set(current,group);result.push(group);
    }
    const last=[...groups.values()].at(-1);if(last)last.activity.last=true;
    rows.splice(0,rows.length,...result);
  }
  function state(group){
    const timing=turns.get(chatKey(cur))?.[group.id]||{};
    const waiting=group.id===pendingTurn||!!timing.paused_at;
    const active=activeTurns.get(chatKey(cur));
    const running=(active?group.id===active:group.last&&!window.readingUI?.historyWindow)&&cur?.status==='running'&&timing.status!=='completed'&&timing.status!=='stopped';
    const failed=group.items.some(m=>m.tool_status==='failed');
    const offline=group.last&&!!chatReadError;
    return {timing,waiting,running,failed,offline,label:offline?'连接中断':waiting?'需要你回答':failed?'执行遇到问题':running?'正在处理':timing.status==='stopped'?'已停止':timing.status==='completed'?'已完成':'处理过程'};
  }
  function render(node,group){
    const storageKey=chatKey(cur)+':'+group.id,model=state(group);
    node.className='activity-group';node.replaceChildren();node._activity=group;
    const head=button('',()=>{
      // Store the desired open state, independently of automatic running defaults.
      expanded[storageKey]=body.hidden;persist('teleply-activity-expanded',Object.fromEntries(Object.entries(expanded).slice(-300)));
      body.hidden=!expanded[storageKey];head.setAttribute('aria-expanded',String(!body.hidden));if(!body.hidden)paint(true);});
    head.className='activity-heading';head.append(el('span','activity-status'),el('span','activity-clock'),el('span','activity-chevron','›'));
    const body=el('div','activity-body');body.hidden=expanded[storageKey]===undefined?!model.running:!expanded[storageKey];head.setAttribute('aria-expanded',String(!body.hidden));
    function paint(all=false){body.replaceChildren();const items=all||expanded[storageKey]?group.items:group.items.slice(-3);
      if(items.length<group.items.length){const more=button('查看全部过程',()=>{expanded[storageKey]=true;persist('teleply-activity-expanded',expanded);paint(true);});body.append(more);}
      for(const item of items){const detail=el('details','activity-item'),title=el('summary');
        const toolKey=storageKey+':'+(item.id||item.source_id||item.time+':'+item.text);detail.open=toolExpanded.get(toolKey)||false;detail.addEventListener('toggle',()=>{toolExpanded.set(toolKey,detail.open);if(toolExpanded.size>1000)toolExpanded.delete(toolExpanded.keys().next().value);});
        const mark=item.role!=='tool'?'·':item.tool_status==='failed'?'!':item.tool_status==='running'?'◌':item.tool_status==='completed'?'✓':'·';
        title.append(el('span','activity-mark',mark),el('span','activity-title',item.thinking?'思考摘要':item.role==='assistant'?'进度说明':item.activity_title||String(item.text).split('\n')[0].slice(0,140)));
        detail.append(title,el('pre','activity-detail',item.detail||item.text));if(item.result)detail.append(el('pre','activity-detail',item.result));
        body.append(detail);if(item.tool_status==='failed')body.append(el('div','activity-error','操作未完成，展开查看结果'));
        if(item.change_notice)body.append(el('div','hint',item.change_notice));
        if(item.current_file&&item.tool_status==='completed'){const link=el('a','tp-button','查看当前文件');link.href='#';link.dataset.resultPath=item.current_file;body.append(link);}
        for(const c of item.changes||[]){const b=button('',()=>showDiff(c,group.items.flatMap(m=>m.changes||[])));b.className='file-change';b.append(el('span','',c.path.split(/[\\/]/).at(-1)),el('small','',`+${c.added} −${c.removed} · 查看差异 ›`));body.append(b);}
      }
    }
    paint();node.append(head,body);tickNode(node);
  }
  function tickNode(node){if(!cur)return;const g=node._activity,s=state(g);node.querySelector('.activity-status').textContent=(s.running&&!s.waiting&&!s.offline?'◌ ':'')+s.label;
    const storageKey=chatKey(cur)+':'+g.id;if(expanded[storageKey]===undefined&&!s.running){node.querySelector('.activity-body').hidden=true;node.querySelector('.activity-heading').setAttribute('aria-expanded','false');}
    const clock=node.querySelector('.activity-clock'),t=s.timing;
    // Once waiting is observed, this source lacks a persisted pause ledger: omit duration rather than invent one.
    if(s.waiting&&!t.paused_at){unreliableTimes[storageKey]=true;persist('teleply-activity-clock-unknown',Object.fromEntries(Object.entries(unreliableTimes).slice(-300)));}
    const end=t.paused_at||t.ended_at||(s.running&&!s.offline?Date.now():null);
    clock.textContent=!unreliableTimes[storageKey]&&t.started_at&&end?' · '+Math.max(0,Math.floor((end-t.started_at-(t.paused_ms||0))/1000))+' 秒':'';
    const count=new Set(g.items.flatMap(m=>(m.changes||[]).map(c=>c.path))).size;if(count)clock.textContent+=' · 修改 '+count+' 个文件';
  }
  function tick(){if(document.hidden)return;document.querySelectorAll('.activity-group').forEach(tickNode);}
  setInterval(tick,1000);

  const diff=el('div','sheet dialog-sheet');diff.id='diffSheet';diff.setAttribute('aria-label','本轮文件差异');diff.innerHTML='<div class="box diff-box"><div class="diff-heading"></div><div class="diff-controls"></div><div class="diff-content"></div></div>';document.body.append(diff);
  const diffMenu=el('div','sheet popover');diffMenu.id='diffOptions';diffMenu.setAttribute('aria-label','差异显示选项');const diffMenuBox=el('div','box tp-menu');diffMenu.append(diffMenuBox);document.body.append(diffMenu);
  let diffGeneration=0;
  function sideBySide(block){
    const rows=[...block.children],unified=el('div','diff-unified'),side=el('div','diff-side');unified.append(...rows);
    const cell=(row,right)=>{const n=el('div','diff-cell'+(row?.classList.contains('add')?' add':row?.classList.contains('delete')?' delete':''));if(row)n.append(el('span','diff-number',row.children[right?1:0]?.textContent||''),el('code','',row.querySelector('code')?.textContent||''));return n;};
    const pair=(left,right)=>{const row=el('div','diff-pair');row.append(cell(left,false),cell(right,true));side.append(row);};
    for(let i=0;i<rows.length;){const row=rows[i];if(row.classList.contains('diff-range')){side.append(row.cloneNode(true));i++;continue;}
      if(row.classList.contains('context')){pair(row,row);i++;continue;}
      const removed=[],added=[];while(i<rows.length&&(rows[i].classList.contains('delete')||rows[i].classList.contains('add'))){(rows[i].classList.contains('delete')?removed:added).push(rows[i++]);}
      for(let j=0;j<Math.max(removed.length,added.length);j++)pair(removed[j],added[j]);
    }block.append(unified,side);
  }
  async function showDiff(c,files){
    const generation=++diffGeneration,target={...cur};let next=0,split=false,wrap=false;
    const heading=diff.querySelector('.diff-heading'),controls=diff.querySelector('.diff-controls'),content=diff.querySelector('.diff-content');controls.replaceChildren();content.className='diff-content';content.replaceChildren(el('div','hint','正在读取差异…'));
    const title=el('div','tp-header-title');title.append(el('strong','',c.path.split(/[\\/]/).at(-1)),el('small','','本轮差异'));
    const toolbar=el('div','tp-toolbar');
    const more=iconButton('more','差异显示选项',()=>{diffMenuBox.replaceChildren();
      const wrapButton=button('自动换行',()=>{wrap=!wrap;content.classList.toggle('wrap',wrap);wrapButton.setAttribute('aria-pressed',String(wrap));});wrapButton.setAttribute('aria-pressed',String(wrap));diffMenuBox.append(wrapButton);
      if(matchMedia('(min-width:1024px)').matches){const side=button('左右对照',()=>{split=!split;content.classList.toggle('split',split);side.setAttribute('aria-pressed',String(split));});side.setAttribute('aria-pressed',String(split));diffMenuBox.append(side);}
      if(files.length>1)for(const file of files){const b=button(file.path.split(/[\\/]/).at(-1),()=>{closeSheet(diffMenu.id);showDiff(file,files);});b.setAttribute('aria-pressed',String(file.ref===c.ref));diffMenuBox.append(b);}
      openSheet(diffMenu.id,more);
    });
    const index=files.findIndex(f=>f.ref===c.ref);if(files.length>1)for(const [label,i] of [['上一文件',index-1],['下一文件',index+1]]){const b=iconButton('back',label,()=>showDiff(files[i],files));if(i>index)b.classList.add('tp-forward');b.disabled=i<0||i>=files.length;toolbar.append(b);}
    toolbar.append(more);heading.replaceChildren(iconButton('back','返回',()=>closeSheet(diff.id)),title,toolbar);
    openSheet(diff.id);
    async function load(){const offset=next;try{const data=await api('/api/chat/diff?app='+encodeURIComponent(target.app)+'&id='+encodeURIComponent(target.id)+'&ref='+encodeURIComponent(c.ref)+'&offset='+offset);
      if(generation!==diffGeneration)return;if(offset===0){content.replaceChildren();if(data.scope==='fragment')content.append(el('p','hint','工具记录中的替换片段；行号相对于片段，不代表完整文件。'));}
      for(const hunk of data.hunks){const block=el('div','diff-hunk');let old=0,now=0;
        for(const line of hunk.split('\n')){const match=/^@@ -(\d+)(?:,\d+)? \+(\d+)/.exec(line);if(match){old=+match[1];now=+match[2];block.append(el('div','diff-range',line));continue;}
          if(line.startsWith('\\')){block.append(el('div','diff-range',line));continue;}
          const type=line.startsWith('+')?'add':line.startsWith('-')?'delete':'context',row=el('div','diff-line '+type);
          row.append(el('span','diff-number',type==='add'?'':String(old++)),el('span','diff-number',type==='delete'?'':String(now++)),el('code','',line));block.append(row);
        }sideBySide(block);content.append(block);}
      next=data.next;if(next!==null){const more=button('加载更多修改块',()=>{more.remove();load();});content.append(more);}
    }catch(e){if(generation===diffGeneration)content.replaceChildren(el('p','hint',e.message),button('重试',load));}}
    await load();
  }

  const display=el('div','sheet popover');display.id='displayMenu';display.setAttribute('aria-label','列表显示');const menu=el('div','box');display.append(menu);document.body.append(display);
  const choices={group:['分组',[['none','不分组'],['project','按项目'],['app','按来源应用']]],sort:['排序',[['updated','最近活动'],['created','创建时间']]],status:['状态',[['all','全部'],['running','运行中'],['waiting','等待处理'],['idle','已结束']]],source:['来源',[['all','全部应用'],['codex','Codex'],['claude','Claude'],['deepseek','DeepSeek']]]};
  function menuPage(field){menu.replaceChildren();if(field){menu.append(button('‹ 返回',()=>menuPage()));for(const [value,label] of choices[field][1]){if(field==='source'&&value!=='all'&&!hasApp(value))continue;const b=button(label,()=>{preferences[field]=value;persist('teleply-list-display',preferences);if(field==='source')setConvApp(value);else readingUI.loadList(false,true);menuPage(field);});b.setAttribute('aria-pressed',String((field==='source'?convApp:(preferences[field]||choices[field][1][0][0]))===value));if(b.getAttribute('aria-pressed')==='true')b.append(el('span','','✓'));menu.append(b);}}
    else for(const [key,[title,options]] of Object.entries(choices)){const b=button('',()=>menuPage(key));b.append(el('span','',title),el('small','',options.find(v=>v[0]===(key==='source'?convApp:(preferences[key]||options[0][0])))?.[1]||options[0][1]),el('span','menu-arrow','›'));menu.append(b);}fitOverlays();}
  const trigger=button('',()=>{menuPage();openSheet(display.id,trigger);});trigger.className='icon-btn list-display';trigger.setAttribute('aria-label','列表显示选项');trigger.innerHTML=icon('more');document.querySelector('.conversation-home .chips').append(trigger);
  function list(items){let result=items.filter(c=>!preferences.status||preferences.status==='all'||c.status===preferences.status);result=[...result].sort((a,b)=>{const field=preferences.sort==='created'?'created':'updated';return (Number(b[field])||-Infinity)-(Number(a[field])||-Infinity);});
    if(preferences.group==='project'||preferences.group==='app')result.sort((a,b)=>groupName(a).localeCompare(groupName(b)));return result;}
  function groupName(c){return preferences.group==='project'?(c.folder||'未分组'):preferences.group==='app'?({codex:'Codex',claude:'Claude',deepseek:'DeepSeek'}[c.app]||c.app):'';}
  function opened(node){if(!node.classList.contains('popover'))return;clearTimeout(node._tpEntering);node.classList.add('tp-entering');node._tpEntering=setTimeout(()=>node.classList.remove('tp-entering'),300);node.querySelectorAll('.box button').forEach((b,i)=>b.style.setProperty('--enter-delay',Math.min(i*15,60)+'ms'));}
  const query=()=> (preferences.sort==='created'?'&sort=created':'')+(preferences.status&&preferences.status!=='all'?'&status='+encodeURIComponent(preferences.status):'');
  window.interactionUI={meta,control,decorate,render,list,groupName,opened,query,sortLabel:()=>preferences.sort==='created'?'按创建时间排序':'按最近活动排序'};
  if(query())readingUI.loadList(false,true);
})();
