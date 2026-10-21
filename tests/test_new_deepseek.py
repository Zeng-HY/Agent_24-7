"""A new DeepSeek conversation from the shared new-conversation sheet (10-20): one request makes the conversation in a
workspace with the model picked and sends its first message; 继续发送 after a failure never makes a second conversation
or sends the first message twice."""
import json,sys,tempfile,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import chats
import deepseek_control
from codex_control import Bridge
from composer_references import References
from new_conversations import NewConversations

CATALOG={'default':{'provider':'deepseek-account','model':'deepseek-flash','reasoningEffort':'high'},'routableProviders':['deepseek-account'],
         'groups':[{'id':'deepseek-account','name':'DeepSeek Account','models':[
                       {'id':'deepseek-flash','name':'DeepSeek-V4.1-Flash','reasoning':{'efforts':[{'id':'off','name':'Off'},{'id':'high','name':'High'}],'defaultEffort':'high'}},
                       {'id':'deepseek-pro','name':'DeepSeek-V4.1-Pro','reasoning':{'efforts':[{'id':'max','name':'Max'}],'defaultEffort':'max'}}]},
                   {'id':'not-routable','name':'Elsewhere','models':[{'id':'x','name':'X'}]}],'failures':[]}


class FakeDeepSeek:
    """DeepSeek's bridge as the flow uses it: models, and create and send through a ledger that runs an id once and
    refuses to repeat one left unconfirmed (deepseek_control.Bridge.once); receipts by id."""
    def __init__(self):
        self.ledger={};self.created=[];self.sent=[];self.down=False;self.send_error=None;self.permission_calls=[];self.permission_error=None
    def permissions(self):
        return {'options':[{'value':preset,'confirm':preset in deepseek_control.RISKY_PERMISSIONS} for preset in deepseek_control.PERMISSIONS]}
    def set_permission(self,sid,preset,confirmed):
        if self.permission_error:raise self.permission_error
        self.permission_calls.append((sid,preset,confirmed))
        return {'accepted':True,'permission':preset}
    def models(self):
        if self.down:raise deepseek_control.DeepSeekError('连接被拒绝')
        return CATALOG
    def receipt(self,rid):
        entry=self.ledger.get(rid);return {'state':entry['state']} if entry else {'state':'unknown'}
    def _once(self,rid,body,operation):
        key=json.dumps(body,sort_keys=True);entry=self.ledger.get(rid)
        if entry:
            if entry['key']!=key:raise deepseek_control.DeepSeekError('请求编号已用于其他内容',409)
            if entry['state']=='accepted':return entry['result']
            raise deepseek_control.DeepSeekError('上次操作结果尚未确认，不会自动重复发送',409)
        self.ledger[rid]={'key':key,'state':'unconfirmed'}
        result=operation();self.ledger[rid].update(state='accepted',result=result);return result
    def create(self,body):
        sid='session-'+str(uuid.uuid5(uuid.NAMESPACE_URL,'agent-remote:'+body['request_id']))
        def made():
            self.created.append(dict(body));return {'accepted':True,'id':sid,'app':'deepseek','title':'新对话','cwd':body['folder'],'folder':Path(body['folder']).name}
        return self._once(body['request_id'],body,made)
    def send(self,body):
        def sent():
            if self.send_error:raise self.send_error
            self.sent.append(dict(body));return {'accepted':True,'text':'已交给 DeepSeek','request_id':body['request_id']}
        return self._once(body['request_id'],body,sent)


class NewDeepSeekTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.home=self.root/'home';self.home.mkdir()
        self.workspace=self.root/'demo_workspace';self.workspace.mkdir();self.other=self.root/'elsewhere';self.other.mkdir()
        self.history=SimpleNamespace(catalog=lambda:[{'app':'codex','cwd':str(self.other),'id':'1','title':'x','updated':1,'folder':'elsewhere'}])
        self.bridge=Bridge();self.bridge.data_root=self.root/'images';self.bridge.data_root.mkdir()
        self.service=NewConversations(self.history,References(self.history,self.home),self.bridge,Mock(),self.root)
        self.ds=FakeDeepSeek()
        self.patches=[patch('deepseek_control.bridge',return_value=self.ds),
                      patch('deepseek_control.workspaces',return_value=[{'id':'workspace-demo','path':str(self.workspace),'name':'demo'}]),
                      patch('new_conversations.chats.CODEX_HOME',self.home/'.codex')]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in self.patches:p.stop()
        self.bridge.close();self.temp.cleanup()
    def submit(self,**extra):
        body={'request_id':self.service.create_draft()['request_id'],'app':'deepseek','folder':str(self.workspace),'text':'你好','attachments':[],'references':[],**extra}
        with patch('new_conversations.threading.Thread'):self.service.submit(body)
        return body['request_id']
    def test_the_sheet_lists_deepseeks_models_with_their_provider_and_steps(self):
        models=self.service.options('deepseek')['models']
        self.assertEqual([m['id'] for m in models],['deepseek-account/deepseek-flash','deepseek-account/deepseek-pro'])  # routable only
        self.assertEqual(models[0]['label'],'DeepSeek-V4.1-Flash');self.assertEqual(models[0]['efforts'],[{'id':'off','label':'关'},{'id':'high','label':'高'}])
        self.assertEqual(models[0]['default_effort'],'high')
        self.ds.down=True;self.assertIn('读不到',self.service.options('deepseek')['note'])
    def test_its_folder_is_one_of_its_workspaces(self):
        self.assertEqual(self.service.context('deepseek',str(self.workspace)),str(self.workspace.resolve()))
        with self.assertRaises(chats.ChatError):self.service.context('deepseek',str(self.other))
    def test_one_request_makes_the_conversation_and_sends_the_first_message(self):
        rid=self.submit(settings={'model':'deepseek-account/deepseek-pro','effort':'max'})
        self.service._run(rid)
        status=self.service.status(rid)
        self.assertEqual((status['state'],status['app']),('accepted','deepseek'))
        self.assertEqual(status['id'],'session-'+str(uuid.uuid5(uuid.NAMESPACE_URL,'agent-remote:'+rid)))
        self.assertEqual(self.ds.created,[{'request_id':rid,'folder':str(self.workspace.resolve()),
                                           'workspace_id':'workspace-demo',
                                           'settings':{'provider':'deepseek-account','model':'deepseek-pro','reasoningEffort':'max'}}])
        self.assertEqual(len(self.ds.sent),1);sent=self.ds.sent[0]
        self.assertEqual((sent['id'],sent['text'],sent['intent']),(status['id'],'你好','steer'))
        self.assertNotEqual(sent['request_id'],rid)  # its own id in DeepSeek's ledger
    def test_files_alone_go_as_paths_in_the_first_message(self):  # 10-20: ＋ → 电脑上的文件 / 手机上的文件
        import io,pc_files
        files=pc_files.Files('k',inbox=self.root/'inbox',registry=self.root/'phone-files.json')
        self.service.references.files=files
        doc=self.workspace/'需求.md';doc.write_text('# 需求',encoding='utf-8')
        sent_up=files.upload('现场照片说明.txt',io.BytesIO(b'abc').read,3,'deepseek','')
        rid=self.submit(text='',references=[files.entry(doc),sent_up])
        self.service._run(rid)
        text=self.ds.sent[0]['text']
        self.assertTrue(text.startswith('请查看附带的文件。\n\n附带的文件（都在这台电脑上，请直接打开）：'),text)
        self.assertIn(f'- {doc}（文本，8 字节）',text);self.assertIn('现场照片说明.txt（文本，3 字节，从手机传来）',text)
        self.assertEqual(files.remove_upload(sent_up['upload']),{'ok':True,'retained':True})  # went with a message: kept
    def test_deepseek_closed_fails_before_anything_and_continuing_sends_once(self):
        self.ds.down=True;rid=self.submit()
        self.service._run(rid)
        status=self.service.status(rid);self.assertEqual(status['state'],'failed');self.assertTrue(status['not_submitted']);self.assertIn('DeepSeek',status['message'])
        self.assertEqual((self.ds.created,self.ds.sent),([],[]))
        self.ds.down=False
        with patch('new_conversations.threading.Thread'):self.service.retry(rid)
        self.service._run(rid)
        self.assertEqual(self.service.status(rid)['state'],'accepted');self.assertEqual((len(self.ds.created),len(self.ds.sent)),(1,1))
    def test_continuing_after_the_conversation_was_made_does_not_make_a_second_one(self):
        rid=self.submit()
        with patch.object(self.service,'_bind',side_effect=[chats.ChatError('图片归属不一致'),None]):
            self.service._run(rid)  # made, then stopped before its first message
            status=self.service.status(rid);self.assertEqual(status['state'],'failed');self.assertTrue(status['not_submitted'])
            first=status['id']
            with patch('new_conversations.threading.Thread'):self.service.retry(rid)
            self.service._run(rid)
        status=self.service.status(rid)
        self.assertEqual((status['state'],status['id']),('accepted',first))
        self.assertEqual((len(self.ds.created),len(self.ds.sent)),(1,1))  # the same conversation, the first message once
    def test_a_first_message_deepseek_may_have_taken_is_not_sent_again(self):
        self.ds.send_error=deepseek_control.DeepSeekError('连接中断');rid=self.submit()
        self.service._run(rid)
        status=self.service.status(rid);self.assertEqual(status['state'],'unconfirmed');self.assertFalse(status.get('not_submitted'))
        with self.assertRaises(chats.ChatError):self.service.retry(rid)  # not offered: it may have arrived
        first=self.service._deepseek_first(rid);self.ds.ledger[first].update(state='accepted',result={'accepted':True})  # it had arrived
        self.assertEqual(self.service.status(rid)['state'],'accepted')
    def test_interrupted_after_making_it_offers_to_continue(self):
        rid=self.submit();_,data,_,_=self.service._read(rid);data['id']='session-x'
        self.service._save(rid,'prepared',data,{'message':'对话已建好，正在发出第一句话…'});self.service.active.discard(rid)  # the service restarted
        status=self.service.status(rid);self.assertEqual(status['state'],'failed');self.assertTrue(status['not_submitted'])
    def test_no_project_and_skills_are_refused(self):
        for extra in ({'projectless':True,'folder':''},{'references':[{'kind':'skill','id':'s1','name':'demo','app':'deepseek'}]}):
            body={'request_id':self.service.create_draft()['request_id'],'app':'deepseek','folder':str(self.workspace),'text':'你好','attachments':[],'references':[],**extra}
            with self.assertRaises(chats.ChatError):self.service.submit(body)
            self.assertEqual(self.service._read(body['request_id'])[0],'draft')
    def test_a_locked_screen_does_not_stop_it(self):
        rid=self.submit()
        with patch('new_conversations.chats.require_send_desktop',side_effect=chats.SendNotSubmitted('屏幕锁着')):self.service._run(rid)
        self.assertEqual(self.service.status(rid)['state'],'accepted')

    def test_permission_is_set_before_first_message_and_persisted_for_retry(self):
        rid=self.submit(permission='workspace-write',permission_confirmed=False)
        original=self.ds.send
        def send(body):
            self.assertEqual(self.ds.permission_calls,[(body['id'],'workspace-write',False)])
            return original(body)
        self.ds.send=send
        self.service._run(rid)
        self.assertEqual(self.service.status(rid)['state'],'accepted')
        self.assertEqual(self.service._read(rid)[1]['permission'],'workspace-write')

    def test_full_access_needs_confirmation_before_creating(self):
        with self.assertRaises(chats.ChatError):self.submit(permission='danger-full-access')
        self.assertEqual(self.ds.created,[])
        rid=self.submit(permission='danger-full-access',permission_confirmed=True)
        self.service._run(rid)
        self.assertEqual(self.ds.permission_calls[0][1:],('danger-full-access',True))

    def test_permission_failure_prevents_first_prompt_and_retry_reuses_session(self):
        rid=self.submit(permission='workspace-write')
        self.ds.permission_error=deepseek_control.DeepSeekError('未确认权限')
        self.service._run(rid)
        self.assertEqual(self.ds.sent,[])
        self.assertTrue(self.service.status(rid)['not_submitted'])
        self.ds.permission_error=None
        with patch('new_conversations.threading.Thread'):self.service.retry(rid)
        self.service._run(rid)
        self.assertEqual(len(self.ds.created),1)
        self.assertEqual(len(self.ds.sent),1)


if __name__=='__main__':unittest.main()
