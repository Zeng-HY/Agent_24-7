/* Shared reading position for image load, Markdown, activity and viewport changes. */
(() => {
  const box=document.getElementById('cvMsgs');let saved=null,frame=0;
  function capture(){const top=box.getBoundingClientRect().top,node=[...box.children].find(n=>n.getBoundingClientRect().bottom>top);saved={bottom:box.scrollHeight-box.scrollTop-box.clientHeight<80,key:node?.dataset.key,y:node?.getBoundingClientRect().top-top};}
  function restore(){if(!saved)return;if(saved.bottom)box.scrollTop=box.scrollHeight;else{const node=[...box.children].find(n=>n.dataset.key===saved.key);if(node)box.scrollTop+=node.getBoundingClientRect().top-box.getBoundingClientRect().top-saved.y;}box.scrollLeft=0;capture();}
  const observer=new ResizeObserver(()=>{if(!frame)frame=requestAnimationFrame(()=>{frame=0;restore();});});
  new MutationObserver(()=>{for(const node of box.children)observer.observe(node);}).observe(box,{childList:true});
  box.addEventListener('scroll',capture,{passive:true});box.addEventListener('click',capture,true);observer.observe(box);
  window.messageScroll={capture,restore};capture();
})();
