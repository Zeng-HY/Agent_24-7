/* Pinned, local parser + sanitizer. Never trust HTML attributes from a reply. */
(() => {
  const parser=window.markdownit({html:true,breaks:false,linkify:false});
  const local=value=>{try{return /^[A-Za-z]:[\\/]/.test(decodeURIComponent(value));}catch{return false;}};
  const validate=parser.validateLink.bind(parser);
  parser.validateLink=url=>local(url)||validate(url);
  const escape=parser.utils.escapeHtml;
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
    return env.copyable?'<button type="button" class="inline-copy" data-copy-fragment="'+escape(JSON.stringify(raw))+'" aria-label="复制行内内容" title="复制行内内容">'+code+'</button>':code;
  };
  parser.renderer.rules.fence=parser.renderer.rules.code_block=(tokens,i,options,env)=>{
    const t=tokens[i],raw=t.content,language=t.info.trim().split(/\s+/)[0];
    return '<div class="code-wrap"><div class="code-head"><span>'+escape(language||'文本')+'</span><button class="code-lines" type="button">保持原始行</button>'+(env.copyable?'<button type="button" class="code-copy" data-copy-fragment="'+escape(JSON.stringify(raw))+'">复制原文</button>':'')+'</div><pre><code>'+escape(raw)+'</code></pre></div>';
  };
  parser.renderer.rules.table_open=()=>'<div class="table-scroll"><table>';
  parser.renderer.rules.table_close=()=>'</table></div>';
  window.renderMarkdown=(text,copyable=false)=>DOMPurify.sanitize(parser.render(String(text),{referenceIndex:0,copyable}),{
    ALLOWED_TAGS:['p','br','h1','h2','h3','h4','h5','h6','ul','ol','li','blockquote','strong','em','s','hr','pre','code','table','thead','tbody','tr','th','td','a','img','details','summary','div','span','button'],
    ALLOWED_ATTR:['href','src','alt','title','target','rel','loading','referrerpolicy','class','type','start','data-result-index','data-result-key','data-copy-fragment'],ALLOW_DATA_ATTR:false
  });
  window.updateMarkdown=(node,text,copyable=true)=>{
    const details=[...node.querySelectorAll('details')].map(n=>({label:n.querySelector('summary')?.textContent,open:n.open}));
    const code=[...node.querySelectorAll('.code-wrap')].map(n=>({original:n.classList.contains('original-lines'),left:n.querySelector('pre')?.scrollLeft||0}));
    const images=new Map([...node.querySelectorAll('.local-image')].map(n=>[n.dataset.resultIndex+':'+n.dataset.resultKey,n]));
    node.innerHTML=renderMarkdown(text,copyable);
    for(const image of node.querySelectorAll('.local-image')){const old=images.get(image.dataset.resultIndex+':'+image.dataset.resultKey);if(old)image.replaceWith(old);}
    [...node.querySelectorAll('details')].forEach((n,i)=>{if(details[i]?.label===n.querySelector('summary')?.textContent)n.open=details[i].open;});
    [...node.querySelectorAll('.code-wrap')].forEach((n,i)=>{if(code[i]?.original){n.classList.add('original-lines');n.querySelector('.code-lines').textContent='自动换行';n.querySelector('pre').scrollLeft=code[i].left;}});
  };
  document.addEventListener('click',event=>{const button=event.target.closest('.code-lines');if(!button)return;const wrap=button.closest('.code-wrap');wrap.classList.toggle('original-lines');button.textContent=wrap.classList.contains('original-lines')?'自动换行':'保持原始行';});
})();
