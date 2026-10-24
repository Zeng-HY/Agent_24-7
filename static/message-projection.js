/* One identity/order projection. Transport observations never imply text identity. */
(() => {
  const observed=new Map();
  function merge(previous, incoming, prepend=false) {
    const map=new Map(previous.map(m=>[m.id,m]));
    const ids=previous.map(m=>m.id);
    for(const m of incoming){
      const peer=[...map.values()].find(old=>old.id!==m.id&&((m.projection_aliases||[]).includes(old.id)||(m.source_id&&old.source_id===m.source_id)));
      if(peer){map.delete(peer.id);const at=ids.indexOf(peer.id);if(at>=0)ids[at]=m.id;map.set(m.id,{...m,display_id:peer.display_id||peer.id});}
      else if(!(m.streaming&&map.has(m.id)&&!map.get(m.id).streaming))map.set(m.id,{...map.get(m.id),...m});
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
  function place(rows,row,item){
    const previous=rows.findIndex(r=>r.key===item.predecessor||r.message?.id===item.predecessor||r.message?.source_id===item.predecessor||r.items?.some(m=>m.id===item.predecessor));
    // Missing predecessor (e.g. a historical window): do not invent a position.
    if(item.predecessor&&previous<0)return;
    let at=previous+1;
    while(at<rows.length&&rows[at].projectionAnchor===item.predecessor&&rows[at].localOrder<=item.started)at++;
    row.projectionAnchor=item.predecessor;row.localOrder=item.started;
    rows.splice(at,0,row);
  }
  function observe(rows,row,scope,after=null,before=null){
    const key=scope+':'+row.key;
    if(!observed.has(key))observed.set(key,{after:after||rows.at(-1)?.message?.id||rows.at(-1)?.key||null,before});
    const anchor=observed.get(key),next=rows.findIndex(r=>r.key===anchor.before||r.message?.id===anchor.before||r.message?.source_id===anchor.before);
    if(next>=0){rows.splice(next,0,row);return;}
    place(rows,row,{predecessor:anchor.after,started:0});
  }
  window.messageProjection={merge,matches,place,observe};
})();
