"""Local DeepSeek Harness adapter. Credentials never leave the loopback transport.

The installed nightly's private protocol is deliberately checked at each boundary.
Only reader-visible text, thinking and tool activity are projected; signatures and provider data stay local.
"""
from __future__ import annotations
import base64, bisect, copy, hashlib, hmac, http.client, json, os, re, sqlite3, subprocess, threading, time, uuid
from datetime import datetime, timezone
from pathlib import Path
from app_paths import DATA
from types import SimpleNamespace
from contextlib import contextmanager
from deepseek_stream import public_messages,merge_row

HOME = Path.home() / '.dsh'

def workspace_meta():
    try:
        value=json.loads((HOME/'storages/workspace.json').read_text(encoding='utf-8'))
        return value.get('global',value)
    except (OSError,ValueError):return {}

class DeepSeekError(Exception):
    def __init__(self, text, status=409):
        super().__init__(text); self.status=status

def workspaces():
    """The workspaces the Harness sidebar lists, newest first (tables.workspaces in workspace.json).
    Creating a conversation in any other folder would add a workspace the client never showed (10-19)."""
    try:
        data=json.loads((HOME/'storages/workspace.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):
        return []
    table=((data.get('tables') or {}).get('workspaces')) or {}
    rows=[]
    for ident,row in table.items():
        if not isinstance(row,dict):continue
        path=str(row.get('path') or '')
        if not path:continue
        rows.append({'id':str(ident),'path':path,'name':str(row.get('title') or Path(path).name),
                     'sessions':len(row.get('sessionIds') or []),'updated':str(row.get('updatedAt') or '')})
    rows.sort(key=lambda v:v['updated'],reverse=True)
    return rows


def subagent_catalog(values):
    """The parent's subagent list: [{childId, label, mode, createdAt}]; the projection names the child 'id'."""
    value=(values or {}).get('subagentCatalog')
    if isinstance(value,dict):value=(value.get('head') or {}).get('values') or []
    rows=[]
    for v in value or []:
        if not isinstance(v,dict):continue
        child=v.get('childId') or v.get('id')
        if child:rows.append({**v,'childId':str(child)})
    return rows


def workspace_for(folder, identity=None):
    key=os.path.normcase(str(Path(folder).resolve()))
    matches=[row for row in workspaces() if os.path.normcase(str(Path(row['path']).resolve()))==key
             and (identity is None or row['id']==identity)]
    if len(matches)!=1:raise DeepSeekError('所选 DeepSeek 工作区已不存在或不唯一，请重新选择',409)
    return matches[0]


# ---------------------------------------------------------------- conversations, their children and the rest (10-20)
# The Harness sidebar files a session under the workspace whose sessionIds name it; everything else trails in one
# "Ungrouped" bucket, and subagents never show (the parent's row counts them). The phone used to list every session
# flat, so a script that runs `dsh headless` once per model call (150+ one-shot sessions from one batch job on
# 10-19) buried the real conversations.
# Now a workspace session is a conversation; a subagent hangs under the conversation it belongs to; a headless
# session hangs under the conversation that started it when a script recorded that (ParentLinks); the rest is the
# Ungrouped bucket, as on the desktop.

LINKS=Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData'/'Local')/'AgentRemote'/'deepseek-parents.jsonl'
SESSION_ID=re.compile(r'session-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


def norm_path(value):
    """One spelling per folder, compared the way Windows compares them."""
    return os.path.normcase(os.path.normpath(value)) if isinstance(value,str) and value else ''


def workspace_members():
    """{session id: its workspace {id, name, path}} from the Harness sidebar's table; None when there is no table
    or it holds no workspace, and every session is then a conversation, as before 10-20."""
    try:data=json.loads((HOME/'storages/workspace.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return None
    table=((data.get('tables') or {}).get('workspaces')) or {}
    members={}
    for ident,row in table.items():
        if not isinstance(row,dict):continue
        path=str(row.get('path') or '')
        place={'id':str(ident),'name':str(row.get('title') or Path(path).name),'path':path}
        for sid in row.get('sessionIds') or []:members.setdefault(str(sid),place)
    return members if table else None


class ParentLinks:
    """Which conversation started a script's one-shot session.

    `dsh headless` keeps no parent: its session knows its folder and nothing else. A script that runs inside a
    DeepSeek conversation has that conversation's id in DSH_SESSION_ID (the Harness gives it to every shell call);
    before it starts a headless session it can append one line to LINKS:
        {"parent": "<DSH_SESSION_ID>", "cwd": "<the headless session's folder>", "at": <ms since 1970>}
    Each call has its own folder; a folder used again belongs to the newest line written before the session's
    last activity. Read from where the last read stopped; a shorter file is read again from the start."""
    def __init__(self,path=None):
        self.path=Path(path) if path else LINKS;self.lock=threading.Lock();self.offset=0;self.by_cwd={}
    def parent(self,cwd,updated):
        key=norm_path(cwd)
        if not key:return ''
        with self.lock:
            self._refresh();best=''
            for at,parent in self.by_cwd.get(key,()):
                if at>int(updated or 0)+2000:break  # written after the session's last activity: a later run
                best=parent
            return best
    def _refresh(self):
        try:size=self.path.stat().st_size
        except OSError:self.offset=0;self.by_cwd={};return
        if size<self.offset:self.offset=0;self.by_cwd={}
        if size==self.offset:return
        try:
            with self.path.open('rb') as f:f.seek(self.offset);raw=f.read(size-self.offset)
        except OSError:return
        end=raw.rfind(b'\n')
        if end<0:return  # a line still being written
        self.offset+=end+1
        for line in raw[:end].splitlines():
            try:v=json.loads(line)
            except ValueError:continue
            if not isinstance(v,dict):continue
            parent,cwd,at=v.get('parent'),norm_path(v.get('cwd')),v.get('at')
            if not isinstance(parent,str) or not SESSION_ID.fullmatch(parent) or not cwd or not isinstance(at,int):continue
            bisect.insort(self.by_cwd.setdefault(cwd,[]),(at,parent))

_links=None
def parent_links():
    global _links
    if _links is None:_links=ParentLinks()
    return _links


def organize(rows,members,links=None,pinned=()):
    """Sort the host's sessions into {top, ungrouped, index, rows}.

    rows: {id, cwd, updated, running, status, title, values, parent (the host's parentSessionId), subagent}, blank
    and archived ones already left out. members: workspace_members(). top: the conversations, each with its
    children newest first and 'updated' moved up to its newest child's (a pipeline running under it keeps it near
    the top). ungrouped: sessions in no workspace that no conversation claims; a subagent whose conversation is not
    listed is left out, as the desktop leaves it out. index: every listed row by id, for opening one."""
    by_id={r['id']:r for r in rows}
    labels={}
    for r in rows:
        for c in subagent_catalog(r['values']):labels.setdefault(c['childId'],str(c.get('label') or ''))
    tops={r['id'] for r in rows if not r['subagent'] and (members is None or r['id'] in members)}
    def parent_of(r):
        if r['parent']:return r['parent']
        if r['subagent'] or links is None:return ''
        return links.parent(r['cwd'],r['updated'])
    def mother(r):
        seen={r['id']};current=r
        for _ in range(12):  # a subagent's subagent, a script started by a subagent: up to the conversation
            p=parent_of(current)
            if not p or p in seen:return ''
            if p in tops:return p
            seen.add(p);current=by_id.get(p)
            if current is None:return ''
        return ''
    def folder(r):return Path(r['cwd']).name if r['cwd'] else ''
    def child(r,parent):
        label=labels.get(r['id'],'') if r['subagent'] else ''
        title=label or r['title'] or folder(r) or ('子智能体' if r['subagent'] else '新对话')
        return {'app':'deepseek','id':r['id'],'title':title[:120],'kind':'subagent' if r['subagent'] else 'script',
                'parent':parent,'cwd':r['cwd'],'folder':folder(r),'updated':r['updated'],'status':r['status'],
                'turn_started':r.get('turn_started') or 0,'step':r.get('step') or '',
                '_running':r['running'],'_values':r['values']}
    kids={};ungrouped=[];index={}
    for r in rows:
        if r['id'] in tops:continue
        parent=mother(r)
        if parent:item=child(r,parent);kids.setdefault(parent,[]).append(item)
        elif r['subagent']:continue
        else:item=child(r,'');ungrouped.append(item)
        index[r['id']]=item
    top=[]
    for r in rows:
        if r['id'] not in tops:continue
        own=sorted(kids.get(r['id'],[]),key=lambda c:(-c['updated'],c['id']))
        outline=r['values'].get('turnOutline') or [];last=outline[-1] if isinstance(outline,list) and outline else {}
        item={'app':'deepseek','id':r['id'],'title':r['title'] or '新对话','cwd':r['cwd'],'folder':folder(r),
              'updated':max([r['updated']]+[c['updated'] for c in own]),'pinned':r['id'] in pinned,'status':r['status'],
              'preview':str(last.get('response') or last.get('prompt') or '')[:150],
              'turn_started':r.get('turn_started') or 0,'step':r.get('step') or '',
              'workspace':(members or {}).get(r['id']),'children':own,'_values':r['values'],'_running':r['running']}
        top.append(item);index[r['id']]=item
    ungrouped.sort(key=lambda c:(-c['updated'],c['id']))
    return {'top':top,'ungrouped':ungrouped,'index':index,'rows':rows}


PERMISSIONS={  # the Harness's own Chinese labels (dsh client-ui-permission-presets), with what each lets it do
    'read-only':('仅可查看','只读文件，不改动，不运行会改东西的命令'),
    'workspace-write':('工作区内修改','可以修改工作区里的文件；工作区外的操作要你批准'),
    'danger-full-access':('完全权限','不经你批准就能运行任何命令、修改电脑上任何文件'),
    'auto':('自动审查','实验功能：由审查程序决定是否放行'),
}
RISKY_PERMISSIONS={'danger-full-access','auto'}  # the desktop asks to confirm these too

def permission_name(preset):
    if preset=='custom':return '自定义'  # the knobs match no preset; a display state, never offered
    return PERMISSIONS.get(preset,(preset,''))[0] if preset else ''

def current_permission(values):
    """The session's preset from its live projection ({permissions: {currentValue}}; the stored cache row says preset);
    None when the projection has no permissions key, which means the session has no permission service and the
    desktop hides the control."""
    found=(values or {}).get('permissions')
    if not isinstance(found,dict):return None
    return str(found.get('currentValue') or found.get('preset') or '')

def queued_messages(inbox):
    """The messages waiting for the next turn, as the queue tray shows them: {id, text}."""
    rows=[]
    for item in ((inbox or {}).get('next-turn') or []):
        if not isinstance(item,dict) or not item.get('id'):continue
        text=' '.join(str(p.get('text') or '') for p in item.get('content') or [] if isinstance(p,dict) and p.get('type')=='text').strip()
        images=sum(1 for p in item.get('content') or [] if isinstance(p,dict) and p.get('type')=='image')
        rows.append({'id':str(item['id']),'text':text or ('（图片 '+str(images)+' 张）' if images else '（空消息）')})
    return rows


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

def credential_cookie(home, port):
    import yaml
    # Select exactly the approved record; never enumerate or log credential values.
    def select(node):
        if isinstance(node, dict):
            if 'client-connection/browser-session' in node:
                return node['client-connection/browser-session']
            for value in node.values():
                found=select(value)
                if found is not None:return found
        return None
    try:
        record=select(yaml.safe_load((home/'.credentials.yaml').read_text(encoding='utf-8')))
        payload=record['payload']; encoded=payload['secret']
        secret=base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4))
        if record['kind']!='grant' or payload['version']!=1 or len(secret)!=32:raise ValueError()
    except Exception:
        raise DeepSeekError('DeepSeek 本机登录格式不兼容或不可读取',503) from None
    authority=f'127.0.0.1:{port}'; now=int(time.time()*1000)
    body=b64(json.dumps(dict(version=1,authority=authority,issuedAt=now-1000,expiresAt=now+600000),separators=(',',':')).encode())
    return 'dsh-auth-'+b64(hashlib.sha256(authority.encode()).digest())+'=v1.'+body+'.'+b64(hmac.new(secret,body.encode(),hashlib.sha256).digest())

def discover():
    # CIM avoids querying command lines of every unrelated process on this PC.
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    script="Get-CimInstance Win32_Process -Filter \"Name = 'DeepSeek Harness.exe'\" | Where-Object {$_.CommandLine -like '*dsh-desktop-host*'} | ForEach-Object {$_.ProcessId}"
    try:
        pids=set(subprocess.check_output(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],timeout=8,creationflags=flags,text=True,errors="replace").split())
        lines=subprocess.check_output(['netstat.exe','-ano','-p','tcp'],timeout=5,creationflags=flags,text=True,errors="replace").splitlines()
        ports=[int(v[1].rsplit(':',1)[1]) for line in lines if len(v:=line.split())==5 and v[1].startswith('127.0.0.1:') and v[3]=='LISTENING' and v[4] in pids]
    except (OSError,subprocess.SubprocessError):raise DeepSeekError('无法检测 DeepSeek 本机服务',503) from None
    if len(set(ports))!=1:raise DeepSeekError('请在电脑上打开 DeepSeek Harness（未找到唯一的本机服务）',503)
    return ports[0]

class Client:
    def __init__(self, home=HOME):
        self.home=Path(home);self.lock=threading.RLock();self.connection=None;self.checked=0
    def connection_info(self):
        with self.lock:
            if self.connection and time.monotonic()-self.checked<30:return self.connection
            port=discover();cookie=credential_cookie(self.home,port)
            self.connection=(port,cookie);self.checked=time.monotonic()
            return self.connection
    def call(self, method, args):
        port,cookie=self.connection_info();rid=str(uuid.uuid4())
        body=json.dumps({'type':'client-request','rpcId':rid,'method':method,'payload':{'args':args}})
        conn=http.client.HTTPConnection('127.0.0.1',port,timeout=20)
        try:
            conn.request('POST','/api/'+method,body,{'Content-Type':'application/json','Cookie':cookie})
            response=conn.getresponse()
            if response.status!=200:raise DeepSeekError(f'DeepSeek 接口不可用（HTTP {response.status}），请刷新连接',503)
            data=json.loads(response.read())
            if data.get('rpcId')!=rid or not isinstance(data.get('result'),dict):raise DeepSeekError('DeepSeek 接口格式已变化',503)
            result=data['result']
            if result.get('ok') is not True:
                # its own code goes along ({ok:false, error:{code, message}}): workspace/session-active, say (archives.py)
                error=result.get('error') if isinstance(result.get('error'),dict) else {}
                refused=DeepSeekError('DeepSeek 未接受此操作；请刷新状态后核对',409);refused.code=str(error.get('code') or '');refused.detail=str(error.get('message') or '')[:200]
                raise refused
            return result.get('value')
        except (OSError,ValueError,http.client.HTTPException):
            self.checked=0
            raise DeepSeekError('DeepSeek 连接中断，操作结果尚未确认；请核对后再操作',503) from None
        finally:conn.close()


QUESTION_ANSWERED='这个问题已经答过了，以 DeepSeek 对话里的为准'
QUESTION_GONE='这个问题现在不在等回答了，请刷新后再看'
APPROVAL_DONE='这一步已经处理过了'
APPROVAL_GONE='这一步现在不在等处理了，请刷新后再看'


def request_call(request):
    """The tool call a waterfall request belongs to: user questions say wait.callId, approvals say callId.
    The eventId is only the connection's delivery number and changes when the host sends the same step again."""
    if not isinstance(request,dict):return ''
    wait=request.get('wait')
    value=request.get('callId') or request.get('toolCallId') or (wait.get('callId') if isinstance(wait,dict) else None)
    return value if isinstance(value,str) else ''

class Bridge:
    def __init__(self, client=None, root=None, links=None):
        self.client=client or Client();self.lock=threading.RLock();self.cache=(0,None);self.links=links
        self.root=Path(root or DATA/'attachments');self.root.mkdir(exist_ok=True,parents=True)
        self.db=self.root/'deepseek-requests.sqlite';self.uploads=None
        self.log=None  # remote.Log for the day's file: "回答：…" beside the "通知：…" lines
        self.events=Interactions(self.client,note=self._note_answer,answered=self.answered_in_records)
        self.transcripts={}
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, session TEXT, digest TEXT, state TEXT, result TEXT)')
    @contextmanager
    def _db(self):
        connection=sqlite3.connect(self.db,timeout=10)
        try:
            with connection:yield connection
        finally:connection.close()

    def listing(self, fresh=False):
        """organize() over the host's session list; shared by the list, the tree, opening and the cards (3 s)."""
        with self.lock:
            stamp,value=self.cache
            if value is not None and not fresh and time.monotonic()-stamp<3:return value
            data=self.client.call('session/list',{'_request':{}})
            if not isinstance(data,dict) or not isinstance(data.get('items'),list):raise DeepSeekError('DeepSeek 对话目录格式不兼容',503)
            rows=[];workspace=workspace_meta();archived=set(workspace.get('archivedSessionIds',[]));pinned=set(workspace.get('pinnedSessionIds',[]))
            for row in data['items']:
                if not isinstance(row,dict) or not row.get('sessionId') or row.get('blank') or row.get('sessionId') in archived:continue
                sid=str(row['sessionId']);v=(row.get('projections') or {}).get('values') or {};cwd=row.get('cwd') or v.get('workingDirectory') or ''
                status='waiting' if (v.get('userQuestions') or {}).get('active') or self.events.for_session(sid) else 'running' if row.get('running') else 'idle'
                entry={'id':sid,'cwd':str(cwd),'updated':int(row.get('updatedAt') or 0),'running':bool(row.get('running')),'status':status,
                             'title':str(v.get('title') or ''),'values':v,'parent':str(row.get('parentSessionId') or ''),
                             'subagent':row.get('origin')=='subagent'}
                if entry['running']:  # 0.6.4: the list's timer needs the turn's own start
                    outline=v.get('turnOutline') or []
                    try:entry['turn_started'],_,entry['step']=self._turn_times(sid,(outline[-1] or {}).get('seq') if outline else 0)
                    except DeepSeekError:pass
                rows.append(entry)
            value=organize(rows,workspace_members(),self.links or parent_links(),pinned)
            self.cache=(time.monotonic(),value)
            return value
    def catalog(self, fresh=False):
        """The conversations, each with its children."""
        return copy.deepcopy(self.listing(fresh)['top'])
    def ungrouped(self, fresh=False):
        return copy.deepcopy(self.listing(fresh)['ungrouped'])
    def find(self, sid):
        if not isinstance(sid,str) or not SESSION_ID.fullmatch(sid):raise DeepSeekError('DeepSeek 对话编号无效',400)
        row=self.listing()['index'].get(sid)
        if row:return {k:copy.deepcopy(v) for k,v in row.items() if k!='children'}
        p=self.client.call('session/projections',{'request':{'sessionId':sid}})
        if not p:raise DeepSeekError('找不到 DeepSeek 对话',404)
        v=p['values'];cwd=v.get('workingDirectory') or ''
        return dict(app='deepseek',id=sid,title=v.get('title') or '新对话',cwd=cwd,folder=Path(cwd).name,updated=0,status='idle')
    def subagents(self,sid):
        """Child sessions this conversation opened, with the host's current running flag (10-19)."""
        try:rows=self.listing()['rows']
        except DeepSeekError:return []
        return [{'id':r['id'],'title':r['title'],'running':r['running'],'updated':r['updated']} for r in rows if r['parent']==sid]
    def _subagents(self,sid,values):
        """The projection's ordered list (labels the desktop shows) joined with the live child sessions."""
        catalog={str(c['childId']):c for c in subagent_catalog(values)}
        live={row['id']:row for row in self.subagents(sid)}
        rows=[]
        for child,entry in catalog.items():
            state=live.get(child) or {}
            rows.append({'id':child,'label':str(entry.get('label') or '子智能体'),'mode':str(entry.get('mode') or ''),
                         'title':str(state.get('title') or ''),'running':bool(state.get('running')),
                         'created':int(entry.get('createdAt') or 0),'updated':int(state.get('updated') or 0)})
        for child,state in live.items():
            if child in catalog:continue
            rows.append({'id':child,'label':(state['title'] or '子智能体')[:60],'mode':'','title':state['title'],
                         'running':state['running'],'created':0,'updated':state['updated']})
        return rows
    def _turn_times(self,sid,start_seq=0,records=None):
        """The newest turn/start and turn/end events as Unix seconds, and the latest tool action (0.6.4)."""
        if records is not None:
            events=[v.get('event') or {} for v in records]
        else:
            try:page,_=self.records(sid,limit=100)
            except Exception:return 0,0,''
            events=[v.get('event') or {} for v in page.get('records',[])]
            if start_seq and not any(e.get('type')=='turn/start' for e in events):
                try:earlier,_=self.records(sid,before=str(int(start_seq)+1),limit=5)
                except Exception:earlier={}
                events=[v.get('event') or {} for v in earlier.get('records',[])]+events
        starts=[int(e['time']/1000) for e in events if e.get('type')=='turn/start' and e.get('time')]
        ends=[int(e['time']/1000) for e in events if e.get('type')=='turn/end' and e.get('time')]
        from chats import _step_of
        step=''
        for e in reversed(events):
            if e.get('type')=='tool/call':
                step=_step_of('deepseek',str((e.get('data') or {}).get('name') or ''))
                if step:break
        return (starts[-1] if starts else 0),(ends[-1] if ends else 0),step
    def state(self,sid):
        item=self.find(sid);p=self.client.call('session/projections',{'request':{'sessionId':sid}})
        if not p or p.get('kind')!='sequenced':raise DeepSeekError('DeepSeek 对话需要在电脑上升级记录格式',409)
        v=p['values'];selection=(v.get('modelSelection') or {}).get('next') or {}
        outline=v.get('turnOutline') or []
        preset=current_permission(v)
        started,ended,step=(0,0,'')
        if item.get('_running') or outline:
            started,ended,step=self._turn_times(sid,(outline[-1] or {}).get('seq') if outline else 0)
        return {'available':True,'id':sid,'running':item.get('_running',False),'status':item['status'],
            'turn_id':str(outline[-1]['turn']) if outline else None,
            'turn_started':started,'turn_ended':ended,'step':step if item.get('_running') else '',
            'settings':selection,'questions':(v.get('userQuestions') or {}).get('active',[]),
            'inbox':v.get('inbox',{}),'queued':queued_messages(v.get('inbox')),
            'permission':preset or '','permission_name':permission_name(preset),'permission_available':preset is not None,
            'seq':p['asOfSeq'],'subagents':self._subagents(sid,v),
            'interactions':self.events.for_session(sid),'interactions_available':self.events.ready}
    # -- permission presets and the queue (10-20). The Harness switches a session's preset through its /permission
    # command (commands/execute logs command/run, then the permissions projection moves); the presets on offer are
    # permissionPresets/catalog. A queued message is changed with session/updateQueue (steer: hand it to the running turn
    # now; remove: drop it), as Codex's queue tray does.
    def permissions(self,sid=''):
        if sid:self.find(sid)
        stamp,found=getattr(self,'_presets',(0,None))
        if found is None or time.monotonic()-stamp>60:
            found=self.client.call('permissionPresets/catalog',{})
            if not isinstance(found,dict) or not isinstance(found.get('options'),list):raise DeepSeekError('DeepSeek 权限目录格式不兼容',503)
            self._presets=(time.monotonic(),found)
        options=[]
        for o in found['options']:
            if not isinstance(o,dict) or not isinstance(o.get('value'),str) or o['value']=='custom':continue  # custom: a derived display state
            name,text=PERMISSIONS.get(o['value'],(str(o.get('name') or o['value']),str(o.get('description') or '')))
            options.append({'value':o['value'],'name':name,'description':text,'confirm':o['value'] in RISKY_PERMISSIONS})
        return {'options':options,'current':self.permission_of(sid) if sid else ''}
    def permission_of(self,sid):
        p=self.client.call('session/projections',{'request':{'sessionId':sid}})
        return current_permission((p or {}).get('values') or {}) or ''
    def set_permission(self,sid,preset,confirmed=False):
        self.find(sid)
        found=self.permissions(sid);option=next((o for o in found['options'] if o['value']==preset),None)
        if option is None:raise DeepSeekError('这个权限选项已不在 DeepSeek 的目录里，请刷新后再选',409)
        if option['confirm'] and not confirmed:raise DeepSeekError('「'+option['name']+'」要先在手机上确认',400)
        if found['current']==preset:return {'accepted':True,'permission':preset,'text':'已经是「'+option['name']+'」'}
        result=self.client.call('commands/execute',{'agentId':sid,'line':'/permission '+preset,'submittedAttachments':[]})
        if isinstance(result,dict) and result.get('kind')=='error':
            raise DeepSeekError('DeepSeek 没有切换权限：'+str(result.get('text') or '')[:160],409)
        deadline=time.monotonic()+4
        while True:  # the session's own record is the authority, as on the desktop
            if self.permission_of(sid)==preset:
                self.cache=(0,None)
                return {'accepted':True,'permission':preset,'text':'已切换为「'+option['name']+'」'}
            if time.monotonic()>=deadline:raise DeepSeekError('DeepSeek 收到了切换命令，但还没看到新的权限；请刷新后核对',409)
            time.sleep(.3)
    def queue_action(self,sid,item_id,action):
        self.find(sid)
        if action not in ('steer','remove'):raise DeepSeekError('排队操作无效',400)
        if not isinstance(item_id,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',item_id):raise DeepSeekError('排队消息编号无效',400)
        self.client.call('session/updateQueue',{'request':{'sessionId':sid,'itemId':item_id,'action':{'kind':action}}})
        return {'accepted':True,'text':'已立即补充给这一轮' if action=='steer' else '已取消排队'}
    def records(self,sid,before='',limit=60):
        p=self.client.call('session/projections',{'request':{'sessionId':sid}})
        if not p or p.get('kind')!='sequenced':raise DeepSeekError('DeepSeek 记录暂不可读',409)
        req={'address':{'kind':'session','sessionId':sid},'throughSeq':p['asOfSeq'],'maxMessages':max(5,min(100,limit))}
        if before:req['beforeSeq']=int(before)
        return self.client.call('session/page',{'request':req}),p
    def conversation(self,sid,limit=60,before='',around=''):
        # A row's id starts with its event's seq ("12", "12:thinking"); a tool call or a subagent ("tool:…",
        # "subagent:…") carries none, so around one of those the latest page is read (10-27: int('tool') failed).
        if around and (seq:=re.match(r'\d+(?=:|$)',str(around))):before=str(int(seq.group())+1)
        item=self.find(sid);page,p=self.records(sid,before,limit);rows=public_messages(page['records'],sid)
        seqs=[r['event']['seq'] for r in page['records'] if r.get('event')]
        v=p['values'];selection=(v.get('modelSelection') or {}).get('next') or {}
        subs=self._subagents(sid,v);by_child={s['id']:s for s in subs}
        for row in rows:
            if row.get('role')!='subagent':continue
            live=by_child.get(row.get('child'))
            if live is not None:row['status']='running' if live['running'] else 'done'
        outline=v.get('turnOutline') or []
        started,ended,step=self._turn_times(sid,(outline[-1] or {}).get('seq') if outline else 0,
                                           records=page.get('records',[]))
        return {k:val for k,val in item.items() if not k.startswith('_')}|{'messages':rows,'subagents':subs,
            'turn_started':started,'turn_ended':ended,'step':step if item.get('_running') else '',
            'size':p['asOfSeq'],'modified':item.get('updated',0),'runtime':{'model':selection.get('model'),'effort':selection.get('reasoningEffort')},
            'has_more':bool(page['hasMore'] and seqs),'next_cursor':str(min(seqs)) if seqs and page['hasMore'] else None,
            'has_newer':bool(before),'reset':False,'total':len(rows)}
    def image(self,sid,ident,thumbnail=False):
        self.find(sid)
        if not isinstance(ident,str) or not re.fullmatch(r'sha256:[0-9a-f]{64}',ident):raise DeepSeekError('图片编号无效',400)
        result=self.client.call('session/attachment',{'request':{'sessionId':sid,'attachmentId':ident}})
        meta=result['attachment'];mime=meta['mediaType']
        if mime not in ('image/png','image/jpeg','image/webp','image/gif') or meta['bytes']>20<<20:raise DeepSeekError('图片格式或尺寸不受支持',400)
        raw=base64.b64decode(result['data'],validate=True)
        if len(raw)!=meta['bytes']:raise DeepSeekError('图片数据不完整',503)
        if thumbnail:
            import io
            from PIL import Image
            with Image.open(io.BytesIO(raw)) as image:
                image.thumbnail((320,320));out=io.BytesIO();image.save(out,format='PNG');raw=out.getvalue();mime='image/png'
        return raw,mime
    def receipt(self,rid):
        with self._db() as db:row=db.execute('SELECT session,state,result FROM requests WHERE id=?',(rid,)).fetchone()
        if not row:return {'state':'unknown'}
        if row[1]=='unconfirmed':
            # Confirm the exact host-stamped request identity, never matching text.
            try:
                if row[0]=='session-'+str(uuid.uuid5(uuid.NAMESPACE_URL,'agent-remote:'+rid)):
                    item=self.find(row[0]);result={k:item[k] for k in ('app','id','title','cwd','folder')};result['accepted']=True
                    with self._db() as db:db.execute('UPDATE requests SET state=?,result=? WHERE id=?',('accepted',json.dumps(result),rid))
                    return {'id':row[0],'state':'accepted','result':result}
                page,p=self.records(row[0],limit=100)
                candidates=[r.get('event',{}).get('data',{}) for r in page['records'] if r.get('event',{}).get('type')=='user/message']
                inbox=p['values'].get('inbox',{})
                candidates+=inbox.get('next-turn',[])+inbox.get('next-step',[])
                if any((m.get('source') or {}).get('rpcId')==rid for m in candidates):
                    result={'accepted':True,'request_id':rid,'text':'已按请求编号确认送达'}
                    with self._db() as db:db.execute('UPDATE requests SET state=?,result=? WHERE id=?',('accepted',json.dumps(result),rid))
                    return {'id':row[0],'state':'accepted','result':result}
            except DeepSeekError:pass
        return {'id':row[0],'state':row[1],'result':json.loads(row[2])}
    def once(self,rid,sid,payload,operation):
        if not isinstance(rid,str) or not re.fullmatch(r'[a-f0-9-]{16,64}',rid):raise DeepSeekError('请求编号无效',400)
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with self.lock:
            with self._db() as db:
                old=db.execute('SELECT session,digest,state,result FROM requests WHERE id=?',(rid,)).fetchone()
                if old:
                    if old[:2]!=(sid,digest):raise DeepSeekError('请求编号已用于其他内容',409)
                    if old[2]=='accepted':return json.loads(old[3])
                    raise DeepSeekError('上次操作结果尚未确认，不会自动重复发送；请核对对话',409)
                db.execute('INSERT INTO requests VALUES(?,?,?,?,?)',(rid,sid,digest,'unconfirmed','{}'))
            result=operation()
            with self._db() as db:db.execute('UPDATE requests SET state=?,result=? WHERE id=?',('accepted',json.dumps(result),rid))
            self.cache=(0,None)
            return result
    def send(self,body):
        sid=body.get('id');self.find(sid);text=body.get('text','');ids=body.get('attachments',[])
        if not isinstance(text,str) or len(text)>20000 or not isinstance(ids,list) or len(ids)>5 or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):raise DeepSeekError('消息或图片数量超出限制',400)
        if body.get('references'):  # conversations and files (10-20: their paths go under the text); no skills
            if not getattr(self,'references',None):raise DeepSeekError('引用服务暂不可用',503)
            if any(not isinstance(ref,dict) or ref.get('kind') not in ('chat','file','folder') for ref in body['references']):raise DeepSeekError('DeepSeek 不能用技能，只能引用对话、附文件',400)
            text,_=self.references.compose('deepseek',sid,text,body['references'])
        content=[{'type':'text','text':text}] if text.strip() else []
        total=0
        for ident in ids:
            meta=self.uploads.attachment(ident,sid)
            if meta.get('app')!='deepseek':raise DeepSeekError('图片不属于 DeepSeek 对话',400)
            raw=Path(meta['path']).read_bytes()
            total+=len(raw)
            if len(raw)>20<<20:raise DeepSeekError('图片转换后超过 20 MB',400)
            if total>50<<20:raise DeepSeekError('图片合计超过 50 MB',400)
            content.append({'type':'image','mediaType':'image/png','data':base64.b64encode(raw).decode(),'name':meta['name']})
        if not content:raise DeepSeekError('请输入消息或添加图片',400)
        mode=body.get('intent','steer')
        if mode not in ('queue','steer'):raise DeepSeekError('发送模式无效',400)
        rid=body.get('request_id')
        def operation():
            result=self.client.call('session/prompt',{'request':{'sessionId':sid,'requestId':rid,'mode':mode,'content':content,'clientTimeZone':'Asia/Taipei'}})
            if result.get('accepted') is not True:raise DeepSeekError('DeepSeek 尚未确认接收')
            for ident in ids:
                meta=self.uploads.attachment(ident,sid);meta['used']=True;self.uploads._write_meta(meta)
            return {'accepted':True,'text':'已排队' if mode=='queue' else '已交给 DeepSeek','request_id':rid}
        return self.once(rid,sid,body,operation)
    def stop(self,sid,expected_turn=None):
        state=self.state(sid)
        if not expected_turn or expected_turn!=state['turn_id']:raise DeepSeekError('当前轮次已变化，请刷新后再停止')
        return self.client.call('session/cancel',{'request':{'sessionId':sid}})
    def models(self):return self.client.call('session/modelCatalog',{})
    def select_model(self,sid,selection):
        self.find(sid)
        allowed={k:selection[k] for k in ('provider','model','reasoningEffort') if k in selection}
        if not all(isinstance(v,str) for v in allowed.values()):raise DeepSeekError('模型选择无效',400)
        return self.client.call('session/selectModel',{'request':{'sessionId':sid,**allowed}})
    def create(self,body):
        rid=body.get('request_id');folder=body.get('folder')
        if not isinstance(folder,str) or not Path(folder).is_absolute() or not Path(folder).is_dir():raise DeepSeekError('请选择存在的项目文件夹',400)
        workspace=workspace_for(folder,body.get('workspace_id'))
        sid='session-'+str(uuid.uuid5(uuid.NAMESPACE_URL,'agent-remote:'+str(rid)))
        self.receipt(rid)  # reconcile a timed-out creation; once() still checks its fingerprint
        def operation():
            result=self.client.call('session/create',{'request':{'sessionId':sid,'workspaceId':workspace['id']}})
            created=result['sessionId']
            if body.get('settings'):self.select_model(created,body['settings'])
            return {'accepted':True,'id':created,'app':'deepseek','title':'新对话','cwd':folder,'folder':Path(folder).name}
        result=self.once(rid,sid,body,operation)
        deadline=time.monotonic()+5
        while True:
            member=(workspace_members() or {}).get(result['id'])
            if member and member['id']==workspace['id']:return result
            if time.monotonic()>=deadline:raise DeepSeekError('对话已创建，但尚未确认归入所选工作区；首条消息未发送，请核对',409)
            time.sleep(.2)
    def _note_answer(self,sid,call,outcome):
        """One line in the day's log (remote.Log): the app, the conversation, the call's tail and what happened.
        The answers themselves are never written."""
        if not self.log:return
        try:title=self.find(sid).get('title') or '（无标题）'
        except Exception:title='（无标题）'
        try:self.log(f'回答：DeepSeek「{title}」{call[-6:] if call else "（无编号）"} {outcome}')
        except Exception:pass
    def answered_in_records(self,sid,call,pages=2):
        """Whether the conversation already holds this call's outcome: answered on another device or a moment
        ago. One or two newest pages are enough; the record is the authority, the live cards may lag behind it."""
        if not isinstance(call,str) or not call:return False
        before=''
        try:
            for _ in range(max(1,pages)):
                page,_=self.records(sid,before,100)
                if self._answer_record(page,call):return True
                seqs=[r['event']['seq'] for r in page.get('records') or [] if isinstance(r.get('event'),dict) and 'seq' in r['event']]
                if not page.get('hasMore') or not seqs:return False
                nxt=str(min(seqs))
                if nxt==before:return False
                before=nxt
        except DeepSeekError:return False
        return False
    @staticmethod
    def _answer_record(page,call):
        """A tool/result for the call is the record that closes it; the Harness also logs an admitted answer as a
        user-question-reply user message, which serves while the tool result is still being written."""
        for record in (page or {}).get('records') or []:
            event=record.get('event') if isinstance(record,dict) else None
            if not isinstance(event,dict):continue
            data=event.get('data') or {}
            if event.get('type')=='tool/result':
                message=data.get('message') if isinstance(data.get('message'),dict) else {}
                source=message.get('source') if isinstance(message.get('source'),dict) else {}
                if (message.get('toolCallId') or source.get('callId') or data.get('callId'))==call:return True
            elif event.get('type')=='user/message':
                message=data.get('message') if isinstance(data.get('message'),dict) else data
                source=message.get('source') if isinstance(message.get('source'),dict) else {}
                if source.get('kind')=='user-question-reply' and source.get('callId')==call:return True
        return False
    def _pending_question(self,sid,call,event_id):
        """The event still waiting for this question. The callId is the question's own identity, so a host that
        sent it again under a new eventId is still answerable through the event waiting now."""
        events=[e for e in self.events.for_session(sid) if e['event']=='user-questions/request']
        if call:
            same=[e for e in events if request_call(e['request'])==call]
            if same:return next((e for e in same if e['eventId']==event_id),same[-1])
        return next((e for e in events if e['eventId']==event_id),None)
    def answer(self,body):
        sid=body.get('id');call=body.get('call_id')
        if not isinstance(call,str):call=''
        try:
            if body.get('event_id'):
                pending=self._pending_question(sid,call,body['event_id'])
                if pending:
                    try:
                        validate_answers(pending['request'].get('questions',[]),body.get('answers'))
                        result=self.events.answer(sid,pending['eventId'],{'answers':body.get('answers',[])},'user-questions/request')
                    except DeepSeekError as exc:  # it left between the look and the answer
                        if exc.status!=409 or not call or not self.answered_in_records(sid,call):raise
                        result={'accepted':True,'already':True,'text':QUESTION_ANSWERED}
                    self._note_answer(sid,call,'已答过' if result.get('already') else '已提交')
                    return result
                if call and self.answered_in_records(sid,call):
                    self._note_answer(sid,call,'已答过')
                    return {'accepted':True,'already':True,'text':QUESTION_ANSWERED}
                raise DeepSeekError(QUESTION_GONE,409)
            state=self.state(sid)
            question=next((q for q in state['questions'] if q.get('callId')==call),None)
            if question:
                validate_answers(question['questions'],body.get('answers'))
                try:result=self.client.call('userQuestions/answer',{'agentId':sid,'callId':call,'answer':{'answers':body.get('answers',[])}})
                except DeepSeekError:
                    if not call or not self.answered_in_records(sid,call):raise
                    result=False
                if result is True:
                    self._note_answer(sid,call,'已提交')
                    return {'accepted':True}
                if not call or not self.answered_in_records(sid,call):raise DeepSeekError(QUESTION_GONE,409)
            elif call and self.answered_in_records(sid,call):
                pass
            else:
                raise DeepSeekError(QUESTION_GONE,409)
            self._note_answer(sid,call,'已答过')
            return {'accepted':True,'already':True,'text':QUESTION_ANSWERED}
        except DeepSeekError as exc:
            if getattr(exc,'status',None)==409:self._note_answer(sid,call,'拒绝：'+str(exc))
            raise

    def transcript(self,sid):
        item=self.find(sid);projection=self.client.call('session/projections',{'request':{'sessionId':sid}})
        seq=projection['asOfSeq'];cached=self.transcripts.get(sid)
        if cached and cached[0]==seq:return item,cached[1]
        before='';messages=[]
        while True:
            page,_=self.records(sid,before,100);messages=public_messages(page['records'],sid)+messages
            cuts=[v['event']['seq'] for v in page['records'] if v.get('event')]
            if not page['hasMore'] or not cuts:break
            next_before=str(min(cuts))
            if next_before==before:raise DeepSeekError('DeepSeek 分页未前进',503)
            before=next_before
        merged={}
        for message in messages:merged[message['id']]=merge_row(merged.get(message['id']),message)
        messages=sorted(merged.values(),key=lambda m:m['order'])
        entry=SimpleNamespace(messages=messages,by_id=merged,lock=threading.RLock())
        self.transcripts[sid]=(seq,entry)
        if len(self.transcripts)>8:self.transcripts.pop(next(iter(self.transcripts)))
        return item,entry

def validate_answers(questions,answers):
    if not isinstance(answers,list) or len(answers)!=len(questions):raise DeepSeekError('请完整回答每一个问题',400)
    mapped={a.get('id'):a for a in answers if isinstance(a,dict)}
    if len(mapped)!=len(questions) or set(mapped)!={q['id'] for q in questions}:raise DeepSeekError('问题编号不匹配',400)
    for q in questions:
        a=mapped[q['id']];selected=a.get('selected');custom=a.get('custom','')
        options={o['label'] for o in q.get('options',[])}
        if not isinstance(selected,list) or any(not isinstance(v,str) or v not in options for v in selected) or len(set(selected))!=len(selected):raise DeepSeekError('答案选项已变化',400)
        if not isinstance(custom,str) or len(custom)>20000 or not selected and not custom.strip():raise DeepSeekError('请填写答案',400)
        if not q.get('multiSelect') and len(selected)>1:raise DeepSeekError('此问题只能选择一个选项',400)

class Interactions:
    """One event client; an answer names the waiting event, and the call inside it outlives a resend.

    Unknown waterfalls are delegated, never auto-approved. Disconnect clears all
    cards, and reconnect obtains the host's current pending set. An answer that
    arrives after its card left is checked against the conversation's record, so
    a repeat becomes "already handled" instead of a scary error.
    """
    def __init__(self,client,note=None,answered=None):
        self.client=client;self.lock=threading.RLock();self.pending={};self.client_id=None
        self.ready=False;self.stopped=threading.Event();self.worker=None;self.socket=None
        self.note=note;self.answered=answered  # Bridge's log line and record lookup
        self.recent={};self.done={}  # eventId -> (agentId, callId) and the events this client answered
    def start(self):
        with self.lock:
            if self.worker and self.worker.is_alive():return
            self.worker=threading.Thread(target=self.run,name='deepseek-events',daemon=True);self.worker.start()
    def close(self):
        self.stopped.set()
        if self.socket:
            try:self.socket.close()
            except Exception:pass
    def for_session(self,sid):
        with self.lock:return copy.deepcopy([v for v in self.pending.values() if v['agentId']==sid])
    def frame(self,value):
        with self.lock:
            if value.get('type')=='ready':self.client_id=value['clientId'];self.ready=True
            elif value.get('type')=='cancel':self.pending.pop(value.get('eventId'),None)
            elif value.get('type')=='waterfall':
                if value.get('event') in ('approval/request','user-questions/request'):
                    self.pending[value['eventId']]={k:value[k] for k in ('eventId','agentId','event','request')}
                    call=request_call(value.get('request'))
                    if call:self._remember(value['eventId'],value['agentId'],call)
                elif self.client_id:
                    self.client.call('$events/result',dict(clientId=self.client_id,eventId=value['eventId'],outcome={'kind':'next'}))
    def _remember(self,eid,sid,call):
        """Keep the call behind an eventId after the event is gone (answered here, cancelled elsewhere, or the
        connection was replaced), so a late repeat can be told apart from a step that really vanished."""
        self.recent.pop(eid,None);self.recent[eid]=(sid,call)
        if len(self.recent)>100:self.recent.pop(next(iter(self.recent)))
    def _tell(self,sid,call,outcome,event):
        if self.note and event=='approval/request':self.note(sid,call,outcome)
    def answer(self,sid,eid,value,event):
        call='';submitted=False
        with self.lock:
            pending=self.pending.get(eid)
            if not (self.ready and pending and pending['agentId']==sid and pending['event']==event):
                # The event is gone (or not this session's/kind): a host resend carries a new eventId for the same
                # call, so look for the call it names and answer that one instead.
                entry=self.recent.get(eid);call=entry[1] if entry and entry[0]==sid else ''
                pending=None
                if call:
                    pending=next((v for v in self.pending.values() if v['agentId']==sid and v['event']==event and request_call(v['request'])==call),None)
                    if pending:eid=pending['eventId']
            if pending:
                call=request_call(pending['request'])
                if event=='approval/request' and value not in ('allowed-once','rejected'):raise DeepSeekError('批准选项无效',400)
                self.client.call('$events/result',dict(clientId=self.client_id,eventId=eid,outcome={'kind':'result','value':value}))
                self.pending.pop(eid,None)
                self.done[eid]=sid
                if len(self.done)>100:self.done.pop(next(iter(self.done)))
                submitted=True
        if submitted:
            self._tell(sid,call,'已提交',event)
            return {'submitted':True,'text':'已提交选择；以 DeepSeek 对话中的处理结果为准'}
        done,gone=((APPROVAL_DONE,APPROVAL_GONE) if event=='approval/request' else (QUESTION_ANSWERED,QUESTION_GONE))
        if self.done.get(eid)==sid or (call and self.answered and self.answered(sid,call)):
            self._tell(sid,call,'已答过',event)
            if event=='approval/request':return {'submitted':True,'already':True,'text':done}
            return {'accepted':True,'already':True,'text':done}
        self._tell(sid,call,'拒绝：'+gone,event)
        raise DeepSeekError(gone,409)
    def run(self):
        import websocket
        while not self.stopped.is_set():
            try:
                port,cookie=self.client.connection_info()
                self.socket=websocket.create_connection(f'ws://127.0.0.1:{port}/api/remote.mux',cookie=cookie,origin=f'http://127.0.0.1:{port}',timeout=5,http_no_proxy=['127.0.0.1'])
                self.socket.send(json.dumps({'type':'open','streamId':'events','endpoint':'$events','payload':{'args':{}}}))
                while not self.stopped.is_set():
                    try:raw=self.socket.recv()
                    except websocket.WebSocketTimeoutException:continue
                    if not raw:break
                    frame=json.loads(raw)
                    if frame.get('type')=='item' and frame.get('streamId')=='events':self.frame(frame['value'])
                    elif frame.get('type') in ('error','end'):break
            except Exception:pass  # never log headers, cookies or raw protocol error data
            finally:
                if self.socket:
                    try:self.socket.close()
                    except Exception:pass
                with self.lock:self.ready=False;self.client_id=None;self.pending.clear()
            self.stopped.wait(3)

_bridge=None
def bridge():
    global _bridge
    if _bridge is None:_bridge=Bridge()
    return _bridge

def listing():
    """{top, ungrouped, index, rows}: from the running Harness, or from its stored summaries while it is closed."""
    if not HOME.is_dir():return organize([],None)
    try:return bridge().listing()
    except DeepSeekError:return offline_listing()

def catalog():
    """The conversations (each with its children): what the list, the tree, the references and the notices show."""
    return copy.deepcopy(listing()['top'])

def offline_listing():
    """Stored summaries remain discoverable while Harness is closed; status is unknown.
    The stored header has no parentSessionId, so a subagent's conversation comes from that conversation's own
    subagentCatalog; a subagent's file is named by its bare id."""
    rows=[];parents={}
    workspace=workspace_meta()
    archived=set(workspace.get('archivedSessionIds',[]));pinned=set(workspace.get('pinnedSessionIds',[]))
    for path in (HOME/'storages/session_projcache/sessions').glob('*.json'):
        try:
            if path.stem in archived:continue
            record=json.loads(path.read_text(encoding='utf-8'))['record'];found=record['rows'];identity=record['identity']
            def val(name):return (found.get(name) or {}).get('val')
            if (val('sessionListMetadata') or {}).get('blank'):continue
            values={'subagentCatalog':val('subagentCatalog'),'turnOutline':(val('turnOutline') or {}).get('turns',[])}
            for c in subagent_catalog(values):parents.setdefault(c['childId'],path.stem)
            subagent=bool((val('subagent') or {}).get('identity'))
            if not subagent and not val('title'):continue
            rows.append({'id':path.stem,'cwd':str(identity.get('cwd') or ''),'updated':int(path.stat().st_mtime*1000),'running':False,
                         'status':'unknown','title':str(val('title') or ''),'values':values,'parent':'','subagent':subagent})
        except (OSError,ValueError,KeyError,TypeError,AttributeError):continue
    for row in rows:
        if row['subagent']:row['parent']=parents.get(row['id'],'')
    return organize(rows,workspace_members(),parent_links(),pinned)
