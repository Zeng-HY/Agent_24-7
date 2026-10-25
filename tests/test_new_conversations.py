import io,json,tempfile,unittest,sys,threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import chats
import codex_control
from codex_control import Bridge
from composer_references import References
from new_conversations import NewConversations,RequestTiming

class NewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.home=self.root/'home';self.home.mkdir()
        self.projects=[self.root/f'project{i}' for i in range(45)]
        for p in self.projects:p.mkdir()
        self.history=SimpleNamespace(catalog=lambda:[{'app':'codex' if i%2 else 'claude','cwd':str(p),'id':str(i),'title':p.name,'updated':i,'folder':p.name} for i,p in enumerate(self.projects)])
        self.refs=References(self.history,self.home);self.bridge=Bridge();self.bridge.data_root=self.root/'images';self.bridge.data_root.mkdir();self.service=NewConversations(self.history,self.refs,self.bridge,Mock(),self.root)
        self.codexhome=patch('new_conversations.chats.CODEX_HOME',self.home/'.codex');self.codexhome.start()
    def tearDown(self):self.bridge.close();self.codexhome.stop();self.temp.cleanup()
    def body(self):return {'request_id':self.service.create_draft()['request_id'],'app':'codex','folder':str(self.projects[0]),'text':'hello','attachments':[],'references':[]}
    def test_all_projects_not_truncated_and_saved_projects(self):
        extra=self.root/'saved';extra.mkdir();self.home.joinpath('.codex').mkdir()
        (self.home/'.codex/.codex-global-state.json').write_text(json.dumps({'local-projects':{'id':{'name':'My Saved','rootPaths':[str(extra)]}},'electron-saved-workspace-roots':[str(extra)]}))
        rows=self.service.folders();self.assertEqual(len(rows),46);self.assertEqual(rows[0]['name'],'My Saved');self.assertTrue(any('Claude 对话' in r['sources'] for r in rows))
    def test_unlisted_or_removed_folder_rejected(self):
        with self.assertRaises(chats.ChatError):self.service.context('codex',str(self.home))
        self.projects[0].rmdir()
        with self.assertRaises(chats.ChatError):self.service.context('codex',str(self.projects[0]))
    def test_skills_before_thread_are_scoped_and_revalidated(self):
        p=self.projects[0]/'.codex/skills/demo/SKILL.md';p.parent.mkdir(parents=True);p.write_text('---\nname: demo\ndescription: draft test\n---\nDemo')
        q={'app':'codex','folder':str(self.projects[0]),'kind':'skill','query':'demo'}
        row=self.service.search(q)['items'][0];self.assertEqual(row['name'],'demo');self.assertNotIn('path',row)
        b=self.body();b['references']=[row]
        p.write_text('---\nname: demo\nuser-invocable: false\n---\nDisabled')
        with self.assertRaises(chats.ChatError):self.service.submit(b)
        self.assertEqual(self.service._read(b['request_id'])[0],'draft')
    def test_new_skill_search_forwards_refresh_and_snapshot(self):
        with patch.object(self.refs,'search',return_value={'items':[]}) as search:
            self.service.search({'app':'codex','folder':str(self.projects[0]),'kind':'skill','fresh':'1','scan_id':'old','offset':'30'})
        self.assertTrue(search.call_args.kwargs['force'])
        self.assertEqual(search.call_args.kwargs['scan_id'],'old')
        self.assertEqual(search.call_args.kwargs['cwd'],str(self.projects[0]))
    def test_duplicate_and_changed_request_never_creates_twice(self):
        body=self.body()
        with patch('new_conversations.threading.Thread') as thread:
            self.service.submit(body);self.service.submit(body);self.assertEqual(thread.call_count,1)
            with self.assertRaises(chats.ChatError):self.service.submit({**body,'text':'different'})
            self.assertEqual(thread.call_count,1)
        self.assertEqual(self.service._read(body['request_id'])[1]['submitted'],{k:body[k] for k in ('app','folder','text','attachments','references')})
    def test_a_picked_codex_model_is_checked_kept_and_used(self):
        # 10-14: the new-conversation sheet could not pick a model or effort
        catalog={'models':[{'id':'gpt-5.5','name':'GPT-5.5','efforts':['low','medium','high'],'default_effort':'medium','service_tiers':[],'images':True},
                           {'id':'gpt-6-astra','name':'GPT-6 Astra','efforts':['medium','high','xhigh'],'default_effort':'high','service_tiers':[{'id':'priority'}],'images':True}]}
        with patch('new_conversations.codex_control.catalog',return_value=catalog):
            self.assertEqual(self.service.options('codex')['models'][1]['efforts'][2],{'id':'xhigh','label':'xhigh'})
            body={**self.body(),'settings':{'model':'gpt-6-astra','effort':'xhigh'}}
            with patch('new_conversations.threading.Thread'):self.service.submit(body)
            data=self.service._read(body['request_id'])[1]
            self.assertEqual((data['settings'],data['submitted']['settings']),({'model':'gpt-6-astra','effort':'xhigh'},)*2)
            for wrong in ({'model':'gpt-9','effort':None},{'model':'gpt-5.5','effort':'xhigh'}):
                with self.assertRaises(chats.ChatError):self.service.submit({**self.body(),'settings':wrong})
            desk={'model':'gpt-6-astra','effort':'xhigh','mode':'default','service_tier':'priority'}
            # no effort picked: the desktop's when the model takes it, else the model's default; a speed it lacks is dropped
            self.assertEqual(NewConversations._picked(desk,{'model':'gpt-5.5','effort':None}),{'model':'gpt-5.5','effort':'medium','mode':'default','service_tier':None})
            self.assertEqual(NewConversations._picked(desk,{'model':'gpt-6-astra','effort':'medium'})['service_tier'],'priority')
    def test_a_picked_claude_model_is_set_before_the_first_message(self):
        claude=Mock();claude.new_options.return_value={'models':[{'id':'Sonnet 5.5','label':'Sonnet 5.5','efforts':[{'id':0,'label':'Low'},{'id':2,'label':'High'}],'default_effort':None}],'note':''}
        self.service.claude=claude
        body={**self.body(),'app':'claude','settings':{'model':'Sonnet 5.5','effort':2}}
        with patch('new_conversations.threading.Thread'),patch('new_conversations.chats.claude_sessions',return_value=[]):self.service.submit(body)
        self.assertEqual(self.service._read(body['request_id'])[1]['settings'],{'model':'Sonnet 5.5','effort':2})
        captured=[]
        def run(fn,*args,timeout=None):captured.append((args,timeout));raise chats.InputNotSubmitted('测试：不真的打开 Claude')
        self.service.desktop=SimpleNamespace(run=run,new_claude=object())
        with patch('new_conversations.chats.require_send_desktop'):self.service._run(body['request_id'])
        args,timeout=captured[0];args[6](1234)  # the prepare step new_claude runs once its page is ready
        claude.apply_new.assert_called_once_with(1234,'Sonnet 5.5',2);self.assertEqual(timeout,70)
        self.assertEqual(self.service._read(body['request_id'])[0],'failed')  # not sent: the phone may send again
    def test_server_restart_never_replays_creation(self):
        body=self.body()
        with patch('new_conversations.threading.Thread'):self.service.submit(body)
        restarted=NewConversations(self.history,self.refs,self.bridge,Mock(),self.root)
        with patch('new_conversations.threading.Thread') as thread:
            self.assertEqual(restarted.status(body['request_id'])['state'],'unconfirmed');restarted.submit(body);thread.assert_not_called()
    def test_receipt_reconciliation(self):
        b=self.body();data={'app':'codex','id':'new-thread','folder':b['folder']}
        self.service._save(b['request_id'],'dispatching',data,{})
        with patch.object(self.bridge,'receipt',return_value={'state':'accepted','result':{'accepted':True}}):
            self.assertEqual(self.service.status(b['request_id'])['state'],'accepted')
    def test_images_owned_by_draft_then_only_one_thread(self):
        from PIL import Image
        buf=io.BytesIO();Image.new('RGB',(4,3),'red').save(buf,'PNG')
        a=self.body();b=self.body();meta=self.service.upload(a['request_id'],'photo.png',buf.getvalue());b['attachments']=[meta['id']]
        with self.assertRaises(Exception):self.service.submit(b)
        data={'id':'real-thread','app':'claude','attachments':[meta['id']]};self.service._bind(a['request_id'],data)
        self.assertEqual(self.bridge.attachment(meta['id'],'real-thread')['app'],'claude')
        with self.assertRaises(chats.ChatError):self.service._bind(b['request_id'],{'id':'other', 'app':'codex','attachments':[meta['id']]})
    def test_upload_closed_after_submit(self):
        b=self.body()
        with patch('new_conversations.threading.Thread'):self.service.submit(b)
        with self.assertRaises(chats.ChatError):self.service.upload(b['request_id'],'x',b'bytes')
    def test_legacy_first_message_receipt_uses_exact_request_id(self):
        p=self.root/'rollout.jsonl';p.write_text(json.dumps({'type':'event_msg','timestamp':'now','payload':{'type':'user_message','client_id':'exact-request','message':'text'}}))
        with patch('codex_control.chats.find',return_value={'path':str(p)}):
            found=self.bridge.delivery_evidence('new-thread')
        self.assertIn('exact-request',found);self.assertNotIn('other-request',found)
    def test_retry_only_known_unsent_and_keeps_existing_id(self):
        b=self.body();data={'submitted':{k:b[k] for k in ('app','folder','text','attachments','references')},'app':b['app'],'folder':b['folder'],'references':[],'id':'already-created'}
        self.service._save(b['request_id'],'unconfirmed',data,{'not_submitted':False})
        with self.assertRaises(chats.ChatError):self.service.retry(b['request_id'])
        self.service._save(b['request_id'],'failed',data,{'not_submitted':True})
        with patch('new_conversations.threading.Thread') as thread:
            self.assertEqual(self.service.retry(b['request_id'])['id'],'already-created');self.assertEqual(thread.call_count,1)

    def test_timing_monotonic_stages_survive_restart(self):
        b=self.body();rid=b['request_id'];data={'app':'codex','folder':b['folder']}
        self.service._save(rid,'creating',data,{})
        with patch('new_conversations.time.perf_counter',return_value=10) as clock:
            trace=RequestTiming(self.service,rid,data);self.service.traces[rid]=trace;self.service.active.add(rid)
            clock.return_value=10.2;trace.phase('create','创建')
            clock.return_value=10.7;trace.finish()
        self.service._save(rid,'accepted',data,{'message':'done'})
        restarted=NewConversations(self.history,self.refs,self.bridge,Mock(),self.root)
        timing=restarted.status(rid)['timing']
        self.assertEqual(timing['total_ms'],700);self.assertEqual([s['ms'] for s in timing['stages']],[200,500])
        self.assertIsNone(timing['active']);self.assertTrue(timing['complete'])

    def test_client_timing_does_not_overwrite_submission_or_store_content(self):
        b=self.body();rid=b['request_id']
        with patch('new_conversations.threading.Thread'):self.service.submit(b)
        before=self.service._read(rid)
        self.service.client_timing({'request_id':rid,'timing':{'observed_ms':1200,'submit_roundtrip_ms':float('nan'),'text':'private','draft_ms':-1,'backgrounded':True}})
        self.assertEqual(self.service._read(rid),before)
        with self.service._db() as con:value=json.loads(con.execute('select data from client_timings where request_id=?',(rid,)).fetchone()[0])
        self.assertEqual(value,{'observed_ms':1200,'backgrounded':True})

    def test_codex_worker_timing_does_not_duplicate_send(self):
        b=self.body();rid=b['request_id']
        with patch('new_conversations.threading.Thread'):self.service.submit(b)
        def create(request,data):data.update(id='new-thread',title='hello')
        def send(body,timing=None):
            timing('send_ack','回执');return {'accepted':True}
        pipe=Mock();pipe.snapshot.return_value=('owner',{'id':'new-thread'})
        with patch('new_conversations.chats.require_send_desktop'),patch('new_conversations.os.startfile'),patch.object(self.service,'_empty_codex',side_effect=create),patch.object(self.bridge,'_pipe',return_value=pipe),patch('new_conversations.codex_control.selected_settings',return_value={'model':'test','effort':'medium','service_tier':None}),patch('new_conversations.codex_control.catalog',return_value={'models':[]}),patch.object(self.bridge,'send',side_effect=send) as sending:
            self.service._run(rid);self.service.submit(b);sending.assert_called_once()
        result=self.service.status(rid)
        self.assertEqual(result['state'],'accepted');self.assertTrue(result['timing']['complete'])
        self.assertIn('desktop_owner',[s['name'] for s in result['timing']['stages']])

    def _takeover(self,ready_at):
        """Run one Codex creation whose desktop takes ready_at (fake) seconds to pick the conversation up."""
        b=self.body();rid=b['request_id'];clock=[0.0];logged=[]
        with patch('new_conversations.threading.Thread'):self.service.submit(b)
        def create(request,data):data.update(id='new-thread',title='hello')
        def snapshot(tid,timeout,timing=None):
            if clock[0]<ready_at:raise RuntimeError('no-client-found')
            return 'owner',{'id':'new-thread'}
        def sleep(seconds):clock[0]+=seconds
        pipe=Mock();pipe.snapshot.side_effect=snapshot;self.service.desktop.log=logged.append
        with patch('new_conversations.chats.require_send_desktop'),patch('new_conversations.os.startfile') as opened,patch.object(self.service,'_empty_codex',side_effect=create),\
             patch.object(self.bridge,'_pipe',return_value=pipe),patch('new_conversations.codex_control.selected_settings',return_value={'model':'test','effort':'medium','service_tier':None}),\
             patch('new_conversations.codex_control.catalog',return_value={'models':[]}),patch.object(self.bridge,'send',return_value={'accepted':True}),\
             patch('new_conversations.time.monotonic',side_effect=lambda:clock[0]),patch('new_conversations.time.sleep',side_effect=sleep):
            self.service._run(rid)
        return self.service.status(rid),opened.call_count,logged
    def test_a_slow_desktop_gets_a_minute_and_the_link_again_every_ten_seconds(self):
        # 10-13 the company computer: the desktop took longer than the 25 s there were; 继续发送 opened the link again and went through
        result,opened,logged=self._takeover(ready_at=31)
        self.assertEqual(result['state'],'accepted');self.assertEqual(opened,4)  # at 0, 10, 20 and 30 s
        self.assertTrue(logged and logged[-1].startswith('新建 Codex 对话送达'),logged)
    def test_after_a_minute_without_the_desktop_the_draft_is_kept_to_send_again(self):
        result,opened,logged=self._takeover(ready_at=10**6)
        self.assertEqual(result['state'],'failed');self.assertTrue(result['not_submitted']);self.assertIn('60 秒',result['message'])
        self.assertTrue(logged and logged[-1].startswith('新建 Codex 对话没完成：新对话已创建，桌面端 60 秒内没有接管'),logged)
    def _first_message(self,later,default_model='gpt-6-astra'):
        """One Codex creation: the desktop takes the conversation over with no model yet (10-13, the company computer),
        and every later look at it is `later`. Returns the settings the first message was sent with."""
        b=self.body();rid=b['request_id'];clock=[0.0];looks=[];sent=[]
        with patch('new_conversations.threading.Thread'):self.service.submit(b)
        def create(request,data):data.update(id='new-thread',title='hello',default_effort='medium',default_model=default_model)
        def snapshot(tid,timeout,timing=None):
            looks.append(clock[0]);return 'owner',({'id':'new-thread'} if len(looks)==1 else later)
        def send(body,timing=None):sent.append(body['settings']);return {'accepted':True}
        def sleep(seconds):clock[0]+=seconds
        pipe=Mock();pipe.snapshot.side_effect=snapshot
        catalog={'models':[{'id':'gpt-6-astra','efforts':['low','medium','high'],'default_effort':'medium','service_tiers':[],'images':True}]}
        with patch('new_conversations.chats.require_send_desktop'),patch('new_conversations.os.startfile'),patch.object(self.service,'_empty_codex',side_effect=create),\
             patch.object(self.bridge,'_pipe',return_value=pipe),patch('new_conversations.codex_control.catalog',return_value=catalog),patch.object(self.bridge,'send',side_effect=send),\
             patch('new_conversations.time.monotonic',side_effect=lambda:clock[0]),patch('new_conversations.time.sleep',side_effect=sleep):
            self.service._run(rid)
        self.assertEqual(self.service.status(rid)['state'],'accepted')
        return sent[0],clock[0]
    def test_the_first_message_waits_for_the_desktop_to_set_the_model(self):
        settings,waited=self._first_message({'id':'new-thread','latestModel':'gpt-6-astra','latestReasoningEffort':'high'})
        self.assertEqual(settings,{'model':'gpt-6-astra','effort':'high','mode':'default','service_tier':None});self.assertLess(waited,2)
    def test_a_model_never_set_becomes_the_one_the_conversation_was_made_with(self):
        settings,waited=self._first_message({'id':'new-thread'})
        self.assertEqual(settings,{'model':'gpt-6-astra','effort':'medium','mode':'default','service_tier':None});self.assertGreaterEqual(waited,15)
    def test_a_model_the_desktop_set_is_kept_even_when_unlisted(self):
        settings,_=self._first_message({'id':'new-thread','latestModel':'gpt-7-new'})
        self.assertEqual(settings['model'],'gpt-7-new')  # the send's check then names it; nothing is swapped silently
    def _timed_out(self,shows_up_at,begun=True):
        """10-15 19:09: Codex answered the first message with thread-follower-start-turn-timeout, and the message was in
        the conversation's record 5 s later. Runs one such creation whose message shows up at shows_up_at (fake) seconds;
        begun=False: the send was refused before it began. Returns the status, the fake seconds spent, the log lines and
        how many times the record was searched."""
        b=self.body();rid=b['request_id'];clock=[0.0];logged=[];searched=[]
        with patch('new_conversations.threading.Thread'):self.service.submit(b)
        def create(request,data):data.update(id='new-thread',title='hello')
        def send(body,timing=None):
            if begun:self.bridge._begin(rid,'new-thread',body)
            raise codex_control.ControlError('Codex 未完成操作：thread-follower-start-turn-timeout')
        def in_record(request,tid):
            searched.append(clock[0]);return {'source':'conversation_record','time':'t'} if clock[0]>=shows_up_at else None
        def sleep(seconds):clock[0]+=seconds
        pipe=Mock();pipe.snapshot.return_value=('owner',{'id':'new-thread'});self.service.desktop.log=logged.append
        with patch('new_conversations.chats.require_send_desktop'),patch('new_conversations.os.startfile'),patch.object(self.service,'_empty_codex',side_effect=create),\
             patch.object(self.bridge,'_pipe',return_value=pipe),patch('new_conversations.codex_control.selected_settings',return_value={'model':'test','effort':'medium','service_tier':None}),\
             patch('new_conversations.codex_control.catalog',return_value={'models':[]}),patch.object(self.bridge,'send',side_effect=send),patch.object(self.service,'_in_record',side_effect=in_record),\
             patch('new_conversations.time.monotonic',side_effect=lambda:clock[0]),patch('new_conversations.time.sleep',side_effect=sleep):
            self.service._run(rid)
            return self.service.status(rid),clock[0],logged,searched
    def test_a_first_message_codex_called_timed_out_counts_once_it_shows_up(self):
        result,spent,logged,_=self._timed_out(shows_up_at=5)
        self.assertEqual(result['state'],'accepted');self.assertLess(spent,10)
        self.assertTrue(logged[-1].startswith('新建 Codex 对话送达（Codex 先回了'),logged)
        self.assertEqual(self.bridge.receipt('new-thread',result['request_id'])['state'],'accepted')  # the ledger agrees
    def test_a_first_message_that_never_shows_up_stays_unconfirmed_and_counts_once_found(self):
        result,spent,logged,_=self._timed_out(shows_up_at=10**6)
        self.assertEqual(result['state'],'unconfirmed');self.assertFalse(result['not_submitted']);self.assertGreaterEqual(spent,30)
        self.assertTrue(logged[-1].startswith('新建 Codex 对话没完成'),logged)
        # 核对结果 later: before 10-16 an unconfirmed Codex request was never looked at again
        with patch.object(self.service,'_in_record',return_value={'source':'conversation_record','time':'t'}):
            self.assertEqual(self.service.status(result['request_id'])['state'],'accepted')
    def test_a_send_refused_before_it_began_fails_at_once(self):
        result,spent,_,searched=self._timed_out(shows_up_at=0,begun=False)
        self.assertEqual(result['state'],'failed');self.assertTrue(result['not_submitted']);self.assertLess(spent,1);self.assertEqual(searched,[])
    def test_the_first_message_is_found_at_the_start_of_a_long_record(self):
        # 10-16: the conversation of the 10-15 19:09 request had grown to 12.8 MB, its first message on line 11
        b=self.body();rid=b['request_id'];p=self.root/'rollout.jsonl'
        first={'type':'event_msg','timestamp':'2026-10-15T11:09:32.614Z','payload':{'type':'user_message','client_id':rid,'message':'hello'}}
        filler=json.dumps({'type':'response_item','payload':{'type':'message','content':'x'*(1<<20)}})
        p.write_text('\n'.join([json.dumps(first)]+[filler]*9)+'\n',encoding='utf-8')
        self.service._save(rid,'unconfirmed',{'app':'codex','id':'new-thread','folder':b['folder']},{'message':'Codex 未完成操作：thread-follower-start-turn-timeout','not_submitted':False})
        self.bridge._begin(rid,'new-thread',{'text':'hello'})
        with patch('codex_control.chats.find',return_value={'path':str(p)}):
            self.assertNotIn(rid,self.bridge.delivery_evidence('new-thread'))  # past the receipt's last 8 MB
            self.assertEqual(self.service.status(rid)['state'],'accepted')
            self.assertEqual(self.bridge.receipt('new-thread',rid)['state'],'accepted')
    def test_a_record_without_the_message_is_not_read_again_until_it_changes(self):
        b=self.body();rid=b['request_id'];p=self.root/'rollout.jsonl'
        p.write_text(json.dumps({'type':'event_msg','payload':{'type':'user_message','client_id':'someone-else','message':'hi'}})+'\n',encoding='utf-8')
        with patch('codex_control.chats.find',return_value={'path':str(p)}),patch('builtins.open',wraps=open) as opened:
            self.assertIsNone(self.service._in_record(rid,'new-thread'));self.assertIsNone(self.service._in_record(rid,'new-thread'))
            self.assertEqual(sum(1 for c in opened.call_args_list if str(c.args[0])==str(p)),1)
            with p.open('a',encoding='utf-8') as f:f.write(json.dumps({'type':'event_msg','payload':{'type':'user_message','client_id':rid,'message':'hello'}})+'\n')
            self.assertEqual(self.service._in_record(rid,'new-thread')['source'],'conversation_record')
    def test_a_missing_value_never_hides_the_desktops_own(self):
        catalog={'models':[{'id':'gpt-6-astra','efforts':['medium'],'default_effort':'medium','service_tiers':[],'images':True}]}
        state={'id':'t','latestModel':'gpt-6-astra','latestReasoningEffort':'medium'}
        with patch('codex_control.catalog',return_value=catalog):
            self.assertEqual(self.bridge.validate_settings({'effort':'medium','service_tier':None},state,False)['model'],'gpt-6-astra')
            with self.assertRaises(Exception) as refused:self.bridge.validate_settings({'model':None},state,False)
        self.assertIn('没有 所选模型',str(refused.exception))  # 10-13: the refusal now says which of the two
    def test_claude_worker_retains_fast_confirmation_and_timing(self):
        b=self.body();b['app']='claude';rid=b['request_id']
        with patch('new_conversations.threading.Thread'),patch('new_conversations.chats.claude_sessions',return_value=[]):self.service.submit(b)
        def run(fn,folder,text,images,dispatched,unique,timing,timeout):
            timing('claude_open','打开');timing('claude_invoke','发送');dispatched()
        self.service.desktop.run.side_effect=run
        with patch('new_conversations.chats.require_send_desktop'),patch.object(self.service,'_find_claude',return_value={'id':'claude-new','title':'hello'}),patch.object(self.service,'_record_claude'):
            self.service._run(rid)
        result=self.service.status(rid)
        self.assertEqual(result['state'],'accepted');self.assertTrue(result['timing']['complete'])
        self.assertIn('claude_record',[s['name'] for s in result['timing']['stages']])

    def test_worker_failure_keeps_timing_and_no_replay(self):
        b=self.body();rid=b['request_id']
        with patch('new_conversations.threading.Thread'):self.service.submit(b)
        with patch('new_conversations.chats.require_send_desktop',side_effect=chats.InputNotSubmitted('locked')):self.service._run(rid)
        result=self.service.status(rid)
        self.assertEqual(result['state'],'failed');self.assertTrue(result['not_submitted']);self.assertTrue(result['timing']['complete'])
        with patch('new_conversations.threading.Thread') as worker:self.service.submit(b);worker.assert_not_called()

    def test_timing_phase_does_not_fsync_each_stage(self):
        trace=RequestTiming(self.service,'ignored',{})
        with patch.object(self.service,'_save') as save:
            trace.phase('create','创建');trace.phase('handoff','交接');save.assert_not_called()

    def test_unpersisted_request_requires_restore_instead_of_retry(self):
        b=self.body();self.service._save(b['request_id'],'failed',{'app':'codex','folder':b['folder']},{'not_submitted':True,'can_retry':False})
        with patch('new_conversations.threading.Thread') as worker:
            with self.assertRaises(chats.ChatError):self.service.retry(b['request_id'])
            worker.assert_not_called()

    def test_question_reply_is_displayed_as_answer_without_changing_arbitrary_text(self):
        answer='保留原文 <tag> 与数字 123'
        text='<send_user_message_question_reply>'+json.dumps([{'questionItemId':json.dumps(['request_user_input_async','call_id',0]),'answer':answer}])+'</send_user_message_question_reply>'
        self.assertEqual(chats.clean_codex_user(text),answer)
        malformed='<send_user_message_question_reply>not json</send_user_message_question_reply>'
        self.assertEqual(chats.clean_codex_user(malformed),malformed)

if __name__=='__main__':unittest.main()
