"""Identity, public phases and exact-file authorization, using disposable data."""
import json,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import chats
import activity_records
from chat_history import History,HistoryError,Transcript
from message_files import references

class Candidate(unittest.TestCase):
    def test_search_no_match_is_distinct_from_command_failure(self):
        for command,expected in [('rg missing file.txt','no_matches'),('other-command','failed'),('rg missing file.txt; other-command','failed')]:
            raw=json.dumps({'type':'event_msg','payload':{'type':'item_completed','item':{'type':'CommandExecution','command':command,'exit_code':1,'aggregated_output':''}}}).encode()
            rows=activity_records.enrich('codex',raw,[{'role':'tool','text':'search'}],{})
            self.assertEqual(rows[0]['tool_status'],expected)

    def test_public_phase_and_client_identity(self):
        def event(p):return json.dumps({'type':'event_msg','payload':p}).encode()
        rows,_=chats.parse_codex([event({'type':'user_message','message':'same','client_id':'a'}),event({'type':'user_message','message':'same','client_id':'b'}),event({'type':'agent_message','message':'progress','phase':'commentary'}),event({'type':'agent_message','message':'PRIVATE','phase':'analysis'})])
        self.assertEqual([m.get('client_request_id') for m in rows[:2]],['a','b'])
        self.assertEqual(rows[-1]['phase'],'commentary');self.assertEqual(len(rows),3)

    def test_markdown_nodes_exclude_code_and_preserve_paths(self):
        text='[file](<D:/outside/中文 (a).md:12>)\n\n![image](D:/outside/a.png)\n\n`[example](D:/secret.md)`\n\n```md\n[x](D:/secret2.md)\n```'
        self.assertEqual(references(text),['D:/outside/中文 (a).md','D:/outside/a.png'])
        self.assertEqual(references('[nested](D:/a(b).md)'),['D:/a(b).md'])

    def test_exact_cross_project_old_file_change_delete_and_forgeries(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);a=root/'中文 (a).md';a.write_text('one');adjacent=root/'private.md';adjacent.write_text('secret')
            messages=[{'id':'old','role':'assistant','text':f'[old](<{a}>)'}]+[{'id':str(i),'role':'assistant','text':f'[file](<{root / (str(i)+".md")}>)'} for i in range(120)]
            entry=SimpleNamespace(lock=threading.RLock(),messages=messages)
            h=History(secret='fixture');h.transcript=lambda *args:({'cwd':str(root/'different')},entry)
            rows=h.list_files('codex','test','old')['items'];self.assertEqual(len(rows),1);f=rows[0]
            self.assertEqual(f['state'],'current');self.assertEqual(h.file('codex','test',f['id'])['path'],a)
            for tid,fid in [('other',f['id']),('test','forged')]:
                with self.assertRaises(HistoryError):h.file('codex',tid,fid)
            a.write_text('changed current content');self.assertTrue(h.file('codex','test',f['id'])['updated'])
            self.assertFalse(any(v['path']==str(adjacent) for v in h.list_files('codex','test')['items']))
            a.unlink()
            with self.assertRaises(HistoryError):h.file('codex','test',f['id'])

    def test_public_response_and_legacy_alias_do_not_duplicate_or_drop_user(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'log.jsonl'
            def line(t,p):return json.dumps({'type':t,'timestamp':'2026-10-24T00:00:00Z','payload':p})+'\n'
            p.write_text(line('event_msg',{'type':'task_started','turn_id':'t'})+line('event_msg',{'type':'user_message','message':'question'})+line('response_item',{'type':'message','role':'assistant','phase':'commentary','id':'s','content':[{'type':'output_text','text':'progress'}]})+line('event_msg',{'type':'agent_message','message':'progress','phase':'commentary'}),encoding='utf-8')
            rows=Transcript(p,'codex').refresh().messages
            self.assertEqual([m['text'] for m in rows],['question','progress'])

if __name__=='__main__':unittest.main()
