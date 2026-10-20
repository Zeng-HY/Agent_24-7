/* ＋ → 手机上的文件 / 电脑上的文件 (10-20). An attached file travels as a reference (references-ui.js for a conversation,
   new-chat-ui.js for a new one): the service writes the file's path on this computer under the message, and Codex,
   Claude or DeepSeek open it there themselves (pc_files.py). One from the phone is sent up first, into
   下载\手机传来的文件 on the computer, and is then the same as any file there. Pictures go the way photos go, so the model
   sees them at once: from the phone as photos, from the computer read in by the service (/api/files/image).
   The sheet of the computer's folders shows names, sizes and times, never what a file holds. */
(() => {
  const PICTURE=/\.(png|jpe?g|webp|hei[cf])$/i,PHOTO=/^image\/(png|jpe?g|webp|hei[cf])$/i;
  const MAX_UPLOAD=100*1024*1024,MAX_FILES=20,MAX_PHONE=10,MAX_PHOTO=20*1024*1024;
  ICONS.file='M6 3h8l4 4v14H6zM14 3v4h4';
  const uid=()=>[...crypto.getRandomValues(new Uint8Array(16))].map(v=>v.toString(16).padStart(2,'0')).join('');
  const localGet=(key,fallback)=>{try{return JSON.parse(localStorage.getItem(key))??fallback;}catch(e){return fallback;}};
  const localSet=(key,value)=>{try{localStorage.setItem(key,JSON.stringify(value));}catch(e){}};
  const same=(a,b)=>String(a||'').toLowerCase()===String(b||'').toLowerCase();  // Windows paths
  const isFile=v=>v&&(v.kind==='file'||v.kind==='folder');
  const isPending=v=>isFile(v)&&!!v.status;  // still going up from the phone, or failed to
  function size(n){if(n==null)return '';if(n<1024)return n+' 字节';if(n<1048576)return Math.max(1,Math.round(n/1024))+' KB';if(n<1073741824){const v=n/1048576;return (v<100?v.toFixed(1):Math.round(v))+' MB';}return (n/1073741824).toFixed(1)+' GB';}
  function when(ms){if(!ms)return '';const t=new Date(ms);return t.getFullYear()===new Date().getFullYear()?ago(ms):t.getFullYear()+'-'+(t.getMonth()+1)+'-'+t.getDate();}
  function iconFor(v){return icon(v.kind==='folder'?'folder':'file');}
  // the label of an attached file on its chip and in sent-message summaries: 📁 a folder, 📄 a file
  function label(v){return (v.kind==='folder'?'📁 ':'📄 ')+(v.name||'');}
  const css=el('style');css.textContent=`
    #pcFiles .box{height:min(calc(var(--overlay-height,100dvh) - 40px),760px);max-height:none}#pcFiles .sh-body{flex:1;min-height:0;overflow:hidden;gap:8px;padding-bottom:0}
    #pcFiles .sh-head small{color:var(--muted);font-size:12px;font-weight:400}
    .pcf-places,.pcf-crumbs{display:flex;gap:6px;overflow-x:auto;flex:none;scrollbar-width:none;-webkit-overflow-scrolling:touch}.pcf-places::-webkit-scrollbar,.pcf-crumbs::-webkit-scrollbar{display:none}
    .pcf-places button{flex:none;border-radius:999px;padding:7px 12px;min-height:36px;font-size:13px;font-weight:500;background:var(--bg);border:1px solid transparent;color:var(--text)}
    .pcf-places button[aria-current=true]{color:var(--blue);background:#eef2ff}
    .pcf-crumbs{align-items:center;font-size:13px;color:var(--muted);white-space:nowrap}.pcf-crumbs button{flex:none;border:0;background:transparent;padding:6px 3px;min-height:32px;font-size:13px;font-weight:500;color:var(--blue)}.pcf-crumbs button:last-child{color:var(--text)}
    .pcf-tools{display:flex;gap:8px;flex:none}.pcf-tools input{flex:1;min-width:0;font:inherit;font-size:16px;padding:8px 12px;border:1px solid var(--line);border-radius:12px;background:var(--bg)}
    .pcf-tools button{flex:none;font-size:13px;font-weight:500;padding:8px 12px;border-radius:12px;min-height:40px}
    .pcf-list{flex:1;min-height:0;overflow:auto;overscroll-behavior:contain;margin:0 -14px;border-top:1px solid var(--line)}
    .pcf-row{display:flex;align-items:center;gap:12px;width:100%;border:0;border-bottom:1px solid var(--line);border-radius:0;background:transparent;padding:9px 14px;min-height:56px;text-align:left;font-weight:400;font-size:15px;color:var(--text)}
    .pcf-row:active{background:var(--bg)}.pcf-row .pcf-icon{flex:none;display:flex;color:var(--muted)}.pcf-row .pcf-icon svg{width:26px;height:26px}.pcf-row.is-folder .pcf-icon{color:#b7791f}
    .pcf-row .pcf-name{flex:1;min-width:0}.pcf-row .pcf-name b{display:block;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.pcf-row small{display:block;font-size:12px;color:var(--muted);margin-top:2px}
    .pcf-check{flex:none;width:22px;height:22px;border:1.5px solid #c4c9d4;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff}.pcf-check svg{width:14px;height:14px;opacity:0}
    .pcf-row[aria-selected=true]{background:#f5f8ff}.pcf-row[aria-selected=true] .pcf-check{background:var(--blue);border-color:var(--blue)}.pcf-row[aria-selected=true] .pcf-check svg{opacity:1}
    .pcf-go{flex:none;color:var(--muted);font-size:20px;line-height:1}.pcf-empty{padding:28px 16px;color:var(--muted);font-size:14px;text-align:center;line-height:1.6}
    .pcf-more{display:block;width:100%;border:0;border-radius:0;background:transparent;color:var(--blue);font-size:14px;font-weight:500;min-height:48px}
    .pcf-foot{display:flex;gap:8px;padding:10px 14px;border-top:1px solid var(--line);flex:none}.pcf-foot button{flex:1;min-width:0;min-height:48px;border-radius:14px;font-size:15px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.pcf-foot button:disabled{opacity:.5}
    .reference-chip.is-file{background:#fff;color:var(--text)}.reference-chip.is-file.is-failed{border-color:#f3b4b4;color:var(--red)}.reference-chip .chip-progress{color:var(--muted);font-size:12px;flex:none;padding-left:4px}
    .reference-chip .chip-retry{color:var(--blue);font-size:12px;min-width:0;padding:8px 6px}`;
  document.head.append(css);
  const sheet=el('div','sheet');sheet.id='pcFiles';sheet.setAttribute('aria-label','电脑上的文件');
  sheet.innerHTML='<div class="box"><div class="sh-head"><b>电脑上的文件</b><small id="pcfCount"></small><button class="icon-btn" aria-label="关闭">'+icon('close')+'</button></div>'
    +'<div class="sh-body"><div class="pcf-places" id="pcfPlaces" aria-label="常用位置"></div><div class="pcf-crumbs" id="pcfCrumbs" aria-label="所在位置"></div>'
    +'<div class="pcf-tools"><input id="pcfFilter" type="search" enterkeyhint="search" placeholder="在这个文件夹里按名字找" aria-label="在这个文件夹里按名字找"><button id="pcfSort" type="button"></button></div>'
    +'<div class="pcf-list" id="pcfList" role="listbox" aria-multiselectable="true" aria-label="文件夹里的东西"></div></div>'
    +'<div class="pcf-foot"><button id="pcfFolder" type="button">选这个文件夹</button><button id="pcfAdd" class="big" type="button" disabled>添加</button></div></div>';
  document.body.append(sheet);sheet.querySelector('.sh-head button').onclick=()=>closeSheet(sheet.id);sheet.addEventListener('click',e=>{if(e.target===sheet)closeSheet(sheet.id);});
  let browse=null,filterTimer=null,composingFilter=false;
  // browse: {room(): how many more may be attached, onPick(entries), places, path, data, items, picked: Map(path -> entry), seq, sort, query}
  function recent(){return localGet('lbr_pcf_recent',[]).filter(v=>v&&v.path);}
  function remember(folders){const list=recent();for(const path of folders){const i=list.findIndex(v=>same(v.path,path));if(i>=0)list.splice(i,1);list.unshift({path,name:path.split(/[\\/]/).filter(Boolean).pop()||path});}localSet('lbr_pcf_recent',list.slice(0,5));}
  function parentOf(path){const i=path.replace(/[\\/]+$/,'').search(/[\\/][^\\/]*$/);return i<0?path:path.slice(0,i)||path;}
  async function open(opts){
    browse={...opts,places:[],path:'',data:null,items:[],picked:new Map(),seq:0,sort:localGet('lbr_pcf_sort','name')==='time'?'time':'name',query:''};
    const b=browse;$('pcfFilter').value='';paintSort();paintFoot();$('pcfCrumbs').replaceChildren();$('pcfPlaces').replaceChildren();
    $('pcfList').replaceChildren(el('div','pcf-empty','正在读电脑上的文件夹…'));openSheet(sheet.id);
    let places=[];
    try{places=(await api('/api/files/places?'+new URLSearchParams(opts.folder!=null?{folder:opts.folder}:{app:opts.app,id:opts.id}),null,15000)).items||[];}
    catch(e){if(browse===b)$('pcfList').replaceChildren(el('div','pcf-empty','读不到电脑上的文件夹：'+e.message));return;}
    if(browse!==b)return;b.places=places;
    const last=localGet('lbr_pcf_last',''),start=places.find(p=>p.kind==='conversation')?.path||last||places.find(p=>p.kind==='downloads')?.path||places[0]?.path;
    paintPlaces();if(start)go(start);else $('pcfList').replaceChildren(el('div','pcf-empty','这台电脑上没有可以看的磁盘'));
  }
  async function go(path,more=false){
    const b=browse;if(!b)return;const seq=++b.seq;
    if(!more){b.path=path;b.items=[];b.data=null;$('pcfList').replaceChildren(el('div','pcf-empty','读取中…'));paintPlaces();paintFoot();}
    try{
      const data=await api('/api/files/list?'+new URLSearchParams({path,sort:b.sort,query:b.query,offset:more?b.data.next_offset:0}),null,20000);
      if(browse!==b||seq!==b.seq)return;
      b.data=data;b.path=data.path;b.items=more?[...b.items,...data.items]:data.items;localSet('lbr_pcf_last',data.path);
      paintCrumbs();paintList(more);paintPlaces();paintFoot();if(!more)$('pcfList').scrollTop=0;
    }catch(e){
      if(browse!==b||seq!==b.seq)return;
      // a folder that went away or cannot be opened: the place it was in, if that one opens
      const list=$('pcfList');list.replaceChildren(el('div','pcf-empty',e.message));
      const up=parentOf(path);if(!more&&up&&!same(up,path)){const back=el('button','pcf-more','回到上一层');back.type='button';back.onclick=()=>go(up);list.append(back);}
      b.data=null;paintFoot();
    }
  }
  function paintPlaces(){
    const b=browse,box=$('pcfPlaces');if(!b)return;
    const rows=[...b.places];for(const r of recent())if(!rows.some(p=>same(p.path,r.path)))rows.push({name:'最近 · '+r.name,path:r.path,kind:'recent'});
    const sig=JSON.stringify([rows,b.path]);if(box.dataset.sig===sig)return;box.dataset.sig=sig;box.replaceChildren();
    for(const p of rows){const c=el('button','',p.name);c.type='button';c.title=p.path;c.setAttribute('aria-current',String(same(p.path,b.path)));c.onclick=()=>{if(!same(p.path,b.path)){b.query='';$('pcfFilter').value='';go(p.path);}};box.append(c);}
  }
  function paintCrumbs(){
    const box=$('pcfCrumbs');box.replaceChildren();const crumbs=browse?.data?.crumbs||[];
    crumbs.forEach((c,i)=>{if(i)box.append(el('span','','›'));const b=el('button','',c.name);b.type='button';b.title=c.path;if(i<crumbs.length-1)b.onclick=()=>{browse.query='';$('pcfFilter').value='';go(c.path);};else b.setAttribute('aria-current','location');box.append(b);});
    requestAnimationFrame(()=>{box.scrollLeft=box.scrollWidth;});
  }
  function paintSort(){$('pcfSort').textContent=browse?.sort==='time'?'按时间':'按名称';$('pcfSort').setAttribute('aria-label',browse?.sort==='time'?'现在最近改过的在前，点这里改按名称':'现在按名称排，点这里改成最近改过的在前');}
  function row(v){
    const folder=v.kind==='folder',b=el('button','pcf-row'+(folder?' is-folder':''));b.type='button';b.setAttribute('role','option');
    const ic=el('span','pcf-icon');ic.innerHTML=iconFor(v);const name=el('span','pcf-name');name.append(el('b','',v.name));
    name.append(el('small','',folder?when(v.modified):[size(v.size),when(v.modified)].filter(Boolean).join(' · ')));b.append(ic,name);
    if(folder){b.append(el('span','pcf-go','›'));b.setAttribute('aria-label','打开文件夹 '+v.name);b.onclick=()=>{browse.query='';$('pcfFilter').value='';go(v.path);};}
    else{const check=el('span','pcf-check');check.innerHTML=icon('check');b.append(check);b.setAttribute('aria-selected',String(browse.picked.has(v.path.toLowerCase())));b.onclick=()=>toggle(v,b);}
    return b;
  }
  function paintList(more){
    const b=browse,list=$('pcfList'),data=b.data;
    if(!more)list.replaceChildren();else list.querySelectorAll('.pcf-more,.pcf-empty').forEach(n=>n.remove());
    for(const v of more?data.items:b.items)list.append(row(v));
    if(!b.items.length)list.append(el('div','pcf-empty',b.query?'这个文件夹里没有名字带「'+b.query+'」的':'这个文件夹是空的'));
    if(data.has_more){const m=el('button','pcf-more','再显示 '+Math.min(200,data.total-b.items.length)+' 项（共 '+data.total+' 项）');m.type='button';m.onclick=()=>go(b.path,true);list.append(m);}
    if(data.truncated)list.append(el('div','pcf-empty','这个文件夹里的东西太多，只列了前 2 万项；可以用上面的框按名字找'));
  }
  function toggle(v,node){
    const b=browse,key=v.path.toLowerCase();
    if(b.picked.has(key))b.picked.delete(key);
    else{if(b.picked.size>=b.room()){toast(b.room()>0?'这条消息最多再附 '+b.room()+' 个文件':'这条消息已经附满 '+MAX_FILES+' 个文件或文件夹',true);return;}b.picked.set(key,v);}
    node.setAttribute('aria-selected',String(b.picked.has(key)));window.navigationUI?.haptic?.();paintFoot();
  }
  function paintFoot(){
    const b=browse,n=b?.picked.size||0;$('pcfAdd').disabled=!n;$('pcfAdd').textContent=n?'添加 '+n+' 个文件':'添加';$('pcfCount').textContent=n?'已选 '+n+' 个':'';
    const folder=b?.data?.folder;$('pcfFolder').disabled=!folder||n>0;$('pcfFolder').textContent=n?'选这个文件夹':folder?'选「'+folder.name+'」整个文件夹':'选这个文件夹';
  }
  $('pcfSort').onclick=()=>{const b=browse;if(!b)return;b.sort=b.sort==='time'?'name':'time';localSet('lbr_pcf_sort',b.sort);paintSort();if(b.path)go(b.path);};
  const filter=$('pcfFilter');
  filter.addEventListener('compositionstart',()=>{composingFilter=true;});filter.addEventListener('compositionend',()=>{composingFilter=false;filter.dispatchEvent(new Event('input'));});
  filter.addEventListener('input',()=>{if(composingFilter||!browse)return;clearTimeout(filterTimer);filterTimer=setTimeout(()=>{if(!browse?.path)return;browse.query=filter.value.trim();go(browse.path);},250);});
  filter.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();filter.blur();}});
  $('pcfAdd').onclick=()=>{const b=browse;if(!b||!b.picked.size)return;const picked=[...b.picked.values()];remember([...new Set(picked.map(v=>parentOf(v.path)))]);closeSheet(sheet.id);browse=null;b.onPick(picked);};
  $('pcfFolder').onclick=()=>{const b=browse,folder=b?.data?.folder;if(!folder||b.picked.size)return;if(b.room()<1){toast('这条消息已经附满 '+MAX_FILES+' 个文件或文件夹',true);return;}remember([folder.path]);closeSheet(sheet.id);browse=null;b.onPick([folder]);};

  // ---- files from the phone
  const phoneInput=el('input');phoneInput.type='file';phoneInput.multiple=true;phoneInput.hidden=true;document.body.append(phoneInput);
  let phonePick=null;phoneInput.addEventListener('change',()=>{const files=[...phoneInput.files],pick=phonePick;phoneInput.value='';phonePick=null;if(pick&&files.length)pick(files);});
  function choosePhone(pick){phonePick=pick;phoneInput.click();}  // within the tap: iPhone opens its picker only then
  // A photo the photo path can read goes as a photo; any other file, and a picture too big for it, goes up as a file.
  function splitPhone(files){const photos=[],others=[];for(const f of files)(((PHOTO.test(f.type)||PICTURE.test(f.name))&&f.size<=MAX_PHOTO)?photos:others).push(f);return {photos,others};}
  let dbPromise=null;  // the same store the photo drafts use (codex-ui.js): a file waiting to go up survives a reload
  function filesDB(){return dbPromise ||= new Promise((resolve,reject)=>{const r=indexedDB.open('agent-remote-image-drafts',1);r.onupgradeneeded=()=>r.result.createObjectStore('files');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
  async function blob(op,key,value){const db=await filesDB();return new Promise((resolve,reject)=>{const tx=db.transaction('files',op==='get'?'readonly':'readwrite'),s=tx.objectStore('files'),r=op==='put'?s.put(value,key):s[op](key);let result;r.onsuccess=()=>{result=r.result;};tx.oncomplete=()=>resolve(result);tx.onerror=()=>reject(tx.error);});}
  const live=new Map();  // localId -> the upload under way on this page
  function sendUp(file,params,onProgress){
    const x=new XMLHttpRequest();
    const done=new Promise((resolve,reject)=>{
      x.open('POST','/api/files/upload?'+new URLSearchParams({...params,name:file.name||'文件'}));x.setRequestHeader('Content-Type','application/octet-stream');
      x.upload.onprogress=e=>{if(e.lengthComputable)onProgress?.(e.loaded/e.total);};
      x.onload=()=>{let j=null;try{j=JSON.parse(x.responseText);}catch(e){}if(x.status>=200&&x.status<300&&j&&!j.error)resolve(j);else reject(Error(j?.error||'没传上去（HTTP '+x.status+'）'));};
      x.onerror=()=>reject(Error('传到一半断了，检查网络后点重试'));x.onabort=()=>reject(Object.assign(Error('已取消'),{aborted:true}));x.send(file);});
    return {done,abort:()=>x.abort()};
  }
  // Uploads into a list of references (a conversation's or the new one's): list() gives the live array, changed() saves
  // and repaints it. An entry going up carries status 'uploading' (progress 0..1) or 'failed' (error), and becomes the
  // service's reference once there; it is taken out of the browser's store then.
  function upload(files,{list,changed,params}){
    const room=MAX_FILES-list().filter(isFile).length,phone=list().filter(v=>v.from_phone).length;
    if(files.length>room){toast(room>0?'这条消息最多再附 '+room+' 个文件':'这条消息已经附满 '+MAX_FILES+' 个文件或文件夹',true);files=files.slice(0,Math.max(0,room));}
    if(phone+files.length>MAX_PHONE){toast('一条消息最多从手机传 '+MAX_PHONE+' 个文件',true);files=files.slice(0,Math.max(0,MAX_PHONE-phone));}
    for(const f of files){
      if(f.size>MAX_UPLOAD){toast('「'+f.name+'」超过 100 MB，传不了',true);continue;}
      if(!f.size){toast('「'+f.name+'」是空文件',true);continue;}
      const v={kind:'file',app:'pc',id:'up-'+uid(),name:f.name||'文件',size:f.size,from_phone:true,status:'uploading',progress:0};v.localId=v.id;
      list().push(v);changed();blob('put',v.localId,f).catch(()=>{});start(v,f,{list,changed,params});
    }
  }
  async function start(v,file,{list,changed,params}){
    if(live.has(v.localId))return;
    if(!file)try{file=await blob('get',v.localId);}catch(e){}
    if(!file){v.status='failed';v.error='手机上的原文件找不到了，请去掉它再重新选';changed();return;}
    v.status='uploading';v.progress=0;v.error='';changed();let painted=0;
    const job=sendUp(file,typeof params==='function'?await params():params,p=>{v.progress=p;const now=Date.now();if(now-painted>200){painted=now;changed(true);}});
    live.set(v.localId,job);
    try{
      const ref=await job.done,at=list().indexOf(v);
      if(at<0){api('/api/files/remove',{upload:ref.upload}).catch(()=>{});return;}  // taken off while it went up
      list().splice(at,1,ref);blob('delete',v.localId).catch(()=>{});changed();
    }catch(e){if(e.aborted)return;v.status='failed';v.error=e.message;changed();}
    finally{live.delete(v.localId);}
  }
  function retry(v,target){start(v,null,target);}
  // a reference taken off a draft: an upload stops; a file already sent up and never sent with a message is deleted
  function discard(v){if(!isFile(v))return;if(v.localId){live.get(v.localId)?.abort();blob('delete',v.localId).catch(()=>{});}if(v.upload&&!v.status)api('/api/files/remove',{upload:v.upload}).catch(()=>{});}
  // after a reload no upload is under way: one shown as going up failed, and goes again with 重试
  function settle(list){let changed=false;for(const v of list)if(v.status==='uploading'&&!live.has(v.localId)){v.status='failed';v.error='上传中断了，点重试';changed=true;}return changed;}
  // a chip for an attached file: name, progress or failure with 重试, ×; tapping the name shows where the file is
  function chip(v,{remove,retry:again}){
    const c=el('div','reference-chip is-file'+(v.status==='failed'?' is-failed':'')),name=el('span','',label(v));name.title=v.path||v.name;
    name.onclick=()=>toast(v.status==='failed'?v.error:v.path||(v.status==='uploading'?'正在传到电脑…':v.name));c.append(name);
    if(v.status==='uploading')c.append(el('span','chip-progress',v.progress>0?Math.round(v.progress*100)+'%':'上传中'));
    if(v.status==='failed'){const r=el('button','chip-retry','重试');r.type='button';r.setAttribute('aria-label','重新上传 '+v.name);r.onclick=again;c.append(r);}
    const x=el('button','','×');x.type='button';x.setAttribute('aria-label','去掉 '+v.name);x.onclick=remove;c.append(x);return c;
  }
  // a picture on the computer read in as a photo: {meta} as a photo upload answers, or null when it is to go as a path
  async function importPicture(ref,where){
    if(ref.kind!=='file'||!PICTURE.test(ref.name)||ref.size>MAX_PHOTO)return null;
    try{return await api('/api/files/image',{ref,...where},30000);}catch(e){toast('「'+ref.name+'」没按图片读进来，改按文件路径发：'+e.message,true);return null;}
  }
  // ＋ menus: after 从相册选择 in the conversation's (codex-ui.js) and in the new conversation's (new-chat-ui.js)
  function menuRow(id,text,act){const b=el('button','menu-row',text);b.id=id;b.type='button';b.onclick=act;return b;}
  $('choosePhoto').after(menuRow('pickPhoneFiles','手机上的文件',()=>{const me=cur;closeSheet('attachmentMenu');if(me)choosePhone(files=>addPhone(me,files));}),
                         menuRow('pickPcFiles','电脑上的文件',()=>{const me=cur;dismissOverlays();if(me)setTimeout(()=>openFor(me),0);}));
  const menu=$('attachmentMenu');menu.querySelector('b').textContent='添加';menu.setAttribute('aria-label','添加');
  $('addImageBtn').setAttribute('aria-label','添加图片或文件');
  function addPhone(me,files){
    const {photos,others}=splitPhone(files);
    if(photos.length)window.codexUI?.addPhotos(me,photos);
    if(others.length)window.referencesUI?.uploadFiles(me,others);
  }
  function openFor(me){
    open({app:me.app,id:me.id,room:()=>MAX_FILES-(window.referencesUI?.fileCount(me,true)||0),onPick:async entries=>{
      const refs=[];
      for(const v of entries){
        const meta=window.codexUI?.photoRoom(me)>0?await importPicture(v,{app:me.app,id:me.id}):null;
        if(meta)window.codexUI.addImported(me,meta,v);else refs.push(v);
      }
      if(refs.length)window.referencesUI?.addFiles(me,refs);
    }});
  }
  window.filesUI={open,choosePhone,splitPhone,upload,retry,discard,settle,chip,label,importPicture,isFile,isPending,MAX_FILES};
})();
