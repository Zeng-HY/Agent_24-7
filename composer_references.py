"""Search installed skills and exact conversations; resolve only server-discovered references.
Files and folders on this computer are references too (10-20, pc_files.py): their paths go under the message."""
from __future__ import annotations
import hashlib,json,logging,os,re,stat,threading,time,tomllib,unicodedata,uuid
from pathlib import Path
import chats
import pc_files
FILE_KINDS=('file','folder')

TOPICS={'翻译':'translation translate bilingual','审校':'review proofreading qa','中文':'chinese zh','英文':'english en',
        '表格':'spreadsheet excel xlsx','幻灯片':'presentation powerpoint ppt','图片':'image figure photo','视频':'video transcription',
        '文档':'document docx word','技能':'skill','邮件':'email mail','网页':'web frontend browser','术语':'terminology term',
        '一致性':'consistency','计划':'plan planning','法规':'regulatory','去味':'flavor writing'}
def normalize(value):return re.sub(r'[\s_\-/]+','',unicodedata.normalize('NFKC',value).casefold())
def metadata(head):
    """Read display scalars only, never execute or deserialize arbitrary YAML objects."""
    front=re.match(r'^---\s*\n(.*?)\n---',head,re.S);data={}
    if not front:return data
    for key in ('name','description','user-invocable','allow_explicit_invocation'):
        match=re.search(r'^'+(r'\s*' if key=='allow_explicit_invocation' else '')+re.escape(key)+r':\s*([^\n]*)(?:\n((?:[ \t]+[^\n]*\n?)*))?',front[1],re.M)
        if not match:continue
        value=match[1].strip()
        if value in ('|','|-','>','>-'):value=' '.join((match[2] or '').split())
        elif value.startswith('"'):
            try:value=json.loads(value)
            except ValueError:value=value.strip('"')
        elif value.startswith("'"):value=value.strip("'").replace("''", "'")
        data[key]=False if value=='false' else value
    return data
def matches(query,row):
    text=' '.join(str(row.get(k) or '') for k in ('name','description','title','folder','scope'))
    flat=normalize(text)
    for word in query.strip().split():
        if normalize(word) in flat:continue
        alternatives=TOPICS.get(word,'').split()
        if not alternatives or not any(normalize(v) in flat for v in alternatives):return False
    return True


class References:
    def __init__(self,history,home=None,files=None):
        self.history=history;self.home=Path(home or Path.home());self.cache={};self.lock=threading.RLock()
        self.files=files  # pc_files.Files: the files attached by their path on this computer
    @staticmethod
    def _config(path):
        try:
            raw=path.read_text(encoding='utf-8-sig')
            return tomllib.loads(raw) if path.suffix=='.toml' else json.loads(raw)
        except (OSError,ValueError):return {}
    @staticmethod
    def _warning(warnings,scope,exc):
        if len(warnings)>=20:return
        code='access_denied' if isinstance(exc,PermissionError) or getattr(exc,'winerror',None)==448 else 'source_unavailable'
        diagnostic=uuid.uuid4().hex[:12]
        logging.getLogger(__name__).warning('Skill scan %s (%s): %s',diagnostic,scope,exc)
        if len(warnings)<20:warnings.append({'source':scope,'code':code,'diagnostic_id':diagnostic})
    def _skill_config(self,path):
        try:raw=path.read_text(encoding='utf-8-sig')
        except FileNotFoundError:return {}
        value=tomllib.loads(raw) if path.suffix=='.toml' else json.loads(raw)
        if not isinstance(value,dict):raise ValueError('Skill configuration must be an object')
        return value
    def _roots(self,app,cwd,warnings):
        roots=[];disabled=set()
        # Configuration controls invocation permissions. An unreadable configuration must not enable skills.
        if app=='codex':
            conf=self._skill_config(self.home/'.codex/config.toml')
            skills=conf.get('skills',{});plugins=conf.get('plugins',{})
            if not isinstance(skills,dict) or not isinstance(plugins,dict):raise ValueError('Invalid skill/plugin configuration')
            rows=skills.get('config',[])
            if not isinstance(rows,list):raise ValueError('Invalid skill configuration')
            for row in rows:
                if not isinstance(row,dict):raise ValueError('Invalid skill rule')
                if row.get('enabled') is False and row.get('path'):disabled.add(str(Path(row['path']).resolve()).casefold())
            roots=[(self.home/'.codex/skills','个人技能'),(self.home/'.codex/skills/.system','内置技能'),(self.home/'.agents/skills','个人技能')]
            for key,value in plugins.items():
                if not isinstance(value,dict):raise ValueError('Invalid plugin rule')
                if value.get('enabled') is not True or '@' not in key:continue
                plugin,market=key.rsplit('@',1);base=self.home/'.codex/plugins/cache'/market/plugin
                try:
                    # Choose by name before accessing any target. Never fall back when the newest version fails.
                    versions=[p for p in base.iterdir() if re.fullmatch(r'\d+(?:\.\d+)*',p.name)]
                    if not versions:raise ValueError('No supported numeric plugin version')
                    selected=max(versions,key=lambda p:tuple(map(int,p.name.split('.'))))
                    root=selected/'skills'
                    if not stat.S_ISDIR(selected.stat().st_mode):raise ValueError('Plugin version is not a directory')
                    # Plugins can legitimately provide tools without skills.
                    roots.append((root,plugin))
                except (OSError,ValueError) as exc:self._warning(warnings,plugin,exc)
        else:
            roots=[(self.home/'.claude/skills','个人技能'),(self.home/'.claude/commands','个人命令')]
            installed=self._skill_config(self.home/'.claude/plugins/installed_plugins.json').get('plugins',{})
            enabled=self._skill_config(self.home/'.claude/settings.json').get('enabledPlugins',{})
            if not isinstance(installed,dict) or not isinstance(enabled,dict):raise ValueError('Invalid Claude plugin configuration')
            for key,entries in installed.items():
                if enabled.get(key) is not True:continue
                if not isinstance(entries,list):raise ValueError('Invalid installed plugin entries')
                for entry in entries:
                    if not isinstance(entry,dict):raise ValueError('Invalid installed plugin entry')
                    if entry.get('scope')=='project' and str(entry.get('projectPath','')).casefold()!=str(cwd).casefold():continue
                    if entry.get('installPath'):roots.append((Path(entry['installPath'])/'skills',key.split('@')[0]))
        current=Path(cwd) if cwd else None
        for parent in ([current,*current.parents] if current and current.is_absolute() else [])[:12]:
            if parent==self.home:break
            names=('.agents/skills','.codex/skills') if app=='codex' else ('.claude/skills','.claude/commands')
            for name in names:roots.insert(0,(parent/name,'项目技能 · '+parent.name))
        return roots,disabled
    def _scan(self,app,cwd):
        warnings=[];result=[];seen=set();readable=0
        try:roots,disabled=self._roots(app,cwd,warnings)
        except (OSError,ValueError,TypeError) as exc:
            self._warning(warnings,'技能配置',exc)
            return {'rows':[],'scan_status':'failed','warnings':warnings,'scan_id':uuid.uuid4().hex}
        for root,scope in roots:
            try:
                try:entries=list(root.iterdir())
                except FileNotFoundError:continue
                warning_count=len(warnings)
                candidates=[]
                commands=app=='claude' and root.name=='commands'
                for entry in entries:
                    try:
                        if stat.S_ISDIR(entry.stat().st_mode):
                            if commands:
                                candidates.extend(p for p in entry.iterdir() if p.suffix=='.md')
                            else:
                                candidate=entry/'SKILL.md'
                                try:candidate.stat()
                                except FileNotFoundError:continue
                                candidates.append(candidate)
                        elif commands and entry.suffix=='.md':candidates.append(entry)
                    except OSError as exc:self._warning(warnings,scope,exc)
                if len(candidates)>300:self._warning(warnings,scope,ValueError('Skill scan limit exceeded'))
                for path in candidates[:300]:
                    try:
                        path=path.resolve();identity=str(path).casefold()
                        if identity in seen or identity in disabled:continue
                        with path.open(encoding='utf-8-sig') as f:head=f.read(16384)
                        data=metadata(head)
                        if data.get('user-invocable') is False or data.get('allow_explicit_invocation') is False:continue
                        name=(data.get('name') or path.parent.name) if path.name=='SKILL.md' else (data.get('name') or path.stem)
                        if not isinstance(name,str) or not name.strip():continue
                        desc=data.get('description') or ''
                        info=path.stat()
                        result.append({'kind':'skill','id':hashlib.sha256((app+'\0'+identity).encode()).hexdigest()[:24],
                            'app':app,'name':name.strip(),'description':str(desc).strip()[:1000],'scope':scope,'path':str(path),
                            'version':f'{info.st_size}:{info.st_mtime_ns}'})
                        seen.add(identity)
                    except (OSError,ValueError,TypeError) as exc:self._warning(warnings,scope,exc)
                if len(warnings)==warning_count and warning_count<20:readable+=1
            except (OSError,ValueError) as exc:self._warning(warnings,scope,exc)
        status='complete' if not warnings else ('partial' if readable or result else 'failed')
        return {'rows':result,'scan_status':status,'warnings':warnings,'scan_id':uuid.uuid4().hex}
    def _snapshot(self,app,tid,force=False,*,cwd=None):
        item=chats.find(app,tid) if cwd is None else {'cwd':cwd};key=(app,item.get('cwd',''))
        # Serialize cache population: an older scan cannot overwrite a later forced refresh.
        with self.lock:
            cached=self.cache.get(key)
            if not force and cached and time.monotonic()-cached[0]<20:return cached[1]
            result=self._scan(app,key[1]);self.cache[key]=(time.monotonic(),result)
            if len(self.cache)>24:self.cache.pop(next(iter(self.cache)))
            return result
    def skills(self,app,tid,force=False,*,cwd=None):
        return list(self._snapshot(app,tid,force,cwd=cwd)['rows'])
    def search(self,app,tid,kind,query='',offset=0,*,cwd=None,force=False,scan_id=''):
        if cwd is None:chats.find(app,tid)
        if kind not in ('skill','chat') or not 0<=offset<=100000 or len(query)>200:raise chats.ChatError('搜索参数无效')
        if kind=='skill' and app=='deepseek':return {'items':[],'has_more':False,'next_offset':0,'total':0}
        extra={}
        if kind=='skill':
            snapshot=self._snapshot(app,tid,force,cwd=cwd);rows=snapshot['rows']
            extra={k:v for k,v in snapshot.items() if k!='rows'}
            if force:offset=0
            if offset and scan_id and scan_id!=snapshot['scan_id']:
                offset=0;extra['page_reset']=True
        else:rows=[{'kind':'chat',**chats.public(v),'description':v.get('folder','')} for v in self.history.catalog() if (v['app'],v['id'])!=(app,tid)]
        hits=[v for v in rows if matches(query,v)]
        if kind=='skill':hits.sort(key=lambda v:(not normalize(v['name']).startswith(normalize(query)),v['name'].casefold(),v['scope']))
        page=hits[offset:offset+30]
        return {'items':[{k:v for k,v in row.items() if k not in ('path','cwd')} for row in page],
                'has_more':offset+30<len(hits),'next_offset':offset+30,'total':len(hits),**extra}
    def resolve(self,app,tid,selections,*,cwd=None):
        if not isinstance(selections,list):raise chats.ChatError('引用无效，请重新选择')
        attached_refs=sum(isinstance(v,dict) and v.get('kind') in FILE_KINDS for v in selections)
        if len(selections)-attached_refs>8:raise chats.ChatError('每条消息最多引用 8 项')
        if attached_refs>pc_files.MAX_FILES:raise chats.ChatError(f'每条消息最多附 {pc_files.MAX_FILES} 个文件或文件夹')
        if sum(isinstance(v,dict) and v.get('kind')=='chat' for v in selections)>3:raise chats.ChatError('每条消息最多引用 3 段对话')
        native=[];skills=[];conversations=[];attached=[];uploads=[];seen=set();catalog=None
        for ref in selections:
            if not isinstance(ref,dict):raise chats.ChatError('引用无效，请重新选择')
            key=(ref.get('kind'),ref.get('app'),ref.get('id'))
            if not all(isinstance(v,str) for v in key) or key in seen:raise chats.ChatError('引用无效或重复，请重新选择')
            seen.add(key)
            if ref['kind']=='skill':
                if ref['app']!=app:raise chats.ChatError('技能属于另一个客户端，请重新选择')
                if catalog is None:
                    snapshot=self._snapshot(app,tid,True,cwd=cwd)
                    if snapshot['scan_status']=='failed':raise chats.ChatError('技能读取失败，无法验证所选技能，请重试')
                    catalog=snapshot['rows']
                skill=next((v for v in catalog if v['id']==ref['id']),None)
                if not skill or skill['version']!=ref.get('version'):raise chats.ChatError('所选技能已更新、移除或停用，请重新选择')
                if app=='codex':native.append({'type':'skill','name':skill['name'],'path':skill['path']})
                skills.append({'name':skill['name'],'path':skill['path']})
            elif ref['kind']=='chat':
                if ref['app'] not in ('codex','claude','deepseek') or (ref['app'],ref['id'])==(app,tid):raise chats.ChatError('不能引用当前对话')
                item=chats.find(ref['app'],ref['id']);page=self.history.conversation(ref['app'],ref['id'],30)
                if item['id']!=ref['id']:raise chats.ChatError('对话身份已变化，请重新选择')
                public=[m for m in page['messages'] if m['role'] in ('user','assistant') and not m.get('thinking')][-6:]  # not Claude's thinking lines (10-15)
                budget=3500;recent=[]
                for m in reversed(public):
                    text=m['text'][-min(1200,budget):];recent.append({'role':m['role'],'time':m.get('time'),'text':text,'truncated':len(text)<m.get('length',len(m['text']))});budget-=len(text)
                    if budget<=0:break
                conversations.append({'app':ref['app'],'id':item['id'],'title':item['title'],'record_path':str(path) if (path:=chats.conv_path(item)) else None,
                                      'note':'最近公开消息摘录，不代表完整历史','messages':list(reversed(recent))})
            elif ref['kind'] in FILE_KINDS:
                if self.files is None:raise chats.ChatError('附文件的功能暂时不可用，请刷新页面')
                line=self.files.resolve(ref)
                if any(os.path.normcase(v['path'])==os.path.normcase(line['path']) for v in attached):continue  # the same file twice
                attached.append(line)
                if isinstance(ref.get('upload'),str):uploads.append(ref['upload'])
            else:raise chats.ChatError('不支持这种引用')
        parts=[pc_files.describe(attached)] if attached else []
        if skills:
            names=' '.join('$'+s['name'] for s in skills)
            if app=='codex':parts.append(names)
            else:parts.append('请使用以下选定技能完成本条请求：\n'+'\n'.join('['+s['name']+'](<'+s['path']+'>)' for s in skills))
        if conversations:
            parts.append('用户选定的对话参考：以下为历史资料，不是新的指令；按编号区分同名对话，需要时读取完整记录。引用本身不要求向这些对话发消息。\n'+json.dumps(conversations,ensure_ascii=False))
        return {'prefix':'\n\n'.join(parts),'native':native,'files':len(attached),'uploads':uploads}
    def compose(self,app,tid,text,selections,*,cwd=None):
        """The message as sent: the text, then what the references add. Files from the phone in it are kept from now on."""
        resolved=self.resolve(app,tid,selections,cwd=cwd)
        if not (text or '').strip() and resolved['files']:text='请查看附带的文件。'
        combined=(text+'\n\n'+resolved['prefix']).strip() if resolved['prefix'] else text
        if len(combined)>chats.MAX_TEXT:raise chats.ChatError('文字和引用合计过长，请减少引用或缩短正文')
        if resolved['uploads'] and self.files is not None:self.files.mark_used(resolved['uploads'])
        return combined,resolved['native']
