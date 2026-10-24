"""Append-aware public transcript index and scoped result-file registry."""
from __future__ import annotations
import base64,copy,hashlib,hmac,json,mimetypes,re,threading,time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote
import chats
import activity_records

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
                    if self.app=='codex' and b'"event_msg"' not in raw[:160] and b'"response_item"' not in raw[:160]:continue
                    msgs,state=chats._parse(self.app,[raw],self.context)
                    msgs=activity_records.enrich(self.app,raw,msgs,self.context)
                    for k,v in state.items():
                        if v is not None and v!='':self.state[k]=v
                    for m in msgs:
                        # Dual log representations may share a source ID, or exact
                        # timestamp/turn/phase/content evidence. Never drop all legacy rows.
                        if self.app=='codex':
                            peer=next((v for v in reversed(self.messages[-4:]) if v['role']==m['role'] and v.get('time')==m.get('time') and v.get('phase','')==m.get('phase','') and v['text']==m['text'] and v.get('turn_id')==self.state.get('current_turn_id') and bool(v.get('public_response'))!=bool(m.get('public_response'))),None)
                            if peer:
                                if m.get('source_id'):peer['source_id']=m['source_id'];self.by_id[m['source_id']]=peer
                                continue
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
        self.catalog_load_lock=threading.Lock();self.catalog_generation=0
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
        # The home list and sidebar arrive together. Only one request scans a cold catalog.
        with self.catalog_load_lock:
            return self._load_catalog()
    def _load_catalog(self):
        with self.lock:
            if time.monotonic()-self.catalog_cache[0]<10:return self.catalog_cache[1],self.catalog_cache[2]
            generation=self.catalog_generation
        items=[]
        try:items+=chats.codex_threads(1000000)
        except Exception:pass
        import deepseek_control
        found=deepseek_control.listing()
        items+=chats.claude_sessions(1000000);items+=copy.deepcopy(found['top']);items.sort(key=lambda v:(-v['updated'],v['app'],v['id']))
        stray=copy.deepcopy(found['ungrouped'])
        with self.lock:
            if generation==self.catalog_generation:self.catalog_cache=(time.monotonic(),items,stray)
        return items,stray
    def invalidate(self):
        """Read the lists again at the next ask: one was archived or restored from the phone (archives.py)."""
        with self.lock:
            self.catalog_generation+=1;self.catalog_cache=(0,[],[])
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
    def conversations(self,app='all',limit=40,cursor='',query='',sort='updated',status='all',status_resolver=None):
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
        if status not in ('all','running','waiting','idle'):raise HistoryError('状态筛选无效')
        if sort not in ('updated','created'):raise HistoryError('排序无效')
        if status!='all':
            items=[v|{'status':chats.summary(v)['status']} if not v.get('kind') else v for v in items]
            if status_resolver:items=status_resolver(items)
            items=[v for v in items if v.get('status')==status]
        def sort_key(v):return (-(v.get(sort) or 0),v['app'],v['id'])
        items.sort(key=sort_key)
        total=len(items)
        if cursor:
            boundary=decode(cursor)
            if not isinstance(boundary,list) or len(boundary)!=3 or not isinstance(boundary[0],(int,float)) or not all(isinstance(v,str) for v in boundary[1:]):raise HistoryError('分页位置无效')
            items=[v for v in items if sort_key(v)>tuple(boundary)]
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
        next_cursor=encode(list(sort_key(page[-1]))) if len(items)>limit and page else None
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
        result=activity_records.public_message(m)
        result.pop('legacy',None)
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
                'activity_turns':{k:v for k,v in entry.context.get('activity_turns',{}).items() if k == entry.context.get('activity_turn') or k in {m.get('activity_turn') for m in page}},
                'activity_current':entry.context.get('activity_turn'),
                'has_more':start>0,'next_cursor':page[0]['id'] if start>0 and page else None,'has_newer':end<len(rows),'reset':reset,'total':len(rows)}
    def message(self,app,tid,mid):
        _,entry=self.transcript(app,tid)
        with entry.lock:
            m=entry.by_id.get(mid)
            if not m:raise HistoryError('消息已变化，请刷新',404)
            return self.public_message(m,True)
    def diff(self,app,tid,ref,offset=0):
        _,entry=self.transcript(app,tid)
        with entry.lock:
            result=activity_records.diff_page(entry.messages,ref,offset)
            if result is None:raise HistoryError('这份修改记录不可用，请刷新对话',404)
            return result
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
    def list_files(self,app,tid,message_id=None):
        from message_files import references
        item,entry=self.transcript(app,tid)
        out=[]
        with entry.lock:
            messages=[m for m in entry.messages if (m['role']=='assistant' or (m.get('current_file') and m.get('tool_status')=='completed')) and (not message_id or m['id']==message_id)]
            for m in reversed(messages):
                paths=references(m['text']) if m['role']=='assistant' else [m['current_file']]
                for index,raw in enumerate(paths):
                    p=Path(raw)
                    # Only an explicit source reference authorizes this exact regular local file.
                    if not p.is_absolute() or not re.match(r'^[A-Za-z]:[\\/]',raw) or ':' in raw[2:] or '\x00' in raw:continue
                    identity=[app,tid,m['id'],index,str(p)]
                    fid=hmac.new(self.secret,json.dumps(identity).encode(),hashlib.sha256).hexdigest()[:32]
                    old=self.files.get((app,tid,fid))
                    try:
                        resolved=p.resolve()
                        # A specific path grants no authority over a symlink/junction's new target.
                        if resolved!=p.absolute():continue
                        st=p.stat() if p.is_file() else None
                    except (OSError,ValueError):st=None
                    suffix=p.suffix.lower();size=st.st_size if st else 0
                    kind='pdf' if suffix=='.pdf' else 'image' if suffix in ('.png','.jpg','.jpeg','.webp') else 'text' if suffix in ('.txt','.md','.csv','.tsv','.json','.py','.js','.html','.htm','.markdown','.css','.ts','.tsx','.jsx','.ps1','.sh','.yaml','.yml','.sql') and size<=1<<20 else 'download'
                    updated=bool(old and st and old['mtime'] is not None and (old['mtime']!=st.st_mtime_ns or old['size']!=size))
                    self.files[(app,tid,fid)]={'path':p,'resolved':resolved,'size':size,'mtime':st.st_mtime_ns if st else None,'kind':kind,'message_id':m['id'],'index':index,'updated':updated or bool(old and old.get('updated'))}
                    out.append({'id':fid,'name':p.name,'path':str(p),'size':size,'modified':st.st_mtime_ns//1000000 if st else None,'kind':kind,'message_id':m['id'],'index':index,'state':'missing' if not st else 'updated' if self.files[(app,tid,fid)]['updated'] else 'current'})
        return {'items':out,'scope':'当前会话明确引用的具体文件；打开当前内容，不保存历史副本'}

    def file(self,app,tid,fid):
        meta=self.files.get((app,tid,fid))
        # Revalidate source authorization on every access, including old references.
        listed=self.list_files(app,tid,meta['message_id'] if meta else None)
        if not any(f['id']==fid for f in listed['items']):raise HistoryError('文件引用无效或不属于当前对话',403)
        meta=self.files[(app,tid,fid)]
        try:
            p=meta['path'].resolve()
            if p!=meta['resolved'] or p!=meta['path'].absolute():raise HistoryError('文件真实路径已变化，引用无效',403)
            if not p.is_file():raise HistoryError('文件已移动或删除',404)
            st=p.stat()
        except OSError:raise HistoryError('文件已移动或删除',404) from None
        mime='application/pdf' if meta['kind']=='pdf' else (mimetypes.guess_type(p.name)[0] or 'image/png') if meta['kind']=='image' else 'text/plain; charset=utf-8' if meta['kind']=='text' else 'application/octet-stream'
        return {**meta,'path':p,'size':st.st_size,'mime':mime}
