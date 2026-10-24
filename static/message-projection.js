/* One identity/order projection. Transport observations never imply text identity. */
(() => {
  function merge(previous, incoming, prepend=false) {
    const map=new Map(previous.map(m=>[m.id,m]));
    const ids=previous.map(m=>m.id);
    for(const m of incoming){
      const peer=[...map.values()].find(old=>old.id!==m.id&&((m.projection_aliases||[]).includes(old.id)||(m.source_id&&old.source_id===m.source_id)));
      if(peer){map.delete(peer.id);const at=ids.indexOf(peer.id);if(at>=0)ids[at]=m.id;map.set(m.id,{...m,display_id:peer.display_id||peer.id});}
      else if(!(m.streaming&&map.has(m.id)&&!map.get(m.id).streaming)){
        const next={...map.get(m.id),...m};
        if(!m.streaming){delete next.streaming;delete next.sync_pending;}
        map.set(m.id,next);
      }
    }
    const known=new Set(ids);
    for(const m of (prepend?[...incoming].reverse():incoming))if(map.has(m.id)&&!known.has(m.id)){prepend?ids.unshift(m.id):ids.push(m.id);known.add(m.id);}
    // Sort only source-ordered slots. Unordered records keep their stable slots;
    // a comparator returning zero for mixed pairs is not a transitive ordering.
    const stable=[...new Set(ids.filter(id=>map.has(id)))];
    const ordered=stable.map(id=>map.get(id)).filter(m=>Number.isFinite(m.order)).sort((a,b)=>a.order-b.order);
    let i=0;return stable.map(id=>Number.isFinite(map.get(id).order)?ordered[i++]:map.get(id));
  }
  function matches(m,item){return !!m&&[m.client_request_id,m.request_id,m.client_id].some(id=>id&&[item.rid,item.client_id,item.queue_id].includes(id))||!!(item.source_id&&[m?.id,m?.source_id].includes(item.source_id));}
  function reconcileLive(messages,ids){
    if(!Array.isArray(ids))return messages;
    const active=new Set(ids);
    return messages.map(m=>m.streaming?{...m,sync_pending:!active.has(m.id)}:m);
  }
  function place(rows,row,item){
    const previous=rows.findIndex(r=>r.key===item.predecessor||r.message?.id===item.predecessor||r.message?.source_id===item.predecessor||r.items?.some(m=>m.id===item.predecessor));
    // Missing predecessor (e.g. a historical window): do not invent a position.
    if(item.predecessor&&previous<0)return;
    let at=previous+1;
    while(at<rows.length&&rows[at].projectionAnchor===item.predecessor&&rows[at].localOrder<=item.started)at++;
    row.projectionAnchor=item.predecessor;row.localOrder=item.started;
    rows.splice(at,0,row);
  }
  // Control observations may enrich a visible source node, never create a tail.
  function sourceRow(rows,id){return id&&rows.find(r=>r.message&&(r.message.id===id||r.message.source_id===id));}
  function decorate(rows){
    for(let i=rows.length-1;i>=0;i--)if(rows[i].key?.startsWith('pending:'))rows.splice(i,1);
    const control=window.codexUI?.observations()||{},items=window.workspaceUI?.observations()||[];
    const claimed=new Set(),unresolved=[];
    for(const item of items){
      const candidates=rows.filter(r=>r.message?.role==='user'&&!claimed.has(r)&&matches(r.message,item));
      const row=candidates.length===1?candidates[0]:null;
      if(row){claimed.add(row);row.key='outbox:'+item.rid;row.images=row.images||item.images?.map(v=>v.meta).filter(Boolean);row.receipt={k:'done',text:'电脑已接收'};window.workspaceUI?.acceptSource(item.rid,row.message);continue;}
      if(item.recorded||item.resolution?.status==='recorded')continue;
      if(item.state==='queued'||item.body?.intent==='queue'&&['sending','queued','unconfirmed','cancelled'].includes(item.state))continue;
      const positioned=item.position_version===2&&Object.hasOwn(item,'predecessor')&&!window.readingUI?.historyWindow;
      const bubble={key:'outbox:'+item.rid,workspace:{...item,body:undefined},created:item.started/1000};
      if(positioned){const before=rows.length;place(rows,bubble,item);if(rows.length>before)continue;}
      unresolved.push(item);
    }
    for(const post of control.images||[]){const row=rows.find(r=>r.message?.role==='user'&&matches(r.message,{rid:post.request_id,client_id:post.client_id,source_id:post.message_id}));if(row)row.images=post.images;}
    for(const card of control.questions||[]){
      let row=sourceRow(rows,card.source_id)||sourceRow(rows,card.request_id);
      if(!row&&card.source_id&&Number.isFinite(card.source_order)){
        const ordered=rows.filter(r=>Number.isFinite(r.message?.order));
        if(ordered.length&&card.source_order>=ordered[0].message.order&&card.source_order<=ordered.at(-1).message.order){
          row={key:card.source_id,message:{id:card.source_id,source_id:card.source_id,role:'question',order:card.source_order,turn_id:card.turn_id,text:''}};
          const at=rows.findIndex(r=>Number.isFinite(r.message?.order)&&r.message.order>card.source_order);rows.splice(at<0?rows.length:at,0,row);
        }
      }
      if(row){row.custom={type:'answer',card};row.message={...row.message,role:'question'};}
    }
    if(control.plan){const row=sourceRow(rows,control.plan.source_id)||sourceRow(rows,control.plan.id);if(row){row.custom={type:'plan',plan:control.plan};row.message={...row.message,role:'plan-card'};}}
    window.workspaceUI?.setUnresolved(unresolved);
  }
  window.messageProjection={merge,matches,place,decorate,reconcileLive};
})();
