"""Append-aware public transcript index and scoped result-file registry."""
from __future__ import annotations
import base64,copy,hashlib,hmac,json,mimetypes,re,threading,time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote
import chats

class HistoryError(Exception):
    def __init__(self,message,status=400):super().__init__(message);self.status=status

UNGROUPED='ungrouped'  # the list row standing for DeepSeek's Ungrouped bucket (10-20)
CHILDREN_SHOWN=30      # children sent with a row; the rest on request (/api/chats/children)

def encode(value):return base64.urlsafe_b64encode(json.dumps(value,separators=(',',':')).encode()).decode().rstrip('=')
def decode(value):
    try:return json.loads(base64.urlsafe_b64decode(value+'='*(-len(value)%4)))
    except Exception:raise HistoryError('分页位置无效，请刷新') from None

class Transcript:
    def __init__(self,path,app):
        self.path=path;self.app=app;self.offset=0;self.inode=None;self.messages=[];self.by_id={};self.duplicates={};self.state={};self.modern=False;self.lock=threading.RLock();self.size=0;self.mtime=0
        self.context={}  # what a line needs to know of earlier ones (Claude's next-step boxes, 10-16)
    def refresh(self):
        with self.lock:
            st=self.path.stat()
            if self.inode is not None and (st.st_ino!=self.inode or st.st_size<self.offset or (st.st_size==self.offset and st.st_mtime_ns!=self.mtime)):
                self.offset=0;self.messages=[];self.by_id={};self.duplicates={};self.state={};self.modern=False;self.context={}
            self.inode=st.st_ino
            if st.st_size==self.offset:self.size=st.st_size;self.mtime=st.st_mtime_ns;return self
            with self.path.open('rb') as f:
                f.seek(self.offset)
                while f.tell()<st.st_size:
                    raw=f.readline(st.st_size-f.tell())
                    if not raw.endswith(b'\n'):break
                    self.offset=f.tell()
                    if self.app=='codex' and b'"event_msg"' not in raw[:160]:continue
                    msgs,state=chats._parse(self.app,[raw],self.context)
                    for k,v in state.items():
                        if v is not None and v!='':self.state[k]=v
                    for m in msgs:
                        modern=self.app=='codex' and m['role'] in ('user','assistant') and not m.get('legacy')
                        if modern and not self.modern:
                            self.modern=True;self.messages=[v for v in self.messages if not v.get('legacy')];self.by_id={v['id']:v for v in self.messages}
                        if self.modern and m.get('legacy'):continue
                        identity=json.dumps([m.get('time'),m['role'],m.get('phase'),m['text']],ensure_ascii=False)
                        digest=hashlib.sha256(identity.encode()).hexdigest()[:24]
                        self.duplicates[digest]=self.duplicates.get(digest,0)+1
                        m['id']=m.get('source_id') or digest+':'+str(self.duplicates[digest])
                        m['order']=self.offset
                        if self.app=='codex' and self.state.get('current_turn_id'):m['turn_id']=self.state['current_turn_id']
                        if m['id'] in self.by_id:
                            m['order']=self.by_id[m['id']]['order'];self.by_id[m['id']].update(m)
                        else:self.messages.append(m);self.by_id[m['id']]=m
            # Read a line at a time, a box looked open on its own line for good, even after the user had answered (10-16)
            if self.app=='claude':chats.mark_open_next(self.messages)
            self.size=st.st_size;self.mtime=st.st_mtime_ns
        return self

class History:
    def __init__(self,roots=None,secret=''):
        self.entries=OrderedDict();self.lock=threading.RLock();self.roots=roots or [];self.secret=secret.encode();self.files={};self.catalog_cache=(0,[],[])
    def transcript(self,app,tid):
        if app=='deepseek':
            import deepseek_control
            try:return deepseek_control.bridge().transcript(tid)
            except deepseek_control.DeepSeekError as exc:raise HistoryError(str(exc),exc.status) from None
        item=chats.find(app,tid);path=chats.conv_path(item)
        if not path or not path.is_file():raise HistoryError('没有找到这段对话的记录',404)
        key=(app,tid,str(path))
        with self.lock:
            entry=self.entries.get(key)
            if entry is None:entry=Transcript(path,app);self.entries[key]=entry
            self.entries.move_to_end(key)
            while len(self.entries)>8:self.entries.popitem(last=False)
        return item,entry.refresh()
    def _load(self):
        """(conversations of every app, DeepSeek sessions in no workspace that no conversation claims), 10 s."""
        with self.lock:
            if time.monotonic()-self.catalog_cache[0]<10:return self.catalog_cache[1],self.catalog_cache[2]
        items=[]
        try:items+=chats.codex_threads(1000000)
        except Exception:pass
        import deepseek_control
        found=deepseek_control.listing()
        items+=chats.claude_sessions(1000000);items+=copy.deepcopy(found['top']);items.sort(key=lambda v:(-v['updated'],v['app'],v['id']))
        stray=copy.deepcopy(found['ungrouped'])
        with self.lock:self.catalog_cache=(time.monotonic(),items,stray)
        return items,stray
    def invalidate(self):
        """Read the lists again at the next ask: one was archived or restored from the phone (archives.py)."""
        with self.lock:self.catalog_cache=(0,[],[])
    def catalog(self):
        return list(self._load()[0])
    def ungrouped(self):
        """DeepSeek's Ungrouped bucket (10-20): sessions in no workspace that no conversation claims."""
        return list(self._load()[1])
    @staticmethod
    def bucket(stray):
        """The Ungrouped bucket as one row of the list, placed by its newest session."""
        running=sum(1 for c in stray if c.get('status')=='running')
        return {'app':'deepseek','id':UNGROUPED,'group':True,'title':'未分组的会话','folder':'','cwd':'',
                'updated':max(c['updated'] for c in stray),'status':'running' if running else 'idle',
                'preview':'不在 DeepSeek 工作区里，多是脚本或命令行开的一次性会话','children':stray}
    @staticmethod
    def child_row(c):
        return {k:c.get(k) for k in ('app','id','title','folder','cwd','updated','status','kind','parent')}|(
            {'parent_title':c['parent_title']} if c.get('parent_title') else {})
    def conversations(self,app='all',limit=40,cursor='',query=''):
        limit=max(5,min(100,limit));query=query.strip().casefold()[:200]
        found,stray=self._load()
        items=[v for v in found if app=='all' or v['app']==app]
        if query:
            # a search looks through children and the Ungrouped bucket too; a hit is a row of its own
            if app in ('all','deepseek'):
                for v in found:
                    if v['app']=='deepseek':items+=[c|{'parent_title':v['title']} for c in v.get('children',[])]
                items+=stray
            items=[v for v in items if query in (v['title']+' '+(v.get('folder') or '')+' '+v['id']).casefold()]
            items.sort(key=lambda v:(-v['updated'],v['app'],v['id']))
        elif stray and app in ('all','deepseek'):
            items=sorted(items+[self.bucket(stray)],key=lambda v:(-v['updated'],v['app'],v['id']))
        total=len(items)
        if cursor:
            boundary=decode(cursor)
            if not isinstance(boundary,list) or len(boundary)!=3 or not isinstance(boundary[0],(int,float)) or not all(isinstance(v,str) for v in boundary[1:]):raise HistoryError('分页位置无效')
            items=[v for v in items if (-v['updated'],v['app'],v['id'])>tuple(boundary)]
        page=items[:limit];out=[]
        for item in page:
            if item.get('kind'):out.append(self.child_row(item));continue
            info=chats.summary(item);row=chats.public(item)|{'status':info['status'],'preview':info['preview']}
            if item.get('group'):row['group']=True
            if item.get('children'):
                kids=item['children']
                row|={'children':[self.child_row(c) for c in kids[:CHILDREN_SHOWN]],'child_count':len(kids),
                      'child_running':sum(1 for c in kids if c.get('status')=='running')}
            out.append(row)
        next_cursor=encode([-page[-1]['updated'],page[-1]['app'],page[-1]['id']]) if len(items)>limit and page else None
        return {'items':out,'has_more':bool(next_cursor),'next_cursor':next_cursor,'total':total,'now':int(time.time()*1000)}
    def children(self,app,tid,offset=0,limit=50):
        """More children of one conversation, or more of the Ungrouped bucket, past the first CHILDREN_SHOWN."""
        if app!='deepseek':raise HistoryError('只有 DeepSeek 对话有子对话',400)
        found,stray=self._load()
        kids=stray if tid==UNGROUPED else next((v.get('children',[]) for v in found if v['app']==app and v['id']==tid),None)
        if kids is None:raise HistoryError('找不到这个对话，请刷新列表',404)
        offset=max(0,int(offset));limit=max(1,min(100,int(limit)))
        return {'items':[self.child_row(c) for c in kids[offset:offset+limit]],'total':len(kids),'offset':offset}
    @staticmethod
    def public_message(m,full=False):
        result={k:v for k,v in m.items() if k not in ('legacy',)}
        result['length']=len(m['text']);result['truncated']=not full and len(m['text'])>6000
        if result['truncated']:result['text']=m['text'][:6000]
        return result
    def conversation(self,app,tid,limit=60,before='',around=''):
        if app=='deepseek':
            import deepseek_control
            try:return deepseek_control.bridge().conversation(tid,limit,before,around)
            except deepseek_control.DeepSeekError as exc:raise HistoryError(str(exc),exc.status) from None
        item,entry=self.transcript(app,tid);limit=max(5,min(100,limit));reset=False
        with entry.lock:
            rows=entry.messages;end=len(rows)
            if before:
                at=next((i for i,m in enumerate(rows) if m['id']==before),None)
                if at is None:reset=True
                else:end=at
            if around:
                at=next((i for i,m in enumerate(rows) if m['id']==around),None)
                if at is not None:end=min(len(rows),at+limit//2+1)
            start=max(0,end-limit);page=rows[start:end]
            return chats.public(item)|{'messages':[self.public_message(m) for m in page], 'status':chats._status(entry.state,entry.mtime/1e9),
                'size':entry.size,'runtime':chats.runtime_info(app,entry.path),'modified':entry.mtime//1000000,
                'has_more':start>0,'next_cursor':page[0]['id'] if start>0 and page else None,'has_newer':end<len(rows),'reset':reset,'total':len(rows)}
    def message(self,app,tid,mid):
        _,entry=self.transcript(app,tid)
        with entry.lock:
            m=entry.by_id.get(mid)
            if not m:raise HistoryError('消息已变化，请刷新',404)
            return self.public_message(m,True)
    def search(self,app,tid,query,cursor='',limit=30):
        if not query.strip() or len(query)>200:raise HistoryError('请输入 1 至 200 字的关键词')
        _,entry=self.transcript(app,tid);needle=query.casefold();offset=decode(cursor) if cursor else 0
        if not isinstance(offset,int) or offset<0:raise HistoryError('搜索分页位置无效')
        with entry.lock:
            hits=[]
            for m in entry.messages:
                if m['role'] not in ('user','assistant'):continue
                at=m['text'].casefold().find(needle)
                if at<0:continue
                hits.append({'id':m['id'],'role':m['role'],'origin':m.get('origin'),'time':m.get('time'),'snippet':m['text'][max(0,at-60):at+len(query)+100]})
            more=offset+limit<len(hits)
            return {'items':hits[offset:offset+limit],'has_more':more,'next_cursor':encode(offset+limit) if more else None,'total':len(hits)}
    def list_files(self,app,tid):
        item,entry=self.transcript(app,tid);roots=[Path(r).resolve() for r in self.roots if r]
        if item.get('cwd'):roots.append(Path(item['cwd']).resolve())
        allowed={'.pdf','.doc','.docx','.xls','.xlsx','.csv','.tsv','.txt','.md','.png','.jpg','.jpeg','.webp','.json','.py','.js','.html','.zip','.pptx'}
        seen=set();out=[]
        with entry.lock:
            messages=[m for m in entry.messages if m['role']=='assistant' and m.get('phase')!='commentary']
            for m in reversed(messages):
                for match in re.finditer(r'!?\[([^\]]*)\]\((?:<([^>]+)>|([^\n)]+))\)',m['text']):
                    raw=unquote((match[2] or match[3] or '').strip());raw=re.sub(r':\d+(?:-\d+)?$','',raw)
                    if not re.match(r'^[A-Za-z]:[\\/]',raw):continue
                    p=Path(raw)
                    if p.suffix.lower() not in allowed:continue
                    try:
                        p=p.resolve()
                        if not any(p.is_relative_to(root) for root in roots) or not p.is_file() or str(p) in seen:continue
                        st=p.stat()
                    except (OSError,ValueError):continue
                    seen.add(str(p));identity=[app,tid,str(p),st.st_size,st.st_mtime_ns]
                    fid=hmac.new(self.secret,json.dumps(identity).encode(),hashlib.sha256).hexdigest()[:32]
                    suffix=p.suffix.lower();kind='pdf' if suffix=='.pdf' else 'image' if suffix in ('.png','.jpg','.jpeg','.webp') else 'text' if suffix in ('.txt','.md','.csv','.tsv','.json','.py','.js','.html') and st.st_size<=1<<20 else 'download'
                    self.files[(app,tid,fid)]={'path':p,'size':st.st_size,'mtime':st.st_mtime_ns,'roots':roots,'kind':kind}
                    out.append({'id':fid,'name':p.name,'size':st.st_size,'modified':st.st_mtime_ns//1000000,'kind':kind,'message_id':m['id']})
                if len(out)>=100:break
        if len(self.files)>1000:
            for key in list(self.files)[:len(self.files)-1000]:self.files.pop(key,None)
        return {'items':out,'scope':'助手正式回复中引用、且位于允许目录内的文件'}
    def file(self,app,tid,fid):
        meta=self.files.get((app,tid,fid))
        if not meta:self.list_files(app,tid);meta=self.files.get((app,tid,fid))
        if not meta:raise HistoryError('文件引用不存在或已更新，请刷新文件列表',404)
        try:
            p=meta['path'].resolve();st=p.stat()
            if not any(p.is_relative_to(r) for r in meta['roots']):raise HistoryError('文件已移出允许范围',403)
            if st.st_size!=meta['size'] or st.st_mtime_ns!=meta['mtime']:raise HistoryError('文件已更新，请刷新文件列表',409)
        except OSError:raise HistoryError('文件已移动或删除',404) from None
        mime='application/pdf' if meta['kind']=='pdf' else (mimetypes.guess_type(p.name)[0] or 'image/png') if meta['kind']=='image' else 'text/plain; charset=utf-8' if meta['kind']=='text' else 'application/octet-stream'
        return {**meta,'path':p,'mime':mime}
