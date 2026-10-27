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

    def test_an_answer_written_twice_milliseconds_apart_shows_once(self):
        # 10-27: newer Codex writes each answer as an event and then as a response item 12 ms later (an older one as an
        # item_completed item and a response item); only the very same timestamp was taken for one, so every answer
        # showed twice in every app. The first copy stays with its id; the second copy's id still finds it.
        def line(t,ts,p):return json.dumps({'type':t,'timestamp':ts,'payload':p},ensure_ascii=False)+'\n'
        def item(text,ts,mid):return line('response_item',ts,{'type':'message','role':'assistant','phase':'final_answer','id':mid,'content':[{'type':'output_text','text':text}]})
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'log.jsonl'
            p.write_text(line('event_msg','2026-10-26T23:21:00.000Z',{'type':'task_started','turn_id':'t'})
                         +line('event_msg','2026-10-26T23:21:17.014Z',{'type':'agent_message','phase':'final_answer','message':'核实了。\n'})
                         +item('核实了。','2026-10-26T23:21:17.026Z','msg_new')
                         +line('event_msg','2026-10-26T23:21:20.100Z',{'type':'item_completed','item':{'type':'AgentMessage','id':'item_old','phase':'final_answer','content':[{'type':'Text','text':'又一条'}]}})
                         +item('又一条','2026-10-26T23:21:20.117Z','msg_old')
                         +item('又一条','2026-10-26T23:21:40.000Z','msg_later'),encoding='utf-8')  # said again 20 s on: a message of its own
            entry=Transcript(p,'codex').refresh()
            self.assertEqual([(m['text'],m['id']) for m in entry.messages][1:],[('又一条','item_old'),('又一条','msg_later')])
            first=entry.messages[0];self.assertEqual(first['text'],'核实了。\n');self.assertRegex(first['id'],r'^[0-9a-f]{24}:1$')
            self.assertIs(entry.by_id['msg_new'],first);self.assertIs(entry.by_id['msg_old'],entry.messages[1])
            h=History(secret='fixture');h.transcript=lambda *args:({'app':'codex','id':'x'},entry)
            page=h.conversation('codex','x',5,around='msg_new');self.assertFalse(page['reset']);self.assertIn(first['id'],[m['id'] for m in page['messages']])
            self.assertEqual([m['id'] for m in h.conversation('codex','x',5,before='msg_old')['messages']],[first['id']])
            self.assertEqual(len(chats.parse_codex(p.read_bytes().splitlines())[0]),3)  # the batch reading (list previews) agrees

    def test_codex_memory_notes_left_out_and_file_citations_made_links(self):
        # 10-27: what Codex's desktop draws on its own, every app showed as raw text, and a file Codex made could not be
        # fetched from the phone.
        cited=':codex-file-citation{path="D:\\Personal\\.codex\\my_x (1).docx" purpose="output" page_number="2"}'
        text='做好了。\n\n'+cited+'\n\n<oai-mem-citation>\n<citation_entries>\nMEMORY.md:694-696|note=[x]\n</citation_entries>\n<rollout_ids>\n</rollout_ids>\n</oai-mem-citation>'
        answer=chats.codex_answer(text)
        self.assertEqual(answer,'做好了。\n\n[my_x (1).docx](<D:/Personal/.codex/my_x (1).docx>)')  # / : a \ before . or _ is lost
        self.assertEqual(references(answer),['D:/Personal/.codex/my_x (1).docx'])
        self.assertEqual(chats.one_line(chats.plain(answer)),'做好了。 my_x (1).docx')
        self.assertEqual(chats.codex_answer(':codex-file-citation{path="D:\\a\\[v2] x.md"}'),'[\\[v2\\] x.md](<D:/a/[v2] x.md>)')
        self.assertEqual(chats.codex_answer('见 :codex-file-citation{path="notes/x.md" purpose="output"}。'),'见 `notes/x.md`。')
        self.assertEqual(chats.codex_answer('还在写 <oai-mem-citation>\n<citation_entries>\nMEMO'),'还在写')  # cut off while streaming
        self.assertEqual(chats.codex_answer('平常的回答\n'),'平常的回答\n')
        raw=json.dumps({'type':'response_item','timestamp':'2026-10-27T01:00:00Z','payload':{'type':'message','role':'assistant','phase':'final_answer','id':'m','content':[{'type':'output_text','text':text}]}},ensure_ascii=False).encode()
        self.assertEqual(chats.parse_codex([raw])[0][0]['text'],answer)

if __name__=='__main__':unittest.main()
