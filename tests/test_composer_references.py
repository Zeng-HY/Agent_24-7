import json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import chats
from composer_references import References,metadata
from codex_control import Bridge

class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name);self.cwd=self.home/'project';self.cwd.mkdir()
        self.path=self.home/'.codex/skills/clear/SKILL.md';self.path.parent.mkdir(parents=True);self.path.write_text('---\nname: clear-chinese\ndescription: >-\n  Write Chinese clearly\n  and review translation.\n---\nRead this skill.',encoding='utf-8')
        self.target={'app':'codex','id':'target','title':'当前','cwd':str(self.cwd)}
        self.source={'app':'codex','id':'other','title':'同名对话','folder':'source','path':str(self.home/'rollout.jsonl'),'updated':1000}
        Path(self.source['path']).write_text('',encoding='utf-8')
        self.history=SimpleNamespace(catalog=lambda:[self.target,self.source],conversation=lambda *a:{'messages':[{'role':'user','text':'source user'},{'role':'tool','text':'PRIVATE TOOL'},{'role':'assistant','text':'PUBLIC ANSWER'}]})
        self.refs=References(self.history,self.home);self.find=patch('composer_references.chats.find',side_effect=lambda app,tid: self.target if tid=='target' else self.source);self.find.start()
    def tearDown(self):self.find.stop();self.temp.cleanup()
    def test_search_names_descriptions_and_source_identity(self):
        row=self.refs.search('codex','target','skill','中文')['items'][0]
        self.assertEqual(row['name'],'clear-chinese');self.assertNotIn('path',row)
        self.assertEqual(self.refs.search('codex','target','skill','clear chi')['total'],1)
        hits=self.refs.search('codex','target','chat','同名')['items'];self.assertEqual(hits[0]['id'],'other')
        text,native=self.refs.compose('codex','target','请处理',[row,hits[0]])
        self.assertIn('PUBLIC ANSWER',text);self.assertNotIn('PRIVATE TOOL',text);self.assertIn('"id": "other"',text)
        self.assertEqual(native,[{'type':'skill','name':'clear-chinese','path':str(self.path.resolve())}])
    def test_stale_forged_cross_app_and_disabled_skill_rejected(self):
        row=self.refs.skills('codex','target')[0]
        for changed in ({**row,'id':'forged'},{**row,'app':'claude'},{**row,'version':'old'}):
            with self.assertRaises(chats.ChatError):self.refs.resolve('codex','target',[changed])
        self.path.write_text('---\nname: clear-chinese\nuser-invocable: false\n---\nHidden',encoding='utf-8')
        with self.assertRaises(chats.ChatError):self.refs.resolve('codex','target',[row])
    def test_enabled_plugins_only_and_claude_roots_separate(self):
        config=self.home/'.codex/config.toml';config.write_text('[plugins."demo@market"]\nenabled=true\n',encoding='utf-8')
        for version in ('1.0','2.0'):
            p=self.home/f'.codex/plugins/cache/market/demo/{version}/skills/task/SKILL.md';p.parent.mkdir(parents=True);p.write_text('---\nname: plugin-'+version+'\ndescription: test\n---')
        names=[v['name'] for v in self.refs.skills('codex','target',True)];self.assertIn('plugin-2.0',names);self.assertNotIn('plugin-1.0',names)
        self.assertEqual(self.refs.skills('claude','target',True),[])
    def test_native_send_carries_skill_and_same_reference_snapshot(self):
        bridge=Bridge();bridge.data_root=self.home/'attachments';bridge.references=self.refs
        state={'threadRuntimeStatus':{'type':'idle'},'latestCollaborationMode':{'mode':'default','settings':{'model':'test','reasoning_effort':'low'}}}
        bridge.snapshot=Mock(return_value=(self.target,'owner',state));bridge.validate_settings=Mock(return_value={'model':'test','effort':'low','mode':'default'})
        pipe=SimpleNamespace(call=Mock(return_value={'result':{}}));bridge._pipe=lambda:pipe
        row=self.refs.search('codex','target','skill','clear')['items'][0];body={'id':'target','request_id':'ref-request-00001','text':'使用技能','references':[row]}
        with patch('chats.require_send_desktop'):
            bridge.send(body);bridge.send(body)
        self.assertEqual(pipe.call.call_count,1);request=pipe.call.call_args.args[1]['turnStart']['request']
        self.assertEqual(request['input'][-1]['type'],'skill');self.assertIn('$clear-chinese',request['input'][0]['text'])
        self.assertEqual(bridge.receipt('target',body['request_id'])['result']['submission']['references'],[row])
    def test_frontmatter_is_metadata_only(self):
        self.assertEqual(metadata('---\nname: "a"\ndescription: >-\n  x\n  y\n---')['description'],'x y')

if __name__=='__main__':unittest.main()
