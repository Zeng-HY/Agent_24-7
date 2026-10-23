"""Bounded task summaries; desktop reads never launch or take ownership of a task."""
from __future__ import annotations
import copy,threading,time
import chats
from codex_control import native_questions,latest_plan,ordered_turns,is_running,async_questions
from pathlib import Path

class TaskCenter:
    def __init__(self,bridge):
        self.bridge=bridge;self.rows=[];self.lock=threading.Lock();self.stop=threading.Event();self.started=False;self.live={};self.checked={};self.last_catalog=0;self.last_client=0
    def start(self):
        with self.lock:
            if self.started:return
            self.started=True;threading.Thread(target=self._run,name='remote-task-summary',daemon=True).start()
    def _run(self):
        while not self.stop.is_set():
            try:
                now=time.time()
                if now-self.last_client>60:
                    self.stop.wait(2);continue
                if now-self.last_catalog>20:
                    rows=chats.list_conversations('all',100)
                    with self.lock:self.rows=rows;self.last_catalog=now
                recent={r['id'] for r in self.rows[:20]}
                candidates=[r for r in self.rows if r['app']=='codex' and (r['id'] in recent or r['status'] in ('running','unknown') or r['id'] in self.bridge.cache or (self.live.get(r['id']) or {}).get('pending'))]
                candidates.sort(key=lambda r:self.checked.get(r['id'],0))
                for row in candidates[:1]:
                    tid=row['id']
                    if now-self.checked.get(tid,0)<12:continue
                    self.checked[tid]=now
                    if not self.bridge.lock.acquire(blocking=False):continue
                    try:
                        item,_,state=self.bridge.snapshot(tid,timeout=2)
                        turns=ordered_turns(state);questions=native_questions(state)
                        questions+=async_questions(Path(item['path']),turns[-1].get('turnId') if turns and is_running(state) else None)
                        pending=sum(q['status']=='pending' for q in questions);plan=latest_plan(state);pending+=int(bool(plan and plan['ready']))
                        self.live[tid]={'running':is_running(state),'pending':pending,'observed_at':int(now*1000),'source':'desktop','last_turn_id':turns[-1].get('turnId') if turns else None,'outcome':turns[-1].get('status') if turns else None}
                    except Exception:
                        self.live[tid]={'verified':False,'observed_at':int(now*1000),'source':'unavailable'}
                    finally:self.bridge.lock.release()
            except Exception:pass
            self.stop.wait(2)
    def summary(self):
        self.last_client=time.time()
        self.start()
        with self.lock:rows=copy.deepcopy(self.rows);updated=self.last_catalog
        out=[];counts={'pending':0,'running':0,'completed':0,'unverified':0}
        for row in rows:
            live=self.live.get(row['id']) if row['app']=='codex' else None
            fresh=bool(live and time.time()*1000-live['observed_at']<45000)
            if fresh and live.get('source')=='desktop':
                state='pending' if live['pending'] else 'running' if live['running'] else 'completed'
                source='desktop';observed=live['observed_at'];pending=live['pending'];turn=live['last_turn_id']
            else:
                state='running' if row['status']=='running' else 'completed' if row['status']=='idle' else 'unverified'
                source='log';observed=row['updated'];pending=None;turn=None
            counts[state]+=1
            out.append({**row,'task_state':state,'source':source,'observed_at':observed,'pending_count':pending,'last_turn_id':turn,'outcome':live.get('outcome') if source=='desktop' else None})
        out.sort(key=lambda r:({'pending':0,'running':1,'unverified':2,'completed':3}[r['task_state']],-r['updated']))
        return {'items':out,'counts':counts,'updated_at':int(updated*1000),'loading':not updated,'scope':'最近 100 个对话；无法取得桌面状态的项目已标注来源或待核对。'}
    def apply_status(self,rows):
        """Use already-observed live state without blocking the conversation list on IPC."""
        now=time.time()*1000
        for row in rows:
            live=self.live.get(row['id']) if row['app']=='codex' else None
            if live and live.get('source')=='desktop' and now-live['observed_at']<45000:
                row['status']='waiting' if live.get('pending') else 'running' if live['running'] else 'idle'
                row['status_source']='desktop'
        return rows
    def observe(self,tid,data):
        if data.get('available'):
            self.live[tid]={'running':data.get('running',False),'pending':sum(q.get('status')=='pending' for q in data.get('questions',[]))+int(bool((data.get('plan') or {}).get('ready'))),
                            'observed_at':data.get('observed_at',int(time.time()*1000)),'source':'desktop','last_turn_id':(data.get('recent_turns') or [{}])[-1].get('id'),'outcome':(data.get('recent_turns') or [{}])[-1].get('status')}
    def close(self):self.stop.set()
