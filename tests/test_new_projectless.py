"""New conversations in no project (10-12), and the ＋ data the sidebar's projects carry."""
import json,re,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import chats
import chat_projects
import new_conversations
from codex_control import Bridge
from composer_references import References
from new_conversations import NewConversations

# Codex desktop (app.asar, 10-12) counts a conversation as projectless when its working folder matches this.
CODEX_DESKTOP_PROJECTLESS=re.compile(r'^(.*(?:^|[\\/])Documents[\\/]+Codex)[\\/]+(?:\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*|\d{4}-\d{2}-\d{2}[\\/]+[a-z0-9][a-z0-9-]*)[\\/]*$')

class ProjectlessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.home=self.root/'home';self.home.mkdir()
        self.project=self.root/'project';self.project.mkdir()
        self.history=SimpleNamespace(catalog=lambda:[{'app':'codex','cwd':str(self.project),'id':'1','title':'p','updated':1,'folder':'project'}])
        self.refs=References(self.history,self.home);self.bridge=Bridge();self.bridge.data_root=self.root/'images';self.bridge.data_root.mkdir()
        self.service=NewConversations(self.history,self.refs,self.bridge,Mock(),self.root)
        self.patches=[patch('new_conversations.chats.CODEX_HOME',self.home/'.codex'),patch('new_conversations.CODEX_PROJECTLESS',self.home/'Documents'/'Codex')]
        for p in self.patches:p.start()
    def tearDown(self):
        self.bridge.close()
        for p in self.patches:p.stop()
        self.temp.cleanup()
    def body(self,app,**more):return {'request_id':self.service.create_draft()['request_id'],'app':app,'folder':'','text':'hello','attachments':[],'references':[],**more}

    def test_codex_projectless_gets_its_own_folder_codex_desktop_counts_as_projectless(self):
        with patch('new_conversations.threading.Thread'):
            first=self.body('codex',projectless=True);self.service.submit(first)
            second=self.body('codex',projectless=True);self.service.submit(second)
        a=self.service._read(first['request_id'])[1];b=self.service._read(second['request_id'])[1]
        day=self.home/'Documents'/'Codex'/time.strftime('%Y-%m-%d')
        self.assertEqual((a['folder'],b['folder']),(str(day/'new-chat'),str(day/'new-chat-2')))
        self.assertTrue(a['projectless'] and Path(a['folder']).is_dir())
        for folder in (a['folder'],b['folder']):self.assertRegex(folder,CODEX_DESKTOP_PROJECTLESS)
        self.assertEqual(a['submitted'],{**{k:first[k] for k in ('app','folder','text','attachments','references')},'projectless':True})

    def test_claude_projectless_has_no_folder_and_needs_no_known_folder(self):
        with patch('new_conversations.threading.Thread'),patch.object(self.service,'context',side_effect=AssertionError('no folder check')):
            b=self.body('claude',projectless=True);self.service.submit(b)
        data=self.service._read(b['request_id'])[1]
        self.assertEqual((data['folder'],data['projectless']),('',True))

    def test_a_bad_request_leaves_no_folder_behind(self):
        b=self.body('codex',projectless=True,attachments=['x','x'])
        with self.assertRaises(chats.ChatError):self.service.submit(b)
        self.assertFalse((self.home/'Documents').exists())

    def test_ordinary_submission_stored_as_before(self):
        with patch('new_conversations.threading.Thread'):
            b=self.body('codex',folder=str(self.project));self.service.submit(b)
        data=self.service._read(b['request_id'])[1]
        self.assertEqual(data['submitted'],{k:b[k] for k in ('app','folder','text','attachments','references')})
        self.assertFalse(data['projectless'])

    def test_search_without_project_uses_no_folder(self):
        seen={}
        with patch.object(self.service.references,'search',side_effect=lambda *a,**k:seen.update(k) or {'items':[]}):
            self.service.search({'app':'claude','projectless':'1','kind':'skill','query':''})
        self.assertEqual(seen['cwd'],'')

    def test_claude_no_folder_session_found_in_a_scratch_folder(self):
        scratch=r'C:\Users\u\AppData\Roaming\Claude\scratch-workspaces\acc\org\scratch-2026-10-12-0a1b2c'
        transcript=self.root/'t.jsonl';transcript.write_text(json.dumps({'type':'user','message':{'content':'hello'}}),encoding='utf-8')
        sessions=[{'id':'local_new','updated':time.time()*1000,'origin':scratch,'cwd':scratch,'title':'t'},
                  {'id':'local_other','updated':time.time()*1000,'origin':str(self.project),'cwd':str(self.project),'title':'t'}]
        data={'projectless':True,'folder':'','known_ids':[],'started':int(time.time()*1000)-1000,'compiled':'hello'}
        with patch('new_conversations.chats.claude_sessions',return_value=sessions),patch('new_conversations.chats.claude_transcript',return_value=transcript):
            self.assertEqual(self.service._find_claude(data)['id'],'local_new')

    def test_claude_new_session_found_before_its_index_names_the_record(self):
        # 10-12: Claude names the record in its index ~6 s after the record holds the first message
        scratch=r'C:\Users\u\AppData\Roaming\Claude\scratch-workspaces\acc\org\scratch-2026-10-12-0a1b2c'
        projects=self.root/'projects';folder=projects/re.sub(r'[^A-Za-z0-9]','-',scratch);folder.mkdir(parents=True)
        (folder/'cli.jsonl').write_text(json.dumps({'type':'user','message':{'content':'hello'}}),encoding='utf-8')
        sessions=[{'id':'local_new','updated':time.time()*1000,'origin':scratch,'cwd':scratch,'title':'t','cli':None}]
        data={'projectless':True,'folder':'','known_ids':[],'started':int(time.time()*1000)-1000,'compiled':'hello'}
        with patch('new_conversations.chats.claude_sessions',return_value=sessions),patch('new_conversations.chats.CLAUDE_PROJECTS',projects):
            self.assertEqual(self.service._find_claude(data)['id'],'local_new')
            self.assertIsNone(self.service._find_claude({**data,'compiled':'别的话'}))
            sessions[0]['updated']=time.time()*1000+120000  # the conversation is new, but the record was made before the request
            self.assertIsNone(self.service._find_claude({**data,'started':int(time.time()*1000)+60000}))

class SidebarPlusTests(unittest.TestCase):
    def test_projects_carry_where_their_plus_starts_and_other_is_always_there(self):
        layout=({'p1':{'name':'示例项目','roots':['D:\\Projects\\示例项目']}},{'t1':'p1'},set(),set())
        catalog=[{'app':'codex','id':'t1','title':'a','cwd':'D:\\Projects\\示例项目','updated':2},
                 {'app':'claude','id':'c1','title':'b','cwd':'D:\\x\\repo','origin':'D:\\x\\repo','updated':3}]
        with patch('chat_projects.codex_layout',return_value=layout),patch('chat_projects.git_name',return_value=''):
            tree=chat_projects.tree(catalog,lambda item:'idle')
        codex,claude=tree['apps'][:2]
        self.assertEqual(tree['apps'][2]['app'],'deepseek')
        self.assertEqual([(p['name'],p['folder'],p['projectless']) for p in codex['projects']],[('示例项目','D:\\Projects\\示例项目',False),('其他对话','',True)])
        self.assertEqual([(p['name'],p['folder'],p['projectless']) for p in claude['projects']],[('repo','D:\\x\\repo',False),('其他对话','',True)])
        self.assertEqual(codex['projects'][-1]['count'],0)

if __name__=='__main__':unittest.main()
