import base64, hashlib, hmac, json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import deepseek_control as d
import chat_projects

SID='session-11111111-1111-1111-1111-111111111111'
CALLC='call_00_T2mUOm814XYOd5vrQax43388'
QUESTION=[{'id':'q','options':[{'label':'yes'},{'label':'no'}]}]

class AdapterTests(unittest.TestCase):
    def test_create_uses_workspace_identity_not_cwd_and_confirms_membership(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace={'id':'workspace-test','path':folder,'name':'测试'}
            self.client.call.return_value={'sessionId':SID}
            with patch.object(d,'workspaces',return_value=[workspace]),patch.object(d,'workspace_members',return_value={SID:workspace}):
                body={'request_id':'a'*32,'folder':folder}
                self.assertEqual(self.bridge.create(body)['id'],SID)
                self.bridge.create(body)
            self.client.call.assert_called_once()
            request=self.client.call.call_args.args[1]['request']
            self.assertEqual(request['workspaceId'],'workspace-test');self.assertNotIn('cwd',request)

    def test_create_refuses_missing_workspace_before_host_call(self):
        with patch.object(d,'workspaces',return_value=[]),self.assertRaises(d.DeepSeekError):
            self.bridge.create({'request_id':'a'*32,'folder':self.tmp.name})
        self.client.call.assert_not_called()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.client=Mock();self.bridge=d.Bridge(self.client,self.tmp.name,links=d.ParentLinks(Path(self.tmp.name)/'links.jsonl'))
    def test_cookie_only_approved_key_and_short_lifetime(self):
        secret=bytes(range(32));p=Path(self.tmp.name)
        (p/'.credentials.yaml').write_text(json.dumps({'records':{'unrelated':{'secret':'DO_NOT_USE'},'client-connection/browser-session':{'kind':'grant','payload':{'version':1,'secret':d.b64(secret)}}}}))
        cookie=d.credential_cookie(p,1234);name,value=cookie.split('=',1);version,body,signature=value.split('.')
        self.assertEqual(name,'dsh-auth-'+d.b64(hashlib.sha256(b'127.0.0.1:1234').digest()))
        self.assertEqual(signature,d.b64(hmac.new(secret,body.encode(),hashlib.sha256).digest()))
        payload=json.loads(base64.urlsafe_b64decode(body+'='*(-len(body)%4)))
        self.assertLessEqual(payload['expiresAt']-payload['issuedAt'],601000)
    def test_bad_credential_does_not_expose_contents(self):
        p=Path(self.tmp.name);(p/'.credentials.yaml').write_text('secret: SECRET_SENTINEL')
        with self.assertRaises(d.DeepSeekError) as error:d.credential_cookie(p,1)
        self.assertNotIn('SECRET_SENTINEL',str(error.exception))
    def test_public_messages_show_visible_thinking_without_provider_metadata(self):
        records=[{'event':{'type':'assistant/message','seq':9,'time':0,'data':{'message':{'content':[{'type':'reasoning','text':'visible thinking','signature':'secret signature'},{'type':'text','text':'public'},{'type':'tool-call','arguments':'secret tool'}],'source':{'signature':'secret'}}}}}]
        rows=d.public_messages(records);text=json.dumps(rows)
        self.assertIn('public',text);self.assertIn('visible thinking',text);self.assertTrue(rows[0]['thinking']);self.assertNotIn('secret',text)
    def test_exact_once_and_conflicting_id(self):
        operation=Mock(return_value={'accepted':True});rid='a'*32
        self.bridge.once(rid,SID,{'text':'a'},operation);self.bridge.once(rid,SID,{'text':'a'},operation)
        operation.assert_called_once()
        with self.assertRaises(d.DeepSeekError):self.bridge.once(rid,SID,{'text':'b'},operation)
    def test_timeout_is_never_replayed(self):
        operation=Mock(side_effect=d.DeepSeekError('timeout',503));rid='b'*32
        for _ in range(2):
            with self.assertRaises(d.DeepSeekError):self.bridge.once(rid,SID,{},operation)
        operation.assert_called_once()
        with patch.object(self.bridge,'records',side_effect=d.DeepSeekError('offline',503)):
            self.assertEqual(self.bridge.receipt(rid)['state'],'unconfirmed')
    def test_receipt_matches_id_not_same_text(self):
        rid='c'*32
        with self.assertRaises(d.DeepSeekError):self.bridge.once(rid,SID,{},Mock(side_effect=d.DeepSeekError('timeout',503)))
        page={'records':[{'event':{'type':'user/message','data':{'source':{'rpcId':'other'},'content':[{'text':'same'}]}}}]}
        with patch.object(self.bridge,'records',return_value=(page,{'values':{}})):
            self.assertEqual(self.bridge.receipt(rid)['state'],'unconfirmed')
            page['records'][0]['event']['data']['source']['rpcId']=rid
            self.assertEqual(self.bridge.receipt(rid)['state'],'accepted')
    def test_approval_is_bound_to_session_event_and_connection(self):
        events=self.bridge.events;events.frame({'type':'ready','clientId':'client'})
        events.frame({'type':'waterfall','eventId':'event','agentId':SID,'event':'approval/request','request':{'toolName':'pwsh'}})
        with self.assertRaises(d.DeepSeekError):events.answer('other','event','allowed-once','approval/request')
        self.client.call.assert_not_called()
        result=events.answer(SID,'event','allowed-once','approval/request');self.assertTrue(result['submitted']);self.assertNotIn('accepted',result)
        again=events.answer(SID,'event','allowed-once','approval/request');self.assertTrue(again['already'])
    def answered_page(self,call=CALLC):
        return {'records':[{'event':{'type':'tool/result','seq':9,'time':0,'data':{'message':{'toolCallId':call,'isError':False,'content':[]}}}}],'hasMore':False}
    def test_an_answer_uses_the_event_now_waiting_for_the_same_call(self):
        events=self.bridge.events;events.frame({'type':'ready','clientId':'client'})
        # the host sends user questions with wait.callId; this one came again with a new eventId
        events.frame({'type':'waterfall','eventId':'new','agentId':SID,'event':'user-questions/request',
                      'request':{'questions':QUESTION,'wait':{'callId':CALLC}}})
        result=self.bridge.answer({'id':SID,'event_id':'old','call_id':CALLC,'answers':[{'id':'q','selected':['yes']}]})
        self.assertTrue(result['submitted'])
        self.assertEqual(self.client.call.call_args.args[1]['eventId'],'new')
        self.assertEqual(events.for_session(SID),[])
    def test_an_answer_already_in_the_record_is_not_sent_again(self):
        self.bridge.events.frame({'type':'ready','clientId':'client'})
        with patch.object(self.bridge,'records',return_value=(self.answered_page(),{})):
            result=self.bridge.answer({'id':SID,'event_id':'old','call_id':CALLC,'answers':[{'id':'q','selected':['yes']}]})
        self.assertEqual((result['accepted'],result['already']),(True,True))
        self.assertIn('已经答过了',result['text'])
        self.client.call.assert_not_called()
    def test_the_state_route_also_reports_an_answer_in_the_record(self):
        self.bridge.events.frame({'type':'ready','clientId':'client'})
        with patch.object(self.bridge,'state',return_value={'questions':[]}),patch.object(self.bridge,'records',return_value=(self.answered_page(),{})):
            result=self.bridge.answer({'id':SID,'call_id':CALLC,'answers':[{'id':'q','selected':['yes']}]})
        self.assertTrue(result['already']);self.client.call.assert_not_called()
    def test_a_refused_second_answer_in_the_old_state_route_becomes_already(self):
        self.bridge.events.frame({'type':'ready','clientId':'client'})
        self.client.call.side_effect=d.DeepSeekError('DeepSeek 未接受此操作；请刷新状态后核对',409)
        with patch.object(self.bridge,'state',return_value={'questions':[{'callId':CALLC,'questions':QUESTION}]}),patch.object(self.bridge,'records',return_value=(self.answered_page(),{})):
            result=self.bridge.answer({'id':SID,'call_id':CALLC,'answers':[{'id':'q','selected':['yes']}]})
        self.assertEqual((result['accepted'],result['already']),(True,True))
    def test_an_answer_that_is_neither_waiting_nor_recorded_is_refused_with_the_new_words(self):
        self.bridge.events.frame({'type':'ready','clientId':'client'})
        with patch.object(self.bridge,'records',return_value=({'records':[],'hasMore':False},{})):
            with self.assertRaises(d.DeepSeekError) as error:
                self.bridge.answer({'id':SID,'event_id':'old','call_id':CALLC,'answers':[{'id':'q','selected':['yes']}]})
        self.assertEqual(error.exception.status,409)
        self.assertEqual(str(error.exception),'这个问题现在不在等回答了，请刷新后再看')
    def test_an_answer_is_written_to_the_day_log_without_its_text(self):
        lines=[];self.bridge.log=lines.append
        events=self.bridge.events;events.frame({'type':'ready','clientId':'client'})
        events.frame({'type':'waterfall','eventId':'event','agentId':SID,'event':'user-questions/request',
                      'request':{'questions':QUESTION,'wait':{'callId':CALLC}}})
        with patch.object(self.bridge,'find',return_value={'id':SID,'title':'灵动岛'}):
            self.bridge.answer({'id':SID,'event_id':'event','call_id':CALLC,'answers':[{'id':'q','selected':['yes']}]})
        self.assertEqual(len(lines),1)
        self.assertIn('DeepSeek「灵动岛」',lines[0]);self.assertIn(CALLC[-6:],lines[0]);self.assertIn('已提交',lines[0])
        self.assertNotIn('yes',lines[0])
    def test_a_repeated_approval_is_reported_as_processed(self):
        events=self.bridge.events;events.frame({'type':'ready','clientId':'client'})
        events.frame({'type':'waterfall','eventId':'approve','agentId':SID,'event':'approval/request',
                      'request':{'toolName':'pwsh','callId':CALLC}})
        self.assertTrue(events.answer(SID,'approve','allowed-once','approval/request')['submitted'])
        again=events.answer(SID,'approve','allowed-once','approval/request')
        self.assertTrue(again['already']);self.assertIn('已经处理过了',again['text'])
        self.assertEqual(self.client.call.call_count,1)
    def test_an_approval_whose_call_already_has_a_result_is_processed(self):
        events=self.bridge.events;events.frame({'type':'ready','clientId':'client'})
        events.frame({'type':'waterfall','eventId':'approve','agentId':SID,'event':'approval/request',
                      'request':{'toolName':'pwsh','callId':CALLC}})
        events.frame({'type':'cancel','eventId':'approve'})
        with patch.object(self.bridge,'records',return_value=(self.answered_page(),{})):
            result=events.answer(SID,'approve','allowed-once','approval/request')
        self.assertTrue(result['already']);self.assertIn('已经处理过了',result['text'])
        self.client.call.assert_not_called()
    def test_an_approval_that_vanished_without_a_result_is_refused_with_the_new_words(self):
        events=self.bridge.events;events.frame({'type':'ready','clientId':'client'})
        events.frame({'type':'waterfall','eventId':'approve','agentId':SID,'event':'approval/request',
                      'request':{'toolName':'pwsh','callId':CALLC}})
        events.frame({'type':'cancel','eventId':'approve'})
        with patch.object(self.bridge,'records',return_value=({'records':[],'hasMore':False},{})):
            with self.assertRaises(d.DeepSeekError) as error:events.answer(SID,'approve','allowed-once','approval/request')
        self.assertEqual(error.exception.status,409)
        self.assertEqual(str(error.exception),'这一步现在不在等处理了，请刷新后再看')
    def test_cancel_removes_approval(self):
        events=self.bridge.events;events.frame({'type':'ready','clientId':'client'})
        events.frame({'type':'waterfall','eventId':'event','agentId':SID,'event':'approval/request','request':{}})
        events.frame({'type':'cancel','eventId':'event'});self.assertEqual(events.for_session(SID),[])
    def test_unknown_event_delegates_never_grants(self):
        events=self.bridge.events;events.frame({'type':'ready','clientId':'client'})
        events.frame({'type':'waterfall','eventId':'event','agentId':SID,'event':'unknown','request':{}})
        self.assertEqual(self.client.call.call_args.args[1]['outcome'],{'kind':'next'})
    def test_answer_validation(self):
        q=[{'id':'q','options':[{'label':'yes'},{'label':'no'}]}]
        d.validate_answers(q,[{'id':'q','selected':['yes']}])
        for a in ([],[{'id':'other','selected':['yes']}],[{'id':'q','selected':['yes','no']}],[{'id':'q','selected':['bad']}],[{'id':'q','selected':[]}]):
            with self.assertRaises(d.DeepSeekError):d.validate_answers(q,a)
    def test_question_event_without_call_id(self):
        events=self.bridge.events;events.frame({'type':'ready','clientId':'client'})
        events.frame({'type':'waterfall','eventId':'event','agentId':SID,'event':'user-questions/request','request':{'questions':[{'id':'q','options':[{'label':'yes'}]}]}})
        result=self.bridge.answer({'id':SID,'event_id':'event','answers':[{'id':'q','selected':['yes']}]})
        self.assertTrue(result['submitted'])
    def test_stop_does_not_cancel_a_different_turn(self):
        with patch.object(self.bridge,'state',return_value={'turn_id':'2'}):
            with self.assertRaises(d.DeepSeekError):self.bridge.stop(SID,'1')
        self.client.call.assert_not_called()
    def test_runtime_context_is_not_a_user_message(self):
        record={'event':{'type':'user/message','seq':1,'data':{'source':{'kind':'runtime-context'},'content':[{'type':'text','text':'private context'}]}}}
        self.assertEqual(d.public_messages([record]),[])
    def test_legacy_route_never_touches_claude_for_deepseek(self):
        import remote
        from types import SimpleNamespace
        for path in ('/api/chat/send','/api/chat/enter','/api/chat/check'):
            handler=object.__new__(remote.Handler);handler.path=path;handler._authorized=lambda:True;handler._body=lambda:{'app':'deepseek','id':SID}
            handler.server=SimpleNamespace(machine={'voice':False},desktop=Mock());handler._json=Mock()
            handler.do_POST();self.assertEqual(handler._json.call_args.args[1],400);handler.server.desktop.assert_not_called()
        # a new conversation goes to the shared new-conversation flow, which drives DeepSeek through its interface (10-20)
        handler=object.__new__(remote.Handler);handler.path='/api/chat/new';handler._authorized=lambda:True;handler._body=lambda:{'app':'deepseek','request_id':'r'}
        handler.server=SimpleNamespace(machine={'voice':False},desktop=Mock(),new_chats=Mock());handler._json=Mock()
        handler.server.new_chats.submit.return_value={'state':'creating'}
        handler.do_POST();handler.server.new_chats.submit.assert_called_once_with({'app':'deepseek','request_id':'r'});handler.server.desktop.assert_not_called()
    def test_image_cross_session_rejected_before_prompt(self):
        self.bridge.uploads=Mock();self.bridge.uploads.attachment.return_value={'app':'claude'}
        with patch.object(self.bridge,'find',return_value={}):
            with self.assertRaises(d.DeepSeekError):self.bridge.send({'id':SID,'text':'a','attachments':['x'],'request_id':'a'*32})
        self.client.call.assert_not_called()
    def test_sidebar_groups_by_full_folder(self):
        rows=[dict(app='deepseek',id=SID,title='one',cwd='D:/a/shared',folder='shared',updated=1),dict(app='deepseek',id='two',title='two',cwd='D:/b/shared',folder='shared',updated=0)]
        with patch.object(chat_projects,'codex_layout',return_value=({}, {}, set(), set())):
            tree=chat_projects.tree(rows,lambda _: 'idle')
        self.assertEqual(len(tree['apps'][2]['projects']),3)
    def test_subagent_children_come_from_the_host_session_list(self):
        child='22222222-2222-2222-2222-222222222222'
        self.client.call.return_value={'items':[
            {'sessionId':child,'parentSessionId':SID,'running':True,'updatedAt':5,'projections':{'values':{'title':'child prompt'}}},
            {'sessionId':'33333333-3333-3333-3333-333333333333','parentSessionId':'other','running':False}]}
        self.assertEqual(self.bridge.subagents(SID),[{'id':child,'title':'child prompt','running':True,'updated':5}])
    def test_subagent_catalog_accepts_the_projection_id_key(self):
        rows=d.subagent_catalog({'subagentCatalog':[{'id':'child','label':'答 quote-0001 至 0010','mode':'continuable'}]})
        self.assertEqual([(r['childId'],r['label']) for r in rows],[('child','答 quote-0001 至 0010')])
    def test_subagent_labels_join_the_live_child_status(self):
        child='22222222-2222-2222-2222-222222222222'
        values={'subagentCatalog':[{'childId':child,'label':'答 quote-0001 至 0010','mode':'continuable','createdAt':7}]}
        self.client.call.return_value={'items':[{'sessionId':child,'parentSessionId':SID,'running':False,'updatedAt':9,
            'projections':{'values':{'title':'system prompt'}}}]}
        rows=self.bridge._subagents(SID,values)
        self.assertEqual([(r['label'],r['running'],r['created']) for r in rows],[('答 quote-0001 至 0010',False,7)])
    def test_conversation_marks_a_finished_child_on_its_card(self):
        child='22222222-2222-2222-2222-222222222222'
        page={'records':[{'event':{'seq':4,'type':'subagent/catalog','time':0,
            'data':{'childId':child,'label':'答 quote-0001 至 0010','mode':'continuable'}}}],'hasMore':False}
        self.client.call.side_effect=lambda method,args:{
            'session/list':{'items':[{'sessionId':child,'parentSessionId':SID,'running':False,'updatedAt':9,
                'projections':{'values':{'title':'child'}}}]},
            'session/projections':{'kind':'sequenced','asOfSeq':4,'values':{'title':'parent','workingDirectory':'D:/p',
                'subagentCatalog':[{'childId':child,'label':'答 quote-0001 至 0010','mode':'continuable','createdAt':7}]}},
            'session/page':page}[method]
        out=self.bridge.conversation(SID)
        self.assertEqual(out['messages'][0]['role'],'subagent');self.assertEqual(out['messages'][0]['status'],'done')
        self.assertEqual(out['subagents'][0]['label'],'答 quote-0001 至 0010')
    def test_conversation_around_a_row_without_a_seq_reads_the_latest_page(self):
        asked=[]
        def call(method,args):
            if method=='session/page':asked.append(args['request'].get('beforeSeq'))
            return {'session/list':{'items':[]},
                'session/projections':{'kind':'sequenced','asOfSeq':20,'values':{'title':'parent','workingDirectory':'D:/p'}},
                'session/page':{'records':[],'hasMore':False}}[method]
        self.client.call.side_effect=call
        for around in ('tool:call_abc','subagent:22222222-2222-2222-2222-222222222222','12:thinking','12'):
            out=self.bridge.conversation(SID,around=around)
            self.assertEqual(out['has_newer'],around[0].isdigit())
        self.assertEqual(asked,[None,None,13,13])
    def test_workspaces_are_the_sidebar_table_newest_first(self):
        home=Path(self.tmp.name);(home/'storages').mkdir(exist_ok=True)
        (home/'storages'/'workspace.json').write_text(json.dumps({'tables':{'workspaces':{
            'a':{'path':'D:/a','title':'alpha','sessionIds':['s1','s2'],'updatedAt':'2026-10-19T06:31:45.494Z'},
            'b':{'path':'D:/b','title':'beta','sessionIds':[],'updatedAt':'2026-10-19T08:00:00.000Z'}}}}))
        with patch.object(d,'HOME',home):rows=d.workspaces()
        self.assertEqual([r['name'] for r in rows],['beta','alpha']);self.assertEqual(rows[1]['sessions'],2)
    def test_new_chat_offers_the_client_workspaces(self):
        import new_conversations
        a=Path(self.tmp.name)/'a';b=Path(self.tmp.name)/'b';a.mkdir();b.mkdir()
        home=Path(self.tmp.name)/'home';(home/'storages').mkdir(parents=True)
        (home/'storages'/'workspace.json').write_text(json.dumps({'tables':{'workspaces':{
            'a':{'path':str(a),'title':'alpha','sessionIds':['s'],'updatedAt':'2026-10-19T08:00:00.000Z'},
            'b':{'path':str(b),'title':'beta','sessionIds':[],'updatedAt':'2026-10-19T06:00:00.000Z'}}}}))
        chats=Mock()
        with patch.object(d,'HOME',home):
            items=new_conversations.NewConversations(Mock(),Mock(),Mock(),Mock(),root=str(Path(self.tmp.name)/'state')).folders('deepseek')
        self.assertEqual([v['name'] for v in items],['alpha','beta']);self.assertEqual(items[0]['sources'],['DeepSeek 工作区'])
        chats.assert_not_called()
    def test_archived_sessions_stay_out_of_catalog(self):
        self.client.call.return_value={'items':[{'sessionId':SID,'projections':{'values':{'title':'archived'}}}]}
        with patch.object(d,'workspace_meta',return_value={'archivedSessionIds':[SID]}):
            self.assertEqual(self.bridge.catalog(),[])
    def test_notification_only_once_for_new_pending_and_completion(self):
        import notify
        from types import SimpleNamespace
        # _deepseek now reports a running turn through Notifier._running (the island's "running" event); this fake
        # only needs a stand-in for it, plus the running table the pending/done branches pop from.
        notifier=SimpleNamespace(ended={},since=100,_tell=Mock(),running={},_running=Mock())
        item={'app':'deepseek','id':SID,'status':'running','_running':True,'preview':'done'}
        with patch.object(d,'bridge',return_value=self.bridge):
            notify.Notifier._deepseek(notifier,{},item)
            self.bridge.events.frame({'type':'ready','clientId':'client'})
            self.bridge.events.frame({'type':'waterfall','eventId':'event','agentId':SID,'event':'approval/request','request':{}})
            notify.Notifier._deepseek(notifier,{},item);notify.Notifier._deepseek(notifier,{},item)
            self.assertEqual(notifier._tell.call_count,1)
            self.bridge.events.frame({'type':'cancel','eventId':'event'});item['_running']=False
            page={'records':[{'event':{'type':'turn/end','seq':10,'time':101000,'data':{'reason':{'kind':'completed'}}}}]}
            with patch.object(self.bridge,'records',return_value=(page,{})):
                notify.Notifier._deepseek(notifier,{},item);notify.Notifier._deepseek(notifier,{},item)
            self.assertEqual(notifier._tell.call_count,2)

class PermissionAndQueueTests(unittest.TestCase):
    """10-20: the phone picks the session's permission preset as the desktop's composer does (/permission <preset>, then
    the permissions projection moves), and hands a queued message to the turn or drops it (session/updateQueue)."""
    CATALOG={'options':[{'value':'read-only','name':'Read Only'},{'value':'workspace-write','name':'Workspace Write'},
                        {'value':'danger-full-access','name':'Full access'},{'value':'custom','name':'Custom'},{'value':'team-x','name':'Team X','description':'site preset'}]}
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.preset='workspace-write';self.calls=[]
        def call(method,args):
            self.calls.append((method,args))
            if method=='permissionPresets/catalog':return self.CATALOG
            if method=='session/projections':return {'kind':'sequenced','asOfSeq':1,'values':{'permissions':{'currentValue':self.preset},'inbox':{}}}
            if method=='commands/execute':self.preset=args['line'].split(' ',1)[1];return {'kind':'success'}
            if method=='session/updateQueue':return {'ok':True}
            if method=='session/list':return {'items':[]}
            raise AssertionError(method)
        self.client=Mock();self.client.call.side_effect=call
        self.bridge=d.Bridge(self.client,self.tmp.name,links=d.ParentLinks(Path(self.tmp.name)/'links.jsonl'))
        p=patch.object(self.bridge,'find',return_value={'id':SID,'status':'idle'});p.start();self.addCleanup(p.stop)
    def test_the_catalog_in_the_harness_own_words(self):
        out=self.bridge.permissions(SID)
        self.assertEqual([(o['value'],o['name'],o['confirm']) for o in out['options']],
                         [('read-only','仅可查看',False),('workspace-write','工作区内修改',False),('danger-full-access','完全权限',True),('team-x','Team X',False)])
        self.assertEqual(out['current'],'workspace-write')
    def test_full_access_wants_the_confirmation_and_goes_through_the_command(self):
        with self.assertRaises(d.DeepSeekError):self.bridge.set_permission(SID,'danger-full-access')
        self.assertNotIn('commands/execute',[m for m,_ in self.calls])
        out=self.bridge.set_permission(SID,'danger-full-access',confirmed=True)
        self.assertEqual(out['permission'],'danger-full-access');self.assertIn('完全权限',out['text'])
        self.assertIn(('commands/execute',{'agentId':SID,'line':'/permission danger-full-access','submittedAttachments':[]}),self.calls)
    def test_an_unknown_preset_and_the_current_one_send_nothing(self):
        with self.assertRaises(d.DeepSeekError):self.bridge.set_permission(SID,'custom',confirmed=True)
        self.assertIn('已经是',self.bridge.set_permission(SID,'workspace-write')['text'])
        self.assertNotIn('commands/execute',[m for m,_ in self.calls])
    def test_a_switch_the_session_never_shows_is_not_claimed(self):
        original=self.client.call.side_effect
        def stuck(method,args):
            if method=='commands/execute':return {'kind':'success'}  # accepted, yet the projection never moves
            return original(method,args)
        self.client.call.side_effect=stuck;clock=iter(range(0,1000))
        with patch.object(d.time,'monotonic',side_effect=lambda:next(clock)),patch.object(d.time,'sleep'):
            with self.assertRaises(d.DeepSeekError) as error:self.bridge.set_permission(SID,'read-only')
        self.assertIn('核对',str(error.exception))
    def test_a_queued_message_is_steered_or_removed_by_its_id(self):
        self.assertEqual(self.bridge.queue_action(SID,'d752022a-91d2','steer')['text'],'已立即补充给这一轮')
        self.assertEqual(self.calls[-1],('session/updateQueue',{'request':{'sessionId':SID,'itemId':'d752022a-91d2','action':{'kind':'steer'}}}))
        for item,action in (('x','edit'),('bad id!','remove')):
            with self.assertRaises(d.DeepSeekError):self.bridge.queue_action(SID,item,action)
    def test_queued_messages_are_text_rows_with_their_ids(self):
        inbox={'next-turn':[{'id':'a','content':[{'type':'text','text':'整理成表格'}]},{'id':'b','content':[{'type':'image'}]},{'content':[{'type':'text','text':'no id'}]}],
               'next-step':[{'id':'c','content':[{'type':'text','text':'system note'}]}]}
        self.assertEqual(d.queued_messages(inbox),[{'id':'a','text':'整理成表格'},{'id':'b','text':'（图片 1 张）'}])
        self.assertEqual(d.permission_name('danger-full-access'),'完全权限');self.assertEqual(d.permission_name(''),'')
    def test_the_live_projection_says_current_value_and_no_key_hides_the_control(self):
        # 10-20 live: {permissions: {currentValue}}; the stored cache row says preset; no key: no permission service
        self.assertEqual(d.current_permission({'permissions':{'currentValue':'workspace-write'}}),'workspace-write')
        self.assertEqual(d.current_permission({'permissions':{'preset':'read-only','sandbox':'read-only'}}),'read-only')
        self.assertIsNone(d.current_permission({'title':'x'}))
        self.assertEqual(d.permission_name('custom'),'自定义')
        state=self.bridge.state(SID)
        self.assertEqual((state['permission'],state['permission_name'],state['permission_available']),('workspace-write','工作区内修改',True))

MOTHER='session-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
OTHER='session-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
SCRIPT='session-cccccccc-cccc-cccc-cccc-cccccccccccc'
LOOSE='session-dddddddd-dddd-dddd-dddd-dddddddddddd'

def row(sid,cwd,updated,title='',parent='',subagent=False,running=False,values=None):
    return {'id':sid,'cwd':cwd,'updated':updated,'running':running,'status':'running' if running else 'idle','title':title,
            'values':values or {},'parent':parent,'subagent':subagent}

class FamilyTests(unittest.TestCase):
    """10-20: the list was all one-shot sessions a pipeline started; they fold under the conversation now."""
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'links.jsonl';self.links=d.ParentLinks(self.path)
        self.place={'id':'w1','name':'demo_workspace','path':'D:/work/demo_workspace'}
    def link(self,parent,cwd,at):
        with self.path.open('a',encoding='utf-8') as f:f.write(json.dumps({'parent':parent,'cwd':cwd,'at':at})+'\n')
    def test_workspace_sessions_are_conversations_and_children_fold_under_them(self):
        child='22222222-2222-2222-2222-222222222222'
        values={'subagentCatalog':[{'childId':child,'label':'答 quote-0001 至 0010','mode':'continuable'}]}
        self.link(MOTHER,'G:/runs/harness_calls/k1',1000)
        rows=[row(MOTHER,'D:/work/demo_workspace',500,'# 任务',values=values),
              row(child,'D:/work/demo_workspace',900,'system prompt',parent=MOTHER,subagent=True,running=True),
              row(SCRIPT,'G:\\Runs\\harness_calls\\k1',1500,''),
              row(LOOSE,'C:/Temp/batch_worker_x',2000,'')]
        out=d.organize(rows,{MOTHER:self.place},self.links)
        self.assertEqual([t['id'] for t in out['top']],[MOTHER])
        top=out['top'][0]
        self.assertEqual([(c['id'],c['kind'],c['title']) for c in top['children']],
                         [(SCRIPT,'script','k1'),(child,'subagent','答 quote-0001 至 0010')])
        self.assertEqual(top['updated'],1500)  # a pipeline running under it keeps it near the top
        self.assertEqual(top['workspace'],self.place)
        self.assertEqual([(c['id'],c['parent']) for c in out['ungrouped']],[(LOOSE,'')])
        self.assertEqual(out['index'][SCRIPT]['parent'],MOTHER)
    def test_a_subagent_whose_conversation_is_not_listed_is_left_out(self):
        out=d.organize([row('33333333-3333-3333-3333-333333333333','D:/x',1,parent=OTHER,subagent=True)],{},self.links)
        self.assertEqual((out['top'],out['ungrouped']),([],[]))
    def test_a_nested_child_reaches_the_conversation(self):
        first,second='44444444-4444-4444-4444-444444444444','55555555-5555-5555-5555-555555555555'
        rows=[row(MOTHER,'D:/w',1),row(first,'D:/w',2,parent=MOTHER,subagent=True),row(second,'D:/w',3,parent=first,subagent=True)]
        out=d.organize(rows,{MOTHER:self.place},self.links)
        self.assertEqual({c['id'] for c in out['top'][0]['children']},{first,second})
    def test_no_workspace_table_keeps_the_flat_list(self):
        out=d.organize([row(MOTHER,'D:/a',1),row(SCRIPT,'D:/b',2)],None,self.links)
        self.assertEqual({t['id'] for t in out['top']},{MOTHER,SCRIPT});self.assertEqual(out['ungrouped'],[])
    def test_a_reused_folder_belongs_to_the_newest_line_before_the_session(self):
        self.link(MOTHER,'D:/sidecars/batch_step',1_000_000);self.link(OTHER,'D:/sidecars/batch_step',2_200_000)  # 20 minutes apart
        self.assertEqual(self.links.parent('d:\\sidecars\\batch_step',1_060_000),MOTHER)
        self.assertEqual(self.links.parent('D:/sidecars/batch_step',2_260_000),OTHER)
        self.assertEqual(self.links.parent('D:/sidecars/other',2_260_000),'')
    def test_links_skip_bad_lines_and_wait_for_a_whole_line(self):
        with self.path.open('w',encoding='utf-8') as f:
            f.write('not json\n'+json.dumps({'parent':'session-bad','cwd':'D:/a','at':1})+'\n'+json.dumps({'parent':MOTHER,'cwd':'D:/a'}))
        self.assertEqual(self.links.parent('D:/a',10),'')
        with self.path.open('a',encoding='utf-8') as f:f.write('\n'+json.dumps({'parent':MOTHER,'cwd':'D:/a','at':2})+'\n')
        self.assertEqual(self.links.parent('D:/a',10),MOTHER)
        self.path.write_text(json.dumps({'parent':OTHER,'cwd':'D:/a','at':3})+'\n',encoding='utf-8')  # rewritten shorter
        self.assertEqual(self.links.parent('D:/a',10),OTHER)
    def test_bridge_listing_files_host_rows(self):
        home=Path(self.tmp.name)/'home';(home/'storages').mkdir(parents=True)
        (home/'storages'/'workspace.json').write_text(json.dumps({'global':{'archivedSessionIds':[OTHER]},'tables':{'workspaces':{
            'w1':{'path':'G:/w','title':'w','sessionIds':[MOTHER,OTHER]}}}}))
        client=Mock();client.call.return_value={'items':[
            {'sessionId':MOTHER,'updatedAt':5,'running':False,'cwd':'G:/w','projections':{'values':{'title':'mother'}}},
            {'sessionId':OTHER,'updatedAt':6,'cwd':'G:/w','projections':{'values':{'title':'archived'}}},
            {'sessionId':SCRIPT,'updatedAt':7,'running':True,'cwd':'C:/Temp/run1','projections':{'values':{}}},
            {'sessionId':LOOSE,'updatedAt':8,'blank':True,'cwd':'G:/w'}]}
        self.link(MOTHER,'C:/Temp/run1',6)
        with patch.object(d,'HOME',home):
            bridge=d.Bridge(client,self.tmp.name,links=self.links);top=bridge.catalog()
            self.assertEqual([(t['id'],t['updated'],[c['id'] for c in t['children']]) for t in top],[(MOTHER,7,[SCRIPT])])
            self.assertEqual(bridge.find(SCRIPT)['_running'],True);self.assertNotIn('children',bridge.find(MOTHER))
            self.assertEqual(bridge.ungrouped(),[])
    def test_offline_listing_finds_a_subagent_by_its_conversation_catalog(self):
        home=Path(self.tmp.name)/'home';cache=home/'storages'/'session_projcache'/'sessions';cache.mkdir(parents=True)
        (home/'storages'/'workspace.json').write_text(json.dumps({'tables':{'workspaces':{'w1':{'path':'G:/w','title':'w','sessionIds':[MOTHER]}}}}))
        child='66666666-6666-6666-6666-666666666666'
        def record(name,rows,cwd):(cache/(name+'.json')).write_text(json.dumps({'record':{'identity':{'cwd':cwd},'rows':rows}}),encoding='utf-8')
        record(MOTHER,{'title':{'val':'mother'},'subagentCatalog':{'val':{'head':{'values':[{'childId':child,'label':'判题 1'}]}}},
                       'turnOutline':{'val':{'turns':[{'turn':1,'response':'done'}]}}},'G:/w')
        record(child,{'title':{'val':'prompt'},'subagent':{'val':{'identity':{'label':'判题 1'}}}},'G:/w')
        record(SCRIPT,{'title':{'val':'The following skill bundles'}},'C:/Temp/run2')
        with patch.object(d,'HOME',home),patch.object(d,'parent_links',return_value=self.links):out=d.offline_listing()
        self.assertEqual([(t['id'],t['preview'],[c['title'] for c in t['children']]) for t in out['top']],[(MOTHER,'done',['判题 1'])])
        self.assertEqual([c['id'] for c in out['ungrouped']],[SCRIPT])
    def test_sidebar_files_deepseek_by_workspace_and_strays_under_other(self):
        rows=[dict(app='deepseek',id=MOTHER,title='m',cwd='G:/w',folder='w',updated=3,workspace=self.place),
              dict(app='deepseek',id=SCRIPT,title='k1',cwd='C:/Temp/a',folder='a',updated=2,ungrouped=True),
              dict(app='deepseek',id=LOOSE,title='k2',cwd='C:/Temp/b',folder='b',updated=1,ungrouped=True)]
        with patch.object(chat_projects,'codex_layout',return_value=({}, {}, set(), set())):
            tree=chat_projects.tree(rows,lambda _: 'idle')
        projects=tree['apps'][2]['projects']
        self.assertEqual([(p['name'],p['count'],p['folder']) for p in projects],[('demo_workspace',1,'D:/work/demo_workspace'),(chat_projects.OTHER_NAME,2,'')])

class ListTests(unittest.TestCase):
    def setUp(self):
        import chat_history
        self.h=chat_history;self.history=chat_history.History()
        kids=[{'app':'deepseek','id':f'k{i:03}','title':f'k{i}','kind':'script','parent':MOTHER,'cwd':'','folder':f'f{i}',
               'updated':100-i,'status':'running' if i<2 else 'idle'} for i in range(40)]
        top=[{'app':'deepseek','id':MOTHER,'title':'# 任务','cwd':'G:/w','folder':'w','updated':100,'status':'idle','preview':'p','children':kids}]
        stray=[{'app':'deepseek','id':LOOSE,'title':'batch_worker_x','kind':'script','parent':'','cwd':'','folder':'x','updated':150,'status':'idle'}]
        self.listing={'top':top,'ungrouped':stray,'index':{},'rows':[]}
        for target,value in (('codex_threads',[]),('claude_sessions',[])):
            p=patch.object(self.h.chats,target,return_value=value);p.start();self.addCleanup(p.stop)
        p=patch.object(d,'listing',return_value=self.listing);p.start();self.addCleanup(p.stop)
    def test_rows_carry_a_page_of_children_and_the_bucket_is_one_row(self):
        out=self.history.conversations('deepseek')
        self.assertEqual([v['id'] for v in out['items']],[self.h.UNGROUPED,MOTHER])
        bucket,mother=out['items']
        self.assertTrue(bucket['group']);self.assertEqual((bucket['child_count'],bucket['updated']),(1,150))
        self.assertEqual((len(mother['children']),mother['child_count'],mother['child_running']),(self.h.CHILDREN_SHOWN,40,2))
        self.assertEqual(self.history.conversations('codex')['items'],[])
    def test_children_past_the_first_page_and_unknown_rows(self):
        more=self.history.children('deepseek',MOTHER,self.h.CHILDREN_SHOWN,50)
        self.assertEqual(([v['id'] for v in more['items']][:2],more['total']),(['k030','k031'],40))
        self.assertEqual(self.history.children('deepseek',self.h.UNGROUPED)['items'][0]['id'],LOOSE)
        with self.assertRaises(self.h.HistoryError):self.history.children('deepseek','session-missing')
        with self.assertRaises(self.h.HistoryError):self.history.children('codex',MOTHER)
    def test_a_search_finds_a_child_and_names_its_conversation(self):
        out=self.history.conversations('all',query='f12')
        self.assertEqual([(v['id'],v['parent_title']) for v in out['items']],[('k012','# 任务')])
        self.assertEqual(self.history.conversations('all',query='batch_worker')['items'][0]['kind'],'script')

if __name__=='__main__':unittest.main()
