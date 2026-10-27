"""Reader-visible Harness history and its dense, reconnectable presentation stream.

Only the UI's text/reasoning blocks and tool activity are projected. Signatures,
provider replay state, raw requests, usage chunks and runtime prompts stay local.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from urllib.parse import urlencode


class StreamGap(ValueError):
    pass


def timestamp(ms):
    return datetime.fromtimestamp(ms/1000, timezone.utc).isoformat()


def compact_chunks(records):
    for record in records:
        kind=record.get('type')
        if kind=='chunk':
            yield record.get('time',0),record['chunk']
        elif kind in ('text-chunks','reasoning-chunks','tool-call-chunks'):
            parts=record.get('args' if kind=='tool-call-chunks' else 'texts',[])
            if len(record.get('dt',[]))!=max(0,len(parts)-1):raise StreamGap('Invalid compact stream')
            time=record['time0']
            for i,part in enumerate(parts):
                if i:time+=record['dt'][i-1]
                chunk={'index':record['index']}
                if kind=='tool-call-chunks':chunk.update(type='tool-call-delta',id=record['id'],name=record.get('name'),argumentsDelta=part)
                else:chunk.update(type='text-delta' if kind=='text-chunks' else 'reasoning-delta',text=part)
                yield time,chunk
        else:raise StreamGap('Unknown compact stream')


class Blocks:
    def __init__(self):self.blocks={}
    def accept(self,chunk):
        kind=chunk.get('type');index=chunk.get('index')
        if not isinstance(index,int):return  # usage/finish/signature fragments are not display text
        if kind=='block-start':
            if chunk.get('blockType') in ('text','reasoning','tool-call'):
                self.blocks.setdefault(index,{'type':chunk['blockType'],'text':''})
        elif kind in ('text-delta','reasoning-delta'):
            block=self.blocks.setdefault(index,{'type':'text' if kind=='text-delta' else 'reasoning','text':''})
            block['text']+=chunk.get('text','')
        elif kind=='tool-call-delta':
            block=self.blocks.setdefault(index,{'type':'tool-call','name':''})
            if chunk.get('name'):block['name']=chunk['name']
            # Incomplete argument fragments are not a tool invocation or its output.
        elif kind=='block-end':
            block=chunk.get('block',{});kind=block.get('type')
            if kind in ('text','reasoning'):
                self.blocks[index]={'type':kind,'text':block.get('text',self.blocks.get(index,{}).get('text',''))}
            elif kind=='tool-call':self.blocks[index]={'type':kind,'name':block.get('name','')}
    def content(self):return [self.blocks[k] for k in sorted(self.blocks)]


def tool_label(data):
    name=str(data.get('name') or '工具')
    args=data.get('arguments') or {}
    if isinstance(args,str):
        try:args=json.loads(args)
        except (ValueError,TypeError):args={}
    detail=(args.get('description') or args.get('command') or args.get('path') or args.get('url') or '') if isinstance(args,dict) else ''
    return name+(' · '+str(detail)[:220] if detail else '')


def merge_row(previous,row):
    if previous and row.get('role')=='tool':
        row={**row,'order':previous['order'],'tool_label':previous.get('tool_label','工具')}
        row['text']={'running':'正在执行：','completed':'已完成：','failed':'执行失败：'}[row['tool_status']]+row['tool_label']
    return row


def public_messages(records,sid=None):
    rows={}
    for record in records:
        event=record.get('event',{});kind=event.get('type');data=event.get('data') or {}
        seq=event.get('seq',0);base={'time':timestamp(event.get('time',0)),'turn_id':str(data.get('turn',''))}
        if kind=='deliverables/presented':
            files=data.get('files');turn=data.get('turn');call=data.get('callId')
            if type(turn) is not int or turn<1 or not isinstance(call,str) or not call or not isinstance(files,list):continue
            valid=[{'path':v['path'],'description':v.get('description','')} for v in files if isinstance(v,dict) and isinstance(v.get('path'),str) and v['path'].strip() and isinstance(v.get('description',''),str)]
            if valid:
                rows[str(seq)]={**base,'id':str(seq),'order':seq,'role':'assistant','kind':'deliverables','presented_files':valid,
                    'text':'成果文件：\n'+'\n'.join(v['path'].replace('\\','/').rsplit('/',1)[-1] for v in valid)}
            continue
        if kind=='subagent/catalog':
            # A conversation opened a subagent (the desktop shows these as its own cards). The label is the one the
            # host shows; the child's status is filled in when the history is read (deepseek_control.conversation).
            child=str(data.get('childId') or '')
            if not child:continue
            label=str(data.get('label') or '子智能体')
            rows['subagent:'+child]={**base,'id':'subagent:'+child,'order':seq,'role':'subagent',
                'child':child,'label':label,'mode':str(data.get('mode') or ''),'status':'running',
                'text':'子智能体：'+label}
            continue
        if kind in ('tool/call','tool/result'):
            message=data.get('message',{})
            call=data.get('callId') or message.get('toolCallId')
            if not call:continue
            ident='tool:'+str(call);previous=rows.get(ident,{})
            label=tool_label(data) if kind=='tool/call' else previous.get('tool_label','工具')
            status='running' if kind=='tool/call' else 'failed' if message.get('isError') else 'completed'
            rows[ident]={**base,'id':ident,'role':'tool','order':previous.get('order',seq),
                'tool_label':label,'tool_status':status,'text':{'running':'正在执行：','completed':'已完成：','failed':'执行失败：'}[status]+label}
            continue
        if kind not in ('user/message','assistant/message','assistant/attempt'):continue
        message=data.get('message',data);content=message.get('content',[])
        if kind=='user/message' and (message.get('source') or {}).get('kind') not in ('user','user-question-reply'):continue
        if kind=='assistant/attempt':
            blocks=Blocks()
            for _,chunk in compact_chunks(data.get('stream',[])):blocks.accept(chunk)
            content=blocks.content()
        thinking='\n'.join(p.get('text','') for p in content if p.get('type')=='reasoning')
        if thinking.strip():
            ident=str(seq)+':thinking'
            rows[ident]={**base,'id':ident,'order':seq-.1,'role':'assistant','phase':'commentary','thinking':True,'text':thinking}
        text='\n'.join(p.get('text','') for p in content if p.get('type')=='text')
        images=sum(p.get('type')=='image' for p in content)
        if images:text+=f'\n[{images} 张图片]'
        if not text.strip():continue
        row={**base,'id':str(seq),'source_id':message.get('id') or str(seq),
            'role':'user' if kind=='user/message' else 'assistant','text':text,'order':seq,
            'request_id':(message.get('source') or {}).get('rpcId')}
        if any(p.get('type')=='tool-call' for p in content):row['phase']='commentary'
        if sid:
            attached=[]
            for part in content:
                attachment=part.get('attachment') or {}
                if part.get('type')!='image' or not attachment.get('attachmentId'):continue
                url='/api/deepseek/image?'+urlencode({'id':sid,'attachment':attachment['attachmentId']})
                attached.append({'name':attachment.get('name') or '图片','url':url,'thumbnail':url+'&thumb=1'})
            if attached:row['images']=attached
        rows[row['id']]=row
    return sorted(rows.values(),key=lambda r:r['order'])


class Presentation:
    """One foreground follower. Snapshots reset it; gaps require a new snapshot."""
    def __init__(self,sid,item):
        self.sid=sid;self.item=item;self.rows={};self.cursor=-1;self.revision=0
        self.attempt=None;self.blocks=Blocks();self.has_more=False;self.before=None
        self.running=item.get('_running',item.get('status')=='running');self.modified=0
        # child id -> still running, for the subagent cards in this presentation (10-19)
        self.subagent_status={}
    def set_subagent_status(self,rows):
        mapping={str(r['id']):bool(r.get('running')) for r in rows if isinstance(r,dict) and r.get('id')}
        changed=mapping!=self.subagent_status;self.subagent_status=mapping
        return changed
    def accept(self,value):
        kind=value.get('type')
        if kind=='snapshot':
            if value.get('header',{}).get('id')!=self.sid:raise StreamGap('Session identity changed')
            baseline=value.get('assistantStream')
            if not isinstance(baseline,dict):raise StreamGap('Missing presentation baseline')
            records=value['records'];self.rows={m['id']:m for m in public_messages(records,self.sid)}
            self.cursor=value['cursor'];self.revision=baseline['revision'];self.has_more=value['hasMore']
            self.before=str(min(r['event']['seq'] for r in records)) if records and self.has_more else None
            self.attempt=None;self.blocks=Blocks()
            projections=value.get('projections') or {};values=projections.get('values',projections)
            if values.get('title'):self.item={**self.item,'title':values['title']}
            self.selection=(values.get('modelSelection') or {}).get('next') or {}
            for record in records:
                event=record['event']
                if event['type']=='turn/start':self.running=True
                elif event['type']=='turn/end':self.running=False
            opening=baseline.get('activeAttempt')
            if opening:
                self.attempt={k:opening[k] for k in ('attemptId','startedAfterSeq','turn','step','nextIndex')}
                members=list(compact_chunks(opening['stream']))
                if len(members)!=opening['nextIndex']:raise StreamGap('Incomplete presentation baseline')
                for time,chunk in members:self.blocks.accept(chunk);self.modified=time
                self.running=True
            return
        if kind=='event':
            event=value['event'];seq=event['seq']
            if seq<=self.cursor:return
            if seq!=self.cursor+1:raise StreamGap('History sequence gap')
            self.cursor=seq;self.modified=event.get('time',0)
            data=event.get('data',{})
            for row in public_messages([value],self.sid):
                self.rows[row['id']]=merge_row(self.rows.get(row['id']),row)
            if event['type']=='turn/start':self.running=True
            elif event['type']=='turn/end':self.running=False;self.attempt=None
            elif event['type']=='session/title' and isinstance(data.get('title'),str):self.item={**self.item,'title':data['title']}
            if self.attempt and event['type'] in ('assistant/message','assistant/attempt') and data.get('turn')==self.attempt['turn'] and data.get('step')==self.attempt['step']:
                # The durable representation replaces the transient rows in the same SSE update.
                self.attempt=None
            if len(self.rows)>3000:
                keep=sorted(self.rows.values(),key=lambda r:r['order'])[-2500:];self.rows={r['id']:r for r in keep}
            return
        if kind!='assistant-stream':raise StreamGap('Unknown follow frame')
        frame=value['frame']
        if frame['revision']!=self.revision+1:raise StreamGap('Presentation revision gap')
        self.revision=frame['revision'];kind=frame['type']
        if kind=='start':
            self.attempt={k:frame[k] for k in ('attemptId','startedAfterSeq','turn','step')}
            self.attempt['nextIndex']=0;self.blocks=Blocks();self.running=True
        elif kind in ('chunk','end'):
            if not self.attempt or frame['attemptId']!=self.attempt['attemptId']:return
            if frame['index']!=self.attempt['nextIndex']:raise StreamGap('Presentation chunk gap')
            if kind=='end':self.attempt=None
            else:
                self.attempt['nextIndex']+=1;self.modified=frame.get('time',0);self.blocks.accept(frame['chunk'])
        else:raise StreamGap('Unknown presentation frame')
    def page(self):
        rows=list(self.rows.values());live=[]
        for row in rows:
            if row.get('role')=='subagent':
                child=row.get('child')
                if child in self.subagent_status:row['status']='running' if self.subagent_status[child] else 'done'
        if self.attempt:
            attempt=self.attempt
            for index,block in sorted(self.blocks.blocks.items()):
                kind=block['type'];text=block.get('text','')
                if kind=='tool-call':text='准备调用：'+block.get('name','工具')
                if not text.strip():continue
                ident='live:'+attempt['attemptId']+':'+str(index);live.append(ident)
                row={'id':ident,'role':'tool' if kind=='tool-call' else 'assistant','text':text,'streaming':True,
                    'order':self.cursor+.5+index/10000,'time':timestamp(self.modified),'turn_id':str(attempt['turn'])}
                if kind=='reasoning':row.update(thinking=True,phase='commentary')
                elif kind=='tool-call':row.update(tool_status='running')
                rows.append(row)
        item={k:v for k,v in self.item.items() if not k.startswith('_')}
        return {**item,'messages':sorted(rows,key=lambda r:r['order']),'status':'running' if self.running else 'idle',
            'runtime':{'model':self.selection.get('model'),'effort':self.selection.get('reasoningEffort')},
            'size':self.cursor,'modified':self.modified,'has_more':self.has_more,'next_cursor':self.before,
            'has_newer':False,'reset':False,'total':len(rows)},live
