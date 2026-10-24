/* Pinned, local parser + sanitizer. Never trust HTML attributes from a reply. */
(() => {
  const parser=window.markdownit({html:true,breaks:false,linkify:false});
  const local=value=>{try{return /^[A-Za-z]:[\\/]/.test(decodeURIComponent(value));}catch{return false;}};
  const validate=parser.validateLink.bind(parser);
  parser.validateLink=url=>local(url)||validate(url);
  const escape=parser.utils.escapeHtml;
  // One panel contract for fenced text and public tool command/result details.
  const panelStates=new WeakMap();
  function panelHTML(raw,label,key){return '<div class="code-wrap" data-panel-key="'+escape(key)+'"><div class="code-head"><span>'+escape(label)+'</span><button class="code-lines" type="button" aria-pressed="false">保持原始行</button><button type="button" class="code-copy" data-copy-fragment="'+escape(JSON.stringify(raw))+'">复制原文</button></div><pre tabindex="0" aria-label="'+escape(label)+'内容"><code>'+escape(raw)+'</code></pre></div>';}
  const panelKey=(n,root)=>{const scope=n.closest('[data-panel-scope],[data-message-id]');return JSON.stringify([scope&&root.contains(scope)?scope.dataset.panelScope||scope.dataset.messageId||'':'',n.dataset.panelKey]);};
  function capturePanels(root){
    const saved=new Map(panelStates.get(root)||[]);
    for(const n of root.querySelectorAll('.code-wrap')){const pre=n.querySelector('pre'),key=panelKey(n,root),old=saved.get(key);
      saved.set(key,{original:n.classList.contains('original-lines'),top:pre.getClientRects().length?pre.scrollTop:old?.top||0,left:pre.getClientRects().length?pre.scrollLeft:old?.left||0});}
    panelStates.set(root,saved);return saved;
  }
  function restorePanels(root,saved=panelStates.get(root)||new Map()){
    const current=new Map();
    for(const n of root.querySelectorAll('.code-wrap')){const pre=n.querySelector('pre'),key=panelKey(n,root),value=saved.get(key)||{original:false,top:0,left:0};
      current.set(key,value);n.classList.toggle('original-lines',value.original);const button=n.querySelector('.code-lines');button.textContent=value.original?'自动换行':'保持原始行';button.setAttribute('aria-pressed',String(value.original));
      if(pre.getClientRects().length){pre.scrollTop=value.top;pre.scrollLeft=value.left;}
      n._panelRoot=root;
      if(!pre._panelScrollBound){pre._panelScrollBound=true;pre.addEventListener('scroll',()=>{
        if(!root.contains(n)||!pre.getClientRects().length)return;
        const state=panelStates.get(root);state?.set(key,{original:n.classList.contains('original-lines'),top:pre.scrollTop,left:pre.scrollLeft});
      },{passive:true});}
    }
    panelStates.set(root,current);
  }
  window.codePanels={capture:capturePanels,restore:restorePanels,create(raw,label,key){const template=document.createElement('template');template.innerHTML=panelHTML(String(raw),label,key);return template.content.firstElementChild;}};
  const reference=(token,env)=>{const index=env.referenceIndex++;return 'data-result-index="'+index+'"';};
  parser.renderer.rules.html_block=parser.renderer.rules.html_inline=(tokens,i)=>tokens[i].content.replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1\s*>/gi,'').replace(/<[^>]*>/g,tag=>/^<\/?(?:details|summary)\s*>$/i.test(tag)?tag:'');
  parser.renderer.rules.link_open=(tokens,i,options,env)=>{
    const token=tokens[i],href=token.attrGet('href')||'';
    if(local(href))return '<a href="#" '+reference(token,env)+'>';
    if(/^https?:\/\//i.test(href)){try{const url=new URL(href);if(!url.username&&!url.password)return '<a href="'+escape(url.href)+'" target="_blank" rel="noopener noreferrer">';}catch{}}
    return '<a>';
  };
  parser.renderer.rules.image=(tokens,i,options,env)=>{
    const token=tokens[i],src=token.attrGet('src')||'',alt=escape(token.content);
    if(local(src))return '<a href="#" class="local-image" data-result-key="'+escape(src)+'" '+reference(token,env)+'><img loading="lazy" alt="'+alt+'"><span>读取图片</span></a>';
    if(/^https:\/\//i.test(src))return '<img loading="lazy" referrerpolicy="no-referrer" src="'+escape(src)+'" alt="'+alt+'">';
    return alt;
  };
  parser.renderer.rules.code_inline=(tokens,i,options,env)=>{
    const raw=tokens[i].content,code='<code>'+escape(raw)+'</code>';
    return code;
  };
  parser.renderer.rules.fence=parser.renderer.rules.code_block=(tokens,i,options,env)=>{
    const t=tokens[i],raw=t.content,language=t.info.trim().split(/\s+/)[0];
    return panelHTML(raw,language||'文本','code-'+env.codeIndex++);
  };
  parser.renderer.rules.table_open=()=>'<div class="table-scroll"><table>';
  parser.renderer.rules.table_close=()=>'</table></div>';
  window.renderMarkdown=(text,copyable=false)=>DOMPurify.sanitize(parser.render(String(text),{referenceIndex:0,codeIndex:0,copyable}),{
    ALLOWED_TAGS:['p','br','h1','h2','h3','h4','h5','h6','ul','ol','li','blockquote','strong','em','s','hr','pre','code','table','thead','tbody','tr','th','td','a','img','details','summary','div','span','button'],
    ALLOWED_ATTR:['href','src','alt','title','target','rel','loading','referrerpolicy','class','type','start','tabindex','aria-label','aria-pressed','data-panel-key','data-result-index','data-result-key','data-copy-fragment'],ALLOW_DATA_ATTR:false
  });
  window.updateMarkdown=(node,text,copyable=true)=>{
    const details=[...node.querySelectorAll('details')].map(n=>({label:n.querySelector('summary')?.textContent,open:n.open}));
    const code=capturePanels(node);
    const images=new Map([...node.querySelectorAll('.local-image')].map(n=>[n.dataset.resultIndex+':'+n.dataset.resultKey,n]));
    node.innerHTML=renderMarkdown(text,copyable);
    for(const image of node.querySelectorAll('.local-image')){const old=images.get(image.dataset.resultIndex+':'+image.dataset.resultKey);if(old)image.replaceWith(old);}
    [...node.querySelectorAll('details')].forEach((n,i)=>{if(details[i]?.label===n.querySelector('summary')?.textContent)n.open=details[i].open;});
    restorePanels(node,code);
  };
  document.addEventListener('click',event=>{const button=event.target.closest('.code-lines');if(!button)return;const wrap=button.closest('.code-wrap');wrap.classList.toggle('original-lines');const original=wrap.classList.contains('original-lines');button.textContent=original?'自动换行':'保持原始行';button.setAttribute('aria-pressed',String(original));if(wrap._panelRoot)capturePanels(wrap._panelRoot);});
})();
