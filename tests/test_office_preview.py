"""Word, Excel and PowerPoint as PDF (office_preview.py): offered, converted once per version, served. Office is faked."""
import io, os, tempfile, threading, time, unittest, sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import office_preview as op
from chat_history import History
from remote import Handler

def fake_convert(program,source,target):
    Path(target).write_bytes(b'%PDF-1.7 '+program.encode()+b' '+Path(source).read_bytes()[-8:])

class OfficePreview(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        for name,value in (('folder',Mock(return_value=self.root/'previews')),('installed',Mock(return_value=True))):
            patcher=patch.object(op,name,value);patcher.start();self.addCleanup(patcher.stop)
    def doc(self,name,data=b'PK\x03\x04fixture'):
        p=self.root/name;p.write_bytes(data);return p
    def made(self):
        return sorted(p.name for p in (self.root/'previews').glob('*.pdf'))

    def test_offers_office_files_only_when_the_program_is_there(self):
        self.assertEqual([op.offers(n) for n in ('a.docx','B.XLSX','c.pptx','d.rtf','e.pdf','f.txt','g')],['pdf']*4+[None]*3)
        op.installed.return_value=False
        self.assertIsNone(op.offers('a.docx'))
        with self.assertRaisesRegex(op.PreviewError,'没有装 Word'):op.pdf(self.doc('a.docx'))

    def test_each_version_is_converted_once(self):
        source=self.doc('报告 (1).docx')
        with patch.object(op,'_convert',Mock(side_effect=fake_convert)) as convert:
            first=op.pdf(source);self.assertEqual(op.pdf(source),first);self.assertEqual(convert.call_count,1)
            self.assertEqual(first.read_bytes()[:5],b'%PDF-')
            source.write_bytes(b'PK\x03\x04changed!');later=op.pdf(source)
            self.assertNotEqual(later,first);self.assertEqual(convert.call_count,2)
            self.assertEqual(convert.call_args.args[0],'word')

    def test_a_password_protected_file_is_turned_away_before_office(self):
        locked=self.doc('locked.xlsx',op.OLE+b'EncryptedPackage')
        with patch.object(op,'_convert',Mock(side_effect=fake_convert)) as convert:
            with self.assertRaisesRegex(op.PreviewError,'打开密码'):op.pdf(locked)
            convert.assert_not_called()
            op.pdf(self.doc('old.doc',op.OLE+b'WordDocument'))  # the old binary formats are OLE files anyway
            convert.assert_called_once()

    def test_no_pdf_out_is_an_error_and_leaves_nothing(self):
        with patch.object(op,'_convert',Mock(side_effect=lambda p,s,t:Path(t).write_bytes(b'not a pdf'))):
            with self.assertRaisesRegex(op.PreviewError,'没有转出 PDF'):op.pdf(self.doc('a.pptx'))
        self.assertEqual(list((self.root/'previews').iterdir()),[])

    def test_a_conversion_past_the_deadline_stops_the_office_it_started(self):
        def stuck(job):job.started.add(4242);time.sleep(1.5)
        with patch.object(op,'DEADLINE',0.3),patch.dict(op._CONVERT,{'excel':stuck}),patch.object(op.os,'kill') as kill:
            with self.assertRaises(op.PreviewError) as error:op.pdf(self.doc('a.xlsx'))
        self.assertEqual(error.exception.status,503);self.assertIn('超过',str(error.exception))
        kill.assert_called_once();self.assertEqual(kill.call_args.args[0],4242)

    def test_office_errors_read_short(self):
        exc=Exception(-2147352567,'发生意外。',(0,'Microsoft Word','密码不正确，Word 无法打开文档。',None,0,-2146822880),None)
        self.assertEqual(op._reason(exc),'密码不正确，Word 无法打开文档。')
        self.assertEqual(op._reason(OSError('磁盘已满')),'磁盘已满')

    def test_the_cache_keeps_the_newest(self):
        with patch.object(op,'CACHE_FILES',2),patch.object(op,'_convert',Mock(side_effect=fake_convert)):
            made=[]
            for n in range(3):
                made.append(op.pdf(self.doc(f'{n}.docx',b'PK\x03\x04'+bytes([n])*8)));time.sleep(0.05)
        self.assertEqual(self.made(),sorted(p.name for p in made[1:]))

    def test_the_file_list_offers_it_and_the_pdf_is_served_under_the_document_name(self):
        report=self.doc('季度 报告.docx');other=self.doc('data.bin')
        entry=SimpleNamespace(lock=threading.RLock(),messages=[{'id':'m','role':'assistant','text':f'[r](<{report}>) [d](<{other}>)'}])
        h=History(secret='test-only');h.transcript=lambda *a:({'cwd':str(self.root)},entry)
        rows={r['name']:r for r in h.list_files('claude','c')['items']}
        self.assertEqual(rows['季度 报告.docx']['preview'],'pdf');self.assertNotIn('preview',rows['data.bin'])
        with patch.object(op,'_convert',Mock(side_effect=fake_convert)):made=op.pdf(h.file('claude','c',rows['季度 报告.docx']['id'])['path'])
        st=made.stat();headers={}
        handler=SimpleNamespace(headers={},wfile=io.BytesIO(),send_response=lambda x:None,send_header=lambda k,v:headers.update({k:v}),end_headers=lambda:None)
        Handler._serve_result_file(handler,{'path':made,'size':st.st_size,'mtime':st.st_mtime_ns,'kind':'pdf','mime':'application/pdf','name':'季度 报告.pdf'})
        self.assertTrue(handler.wfile.getvalue().startswith(b'%PDF-'));self.assertEqual(headers['Content-Type'],'application/pdf')
        self.assertEqual(headers['Content-Disposition'],"inline; filename*=UTF-8''%E5%AD%A3%E5%BA%A6%20%E6%8A%A5%E5%91%8A.pdf")

    def test_the_meta_and_pdf_routes(self):
        report=self.doc('r.pptx');other=self.doc('notes.bin')
        entry=SimpleNamespace(lock=threading.RLock(),messages=[{'id':'m','role':'assistant','text':f'[r](<{report}>) [n](<{other}>)'}])
        h=History(secret='test-only');h.transcript=lambda *a:({'cwd':str(self.root)},entry)
        ids={r['name']:r['id'] for r in h.list_files('codex','c')['items']};sent=[];headers={}
        fake=SimpleNamespace(history=h,server=SimpleNamespace(files=None),headers={},wfile=io.BytesIO(),send_response=lambda x:None,
                             send_header=lambda k,v:headers.update({k:v}),end_headers=lambda:None,_json=lambda body,status=200:sent.append((status,body)))
        fake._serve_result_file=lambda meta,download=False:Handler._serve_result_file(fake,meta,download)
        fake._query=lambda:{'app':'codex','id':'c','file':ids['r.pptx']}
        Handler._reading_get(fake,'/api/file/meta');self.assertEqual(sent[-1][1]['preview'],'pdf')
        with patch.object(op,'_convert',Mock(side_effect=fake_convert)):Handler._reading_get(fake,'/api/file/pdf')
        self.assertTrue(fake.wfile.getvalue().startswith(b'%PDF-1.7 powerpoint'));self.assertIn('r.pdf',headers['Content-Disposition'])
        fake._query=lambda:{'app':'codex','id':'c','file':ids['notes.bin']}
        Handler._reading_get(fake,'/api/file/meta');self.assertNotIn('preview',sent[-1][1])
        Handler._reading_get(fake,'/api/file/pdf');self.assertEqual(sent[-1],(400,{'error':'这个文件不提供 PDF 预览'}))

if __name__=='__main__':
    unittest.main()
