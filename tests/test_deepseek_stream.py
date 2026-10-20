import io,json,sys,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from deepseek_stream import Blocks,Presentation,StreamGap,public_messages

SID='session-test'
def event(seq,kind,data=None):return {'type':'event','event':{'seq':seq,'type':kind,'time':1000,'data':data or {}}}
def frame(revision,kind,**kwargs):return {'type':'assistant-stream','frame':dict(revision=revision,type=kind,attemptId='a',**kwargs)}
def snapshot(**baseline):return dict(type='snapshot',header={'id':SID},cursor=10,records=[],hasMore=False,projections={},assistantStream={'revision':0,**baseline})

class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.view=Presentation(SID,dict(app='deepseek',id=SID,title='test',status='idle'));self.view.accept(snapshot())
    def start(self):self.view.accept(frame(1,'start',startedAfterSeq=10,turn=1,step=1))
    def test_live_reasoning_is_visible_before_message_commit(self):
        self.start();self.view.accept(frame(2,'chunk',index=0,time=1100,chunk={'type':'reasoning-delta','index':0,'text':'visible'}))
        page,ids=self.view.page();self.assertTrue(page['messages'][0]['thinking']);self.assertEqual(page['messages'][0]['text'],'visible');self.assertEqual(len(ids),1)
        self.assertEqual(page['size'],10)
    def test_block_end_replaces_delta_not_duplicates_it(self):
        b=Blocks();b.accept({'type':'text-delta','index':0,'text':'hello'})
        b.accept({'type':'block-end','index':0,'block':{'type':'text','text':'hello','secret':'never'}})
        self.assertEqual(b.content(),[{'type':'text','text':'hello'}])
    def test_reconnect_reconstructs_compact_prefix(self):
        opening=dict(attemptId='a',startedAfterSeq=10,turn=1,step=1,nextIndex=3,stream=[{'type':'reasoning-chunks','time0':1100,'index':0,'texts':['one',' two'],'dt':[10]},{'type':'text-chunks','time0':1200,'index':1,'texts':['reply'],'dt':[]}])
        self.view.accept(snapshot(revision=5,activeAttempt=opening))
        self.view.accept(frame(6,'chunk',index=3,time=1300,chunk={'type':'text-delta','index':1,'text':' grows'}))
        page,ids=self.view.page();self.assertEqual([m['text'] for m in page['messages']],['one two','reply grows']);self.assertEqual(len(ids),2)
    def test_revision_or_chunk_gap_requires_rebaseline(self):
        self.start()
        with self.assertRaises(StreamGap):self.view.accept(frame(3,'chunk',index=0,time=0,chunk={}))
        self.view.accept(snapshot());self.start()
        with self.assertRaises(StreamGap):self.view.accept(frame(2,'chunk',index=2,time=0,chunk={}))
    def test_durable_history_gap_requires_rebaseline(self):
        with self.assertRaises(StreamGap):self.view.accept(event(12,'turn/start'))
    def test_settlement_retires_transient_in_same_update(self):
        self.start();self.view.accept(frame(2,'chunk',index=0,time=0,chunk={'type':'reasoning-delta','index':0,'text':'think'}))
        self.view.accept(event(11,'assistant/message',{'turn':1,'step':1,'message':{'content':[{'type':'reasoning','text':'think'},{'type':'text','text':'done'}]}}))
        page,ids=self.view.page();self.assertEqual(ids,[]);self.assertEqual([m['text'] for m in page['messages']],['think','done'])
        self.view.accept(frame(3,'end',index=1,outcome={'kind':'committed','seq':11,'eventType':'assistant/message'}))
        self.assertEqual(len(self.view.page()[0]['messages']),2)
    def test_old_turn_commit_does_not_clear_current_attempt(self):
        self.start();self.view.accept(event(11,'assistant/message',{'turn':0,'step':1,'message':{'content':[{'type':'text','text':'old'}]}}))
        self.assertIsNotNone(self.view.attempt)
    def test_tool_completion_preserves_identity_label_and_order(self):
        self.view.accept(event(11,'tool/call',{'callId':'call','name':'pwsh','arguments':'{"description":"Read files"}'}))
        self.view.accept(event(12,'tool/result',{'message':{'toolCallId':'call','isError':True,'content':[{'type':'text','text':'private raw output'}]}}))
        rows=self.view.page()[0]['messages'];self.assertEqual(len(rows),1);self.assertEqual(rows[0]['order'],11);self.assertEqual(rows[0]['tool_status'],'failed');self.assertIn('Read files',rows[0]['text']);self.assertNotIn('private',json.dumps(rows))
    def test_subagent_catalog_becomes_a_card_at_its_place(self):
        self.view.accept(event(11,'subagent/catalog',{'childId':'child-1','label':'答 quote-0001 至 0010','mode':'continuable'}))
        row=self.view.page()[0]['messages'][0]
        self.assertEqual((row['role'],row['child'],row['status']),('subagent','child-1','running'))
        self.assertIn('答 quote-0001 至 0010',row['text'])
    def test_child_status_follows_the_host_while_the_page_stays_open(self):
        self.view.accept(event(11,'subagent/catalog',{'childId':'c1','label':'答 quote-0001 至 0010'}))
        self.view.set_subagent_status([{'id':'c1','running':True}])
        self.assertEqual(self.view.page()[0]['messages'][0]['status'],'running')
        self.assertTrue(self.view.set_subagent_status([{'id':'c1','running':False}]))
        self.assertEqual(self.view.page()[0]['messages'][0]['status'],'done')
    def test_interrupted_attempt_retains_only_visible_blocks(self):
        rows=public_messages([event(12,'assistant/attempt',{'stream':[{'type':'reasoning-chunks','time0':0,'index':0,'texts':['partial'],'dt':[]},{'type':'chunk','time':0,'chunk':{'type':'signature','text':'hidden'}}]})])
        self.assertEqual(rows[0]['text'],'partial');self.assertNotIn('hidden',json.dumps(rows))
    def test_snapshot_identity_and_partial_baseline_fail_closed(self):
        snap=snapshot();snap['header']['id']='other'
        with self.assertRaises(StreamGap):self.view.accept(snap)
        with self.assertRaises(StreamGap):self.view.accept(snapshot(activeAttempt=dict(attemptId='a',startedAfterSeq=10,turn=1,step=1,nextIndex=1,stream=[])))
    def test_abandonment_and_turn_end_clear_live_rows(self):
        self.start();self.view.accept(frame(2,'chunk',index=0,time=0,chunk={'type':'text-delta','index':0,'text':'partial'}))
        self.view.accept(frame(3,'end',index=1,outcome={'kind':'abandoned'}))
        self.assertEqual(self.view.page()[1],[])
        self.view.accept(event(11,'turn/end'));self.assertEqual(self.view.page()[0]['status'],'idle')


class TransportTests(unittest.TestCase):
    def test_sse_forwards_incremental_thinking_then_retires_it(self):
        import live_events
        import deepseek_control
        values=[snapshot(),frame(1,'start',startedAfterSeq=10,turn=1,step=1),
            frame(2,'chunk',index=0,time=1000,chunk={'type':'reasoning-delta','index':0,'text':'visible progress'}),
            event(11,'assistant/message',{'turn':1,'step':1,'message':{'content':[{'type':'reasoning','text':'visible progress'},{'type':'text','text':'finished'}]}}),event(12,'turn/end')]
        socket=Mock();socket.recv.side_effect=[json.dumps(dict(type='item',streamId='history',value=v)) for v in values]+['']
        bridge=Mock();bridge.find.return_value={'app':'deepseek','id':SID,'title':'test','status':'idle'};bridge.client.connection_info.return_value=(1234,'SECRET_COOKIE')
        handler=SimpleNamespace(send_response=Mock(),send_header=Mock(),end_headers=Mock(),connection=Mock(),wfile=io.BytesIO())
        with patch.object(deepseek_control,'bridge',return_value=bridge),patch('websocket.create_connection',return_value=socket),patch('live_events.select.select',return_value=([],[],[])),patch('live_events.time.monotonic',side_effect=[i*.3 for i in range(100)]):
            live_events.deepseek_stream(handler,SID)
        raw=handler.wfile.getvalue().decode();self.assertNotIn('SECRET_COOKIE',raw)
        updates=[json.loads(line[6:]) for line in raw.splitlines() if line.startswith('data: ')]
        self.assertTrue(any(any(m.get('streaming') and m.get('thinking') for m in e.get('messages',[])) for e in updates))
        self.assertEqual(updates[-1]['streaming_ids'],[]);self.assertTrue(handler.close_connection);socket.close.assert_called_once()
    def test_failed_open_does_not_start_sse_or_expose_transport_credentials(self):
        import live_events,deepseek_control
        from chat_history import HistoryError
        bridge=Mock();bridge.client.connection_info.side_effect=ValueError('SECRET_COOKIE')
        handler=SimpleNamespace(send_response=Mock())
        with patch.object(deepseek_control,'bridge',return_value=bridge):
            with self.assertRaises(HistoryError) as error:live_events.deepseek_stream(handler,SID)
        self.assertNotIn('SECRET',str(error.exception));handler.send_response.assert_not_called()

if __name__=='__main__':unittest.main()
