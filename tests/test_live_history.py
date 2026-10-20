import copy,io,json,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chat_history import Transcript
from live_events import merge_live_messages,stream

class LiveHistoryTests(unittest.TestCase):
    def setUp(self):
        self.rows=[{'id':f'm{i}','source_id':f'm{i}','role':'assistant','phase':'commentary','text':f'progress {i}','order':(i+1)*100,'turn_id':'current'} for i in range(100)]
        self.entry=SimpleNamespace(lock=threading.RLock(),messages=self.rows,by_id={v['id']:v for v in self.rows},offset=11000,state={'running':True,'current_turn_id':'current'})
        self.page={'id':'thread','status':'running','messages':copy.deepcopy(self.rows[-60:])}
        self.turn={'turnId':'current','status':'inProgress','turnStartedAtMs':1000,'items':[{'id':m['id'],'type':'agentMessage','phase':'commentary','text':m['text']} for m in self.rows]}
        self.state={'id':'thread','turns':[self.turn]}
    def test_long_turn_does_not_reappend_old_progress_outside_last_60(self):
        self.turn['items'].append({'id':'live','type':'agentMessage','phase':'commentary','text':'new progress'})
        messages,ids=merge_live_messages(self.page,self.entry,self.state)
        self.assertEqual([v['id'] for v in messages], [v['id'] for v in self.rows[-60:]]+['live'])
        self.assertEqual(ids,['live']);self.assertGreater(messages[-1]['order'],self.rows[-1]['order'])
    def test_stale_other_turn_or_completed_log_cannot_supply_live_messages(self):
        self.turn['items'].append({'id':'old','type':'agentMessage','text':'old turn'})
        self.entry.state['current_turn_id']='next'
        self.assertEqual(merge_live_messages(self.page,self.entry,self.state)[1],[])
        self.entry.state.update(current_turn_id='current',running=False)
        self.assertEqual(merge_live_messages(self.page,self.entry,self.state)[1],[])
        self.entry.state['running']=True;self.state['id']='different-thread'
        self.assertEqual(merge_live_messages(self.page,self.entry,self.state)[1],[])
    def test_legacy_text_fallback_is_scoped_to_public_message_and_turn(self):
        self.rows[0].update(legacy=True,source_id=None)
        self.turn['items']=[{'id':'native-different-id','type':'agentMessage','phase':'commentary','text':'progress 0'}]
        self.assertEqual(merge_live_messages(self.page,self.entry,self.state)[1],[])
        self.rows[0]['turn_id']='earlier'
        self.assertEqual(merge_live_messages(self.page,self.entry,self.state)[1],['native-different-id'])
    def test_live_message_is_promoted_even_after_it_leaves_the_page(self):
        previous={'m0':{**self.rows[0],'streaming':True}}
        messages,ids=merge_live_messages(self.page,self.entry,self.state,previous)
        settled=next(v for v in messages if v['id']=='m0')
        self.assertNotIn('streaming',settled);self.assertEqual(settled['order'],100);self.assertEqual(ids,[])
    def test_internal_items_are_never_exposed(self):
        self.turn['items']=[{'id':'private1','type':'reasoning','text':'private'}, {'id':'private2','type':'agentMessage','phase':'analysis','text':'private'}, {'id':'public','type':'agentMessage','phase':'final_answer','text':'public'}]
        messages,ids=merge_live_messages(self.page,self.entry,self.state)
        self.assertEqual(ids,['public']);self.assertFalse(any(v['text']=='private' for v in messages))
    def test_stream_emits_retirement_when_no_other_fields_change(self):
        self.turn['items'].append({'id':'live','type':'agentMessage','text':'new progress'})
        watcher=SimpleNamespace(closed=False,condition=threading.RLock(),snapshots={'thread':(0,'owner',self.state)},unwatch=Mock())
        history=SimpleNamespace(transcript=lambda *a:({},self.entry),conversation=lambda *a:copy.deepcopy(self.page))
        bridge=SimpleNamespace(watch=lambda *a:watcher,status=lambda *a:{'observed_at':0})
        handler=SimpleNamespace(send_response=Mock(),send_header=Mock(),end_headers=Mock(),connection=Mock(),wfile=io.BytesIO())
        calls=[]
        def tick(_):
            calls.append(1)
            if len(calls)==1:self.entry.state['running']=False
            else:raise RuntimeError('end test stream')
        with patch('live_events.select.select',return_value=([],[],[])),patch('live_events.time.sleep',side_effect=tick):stream(handler,history,bridge,None,'codex','thread')
        events=[json.loads(line[6:]) for line in handler.wfile.getvalue().decode().splitlines() if line.startswith('data: ')]
        self.assertEqual(len(events),2);self.assertEqual(events[0]['streaming_ids'],['live']);self.assertEqual(events[1]['streaming_ids'],[]);self.assertEqual(events[1]['messages'],[])
    def test_transcript_tracks_turn_and_preserves_order_across_updates(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'log.jsonl'
            def event(payload):return json.dumps({'type':'event_msg','timestamp':'2026-10-11T08:00:00Z','payload':payload})+'\n'
            def message(text):return event({'type':'item_completed','item':{'type':'AgentMessage','id':'m1','phase':'commentary','content':[{'text':text}]}})
            p.write_text(event({'type':'task_started','turn_id':'t1'})+message('first'),encoding='utf-8');entry=Transcript(p,'codex').refresh();order=entry.messages[0]['order']
            self.assertEqual(entry.messages[0]['turn_id'],'t1')
            with p.open('a',encoding='utf-8') as f:f.write(message('updated')+event({'type':'task_complete','turn_id':'t1'}))
            entry.refresh();self.assertFalse(entry.state['running']);self.assertEqual(len(entry.messages),1);self.assertEqual(entry.messages[0]['order'],order)
            self.assertEqual(entry.messages[0]['text'],'updated')

if __name__=='__main__':unittest.main()
