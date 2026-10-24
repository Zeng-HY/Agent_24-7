import sys,json,tempfile,threading,sqlite3,hashlib,copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chat_history import History,HistoryError
from chat_history import Transcript
from codex_control import Bridge,async_questions
from live_events import merge_live_messages

class ProjectionTests(unittest.TestCase):
    def test_resolve_endpoint_authenticates_and_only_reads(self):
        import remote
        h=object.__new__(remote.Handler);h.path='/api/chat/resolve';h._authorized=lambda:False;h._refuse=Mock();h._body=Mock()
        h.do_POST();h._refuse.assert_called_once();h._body.assert_not_called()
        h._authorized=lambda:True;h._body.return_value={'app':'codex','id':'one','request_ids':['r']};h._json=Mock()
        h.server=SimpleNamespace(codex=SimpleNamespace(delivery_locations=Mock(return_value={})),history=SimpleNamespace(resolve_requests=Mock(return_value={'items':[]})))
        h.do_POST();h.server.history.resolve_requests.assert_called_once_with('codex','one',['r'],{})
        h._body.return_value={'app':'codex','id':'one','request_ids':['x']*101};h.do_POST();self.assertEqual(h._json.call_args.args[1],400)

    def test_native_plan_and_public_message_share_original_position(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'log.jsonl'
            def rec(payload):return json.dumps({'type':'event_msg','timestamp':'2026-10-24T00:00:00Z','payload':payload})+'\n'
            path.write_text(rec({'type':'task_started','turn_id':'t'})+rec({'type':'item_completed','item':{'type':'AgentMessage','id':'public','phase':'final_answer','content':[{'text':'<proposed_plan>Plan</proposed_plan>'}]}})+rec({'type':'item_completed','item':{'type':'Plan','id':'native-plan','text':'Plan'}}),encoding='utf-8')
            entry=Transcript(path,'codex').refresh();self.assertEqual(len(entry.messages),1);self.assertEqual(entry.messages[0]['id'],'public');self.assertIs(entry.by_id['native-plan'],entry.messages[0])
    def test_resolves_outside_page_same_text_images_and_unknown(self):
        rows=[{'id':'old','role':'user','text':'same','client_request_id':'r1','order':10,'turn_id':'t'}, {'id':'picture','role':'user','text':'','client_request_id':'r2','order':20}]+[{'id':str(i),'role':'assistant','text':'same','order':i+30} for i in range(120)]
        history=History();entry=SimpleNamespace(lock=threading.RLock(),messages=rows,by_id={m['id']:m for m in rows})
        history.transcript=lambda app,tid:({},entry if tid=='one' else SimpleNamespace(lock=threading.RLock(),messages=[],by_id={}))
        resolved=history.resolve_requests('codex','one',['r1','r2','unknown'])['items']
        self.assertEqual([m['status'] for m in resolved],['recorded','recorded','unresolved']);self.assertEqual(resolved[0]['message_id'],'old')
        self.assertEqual(history.resolve_requests('codex','other',['r1'])['items'][0]['status'],'unresolved')
        self.assertNotIn('text',resolved[0])
        for bad in [None,'r1',[{}],['r']*101]:
            with self.assertRaises(HistoryError):history.resolve_requests('codex','one',bad)

    def test_ledger_aliases_are_scoped_and_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            bridge=Bridge();bridge.data_root=Path(td);path=Path(td)/'delivery.sqlite'
            with sqlite3.connect(path) as con:
                con.execute('CREATE TABLE deliveries(id TEXT,thread TEXT,state TEXT,result TEXT)')
                con.execute('INSERT INTO deliveries VALUES(?,?,?,?)',('operation','one','accepted',json.dumps({'client_id':'original-queue','evidence':{'message_id':'record'}})))
            con.close()
            before=hashlib.sha256(path.read_bytes()).digest()
            self.assertEqual(bridge.delivery_locations('other',['operation']),{})
            self.assertEqual(bridge.delivery_locations('one',['operation'])['operation']['client_id'],'original-queue')
            self.assertEqual(before,hashlib.sha256(path.read_bytes()).digest())

    def test_question_call_and_answer_have_distinct_source_positions(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'log.jsonl'
            def rec(kind,payload):return json.dumps({'type':kind,'timestamp':'2026-10-24T00:00:00Z','payload':payload})+'\n'
            answer='<send_user_message_question_reply>'+json.dumps([{'questionItemId':json.dumps(['request_user_input_async','call','0']),'answer':'yes'}])+'</send_user_message_question_reply>'
            path.write_text(rec('event_msg',{'type':'task_started','turn_id':'turn'})+rec('response_item',{'type':'function_call','name':'functions.request_user_input_async','call_id':'call','arguments':json.dumps({'questions':[{'title':'Question','options':['yes','no']}]})})+rec('event_msg',{'type':'user_message','message':answer}),encoding='utf-8')
            q=async_questions(path,None)[0]
            self.assertEqual(q['source_id'],'call');self.assertEqual(q['status'],'answered');self.assertGreater(q['answer_order'],q['source_order']);self.assertEqual(q['turn_id'],'turn')

    def test_live_position_does_not_follow_log_tail(self):
        row={'id':'u','role':'user','text':'start','order':50}
        entry=SimpleNamespace(lock=threading.RLock(),messages=[row],by_id={'u':row},offset=100,state={'running':True,'current_turn_id':'turn'})
        state={'id':'chat','turns':[{'turnId':'turn','status':'inProgress','items':[{'id':'u','type':'userMessage'},{'id':'live','type':'agentMessage','phase':'commentary','text':'public'}]}]}
        page={'id':'chat','messages':[row]}
        first,_=merge_live_messages(page,entry,state);position=first[-1]['order'];entry.offset=100000
        second,_=merge_live_messages(page,entry,state)
        self.assertEqual(second[-1]['order'],position)
        supplement={'id':'u2','role':'user','text':'supplement','order':200};entry.messages.append(supplement);entry.by_id['u2']=supplement
        state['turns'][0]['items'].insert(1,{'id':'u2','type':'userMessage'})
        third,_=merge_live_messages(page,entry,state);self.assertGreater(third[-1]['order'],200)

    def test_missing_snapshot_retains_public_text_and_then_settles(self):
        entry=SimpleNamespace(lock=threading.RLock(),messages=[],by_id={},offset=100,state={'running':True,'current_turn_id':'t'})
        page={'id':'chat','messages':[]}
        old={'id':'live','source_id':'live','role':'assistant','phase':'commentary','turn_id':'t','order':101,'text':'public progress','streaming':True}
        missing,ids=merge_live_messages(page,entry,None,{'live':old})
        self.assertEqual(missing[0]['text'],'public progress');self.assertTrue(missing[0]['sync_pending'])
        state={'id':'chat','turns':[{'turnId':'t','status':'inProgress','items':[{'id':'live','type':'agentMessage','phase':'commentary','text':'public progress updated'}]}]}
        fresh,_=merge_live_messages(page,entry,state,{'live':missing[0]});self.assertEqual(len(fresh),1);self.assertEqual(fresh[0]['text'],'public progress updated')
        entry.by_id['live']={k:v for k,v in fresh[0].items() if k not in ('streaming','sync_pending')}
        settled,_=merge_live_messages(page,entry,None,{'live':fresh[0]});self.assertNotIn('streaming',settled[0])

if __name__=='__main__':unittest.main()
