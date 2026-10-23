import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import activity_records as activity
from chat_history import Transcript, History, HistoryError


def line(kind, payload, ts='2026-10-23T10:00:00Z'):
    return json.dumps({'type':kind,'timestamp':ts,**payload}).encode()+b'\n'


class ActivityRecordsTest(unittest.TestCase):
    def test_sort_and_filter_are_applied_before_pagination(self):
        history=History()
        items=[{'app':'codex','id':str(i),'title':'t','updated':i,'created':100-i if i%2 else None,'status':'waiting' if i%2 else 'idle'} for i in range(12)]
        with patch.object(history,'_load',return_value=(items,[])),patch('chats.summary',side_effect=lambda item:{'status':item['status'],'preview':''}):
            first=history.conversations(limit=5,sort='created',status='waiting')
            self.assertEqual([m['id'] for m in first['items']],['1','3','5','7','9'])
            second=history.conversations(limit=5,sort='created',status='waiting',cursor=first['next_cursor'])
            self.assertEqual([m['id'] for m in second['items']],['11'])
            self.assertEqual(first['total'],6)

    def test_native_file_change_dictionary(self):
        source=line('event_msg',{'payload':{'type':'item_completed','item':{'type':'FileChange','id':'native','status':'completed','changes':{'new.py':{'type':'add','content':'hello\nworld\n'}}}}})
        m=activity.enrich('codex',source,[],{})[0]
        self.assertEqual(activity.public_message(m)['changes'][0]['added'],2)

    def test_question_pause_is_reconstructed_from_source(self):
        context={}
        activity.enrich('codex',line('event_msg',{'payload':{'type':'task_started','turn_id':'t'}}),[],context)
        activity.enrich('codex',line('response_item',{'payload':{'type':'function_call','name':'request_user_input','call_id':'q'}},'2026-10-23T10:00:05Z'),[],context)
        self.assertIsNotNone(context['activity_turns']['t']['paused_at'])
        activity.enrich('codex',line('response_item',{'payload':{'type':'function_call_output','call_id':'q'}},'2026-10-23T10:00:25Z'),[],context)
        activity.enrich('codex',line('event_msg',{'payload':{'type':'task_complete'}},'2026-10-23T10:00:30Z'),[],context)
        clock=context['activity_turns']['t']
        self.assertEqual(clock['ended_at']-clock['started_at']-clock['paused_ms'],10000)
        self.assertNotIn('paused_at',clock)

    def test_reasoning_payload_is_not_exposed(self):
        self.assertEqual(activity.enrich('codex',line('response_item',{'payload':{'type':'reasoning','content':'private'}}),[],{}),[])

    def test_turn_clock_survives_incremental_read_and_rebuild(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'record.jsonl'
            p.write_bytes(line('event_msg',{'payload':{'type':'task_started','turn_id':'t1'}}))
            entry=Transcript(p,'codex').refresh()
            started=entry.context['activity_turns']['t1']['started_at']
            with p.open('ab') as f:f.write(line('event_msg',{'payload':{'type':'task_complete','turn_id':'t1'}},'2026-10-23T10:00:12Z'))
            entry.refresh()
            self.assertEqual(entry.context['activity_turns']['t1']['ended_at']-started,12000)
            self.assertEqual(entry.context,Transcript(p,'codex').refresh().context)

    def test_edit_requires_success_and_preserves_fragment_scope(self):
        context={}
        m={'role':'tool','text':'Edit：a.py','time':'now'}
        source=line('assistant',{'message':{'content':[{'type':'tool_use','name':'Edit','id':'call1','input':{'file_path':'a.py','old_string':'old','new_string':'new'}}]}})
        activity.enrich('claude',source,[m],context);m['id']='call1'
        self.assertNotIn('changes',activity.public_message(m))
        result=line('user',{'message':{'content':[{'type':'tool_result','tool_use_id':'call1','content':'ok'}]}})
        activity.enrich('claude',result,[],context)
        public=activity.public_message(m)
        self.assertNotIn('_changes',public)
        self.assertEqual(public['changes'][0]['scope'],'fragment')
        diff=activity.diff_page([m],public['changes'][0]['ref'])
        self.assertIn('-old\n+new',diff['hunks'][0])
        self.assertEqual(diff['added'],1)
        self.assertEqual(diff['removed'],1)

    def test_failed_edit_cannot_be_read_as_diff(self):
        context={};m={'role':'tool','text':'Edit：a.py'}
        activity.enrich('claude',line('assistant',{'message':{'content':[{'type':'tool_use','name':'Edit','id':'x','input':{'file_path':'a.py','old_string':'x','new_string':'y'}}]}}),[m],context)
        ref=m['_changes'][0]['ref']
        activity.enrich('claude',line('user',{'message':{'content':[{'type':'tool_result','tool_use_id':'x','is_error':True,'content':'failed'}]}}),[],context)
        self.assertIsNone(activity.diff_page([m],ref))

    def test_same_path_different_operations_have_different_refs(self):
        results=[]
        for ident in ('first','second'):
            msgs=activity.enrich('codex',line('event_msg',{'payload':{'type':'item_completed','item':{'type':'FileChange','id':ident,'status':'completed','changes':[{'path':'中文.py','diff':'@@ -1 +1 @@\n-old\n+new'}]}}}),[],{})
            results.append(activity.public_message(msgs[0])['changes'][0]['ref'])
        self.assertNotEqual(*results)
        self.assertIsNone(activity.diff_page([],results[0]))

    def test_hunk_pagination_and_no_path_access(self):
        c=activity.change('C:/secret','\n'.join(f'@@ -{i} +{i} @@\n-a\n+b' for i in range(1,11)))
        c['ref']='ref';m={'id':'m','tool_status':'completed','_changes':[c]}
        self.assertEqual(len(activity.diff_page([m],'ref')['hunks']),8)
        self.assertEqual(activity.diff_page([m],'ref')['next'],8)
        self.assertEqual(len(activity.diff_page([m],'ref',8)['hunks']),2)
        self.assertIsNone(activity.diff_page([m],'C:/secret'))


if __name__=='__main__':unittest.main()
