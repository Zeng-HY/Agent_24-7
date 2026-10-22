"""Durable, one-shot new chat submissions. A timeout never creates a second chat."""
from __future__ import annotations
import hashlib,json,os,queue,re,sqlite3,subprocess,threading,time,uuid
from pathlib import Path
from app_paths import DATA
from contextlib import contextmanager
from urllib.parse import quote
import chats
import codex_control

# A conversation in no project (10-12). Codex desktop counts a conversation as projectless when its working folder is
# Documents\Codex\<date>\<name> (lowercase letters, digits, hyphens; its own projectless folders look like that), so the
# phone makes such a folder and starts the conversation there; nothing of the desktop's own records is touched.
# Claude desktop's "No folder" sessions run in scratch folders it makes itself, which is how they are found afterwards.
CODEX_PROJECTLESS = chats.HOME / 'Documents' / 'Codex'
# How long the Codex desktop may take to pick up a new conversation, and how often its link is opened again meanwhile.
# 10-13 on the company computer the first try stopped after the 25 s there were, and 继续发送 (which opens the link again)
# went through at once; on the home computer the desktop takes about 7 s, minimised or not.
TAKEOVER_SECONDS = 60
REOPEN_SECONDS = 10
# How long, once the desktop holds the new conversation, to wait for it to set the conversation's model. 10-13 on the
# company computer the first look had no model yet, and that empty value, passed on to the send, hid the model the
# desktop set a moment later: the check refused the message (模型或推理强度不在当前桌面目录中). Found by the Codex there.
SETTINGS_SECONDS = 15
# How long a Codex first message whose send ended in an error may take to show up in the conversation's record. 10-15
# 19:09 Codex answered with thread-follower-start-turn-timeout after 5 s, and the message was in the record 5 s later.
LATE_RECEIPT_SECONDS = 30
CLAUDE_SCRATCH = re.compile(r'[\\/]scratch-workspaces[\\/][^\\/]+[\\/][^\\/]+[\\/]scratch-\d{4}-\d{2}-\d{2}-[0-9a-f]{6}(?:[\\/]|$)')
APP_NAMES = {'codex': 'Codex', 'claude': 'Claude', 'deepseek': 'DeepSeek'}
# DeepSeek's reasoning steps, named as its own composer names them (static/deepseek-ui.js)
DEEPSEEK_EFFORTS = {'off': '关', 'none': '关', 'minimal': '最低', 'low': '低', 'medium': '中', 'high': '高', 'xhigh': '很高', 'max': '最高'}


def codex_cli():
    """Prefer the desktop's bundled runtime so creation and delivery share a model catalog.
    An older npm runtime can replace the shared models_cache.json with a different catalog.
    Use npm only on machines without a bundled runtime.
    """
    local=Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData/Local')
    bundled=sorted(local.glob('OpenAI/Codex/bin/*/codex.exe'),key=lambda p:p.stat().st_mtime,reverse=True)
    if bundled:return bundled[0]
    npm=Path(os.environ.get('APPDATA') or Path.home()/'AppData/Roaming')/'npm/node_modules/@openai/codex'
    found=list(npm.glob('node_modules/@openai/codex-win32-x64/vendor/*/bin/codex.exe'))
    return found[0] if len(found)==1 else None


class RequestTiming:
    """Exclusive monotonic stages; no message contents, wall-clock subtraction or fake percentages."""
    def __init__(self,service,rid,data,started=None):
        self.service,self.rid,self.data=service,rid,data
        self.started=self.since=time.perf_counter() if started is None else started
        self.stages=[];self.current=('validation','检查提交内容');self.finished=False
        self.lock=threading.RLock()

    def report(self):
        with self.lock:
            now=self.ended if self.finished else time.perf_counter()
            active=None if self.finished else {'name':self.current[0],'label':self.current[1],'ms':round((now-self.since)*1000,1)}
            return {'total_ms':round((now-self.started)*1000,1),'stages':list(self.stages),'active':active,'complete':self.finished}

    def phase(self,name,label):
        with self.lock:
            if self.finished:return
            now=time.perf_counter()
            self.stages.append({'name':self.current[0],'label':self.current[1],'ms':round((now-self.since)*1000,1)})
            self.since=now;self.current=(name,label)
            # Keep live stages in memory; fsync on every stage adds measurable latency on Windows.
            self.data['timing']=self.report()

    def finish(self):
        with self.lock:
            if self.finished:return
            self.ended=time.perf_counter()
            self.stages.append({'name':self.current[0],'label':self.current[1],'ms':round((self.ended-self.since)*1000,1)})
            self.finished=True;self._persist()

    def _persist(self):
        state,_,result,_=self.service._read(self.rid)
        self.data['timing']=self.report()
        self.service._save(self.rid,state,self.data,result)


class NewConversations:
    def __init__(self,history,references,bridge,desktop,root=None):
        self.history=history;self.references=references;self.bridge=bridge;self.desktop=desktop
        self.claude=None  # claude_control.Controller, set by remote.py: a new Claude conversation's model and effort
        self.root=Path(root or DATA/'attachments');self.root.mkdir(exist_ok=True,parents=True)
        self.db=self.root/'new-conversations.sqlite';self.lock=threading.RLock();self.active=set();self.traces={}
        self.scanned={}  # request id -> the Codex record (path, size, mtime) last searched for it in vain
        with self._db() as con:
            con.execute('CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, state TEXT, data TEXT, result TEXT, created REAL)')
            con.execute('CREATE TABLE IF NOT EXISTS client_timings(request_id TEXT PRIMARY KEY, data TEXT, recorded REAL)')

    @contextmanager
    def _db(self):
        con=sqlite3.connect(self.db,timeout=10)
        try:
            with con:yield con
        finally:con.close()

    def folders(self,app=''):
        rows={}
        def add(path,source,label=None):
            if not isinstance(path,str) or not path:return
            p=Path(chats._strip_unc(path))
            if not p.is_absolute() or not p.is_dir():return
            path=str(p.resolve());key=path.casefold()
            row=rows.setdefault(key,{'path':path,'name':label or p.name or path,'sources':[]})
            if source not in row['sources']:row['sources'].append(source)
            if label:row['name']=label
        if app=='deepseek':
            # The Harness sidebar lists its workspaces; creating a conversation anywhere else adds a new one (10-19).
            import deepseek_control
            for workspace in deepseek_control.workspaces():
                add(workspace['path'],'DeepSeek 工作区',workspace.get('name'))
            if rows:return list(rows.values())
        state=self.references._config(chats.CODEX_HOME/'.codex-global-state.json')
        for v in (state.get('local-projects') or {}).values():
            if isinstance(v,dict):
                for p in v.get('rootPaths',[]):add(p,'Codex 项目',v.get('name'))
        for p in state.get('electron-saved-workspace-roots',[]):add(p,'Codex 项目')
        for p in (self.references._config(self.references.home/'.claude.json').get('projects') or {}):add(p,'Claude 项目')
        for v in self.history.catalog():add(v.get('origin') or v.get('cwd'), {'codex':'Codex 对话','claude':'Claude 对话','deepseek':'DeepSeek 对话'}.get(v['app'],'对话'))
        return list(rows.values())

    def context(self,app,folder):
        if app not in APP_NAMES:raise chats.ChatError('请选择 Codex、Claude 或 DeepSeek')
        key=str(Path(str(folder)).resolve()).casefold() if folder else ''
        # DeepSeek picks from its own workspaces, the list the sheet shows it (folders('deepseek'))
        selected=next((v for v in self.folders('deepseek' if app=='deepseek' else '') if v['path'].casefold()==key),None)
        if not selected:raise chats.ChatError('文件夹已移除或不存在，请重新选择项目文件夹')
        return selected['path']

    def create_draft(self):
        ident=uuid.uuid4().hex
        with self._db() as con:con.execute('INSERT INTO requests VALUES(?,?,?,?,?)',(ident,'draft','{}','{}',time.time()))
        return {'request_id':ident}

    def _read(self,rid):
        if not isinstance(rid,str) or not re.fullmatch('[a-f0-9]{32}',rid):raise chats.ChatError('新对话请求编号无效')
        with self._db() as con:row=con.execute('SELECT state,data,result,created FROM requests WHERE id=?',(rid,)).fetchone()
        if not row:raise chats.ChatError('新对话草稿不存在，请重新打开新建面板')
        return row[0],json.loads(row[1]),json.loads(row[2]),row[3]

    def _save(self,rid,state,data,result):
        with self._db() as con:con.execute('UPDATE requests SET state=?,data=?,result=? WHERE id=?',(state,json.dumps(data,ensure_ascii=False),json.dumps(result,ensure_ascii=False),rid))

    def upload(self,rid,name,raw):
        with self.lock:
            state,_,_,created=self._read(rid)
            if state!='draft' or time.time()-created>7*86400:raise chats.ChatError('此发送副本已提交或过期，请使用新的草稿')
            return self.bridge.upload('new:'+rid,name,raw,new_draft=True)

    def search(self,q):
        app=q.get('app','codex')
        if q.get('projectless')=='1':
            if app not in ('codex','claude'):raise chats.ChatError('DeepSeek 的新对话要选一个工作区')
            folder=''  # no project folder: personal and built-in skills only
        else:folder=self.context(app,q.get('folder',''))
        return self.references.search(app,'',q.get('kind','chat'),q.get('query',''),int(q.get('offset','0')),cwd=folder)

    @staticmethod
    def _projectless_folder():
        """A fresh Documents\\Codex\\<today>\\new-chat (new-chat-2, …) for a Codex conversation in no project."""
        day=CODEX_PROJECTLESS/time.strftime('%Y-%m-%d')
        for n in range(1,200):
            path=day/('new-chat' if n==1 else f'new-chat-{n}')
            try:path.mkdir(parents=True,exist_ok=False);return str(path)
            except FileExistsError:continue
        raise chats.ChatError('今天的无项目对话文件夹已满，尚未创建对话')

    def options(self,app):
        """The models and effort steps the new-conversation sheet offers (10-14). Codex: its model list, each with the
        steps it takes. Claude: what its menus showed before (claude_control.new_options). DeepSeek: its catalog, a model's
        id carrying its provider (provider/model), the steps named as DeepSeek names them (10-20). Default: the desktop's own."""
        if app=='codex':
            return {'models':[{'id':m['id'],'label':m['name'],'efforts':[{'id':e,'label':e} for e in m['efforts']],'default_effort':m.get('default_effort')}
                              for m in codex_control.catalog()['models']],'note':''}
        if app=='claude':
            return self.claude.new_options() if self.claude else {'models':[],'note':'Claude 的模型列表暂时读不到'}
        if app=='deepseek':
            import deepseek_control
            try:catalog=deepseek_control.bridge().models()
            except deepseek_control.DeepSeekError as exc:return {'models':[],'note':'DeepSeek 的模型列表暂时读不到：'+str(exc)[:100]}
            routable=set(catalog.get('routableProviders') or [])
            groups=[g for g in catalog.get('groups') or [] if not routable or g.get('id') in routable]
            return {'models':[{'id':f"{g['id']}/{m['id']}",'label':(m.get('name') or m['id'])+(' · '+(g.get('name') or g['id']) if len(groups)>1 else ''),
                               'efforts':[{'id':e['id'],'label':DEEPSEEK_EFFORTS.get(e['id'],e.get('name') or e['id'])} for e in (m.get('reasoning') or {}).get('efforts') or []],
                               'default_effort':(m.get('reasoning') or {}).get('defaultEffort')} for g in groups for m in g.get('models') or []],'note':''}
        raise chats.ChatError('请选择 Codex、Claude 或 DeepSeek')

    def _settings(self,app,wanted):
        """The model and effort picked on the phone, checked against what options() offers; None: the desktop's own."""
        if not wanted:return None
        if not isinstance(wanted,dict):raise chats.ChatError('模型设置无效，尚未创建对话')
        model,effort=wanted.get('model'),wanted.get('effort')
        if model in (None,'') and effort in (None,''):return None
        offered={m['id']:m for m in self.options(app)['models']}
        if model not in offered:raise chats.ChatError(f'模型「{model}」不在电脑上的模型列表里，尚未创建对话；请重新选择')
        if effort not in (None,'') and effort not in [e['id'] for e in offered[model]['efforts']]:
            raise chats.ChatError(f'「{model}」没有这一档推理强度，尚未创建对话；请重新选择')
        return {'model':model,'effort':None if effort=='' else effort}

    def submit(self,body):
        entered=time.perf_counter()
        rid=body.get('request_id')
        with self.lock:
            state,data,result,_=self._read(rid)
            supplied={k:body.get(k) for k in ('app','folder','text','attachments','references','projectless','settings','permission','permission_confirmed')}
            if not supplied['permission']:
                supplied.pop('permission');supplied.pop('permission_confirmed')
            if not supplied['projectless']:supplied.pop('projectless')  # as stored before projectless existed
            if not supplied['settings']:supplied.pop('settings')  # and before the model could be picked
            if state!='draft':
                if data.get('submitted')!=supplied:raise chats.ChatError('此请求已经提交，不能用同一编号发送不同内容')
                return self.status(rid)
            app=body.get('app');projectless=body.get('projectless') is True
            chosen=self._settings(app,body.get('settings'))
            permission=body.get('permission')
            if permission:
                if app!='deepseek':raise chats.ChatError('新建权限选项仅适用于 DeepSeek')
                import deepseek_control
                option=next((value for value in deepseek_control.bridge().permissions()['options'] if value['value']==permission),None)
                if option is None:raise chats.ChatError('DeepSeek 权限选项已变化，请重新选择')
                if option['confirm'] and body.get('permission_confirmed') is not True:raise chats.ChatError('完全权限或自动审查需要先确认')
            if projectless:
                if app not in ('codex','claude'):raise chats.ChatError('DeepSeek 的新对话要选一个工作区')
                folder=''  # Codex gets its folder below, once the request is known to be sound
            else:folder=self.context(app,body.get('folder'))
            ids=body.get('attachments') or [];refs=body.get('references') or []
            if app=='deepseek' and any(isinstance(r,dict) and r.get('kind') not in ('chat','file','folder') for r in refs):raise chats.ChatError('DeepSeek 不能用技能，只能引用对话、附文件')
            if not isinstance(ids,list) or len(ids)>5 or any(not isinstance(v,str) for v in ids) or len(set(ids))!=len(ids):raise chats.ChatError('最多添加 5 张不重复的图片')
            images=[self.bridge.attachment(i,'new:'+rid) for i in ids]
            if sum(v['original_size'] for v in images)>50<<20:raise chats.ChatError('图片合计不能超过 50 MB')
            only_files=bool(refs) and all(isinstance(r,dict) and r.get('kind') in ('file','folder') for r in refs)
            text=chats.clean_text(body.get('text') or ('请查看这些图片。' if images else '请查看附带的文件。' if only_files else '请根据所选引用协助处理。' if refs else ''))
            compiled,native=self.references.compose(app,'',text,refs,cwd=folder)
            if projectless and app=='codex':folder=self._projectless_folder()
            # Store the complete immutable submission before any desktop effect.
            data={'submitted':supplied,'app':app,'folder':folder,'projectless':projectless,'text':text,'compiled':compiled,'native':native,'attachments':ids,'references':refs,'started':int(time.time()*1000)}
            if chosen:data['settings']=chosen
            if app=='deepseek':
                import deepseek_control
                data['workspace_id']=deepseek_control.workspace_for(folder)['id']
                if permission:data.update(permission=permission,permission_confirmed=body.get('permission_confirmed') is True)
            if app=='claude':data['known_ids']=[v['id'] for v in chats.claude_sessions(1000000,pending=True)]
            self._save(rid,'creating',data,{'message':'正在创建对话…'})
            self.traces[rid]=RequestTiming(self,rid,data,entered)
            self.traces[rid].phase('worker_wait','等待创建任务启动')
            self.active.add(rid)
            threading.Thread(target=self._run,args=(rid,),daemon=True,name='new-chat').start()
            return {'request_id':rid,'state':'creating','message':'正在创建对话…'}

    def status(self,rid):
        with self.lock:
            state,data,result,_=self._read(rid)
            if state not in ('draft','failed','accepted') and rid not in self.active:
                # Read receipts only. Never replay an uncertain creation or Send. An unconfirmed one too: before 10-16 only
                # 'dispatching' was looked at, and a first message that arrived late stayed unconfirmed for good.
                if data.get('app')=='codex' and data.get('id') and state in ('dispatching','unconfirmed') and self._codex_accepted(rid,data):
                    state='accepted';result={'message':'首条消息已送达'};self._save(rid,state,data,result)
                if data.get('app')=='claude' and state in ('dispatching','unconfirmed'):
                    item=self._find_claude(data)
                    if item:data.update(id=item['id'],title=item['title']);state='accepted';result={'message':'首条消息已送达'};self._bind(rid,data);self._record_claude(rid,data);self._save(rid,state,data,result)
                if data.get('app')=='deepseek' and data.get('id') and state in ('dispatching','unconfirmed') and self._deepseek_receipt(rid)=='accepted':
                    state='accepted';result={'message':'首条消息已送达'};self._save(rid,state,data,result)
                if data.get('app')=='deepseek' and state=='prepared':  # the conversation is made and its first message not begun
                    state='failed';result={'message':'对话已建好，第一句话还没发出；可以继续发送','not_submitted':True};self._save(rid,state,data,result)
                if state in ('creating','prepared'):state='unconfirmed';result={'message':'创建过程被中断，请核对电脑；不会重复创建或发送'}
            timing=self.traces[rid].report() if rid in self.traces else data.get('timing')
            return {'request_id':rid,'state':state,'app':data.get('app'),'id':data.get('id'),'title':data.get('title') or '新对话','folder':Path(data.get('folder') or '').name,**result,'timing':timing}

    def client_timing(self,body):
        """Client durations only. Independent storage cannot overwrite a worker's request or receipt."""
        import math
        rid=body.get('request_id');self._read(rid)
        values={}
        for key in ('draft_ms','submit_roundtrip_ms','status_roundtrip_ms','observed_ms','backgrounded'):
            value=(body.get('timing') or {}).get(key)
            if key=='backgrounded':
                if isinstance(value,bool):values[key]=value
            elif type(value) in (float,int) and math.isfinite(value) and 0<=value<=86400000:values[key]=round(value,1)
        with self._db() as con:
            con.execute('INSERT OR REPLACE INTO client_timings VALUES(?,?,?)',(rid,json.dumps(values),time.time()))
        return {'ok':True}

    def retry(self,rid):
        with self.lock:
            state,data,result,_=self._read(rid)
            if state!='failed' or not result.get('not_submitted') or result.get('can_retry') is False or rid in self.active:raise chats.ChatError('发送结果尚未核实，不能重发；请先核对结果')
            if not data.get('projectless'):self.context(data['app'],data['folder'])
            elif data['app']=='codex' and not Path(data['folder']).is_dir():raise chats.ChatError('无项目对话的文件夹已不在，请重新新建')
            self.references.resolve(data['app'],'',data['references'],cwd=data['folder'])
            self._save(rid,'creating',data,{'message':'正在继续提交原来的首条消息…'})
            if data.get('timing'):data.setdefault('prior_timings',[]).append(data.pop('timing'))
            self.traces[rid]=RequestTiming(self,rid,data)
            self.traces[rid].phase('worker_wait','等待继续原请求')
            self.active.add(rid);threading.Thread(target=self._run,args=(rid,),daemon=True,name='new-chat-retry').start()
            return self.status(rid)

    def _bind(self,rid,data):
        for ident in data['attachments']:
            meta=self.bridge.attachment(ident)
            if meta['thread'] not in ('new:'+rid,data['id']):raise chats.ChatError('图片归属不一致')
            meta.update(thread=data['id'],app=data['app'],used=True);self.bridge._write_meta(meta)

    def _record_claude(self,rid,data):
        body={'text':data['text'],'attachments':data['attachments'],'references':data['references']}
        if self.bridge.receipt(data['id'],rid)['state']=='unknown':self.bridge._begin(rid,data['id'],body)
        self.bridge._finish(rid,{'ok':True,'accepted':True,'text':'已从 Claude 记录确认首条消息送达'})

    def _codex_accepted(self,rid,data):
        """Whether a Codex first message reached its conversation: the send's receipt says so, or the conversation's record
        holds a user message sent with this request's id. The receipt reads only the record's last 8 MB, and the first
        message is at its start: 10-16 the conversation of the 10-15 19:09 request had grown to 12.8 MB."""
        try:receipt=self.bridge.receipt(data['id'],rid).get('state')
        except Exception:receipt=None
        if receipt=='accepted':return True
        found=self._in_record(rid,data['id'])
        if found and receipt=='dispatching':  # the delivery ledger too, so the conversation's own view agrees
            try:self.bridge._finish(rid,{'ok':True,'accepted':True,'delivery_state':'accepted','request_id':rid,'text':'已交给 Codex','evidence':found})
            except Exception:pass
        return bool(found)

    def _in_record(self,rid,tid):
        """The user message in the Codex record sent with this request's id ({source, time}), searched from the start;
        None when there is none. A record unchanged since the last search is not read again."""
        try:path=Path(chats.find('codex',tid)['path']);st=path.stat()
        except (chats.ChatError,OSError,KeyError,TypeError):return None
        seen=(str(path),st.st_size,st.st_mtime_ns)
        if self.scanned.get(rid)==seen:return None
        key=rid.encode()
        try:
            with open(path,'rb') as f:
                for raw in f:
                    if key not in raw:continue
                    try:record=json.loads(raw)
                    except ValueError:continue  # a line still being written
                    p=record.get('payload') or {};item=p.get('item') or {}
                    if record.get('type')!='event_msg':continue
                    if p.get('type')=='user_message':sent=p.get('client_id')
                    elif p.get('type')=='item_completed' and item.get('type')=='UserMessage':sent=item.get('client_id')
                    else:continue
                    if sent==rid:return {'source':'conversation_record','time':record.get('timestamp')}
        except OSError:return None
        self.scanned[rid]=seen
        return None

    def _late_receipt(self,rid,data,trace):
        """Whether a Codex first message whose send ended in an error reached the conversation after all. Only for a send
        that had begun (the delivery ledger knows the request); looks for up to LATE_RECEIPT_SECONDS."""
        try:
            if self.bridge.receipt(data['id'],rid).get('state')=='unknown':return False
        except Exception:return False
        trace.phase('late_receipt','等待迟到的送达记录')
        deadline=time.monotonic()+LATE_RECEIPT_SECONDS
        while not self._codex_accepted(rid,data):
            if time.monotonic()>=deadline:return False
            time.sleep(1)
        return True

    def _run(self,rid):
        _,data,_,_=self._read(rid)
        trace=self.traces.get(rid) or RequestTiming(self,rid,data)
        trace.data=data;self.traces[rid]=trace
        try:
            trace.phase('prepare','准备创建对话')
            if data['app']!='deepseek':chats.require_send_desktop()  # DeepSeek goes through its local interface, not the screen
            if data['app']=='deepseek':
                self._run_deepseek(rid,data,trace)
            elif data['app']=='codex':
                if not data.get('id'):self._empty_codex(rid,data)
                self._save(rid,'prepared',data,{'message':'正在连接桌面端的新对话…'})
                trace.phase('desktop_open','在桌面打开新对话')
                chats.require_send_desktop();os.startfile('codex://threads/'+data['id'])
                trace.phase('desktop_owner','等待桌面接管对话')
                deadline=time.monotonic()+TAKEOVER_SECONDS;reopen=time.monotonic()+REOPEN_SECONDS
                while True:
                    try:
                        owner,snapshot=self.bridge._pipe().snapshot(data['id'],5,timing=trace.phase)
                        if snapshot.get('id')==data['id']:break
                    except Exception:
                        now=time.monotonic()
                        if now>=deadline:raise chats.InputNotSubmitted(f'新对话已创建，桌面端 {TAKEOVER_SECONDS} 秒内没有接管；请打开该对话后发送保留的草稿')
                        if now>=reopen:  # what 继续发送 does: open the link again
                            trace.phase('desktop_reopen','再次在桌面打开新对话')
                            chats.require_send_desktop();os.startfile('codex://threads/'+data['id']);reopen=now+REOPEN_SECONDS
                        time.sleep(.5)
                settings=self._desktop_settings(data,snapshot,trace)
                if data.get('settings'):settings=self._picked(settings,data['settings'])
                trace.phase('bind','准备首条消息与附件')
                self._bind(rid,data)
                self._save(rid,'dispatching',data,{'message':'正在提交首条消息…'})
                answer=self.bridge.send({'id':data['id'],'request_id':rid,'text':data['text'],'attachments':data['attachments'],'references':data['references'],'settings':settings},timing=trace.phase)
                if not (answer.get('accepted') or answer.get('delivered')):raise chats.ChatError(answer.get('text') or answer.get('message') or '首条消息结果尚未确认')
            else:
                images=[self.bridge.attachment(v,'new:'+rid) for v in data['attachments']]
                def dispatched():self._save(rid,'dispatching',data,{'message':'已提交，正在核对新对话…'})
                # a folder name no other known folder shares needs no look inside Claude's folder menu ('' is No folder)
                name=Path(data['folder']).name.casefold()
                unique=bool(data['folder']) and sum(Path(v['path']).name.casefold()==name for v in self.folders())==1
                chosen=data.get('settings')
                prepare=(lambda hwnd:self.claude.apply_new(hwnd,chosen['model'],chosen.get('effort'))) if chosen and self.claude else None
                trace.phase('desktop_queue','等待桌面操作')
                extra=(prepare,) if prepare else ()
                self.desktop.run(self.desktop.new_claude,data['folder'],data['compiled'],images,dispatched,unique,trace.phase,*extra,timeout=70 if prepare else 50)
                trace.phase('claude_record','等待首条消息记录')
                deadline=time.monotonic()+35;item=None
                while time.monotonic()<deadline:
                    item=self._find_claude(data)
                    if item:break
                    time.sleep(.5)
                if not item:raise chats.ChatError('尚未在 Claude 记录中确认新对话，请核对电脑；不会重复发送')
                trace.phase('receipt','保存送达回执')
                data.update(id=item['id'],title=item['title']);self._bind(rid,data);self._record_claude(rid,data)
            trace.finish()
            self._save(rid,'accepted',data,{'message':'首条消息已送达'})
            self._log(data,trace,'送达')
        except Exception as exc:
            state,stored,_,_=self._read(rid);data.update(stored)
            if state=='dispatching' and data.get('app')=='codex' and data.get('id') and self._late_receipt(rid,data,trace):
                trace.finish();self._save(rid,'accepted',data,{'message':'首条消息已送达'})
                self._log(data,trace,f'送达（Codex 先回了「{str(exc)[:80]}」，记录里随后有了这条消息）')
                return
            self._log(data,trace,f'没完成：{exc}')
            safe=isinstance(exc,chats.SendNotSubmitted) and state!='dispatching'
            if state=='dispatching' and data.get('app')=='codex' and data.get('id'):
                try:safe=self.bridge.receipt(data['id'],rid).get('state')=='unknown'
                except Exception:pass
            if data.get('app')=='deepseek':  # made but the first message not begun, or begun and DeepSeek never took it
                if state=='prepared':safe=True
                elif state=='dispatching' and data.get('id'):safe=self._deepseek_receipt(rid)=='unknown'
            self._save(rid,'failed' if safe else 'unconfirmed',data,{'message':str(exc)[:350],'not_submitted':safe})
        finally:
            try:trace.finish()
            finally:
                with self.lock:self.active.discard(rid);self.traces.pop(rid,None)

    def _run_deepseek(self,rid,data,trace):
        """A new DeepSeek conversation in one go (10-20): made in the chosen workspace with the model picked, then its
        first message sent. Both go through DeepSeek's own request ledger, the conversation under this request's id and
        the first message under one made from it, so 继续发送 after a failure reaches the same conversation and never
        sends the first message twice. DeepSeek not answering at all happens before anything, so the request can go again."""
        import deepseek_control
        ds=deepseek_control.bridge()
        trace.phase('deepseek_connect','连接 DeepSeek')
        try:ds.models()
        except deepseek_control.DeepSeekError as exc:
            raise chats.SendNotSubmitted('DeepSeek 没有回应，请确认电脑上的 DeepSeek Harness 开着：'+str(exc)[:120]) from None
        trace.phase('deepseek_create','在 DeepSeek 里建对话')
        settings=self._deepseek_settings(data.get('settings'))
        created=ds.create({'request_id':rid,'folder':data['folder'],**({'workspace_id':data['workspace_id']} if data.get('workspace_id') else {}),**({'settings':settings} if settings else {})})
        data.update(id=created['id'],title=created.get('title') or '新对话')
        self._save(rid,'prepared',data,{'message':'对话已建好，正在发出第一句话…'})
        if data.get('permission') and self._deepseek_receipt(rid)!='accepted':
            trace.phase('deepseek_permission','设置并核对 DeepSeek 权限')
            ds.set_permission(data['id'],data['permission'],data.get('permission_confirmed') is True)
        trace.phase('bind','准备首条消息与附件')
        self._bind(rid,data)
        self._save(rid,'dispatching',data,{'message':'正在提交首条消息…'})
        if self._deepseek_receipt(rid)!='accepted':  # the references are in the text already (compiled)
            answer=ds.send({'id':data['id'],'request_id':self._deepseek_first(rid),'text':data['compiled'],
                            'attachments':data['attachments'],'intent':'steer'})
            if not answer.get('accepted'):raise chats.ChatError(answer.get('text') or '首条消息结果尚未确认')

    @staticmethod
    def _deepseek_first(rid):
        """The request id of a new DeepSeek conversation's first message: made from the creation's own, so it is the same
        every time the request is sent, and different from it (DeepSeek's ledger keeps one entry per id)."""
        return hashlib.sha256(('first-message:'+rid).encode()).hexdigest()[:32]

    def _deepseek_receipt(self,rid):
        """What DeepSeek's ledger says of the first message: accepted, unconfirmed, or unknown (never begun)."""
        import deepseek_control
        try:return deepseek_control.bridge().receipt(self._deepseek_first(rid)).get('state') or 'unknown'
        except Exception:return 'unconfirmed'

    @staticmethod
    def _deepseek_settings(chosen):
        """The model picked on the phone ({model: 'provider/model', effort}) as DeepSeek's selectModel takes it; None for
        DeepSeek's own default."""
        if not chosen:return None
        provider,_,model=str(chosen['model']).partition('/')
        return {'provider':provider,'model':model,**({'reasoningEffort':chosen['effort']} if chosen.get('effort') else {})}

    @staticmethod
    def _picked(settings,chosen):
        """The first message's settings as the desktop has them, with the model and effort picked on the phone. With no
        effort picked, the desktop's effort if the model takes it, else the model's default; a speed the model does not
        offer goes back to the default one (the send's check would refuse it)."""
        out=dict(settings);out['model']=chosen['model']
        model=next((m for m in codex_control.catalog()['models'] if m['id']==chosen['model']),{})
        out['effort']=chosen.get('effort') or (out.get('effort') if out.get('effort') in model.get('efforts',[]) else model.get('default_effort'))
        if out.get('service_tier') and out['service_tier'] not in [v.get('id') for v in model.get('service_tiers',[])]:out['service_tier']=None
        return out

    def _desktop_settings(self,data,snapshot,trace):
        """The new conversation's model, effort and speed for its first message, as the desktop has them. Waits up to
        SETTINGS_SECONDS for the desktop to set a model it lists; a model never set becomes the one the conversation was
        made with (a model the desktop did set is kept, and the send's check names it if it is not listed). A value still
        missing is left out, so the send keeps the desktop's own: it reads the conversation again."""
        trace.phase('desktop_settings','等待桌面设好模型')
        settings=codex_control.selected_settings(snapshot)
        models={m['id']:m for m in codex_control.catalog()['models']}
        ready=time.monotonic()+SETTINGS_SECONDS
        while models and settings['model'] not in models and time.monotonic()<ready:
            time.sleep(.5)
            try:settings=codex_control.selected_settings(self.bridge._pipe().snapshot(data['id'],5)[1])
            except Exception:pass
        if not settings['model']:settings['model']=data.get('default_model')
        model=models.get(settings['model'],{})
        if settings['effort'] is None:settings['effort']=data.get('default_effort') or model.get('default_effort')
        if settings['service_tier']=='default':settings['service_tier']=None
        return {k:v for k,v in settings.items() if v is not None or k=='service_tier'}  # None speed is the default one

    def _log(self,data,trace,outcome):
        """One line in the service log (logs/<day>.log) for every new conversation: how it ended and how long each step
        took, so each computer's own log tells where a slow or stopped one spent its time (10-13)."""
        log=getattr(self.desktop,'log',None)
        if not callable(log):return
        try:
            report=trace.report();spent={}
            for stage in report['stages']+([report['active']] if report.get('active') else []):
                spent[stage['label']]=spent.get(stage['label'],0)+stage['ms']
            steps='，'.join(f'{label} {ms/1000:.1f} 秒' for label,ms in spent.items() if ms>=300)
            app=APP_NAMES.get(data.get('app'),'Claude')
            log(f"新建 {app} 对话{outcome}（共 {report['total_ms']/1000:.1f} 秒：{steps}）")
        except Exception:
            pass

    def _find_claude(self,data):
        matches=[]
        for item in chats.claude_sessions(1000000,pending=True):  # a new one is listed before Claude links its record
            if item['id'] in data.get('known_ids',[]) or item['updated']<data['started']-2000:continue
            where=item.get('origin') or item['cwd'] or ''
            if data.get('projectless'):  # No folder: a scratch folder Claude made for the session
                if not CLAUDE_SCRATCH.search(where):continue
            elif not where or Path(where).resolve()!=Path(data['folder']).resolve():continue
            path=chats.claude_transcript(item)
            if any(self._holds(p,data['compiled']) for p in ([path] if path else self._new_records(where,data['started']))):matches.append(item)
        return matches[0] if len(matches)==1 else None

    @staticmethod
    def _new_records(where,started):
        """Records made since the request in the conversation's folder. Claude names a new conversation's record in its
        index seconds after the record holds the first message (13:41:08 against 13:41:02.7 on 10-12), and the phone
        waited 10.5 s for a conversation that was there after 5."""
        folder=chats.CLAUDE_PROJECTS/re.sub(r'[^A-Za-z0-9]','-',where)
        try:return [p for p in folder.glob('*.jsonl') if p.stat().st_ctime*1000>=started-2000]  # st_ctime: made, on Windows
        except OSError:return []

    @staticmethod
    def _holds(path,compiled):
        for raw in chats.read_from(path,0):
            try:record=json.loads(raw)
            except ValueError:continue
            if record.get('type')!='user' or record.get('isMeta') or record.get('isSidechain'):continue
            content=(record.get('message') or {}).get('content')
            parts=[content] if isinstance(content,str) else [v.get('text','') for v in content or [] if isinstance(v,dict) and v.get('type')=='text']
            if any(chats.norm(text)==chats.norm(compiled) for text in parts):return True
        return False

    def _empty_codex(self,rid,data):
        """Create and durably name an empty thread. Exit BEFORE desktop owns any turn."""
        trace=self.traces[rid];trace.phase('cli_spawn','启动创建进程')
        cli=codex_cli()
        if not cli:raise chats.InputNotSubmitted('未找到本机 Codex（命令行版或桌面版），尚未创建新对话')
        p=subprocess.Popen([str(cli),'app-server'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
        messages=queue.Queue()
        def reader():
            for line in p.stdout:
                try:messages.put(json.loads(line))
                except ValueError:pass
        threading.Thread(target=reader,daemon=True).start()
        def call(ident,method,params):
            p.stdin.write(json.dumps({'id':ident,'method':method,'params':params})+'\n');p.stdin.flush();deadline=time.monotonic()+40
            while time.monotonic()<deadline:
                reply=messages.get(timeout=max(.1,deadline-time.monotonic()))
                if reply.get('id')!=ident:continue
                if 'error' in reply:raise chats.ChatError(reply['error'].get('message','创建失败'))
                return reply['result']
            raise chats.ChatError('创建结果未确认')
        try:
            trace.phase('cli_initialize','初始化创建进程')
            call(1,'initialize',{'clientInfo':{'name':'agent_remote','version':'0.15.4'},'capabilities':{'experimentalApi':True}})
            p.stdin.write('{"method":"initialized","params":{}}\n');p.stdin.flush()
            trace.phase('thread_create','创建空对话')
            started=call(2,'thread/start',{'cwd':data['folder'],'ephemeral':False,'historyMode':'legacy'});thread=started['thread']
            data.update(id=thread['id'],title=chats.one_line(data['text'],50),default_effort=started.get('reasoningEffort'),default_model=started.get('model'))
            self._save(rid,'creating',data,{'message':'正在保存新对话…'})
            # Required by this CLI to materialize an empty legacy rollout, not merely cosmetic.
            trace.phase('thread_name','设置标题并触发空对话保存')
            call(3,'thread/name/set',{'threadId':thread['id'],'name':data['title']})
            trace.phase('thread_persist','确认对话保存')
            call(4,'thread/read',{'threadId':thread['id'],'includeTurns':False})
            deadline=time.monotonic()+8
            while not Path(thread['path']).is_file() and time.monotonic()<deadline:time.sleep(.1)
            if not Path(thread['path']).is_file():raise chats.ChatError('新对话尚未保存，未发送首条消息')
        finally:
            trace.phase('cli_exit','移交给桌面前关闭创建进程')
            p.stdin.close()
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:p.terminate();p.wait(timeout=5)
