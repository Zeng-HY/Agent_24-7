(() => {
  // The 停止当前轮 button in a Codex conversation's title bar, shown while a turn runs (codex-ui.js reports the turn).
  // Until 10-12 this file also built the 任务 page (待处理 / 运行中 / 已完成 / 待核对), its sidebar entry and the summary
  // bar over the conversation list; the sidebar now lists conversations by project instead (sidebar-ui.js).
  let control=null;const stopping=new Map();
  const stop=el('button','stop-turn','停止当前轮');stop.hidden=true;stop.setAttribute('aria-label','停止当前轮');document.querySelector('.cv-top .cv-title').after(stop);
  const style=el('style');style.textContent='.stop-turn{border:0;border-radius:999px;background:#fff1f2;color:var(--red);font-size:12px;font-weight:500;min-height:44px;padding:8px;white-space:nowrap}';document.head.append(style);
  function onControl(me,data){
    if(!cur||cur.app!=='codex'||cur.id!==me.id)return;control=data;
    const wait=stopping.get(me.id);
    if(wait){const old=(data.recent_turns||[]).find(t=>t.id===wait);if(old&&old.status!=='inProgress'){stopping.delete(me.id);toast(old.status==='interrupted'?'当前轮已停止':'该轮已结束');}}
    stop.hidden=!data.available||!data.running||!data.active_turn_id;stop.disabled=stopping.has(me.id);stop.textContent=stop.disabled?'正在停止…':'停止当前轮';
    const expected=data.active_turn_id;
    stop.onclick=async()=>{if(!cur||cur.id!==me.id||!expected)return;stopping.set(me.id,expected);stop.disabled=true;stop.textContent='正在停止…';
      const operation=[...crypto.getRandomValues(new Uint8Array(16))].map(v=>v.toString(16).padStart(2,'0')).join('');
      try{const r=await api('/api/codex/stop',{id:me.id,turn_id:expected,operation_id:operation});if(r.ended){stopping.delete(me.id);toast(r.text);}await codexUI.refresh(me,true);}
      catch(e){stopping.delete(me.id);stop.disabled=false;toast('停止结果未确认：'+e.message,true);await codexUI.refresh(me,true);}
    };
  }
  window.activityUI={onControl,onMode(){},onOpen(){stop.hidden=true;}};
})();
