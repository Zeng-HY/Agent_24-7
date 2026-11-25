"""Append-aware public transcript index and scoped result-file registry."""
from __future__ import annotations
import os,sys
import base64,copy,hashlib,hmac,json,re,threading,time
from array import array
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
import chats
import activity_records
import answer_files
import file_policy

class HistoryError(Exception):
    def __init__(self,message,status=400):super().__init__(message);self.status=status

UNGROUPED='ungrouped'  # the list row standing for DeepSeek's Ungrouped bucket (10-20)
CHILDREN_SHOWN=30      # children sent with a row; the rest on request (/api/chats/children)
# 11-16: parsed transcripts kept in memory. A ninth conversation used to throw the oldest away, so opening it again
# parsed a 114 MB file from its first line.
MAX_TRANSCRIPTS=24
# One scan result can serve several messages with the same words (a repeated template, the same answer copied).
MAX_SCAN_CACHE=256
# 11-24: bounded by the memory the parsed messages take (Transcript.weight), no longer by the size of their files. A
# parsed Claude record keeps 6-23% of its file (tracemalloc: 420 MB -> 48 MB, 319 MB -> 19 MB, 114 MB -> 14 MB), so the
# 600 MB of files allowed before let two or three big conversations push out all the others, and each switch back
# read a big file again for seconds.
MAX_TRANSCRIPT_MEMORY=400<<20
# The files' own size is only a far backstop now (the 30 recent Claude records on the PC total 1.3 GB).
MAX_TRANSCRIPT_BYTES=4<<30
# What a message costs beyond the strings, lists and dicts weigh() counts: its slots in messages, by_id and duplicates
# (a 24-character digest each), its weight and its numbers. And each record uuid kept to leave a repeated copy out.
# With these the estimate came within 7% of tracemalloc on 7 Claude records of 3-420 MB (11-24).
MESSAGE_EXTRA=200
UUID_EXTRA=140
WEIGH_AGAIN=64  # rows before a read's first new one weighed again: a tool's result lands on its call's row lines later
# 11-24: the conversations updated last are read ahead in the background, so opening one does not parse its file first
# (a 420 MB Claude record took 5 s cold, 25 ms once read). Only in the installed app: History(warm=None).
WARM_AFTER=20        # seconds after start
WARM_EVERY=60        # seconds between rounds
WARM_COUNT=8         # conversations read ahead, newest first
WARM_SLICE=4<<20     # bytes read at a time, ending at a line's end ...
WARM_PAUSE=.03       # ... with a pause between, so the page requests keep the interpreter
WARM_GUESS=4         # a file not read yet counts as a quarter of its size in memory until it is (6-23% measured)

def weigh(value,depth=0):
    """Bytes held by one parsed message, or a list or dict inside it: the object itself and every string and container
    it holds (sys.getsizeof each). Keys are the parsers' own names, shared by every message, and not counted."""
    size=sys.getsizeof(value)
    if depth>8:return size
    for v in (value.values() if isinstance(value,dict) else value):
        if isinstance(v,(str,bytes)):size+=sys.getsizeof(v)
        elif isinstance(v,(dict,list,tuple,set)):size+=weigh(v,depth+1)
    return size

def encode(value):return base64.urlsafe_b64encode(json.dumps(value,separators=(',',':')).encode()).decode().rstrip('=')
def decode(value):
    try:return json.loads(base64.urlsafe_b64decode(value+'='*(-len(value)%4)))
    except Exception:raise HistoryError('分页位置无效，请刷新') from None


# -- answer files (docs/handoff-file-preview.md §5.1): suffix tables until segment C reads the contents
_IMAGE_KIND={'.png','.jpg','.jpeg','.webp','.bmp','.heic','.heif','.tif','.tiff'}
_IMAGE_VIEW=_IMAGE_KIND|{'.gif'}
_TEXT_KIND={'.txt','.md','.csv','.tsv','.json','.py','.js','.html','.htm','.markdown','.css',
            '.ts','.tsx','.jsx','.ps1','.sh','.yaml','.yml','.sql'}
_OFFICE={'.doc','.docx','.rtf','.odt','.xls','.xlsx','.xlsm','.ods','.ppt','.pptx','.odp'}
_MARKDOWN={'.md','.markdown'}
_HTML={'.html','.htm','.xhtml'}
_CODE={'.py','.js','.mjs','.ts','.tsx','.jsx','.json','.yaml','.yml','.xml','.sql','.r','.log',
       '.css','.scss','.less','.ps1','.sh','.bat','.cmd','.c','.h','.cpp','.hpp','.cs','.java',
       '.kt','.kts','.swift','.go','.rs','.rb','.php','.lua','.toml','.ini','.cfg','.conf',
       '.gradle','.tex','.dockerfile','.makefile'}
_AUDIO={'.mp3','.m4a','.aac','.wav','.flac','.ogg'}
_VIDEO={'.mp4','.m4v','.mov','.webm','.mkv'}
_ARCHIVE={'.zip','.rar','.7z','.tar','.gz','.tgz','.bz2','.xz'}
_IMAGE_MIME={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp',
             '.gif':'image/gif','.bmp':'image/bmp','.tif':'image/tiff','.tiff':'image/tiff',
             '.heic':'image/heic','.heif':'image/heic'}
_AUDIO_MIME={'.mp3':'audio/mpeg','.m4a':'audio/mp4','.aac':'audio/aac','.wav':'audio/wav',
             '.flac':'audio/flac','.ogg':'audio/ogg'}
_VIDEO_MIME={'.mp4':'video/mp4','.m4v':'video/x-m4v','.mov':'video/quicktime','.webm':'video/webm',
             '.mkv':'video/x-matroska'}
_LANG={'.r':'r','.py':'python','.js':'javascript','.mjs':'javascript','.ts':'typescript',
       '.tsx':'typescript','.jsx':'javascript','.json':'json','.yaml':'yaml','.yml':'yaml',
       '.xml':'xml','.sql':'sql','.sh':'bash','.ps1':'powershell','.kt':'kotlin','.kts':'kotlin',
       '.swift':'swift','.java':'java','.c':'c','.h':'c','.cpp':'cpp','.hpp':'cpp','.cs':'csharp',
       '.go':'go','.rs':'rust','.css':'css','.scss':'css','.less':'css','.md':'markdown',
       '.markdown':'markdown','.ini':'ini','.cfg':'ini','.conf':'ini','.toml':'ini',
       '.diff':'diff','.patch':'diff','.tex':'latex'}
_ANSWER_REASONS={'missing':'文件已移动或删除','not_found':'电脑上没找到这个文件',
                 'not_local':'文件在网络位置或别的电脑上，遥应只读这台电脑自己的磁盘',
                 'denied':'出于安全，遥应不让手机读这个文件（可能含密钥或登录信息）',
                 'folder':'这是文件夹，可以在「电脑上的文件」里看'}


def _file_kind(suffix,size):
    if suffix in _IMAGE_KIND:return 'image'
    if suffix=='.pdf':return 'pdf'
    if suffix in _TEXT_KIND and size<=2<<20:return 'text'
    return 'download'


def _file_view(suffix):
    if suffix in _IMAGE_VIEW:return 'image'
    if suffix=='.svg':return 'svg'
    if suffix=='.pdf':return 'pdf'
    if suffix in _OFFICE:return 'office'
    if suffix in ('.csv','.tsv'):return 'table'
    if suffix in _MARKDOWN:return 'markdown'
    if suffix in _HTML:return 'html'
    if suffix in _AUDIO:return 'audio'
    if suffix in _VIDEO:return 'video'
    if suffix in _ARCHIVE:return 'archive'
    if suffix in _CODE:return 'code'
    if suffix in _TEXT_KIND:return 'text'
    return 'none'


def _file_mime(suffix,view):
    if suffix in _IMAGE_MIME:return _IMAGE_MIME[suffix]
    if suffix=='.pdf':return 'application/pdf'
    if suffix in _AUDIO_MIME:return _AUDIO_MIME[suffix]
    if suffix in _VIDEO_MIME:return _VIDEO_MIME[suffix]
    if suffix in ('.html','.htm','.xhtml','.svg','.xml','.js','.mjs'):
        return 'application/octet-stream'  # never let a browser run it (§5.2)
    if view in ('code','text','markdown','table') or suffix in _TEXT_KIND:
        return 'text/plain; charset=utf-8'
    return 'application/octet-stream'


def _file_version(st):
    return hashlib.sha256(f'{st.st_size}:{st.st_mtime_ns}'.encode()).hexdigest()[:12]


def _answer_bases(m,item,entry):
    values=[]
    for source in (m,item):
        if not isinstance(source,dict):continue
        values+=[source.get('cwd'),source.get('turn_cwd'),source.get('working_folder')]
    if entry is not None:values.append(getattr(entry,'cwd',''))
    out=[];seen=set()
    for value in values:
        if not isinstance(value,str) or not value.strip():continue
        key=os.path.normcase(value.strip())
        if key in seen:continue
        seen.add(key);out.append(value.strip())
    return out


class _ScanCache:
    """The answer_files result kept on a message; a plain object so weigh() does not walk its files."""
    __slots__=('key','scan')
    def __init__(self,key,scan):self.key=key;self.scan=scan

class Transcript:
    def __init__(self,path,app,cwd='',tid=''):
        from agents import registry
        self.agent=app if hasattr(app,'manifest') else registry.get(app)
        self.path=path;self.app=self.agent.id;self.cwd=cwd;self.tid=tid;self.offset=0;self.inode=None;self.messages=[];self.by_id={};self.duplicates={};self.state={};self.modern=False;self.lock=threading.RLock();self.size=0;self.mtime=0
        self.context={'thread_id':tid} if tid else {}  # what a line needs to know of earlier ones (Claude's next-step boxes, 10-16)
        # 11-16: Codex writes each answer twice; the final answers by turn, so a big file is not scanned for each.
        self.final_answers={}
        # 11-24: weigh() of each message, in step with self.messages, and their sum: what History's cache counts
        self.weights=array('q');self.held=0
        self.partial=False  # the last refresh stopped at its budget with whole lines left to read
        self.sliced=False   # read in slices since the rows were last all weighed
    @property
    def weight(self):
        """The memory this transcript keeps, estimated (bytes)."""
        return self.held+len(self.messages)*MESSAGE_EXTRA+len(self.context.get('uuids') or ())*UUID_EXTRA
    def refresh(self,budget=None):
        """Read what the file gained since the last call. budget: stop at the end of the line that takes this call past
        that many bytes; self.partial then says lines are left, and the next call goes on from self.offset (History's
        read-ahead parses a big file a slice at a time, 11-24). Whole or in slices, the result is the same."""
        with self.lock:
            st=self.path.stat()
            if self.inode is not None and (st.st_ino!=self.inode or st.st_size<self.offset or (st.st_size==self.offset and st.st_mtime_ns!=self.mtime)):
                self.offset=0;self.messages=[];self.by_id={};self.duplicates={};self.state={};self.modern=False;self.context={'thread_id':self.tid} if self.tid else {};self.final_answers={}
                self.weights=array('q');self.held=0;self.sliced=False
            self.inode=st.st_ino;self.partial=False
            if st.st_size==self.offset:self.size=st.st_size;self.mtime=st.st_mtime_ns;return self
            first=len(self.messages);start=self.offset
            with self.path.open('rb') as f:
                f.seek(self.offset)
                while f.tell()<st.st_size:
                    if budget is not None and self.offset-start>=budget:self.partial=True;break
                    raw=f.readline(st.st_size-f.tell())
                    if not raw.endswith(b'\n'):break
                    self.offset=f.tell()
                    if self.agent.skip_record(raw):continue
                    uuid=self.agent.record_uuid(raw)
                    if uuid:
                        # 11-01: a /compact made Claude write 1226 old records into the file again, every uuid twice.
                        # The copy is not new talk: no message, no state, no queue change (and no turn clock).
                        seen=self.context.setdefault('uuids',set())
                        if uuid in seen:continue
                        seen.add(uuid)
                    parsed={}
                    msgs,state=self.agent.parse_record(raw,self.context,parsed)
                    msgs=activity_records.enrich(self.app,raw,msgs,self.context,record=parsed or None)
                    for k,v in state.items():
                        self.state[k]=v
                    for m in msgs:
                        if self.agent.final_answer(m):
                            plan_text=lambda value:re.sub(r'</?proposed_plan>','',value).strip()
                            turn_id=self.state.get('current_turn_id')
                            peers=[v for v in self.final_answers.get(turn_id,[]) if v.get('role')=='assistant' and v.get('phase')=='final_answer' and bool(v.get('native_plan'))!=bool(m.get('native_plan')) and plan_text(v['text'])==plan_text(m['text'])]
                            if len(peers)==1:
                                peer=peers[0]
                                if m.get('native_plan'):peer.update(native_plan=True,source_id=m.get('source_id'))
                                if m.get('source_id'):self.by_id[m['source_id']]=peer
                                continue
                        # Dual log representations may share a source ID, or turn/phase/content evidence
                        # milliseconds apart (chats.codex_twins). Never drop all legacy rows.
                        if self.agent.dedupe_twins:
                            peer=next((v for v in reversed(self.messages[-4:]) if v.get('turn_id')==self.state.get('current_turn_id') and self.agent.twins(v,m)),None)
                            if peer:
                                if m.get('source_id'):peer['source_id']=m['source_id'];self.by_id[m['source_id']]=peer
                                continue
                        identity=json.dumps([m.get('time'),m['role'],m.get('phase'),m['text']],ensure_ascii=False)
                        digest=hashlib.sha256(identity.encode()).hexdigest()[:24]
                        self.duplicates[digest]=self.duplicates.get(digest,0)+1
                        m['id']=m.get('source_id') or digest+':'+str(self.duplicates[digest])
                        m['order']=self.offset
                        if self.agent.assign_turn_id and self.state.get('current_turn_id'):m['turn_id']=self.state['current_turn_id']
                        if m['id'] in self.by_id:
                            m['order']=self.by_id[m['id']]['order'];self.by_id[m['id']].update(m)
                        else:self.messages.append(m);self.by_id[m['id']]=m
                        if self.agent.final_answer(m):
                            row=self.by_id.get(m['id'])
                            if row is not None:
                                rows=self.final_answers.setdefault(self.state.get('current_turn_id'),[])
                                if not any(v is row for v in rows):rows.append(row)
            # Read a line at a time, a box looked open on its own line for good, even after the user had answered (10-16)
            if self.agent.mark_next_open:self.agent.mark_open_next(self.messages)
            if len(self.messages)>first:self.agent.attach_presented(self.messages)
            # read in slices, a row filled in more than WEIGH_AGAIN rows later was missed: all weighed once at the end
            if self.partial:self.sliced=True
            elif self.sliced:first=0;self.sliced=False
            self._weigh(first)
            self.size=st.st_size;self.mtime=st.st_mtime_ns
        return self
    def _weigh(self,first):
        """Weigh the rows this read added and the WEIGH_AGAIN before them, which a later line may have filled in."""
        rows=self.messages;weights=self.weights
        if len(weights)<len(rows):weights.frombytes(bytes(8*(len(rows)-len(weights))))
        held=self.held
        for i in range(max(0,first-WEIGH_AGAIN),len(rows)):
            w=weigh(rows[i]);held+=w-weights[i];weights[i]=w
        self.held=held

class History:
    def __init__(self,roots=None,secret='',warm=None):
        self.entries=OrderedDict();self.lock=threading.RLock();self.roots=roots or [];self.secret=secret.encode();self.files={};self.catalog_cache=(0,[],[])
        self.scan_cache=OrderedDict();self.scan_cache_lock=threading.Lock()
        self.catalog_load_lock=threading.Lock();self.catalog_generation=0
        # 11-24: the read-ahead (warm_once) runs on its own thread in the installed app only; tests call warm_once().
        self.log=None  # a callable given the read-ahead's errors, when the service hands one over
        self.warm_errors=0;self.warming=None;self.warm_stop=threading.Event()
        if warm is None:warm=getattr(sys,'frozen',False)
        if warm:self.start_warming()
    def transcript(self,app,tid):
        from agents import registry
        from agents.base import AgentError
        try:agent=registry.get(app)
        except AgentError as exc:raise HistoryError(str(exc),400) from None
        if not agent.home_list:
            try:return agent.transcript(tid)
            except AgentError as exc:raise HistoryError(str(exc),getattr(exc,'status',400)) from None
            except chats.ChatError as exc:raise HistoryError(str(exc),getattr(exc,'status',400)) from None
        item=chats.find(app,tid);path=chats.conv_path(item)
        if not path or not path.is_file():raise HistoryError('没有找到这段对话的记录',404)
        key=(app,tid,str(path))
        with self.lock:  # two requests for one conversation share one entry
            entry=self.entries.get(key)
            if entry is None:entry=Transcript(path,agent,item.get('cwd') or '',tid=tid);self.entries[key]=entry
            self.entries.move_to_end(key)
        # 11-24: read outside History's lock. A cold parse of a big record takes seconds, and every other page, list and
        # conversation waited behind it; the transcript's own lock keeps two reads of one file in turn.
        entry.refresh()
        with self.lock:
            if key not in self.entries:self.entries[key]=entry  # pushed out while it was read: it is the newest asked for
            self._evict(keep=entry)  # what it now holds decides how much of the cache is left
        return item,entry
    def _memory(self):return sum(v.weight for v in self.entries.values())
    def _evict(self,keep=None):
        """Within MAX_TRANSCRIPTS, MAX_TRANSCRIPT_MEMORY and MAX_TRANSCRIPT_BYTES, the least recently asked for going
        first; never keep (the one a caller is being given), and always one. With self.lock held."""
        while len(self.entries)>1 and (len(self.entries)>MAX_TRANSCRIPTS or self._memory()>MAX_TRANSCRIPT_MEMORY
                                       or sum(v.size for v in self.entries.values())>MAX_TRANSCRIPT_BYTES):
            victim=next((k for k,v in self.entries.items() if v is not keep),None)
            if victim is None:break
            del self.entries[victim]
    # -- 11-24: reading ahead the conversations updated last
    def start_warming(self):
        if self.warming is None:
            self.warming=threading.Thread(target=self._warm_loop,name='history-warm',daemon=True);self.warming.start()
    def stop_warming(self,timeout=5):
        self.warm_stop.set()
        if self.warming is not None:self.warming.join(timeout)
    def _warm_loop(self):
        if self.warm_stop.wait(WARM_AFTER):return
        while True:
            try:self.warm_once()
            except Exception as exc:self._warm_failed(exc)
            if self.warm_stop.wait(WARM_EVERY):return
    def _warm_failed(self,exc):
        self.warm_errors+=1
        try:
            if self.log:self.log(f'预读对话记录出错：{type(exc).__name__}: {exc}')
        except Exception:pass
    def warm_once(self,count=WARM_COUNT,pause=WARM_PAUSE):
        """Bring the count conversations updated last (of the assistants that keep record files) up to date in memory,
        newest first. Polite: a slice of WARM_SLICE bytes at a time with a pause between, never under History's lock,
        nothing pushed out for it (a conversation not cached yet is read only while the cache has room for it), and a
        request for the same conversation meanwhile simply finishes the read. Returns how many it went through."""
        from agents import registry
        done=0
        for item in self.catalog():
            if done>=count or self.warm_stop.is_set():break
            try:
                agent=registry.get(item['app'])
                if not agent.home_list:continue
                path=chats.conv_path(item)
                if not path or not path.is_file():continue
                done+=1
                self._warm(item,agent,path,pause)
            except Exception as exc:self._warm_failed(exc)
        return done
    def _warm(self,item,agent,path,pause):
        key=(item['app'],item['id'],str(path))
        with self.lock:
            entry=self.entries.get(key)
            if entry is None:
                size=path.stat().st_size
                if (len(self.entries)>=MAX_TRANSCRIPTS or self._memory()+size//WARM_GUESS>MAX_TRANSCRIPT_MEMORY
                        or sum(v.size for v in self.entries.values())+size>MAX_TRANSCRIPT_BYTES):return
                entry=Transcript(path,agent,item.get('cwd') or '',tid=item['id'])
                # the first to go: no one has asked for it yet (an entry already cached keeps its place)
                self.entries[key]=entry;self.entries.move_to_end(key,last=False)
        while not self.warm_stop.is_set():
            with self.lock:
                self._evict()
                if self.entries.get(key) is not entry:return  # pushed out: what it read is not kept
            if not entry.refresh(WARM_SLICE).partial:break
            self.warm_stop.wait(pause)  # a pause, cut short when the service stops
        with self.lock:self._evict()
    def _load(self):
        """(conversations of every app, DeepSeek sessions in no workspace that no conversation claims), 10 s."""
        # The home list and sidebar arrive together. Only one request scans a cold catalog.
        with self.catalog_load_lock:
            return self._load_catalog()
    def _load_catalog(self):
        with self.lock:
            if time.monotonic()-self.catalog_cache[0]<10:return self.catalog_cache[1],self.catalog_cache[2]
            generation=self.catalog_generation
        items=[];stray=[]
        from agents import registry
        for agent in registry.load():
            try:items+=agent.catalog_entries(1000000)
            except Exception:pass
            try:stray+=agent.ungrouped()
            except Exception:pass
        items.sort(key=lambda v:(-v['updated'],v['app'],v['id']))
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
    def bucket(self,stray):
        """The Ungrouped bucket as one row of the list, placed by its newest session."""
        from agents import registry
        return registry.get(stray[0]['app']).ungrouped_bucket(stray)
    @staticmethod
    def child_row(c):
        return {k:c.get(k) for k in ('app','id','title','folder','cwd','updated','status','kind','parent')}|(
            {'parent_title':c['parent_title']} if c.get('parent_title') else {})
    def conversations(self,app='all',limit=40,cursor='',query='',sort='updated',status='all',status_resolver=None,apps=None):
        """One page of conversations. `apps` (when given) is the assistants this client can read: they are left
        out before the page and its total are counted, so an old phone's page is not shortened by ones it cannot see."""
        limit=max(5,min(100,limit));query=query.strip().casefold()[:200]
        found,stray=self._load()
        if apps is not None:
            allowed={str(app) for app in apps}
            found=[v for v in found if v.get('app') in allowed]
            stray=[v for v in stray if v.get('app') in allowed]
        items=[v for v in found if app=='all' or v['app']==app]
        if query:
            # a search looks through children and the Ungrouped bucket too; a hit is a row of its own
            if app=='all' or any(v.get('children') for v in found):
                for v in found:
                    items+=[c|{'parent_title':v['title']} for c in v.get('children',[])]
                items+=stray
            from agents import registry
            preview_apps={a.id for a in registry.load() if getattr(a,'search_in_preview',False)}
            items=[v for v in items if query in (v['title']+' '+(v.get('folder') or '')+' '+v['id']
                                                 +(' '+(v.get('preview') or '') if v['app'] in preview_apps else '')).casefold()]
            items.sort(key=lambda v:(-v['updated'],v['app'],v['id']))
        elif stray and (app=='all' or app==stray[0]['app']):
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
            info=chats.summary(item);row=chats.public(item)|{'status':info['status'],'preview':info['preview'],
                'turn_started':info.get('turn_started') or item.get('turn_started',0),
                'turn_ended':info.get('turn_ended',0),'step':info.get('step','') or item.get('step','')}
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
        from agents import registry
        from agents.base import AgentError, UnknownAgent, Unsupported
        try:
            return registry.get(app).children(tid,offset,limit)
        except (UnknownAgent,Unsupported):
            raise HistoryError('只有 DeepSeek 对话有子对话',400) from None
        except AgentError as exc:
            raise HistoryError(str(exc),getattr(exc,'status',400)) from None
        except chats.ChatError as exc:
            raise HistoryError(str(exc),getattr(exc,'status',400)) from None
    def _file_id(self,app,tid,mid,index,path):
        identity=[app,tid,mid,index,str(path)]
        return hmac.new(self.secret,json.dumps(identity).encode(),hashlib.sha256).hexdigest()[:32]

    def _answer_scan(self,m,item,entry=None,agent=None):
        """answer_files.scan for one message, cached on the message by its text, folders and presented paths."""
        if agent is None:agent=getattr(entry,'agent',None)
        text=m.get('text') or ''
        bases=tuple(_answer_bases(m,item,entry))
        presented=[]
        if agent is not None:
            try:got=agent.presented_files(m,item if isinstance(item,dict) else {})
            except Exception:got=None
            for value in got or ():
                try:value=os.fspath(value)
                except TypeError:continue
                if isinstance(value,str) and value.strip():presented.append(value)
        key=(hashlib.sha256(text.encode('utf-8')).hexdigest(),bases,tuple(presented))
        cached=m.get('_answer_scan')
        if isinstance(cached,_ScanCache) and cached.key==key:return cached.scan
        with self.scan_cache_lock:
            result=self.scan_cache.get(key)
            if result is not None:
                self.scan_cache.move_to_end(key)
        if result is None:
            result=answer_files.scan(text,bases,presented=presented)
            with self.scan_cache_lock:
                self.scan_cache[key]=result
                self.scan_cache.move_to_end(key)
                while len(self.scan_cache)>MAX_SCAN_CACHE:
                    self.scan_cache.popitem(last=False)
        m['_answer_scan']=_ScanCache(key,result)
        return result

    def _file_row(self,m,f,index,st,app,tid):
        """One public file row (§5.1) and its registry entry, rechecked by the caller."""
        import office_preview
        path=Path(f['path']);size=st.st_size if st else 0;suffix=path.suffix.lower()
        kind=_file_kind(suffix,size);view=_file_view(suffix);ext=suffix[1:]
        fid=self._file_id(app,tid,m.get('id'),index,path)
        old=self.files.get((app,tid,fid))
        updated=bool(old and old.get('mtime') is not None and st
                     and (old['mtime']!=st.st_mtime_ns or old['size']!=size))
        updated=updated or bool(old and old.get('updated'))
        state='missing' if st is None else 'updated' if updated else 'current'
        row={'id':fid,'index':index,'name':path.name,'path':str(path),'kind':kind,'view':view,
             'ext':ext,'mime':_file_mime(suffix,view),'size':size,
             'modified':int(st.st_mtime*1000) if st else None,'state':state,
             'v':_file_version(st) if st else '','line':f.get('line'),
             'lang':_LANG.get(suffix) if view in ('code','text') else None,
             'via':list(f.get('via') or []),'thumb':False,'message_id':m.get('id')}
        if f.get('texts'):row['texts']=list(f['texts'])
        if kind=='download' and st and office_preview.offers(path):row['preview']='pdf'
        try:resolved=path.resolve()
        except (OSError,ValueError):resolved=None
        self.files[(app,tid,fid)]={**row,'path':path,'resolved':resolved,
            'size':size,'mtime':st.st_mtime_ns if st else None,'kind':kind,
            'message_id':m.get('id'),'index':index,'updated':updated}
        return row

    def _message_rows(self,m,item,app,tid,entry=None,agent=None,per_index=False,cache_on=None,seen=None,
                      fresh=False):
        """(rewritten text, file rows, file notes) for one message; scans only now, never while reading the record."""
        if not (m.get('role')=='assistant' or (m.get('role')=='tool' and m.get('_presented_files'))):
            return (m.get('text') or ''),[],[]
        scan=self._answer_scan(cache_on or m,item,entry,agent)
        rows=[];notes=[]
        for f in scan.files:
            identity=os.path.normcase(f['path'])
            if seen is not None and identity in seen:continue
            reason,st=file_policy.inspect(f['path'],fresh=fresh)
            if reason in ('denied','not_local','folder'):
                href=(f.get('hrefs') or [f['path']])[0]
                notes.append({'href':href,'reason':reason,'text':_ANSWER_REASONS[reason]})
                continue
            indexes=f.get('indexes') or [f.get('index') or 0]
            for index in (indexes if per_index else [indexes[0]]):
                rows.append(self._file_row(m,f,index,st,app,tid))
        for note in scan.notes:
            notes.append({'href':note['href'],'reason':note['reason'],
                          'text':_ANSWER_REASONS.get(note['reason'],'')})
        note_seen=set();unique=[]
        for note in notes:
            key=(note['href'],note['reason'])
            if key in note_seen:continue
            note_seen.add(key);unique.append(note)
        return scan.text,rows,unique

    def _tool_row(self,m,app,tid,fresh=False):
        raw=m.get('current_file')
        if not isinstance(raw,str) or not raw.strip():return None
        reason,st=file_policy.inspect(raw,fresh=fresh)
        if reason not in (None,'missing'):return None
        path=str(Path(raw))
        f={'path':path,'line':None,'indexes':[1000],'via':['tool']}
        return self._file_row(m,f,1000,st,app,tid)

    def _public_read(self,app,tid,agent,page):
        """Non-transcript assistants (DeepSeek, Antigravity) return public rows directly: add files here too."""
        messages=[]
        for raw in page.get('messages') or []:
            if not isinstance(raw,dict):messages.append(raw);continue
            message=activity_records.public_message(raw)  # drop _answer_scan and other private keys
            if raw.get('role')=='assistant' or (raw.get('role')=='tool' and raw.get('_presented_files')):
                text,files,notes=self._message_rows(raw,page,app,tid,agent=agent,cache_on=raw)
                message={**message,'text':text,'length':len(text),
                         'truncated':len(text)>6000,'files':files}
                if len(text)>6000:message['text']=text[:6000]
                if notes:message['file_notes']=notes
            else:
                text=message.get('text') or ''
                message={**message,'length':len(text),'truncated':len(text)>6000}
                if len(text)>6000:message['text']=text[:6000]
            messages.append(message)
        return {**page,'messages':messages}

    def public_message(self,m,item=None,entry=None,full=False,lite=False,app=None,tid=None,
                       agent=None,cache_on=None):
        result=activity_records.public_message(m)
        # 11-16: a phone stores no tool output; lite pages (lite=1) leave detail and result out before they are sent.
        if lite:result.pop('detail',None);result.pop('result',None)
        result.pop('legacy',None)
        text=m.get('text') or ''
        if m.get('role')=='assistant' or (m.get('role')=='tool' and m.get('_presented_files')):
            if app is None:app=getattr(entry,'app',None) or (item or {}).get('app')
            if tid is None:tid=getattr(entry,'tid',None) or (item or {}).get('id')
            text,files,notes=self._message_rows(cache_on or m,item,app,tid,entry,agent,cache_on=cache_on or m)
            result['files']=files
            if notes:result['file_notes']=notes
        result['length']=len(text);result['truncated']=not full and len(text)>6000
        if result['truncated']:result['text']=text[:6000]
        else:result['text']=text
        return result
    @staticmethod
    def _with_client_request_id(m,req_map):
        if m.get('role')=='user' and not m.get('client_request_id') and req_map:
            rid=req_map.get(m.get('source_id') or '') or req_map.get(m.get('id') or '')
            if rid:return {**m,'client_request_id':rid}
        return m
    def resolve_requests(self,app,tid,request_ids,aliases=None):
        """Read-only resolution against the whole transcript, never the visible page."""
        if not isinstance(request_ids,list) or len(request_ids)>100 or any(not isinstance(v,str) or not v or len(v)>200 for v in request_ids):
            raise HistoryError('消息定位请求无效',400)
        _,entry=self.transcript(app,tid);out=[];aliases=aliases or {}
        entry_agent=getattr(entry,'agent',None)
        req_map=entry_agent.message_request_ids(tid) if entry_agent is not None else {}
        with entry.lock:
            candidates={}
            for m in entry.messages:
                if m.get('role')=='user':
                    cid=m.get('client_request_id') or req_map.get(m.get('source_id') or '') or req_map.get(m.get('id') or '')
                    if cid:candidates.setdefault(cid,{})[m['id']]=m
            by_request={rid:next(iter(rows.values())) for rid,rows in candidates.items() if len(rows)==1}
            for rid in dict.fromkeys(request_ids):
                ledger=aliases.get(rid,{})
                m=by_request.get(rid) or by_request.get(ledger.get('client_id'))
                if m is None and ledger.get('message_id'):
                    candidate=entry.by_id.get(ledger['message_id'])
                    if candidate and candidate.get('role')=='user':m=candidate
                result={'request_id':rid,'status':'recorded' if m else 'unresolved'}
                if m:result.update(message_id=m['id'],source_id=m.get('source_id'),order=m.get('order'),turn_id=m.get('turn_id'),evidence='source_client_id' if by_request.get(rid) is m else 'delivery_ledger_identity')
                elif ledger:result['delivery_state']=ledger.get('state')
                out.append(result)
        return {'items':out}
    def conversation(self,app,tid,limit=60,before='',around='',lite=False):
        from agents import registry
        from agents.base import AgentError
        try:agent=registry.get(app)
        except AgentError as exc:raise HistoryError(str(exc),400) from None
        if not agent.home_list:
            try:return self._public_read(app,tid,agent,agent.read(tid,limit=limit,before=before,around=around,lite=lite))
            except chats.ChatError as exc:raise HistoryError(str(exc),getattr(exc,'status',400)) from None
        item,entry=self.transcript(app,tid);limit=max(5,min(100,limit));reset=False
        req_map=agent.message_request_ids(tid)
        with entry.lock:
            rows=entry.messages;end=len(rows)
            if before:
                at=self._at(entry,before)
                if at is None:reset=True
                else:end=at
            if around:
                at=self._at(entry,around)
                if at is not None:end=min(len(rows),at+limit//2+1)
            start=max(0,end-limit);page=rows[start:end]
            turns=entry.context.get('activity_turns',{})
            current=entry.context.get('activity_turn')
            clock=turns.get(current) or next((turns.get(m.get('activity_turn')) for m in reversed(page)
                                              if turns.get(m.get('activity_turn'))),{})
            def seconds(value):
                return int(value/1000) if isinstance(value,(int,float)) and value>0 else 0
            items=[]
            for m in page:
                tr=turns.get(m.get('activity_turn')) or {}
                enriched=self._with_client_request_id(m,req_map)
                timed={**enriched,'turn_started':seconds(tr.get('started_at')),'turn_ended':seconds(tr.get('ended_at'))}
                items.append(self.public_message(timed,item=item,entry=entry,lite=lite,app=app,tid=tid,
                                                 cache_on=m))
            return chats.public(item)|{'messages':items, 'status':chats._status(entry.state,entry.mtime/1e9),
                'size':entry.size,'runtime':agent.runtime(entry.path),'modified':entry.mtime//1000000,
                # 0.6.4: the turn's own times, Unix seconds; each message of that turn carries them too.
                'turn_started':seconds(clock.get('started_at')),'turn_ended':seconds(clock.get('ended_at')),
                'turn_status':clock.get('status',''),
                'step':entry.state.get('step','') if chats._status(entry.state,entry.mtime/1e9)=='running' else '',
                'activity_turns':{k:v for k,v in turns.items() if k == current or k in {m.get('activity_turn') for m in page}},
                'activity_current':current,
                'has_more':start>0,'next_cursor':page[0]['id'] if start>0 and page else None,'has_newer':end<len(rows),'reset':reset,'total':len(rows)}
    @staticmethod
    def _at(entry,mid):
        """Where a message is, found also by the id of a copy merged into it: a phone may have kept that id (10-27, the
        second copy of each Codex answer, chats.codex_twins)."""
        row=entry.by_id.get(mid)
        return next((i for i,m in enumerate(entry.messages) if m is row),None) if row is not None else None
    def message(self,app,tid,mid):
        item,entry=self.transcript(app,tid)
        entry_agent=getattr(entry,'agent',None)
        req_map=entry_agent.message_request_ids(tid) if entry_agent is not None else {}
        with entry.lock:
            m=entry.by_id.get(mid)
            if not m:raise HistoryError('消息已变化，请刷新',404)
            return self.public_message(self._with_client_request_id(m,req_map),item=item,entry=entry,
                                       full=True,app=app,tid=tid)
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
    def list_files(self,app,tid,message_id=None,fresh=True):
        from agents import registry
        item,entry=self.transcript(app,tid)
        agent=getattr(entry,'agent',None) or registry.get(app)
        out=[];seen_paths=set();notes=[]
        with entry.lock:
            if message_id:message_id=(getattr(entry,'by_id',{}).get(message_id) or {}).get('id',message_id)  # a merged copy's id too
            messages=[m for m in entry.messages
                      if (m.get('role')=='assistant'
                          or (m.get('current_file') and m.get('tool_status')=='completed')
                          or (m.get('role')=='tool' and m.get('_presented_files')))
                      and (not message_id or m.get('id')==message_id)]
            for m in reversed(messages):
                if m.get('role')=='assistant' or (m.get('role')=='tool' and m.get('_presented_files')):
                    _,rows,found_notes=self._message_rows(m,item,app,tid,entry,agent,
                                                          per_index=bool(message_id),
                                                          seen=None if message_id else seen_paths,
                                                          fresh=fresh)
                    notes+=found_notes
                else:
                    row=self._tool_row(m,app,tid,fresh);rows=[row] if row else []
                for row in rows:
                    identity_path=os.path.normcase(row['path'])
                    if not message_id and identity_path in seen_paths:continue
                    seen_paths.add(identity_path)
                    out.append(row)
        unique=[];seen=set()
        for note in notes:
            key=(note['href'],note['reason'])
            if key in seen:continue
            seen.add(key);unique.append(note)
        return {'items':out,'file_notes':unique,
                'scope':'当前会话明确引用的具体文件；打开当前内容，不保存历史副本'}

    def file(self,app,tid,fid):
        meta=self.files.get((app,tid,fid))
        # Revalidate source authorization on every access, including old references.
        listed=self.list_files(app,tid,meta['message_id'] if meta else None,fresh=True)
        if not any(f['id']==fid for f in listed['items']):raise HistoryError('文件引用无效或不属于当前对话',403)
        meta=self.files[(app,tid,fid)]
        try:
            p=meta['path'].resolve()
            if p!=meta['resolved'] or p!=meta['path'].absolute():raise HistoryError('文件真实路径已变化，引用无效',403)
            if not p.is_file():raise HistoryError('文件已移动或删除',404)
            st=p.stat()
        except OSError:raise HistoryError('文件已移动或删除',404) from None
        return {**meta,'path':p,'size':st.st_size,'mime':meta['mime'],'v':_file_version(st),
                'mtime':st.st_mtime_ns,'modified':int(st.st_mtime*1000)}
