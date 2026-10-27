"""Exact-file registry extension and original download bytes; temporary files only."""
import hashlib,io,threading,tempfile,unittest,sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chat_history import History,HistoryError
from message_files import references
from remote import Handler,STATIC_FILES

class Artifacts(unittest.TestCase):
    def fixture(self,root,names):
        paths=[root/n for n in names]
        for p in paths:p.write_bytes(b'fixture\x00bytes')
        entry=SimpleNamespace(lock=threading.RLock(),messages=[{'id':'m','role':'assistant','text':' '.join(f'[f](<{p}>)' for p in paths)}])
        h=History(secret='test-only');h.transcript=lambda *args:({'cwd':str(root/'different-project')},entry)
        return h,entry,paths
    def test_deepseek_presented_event_reaches_exact_file_list_and_download(self):
        from deepseek_stream import public_messages
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'数据核对报告.xlsx';p.write_bytes(b'PK-fixture')
            records=[{'event':{'seq':7,'time':0,'type':'deliverables/presented','data':{'turn':1,'callId':'present-1','files':[{'path':p.name,'description':'数据核对报告'},{'path':p.name}]}}}]
            messages=public_messages(records,'session-test');self.assertEqual(messages[0]['kind'],'deliverables')
            entry=SimpleNamespace(lock=threading.RLock(),messages=messages)
            h=History(secret='fixture');h.transcript=lambda *a:({'cwd':str(root)},entry)
            rows=h.list_files('deepseek','session-test')['items'];self.assertEqual(len(rows),1)
            self.assertEqual(h.file('deepseek','session-test',rows[0]['id'])['path'],p)
            self.assertEqual(len(h.list_files('deepseek','session-test','7')['items']),1)
            self.assertEqual(h.list_files('deepseek','session-test','8')['items'],[])
            entry.messages=[]
            with self.assertRaises(HistoryError):h.file('deepseek','session-test',rows[0]['id'])
    def test_invalid_presented_event_does_not_authorize_files(self):
        from deepseek_stream import public_messages
        for data in ({'files':[{'path':'C:/private.txt'}]}, {'turn':True,'callId':'x','files':[]}):
            self.assertEqual(public_messages([{'event':{'seq':1,'type':'deliverables/presented','data':data}}]),[])

    def test_unknown_extension_and_no_extension_are_exact_references(self):
        with tempfile.TemporaryDirectory() as d:
            h,entry,paths=self.fixture(Path(d),['中文 (1).html','file.unknown','noextension','image.svg'])
            rows=h.list_files('codex','a')['items'];self.assertEqual(len(rows),4)
            for f in rows:
                meta=h.file('codex','a',f['id']);self.assertTrue(meta['path'].is_file())
                with self.assertRaises(HistoryError):h.file('codex','b',f['id'])
            self.assertEqual(rows[-1]['kind'],'download')
            fid=rows[0]['id'];entry.messages[0]['text']=f'[changed](<{paths[1]}>)'
            with self.assertRaises(HistoryError):h.file('codex','a',fid)
    def test_examples_ads_and_unregistered_neighbor_are_not_authority(self):
        with tempfile.TemporaryDirectory() as d:
            h,e,paths=self.fixture(Path(d),['allowed.bin','private.bin'])
            e.messages[0]['text']=f'[file](<{paths[0]}>) `[{paths[1]}]({paths[1]})`\n\n```\n[x]({paths[1]})\n```\n[ads](<{paths[0]}:secret>)'
            self.assertEqual(len(h.list_files('codex','a')['items']),1)
            self.assertEqual(references('plain filename.html and `C:/secret.html`'),[])
    def test_path_redirect_update_delete(self):
        with tempfile.TemporaryDirectory() as d:
            h,e,paths=self.fixture(Path(d),['a.bin','b.bin']);fid=h.list_files('codex','a')['items'][0]['id']
            paths[0].write_bytes(b'changed');self.assertTrue(h.file('codex','a',fid)['updated'])
            paths[0].unlink()
            with self.assertRaises(HistoryError):h.file('codex','a',fid)
            try:paths[0].symlink_to(paths[1])
            except OSError:return  # Windows may disallow symlinks; deletion assertion still runs.
            with self.assertRaises(HistoryError):h.file('codex','a',fid)
    def test_download_hash_and_safe_mime(self):
        with tempfile.TemporaryDirectory() as d:
            h,e,paths=self.fixture(Path(d),['中文 (1).html','active.svg'])
            for row in h.list_files('codex','a')['items']:
                meta=h.file('codex','a',row['id']);headers={}
                handler=SimpleNamespace(headers={},wfile=io.BytesIO(),send_response=lambda x:None,send_header=lambda k,v:headers.update({k:v}),end_headers=lambda:None)
                Handler._serve_result_file(handler,meta,True)
                self.assertEqual(hashlib.sha256(handler.wfile.getvalue()).digest(),hashlib.sha256(meta['path'].read_bytes()).digest())
                self.assertTrue(headers['Content-Disposition'].startswith('attachment'))
                self.assertNotIn(headers['Content-Type'],('text/html','image/svg+xml'))
            self.assertIn('/artifact-preview.js',STATIC_FILES);self.assertIn('/artifact-preview.css',STATIC_FILES)

if __name__=='__main__':unittest.main()
