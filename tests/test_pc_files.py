"""Files on this computer attached by their path, and files sent up from the phone (pc_files.py, 10-20)."""
import io, json, os, sys, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chats
import pc_files
from composer_references import References


class FilesTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.disk = self.root / 'disk'; self.disk.mkdir()
        self.inbox = self.root / 'Downloads' / pc_files.INBOX_NAME
        drive = (self.root.drive + '\\').upper() if os.name == 'nt' else '/'
        self.files = pc_files.Files('secret', inbox=self.inbox, registry=self.root / 'phone-files.json',
                                    drives=lambda: [drive], places=[('downloads', '下载', self.root / 'Downloads')])

    def write(self, name, data=b'x'):
        p = self.disk / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data); return p


class DownloadTests(FilesTestCase):
    def test_exact_download_ticket_rejects_changes_forgery_and_wrong_computer(self):
        p=self.write('中文 报告.xlsx',b'PK-test');row=self.files.entry(p)
        self.assertEqual(self.files.download_meta(row['download_id'])['path'],p)
        self.assertEqual(self.files.resolve(row)['path'],str(p))
        with self.assertRaises(pc_files.FileError):self.files.download_meta(row['download_id']+'0')
        other=pc_files.Files('other',inbox=self.inbox,registry=self.root/'other.json',drives=self.files.drives)
        with self.assertRaises(pc_files.FileError):other.download_meta(row['download_id'])
        p.write_bytes(b'changed')
        with self.assertRaises(pc_files.FileError):self.files.download_meta(row['download_id'])
        p.unlink()
        with self.assertRaises(pc_files.FileError):self.files.download_meta(row['download_id'])
    def test_download_bytes_and_replacement_after_metadata(self):
        from remote import Handler
        p=self.write('结果.pptx',b'PK-content')
        meta=self.files.download_meta(self.files.entry(p)['download_id']);headers={};errors=[]
        h=SimpleNamespace(headers={},wfile=io.BytesIO(),send_response=lambda n:None,send_header=lambda k,v:headers.update({k:v}),end_headers=lambda:None,_json=lambda *a:errors.append(a))
        Handler._serve_result_file(h,meta,True)
        self.assertEqual(h.wfile.getvalue(),p.read_bytes());self.assertIn('attachment',headers['Content-Disposition'])
        p.write_bytes(b'changed-length');h.wfile=io.BytesIO();Handler._serve_result_file(h,meta,True)
        self.assertEqual(h.wfile.getvalue(),b'');self.assertEqual(errors[0][1],409)

class ListingTests(FilesTestCase):
    def test_folders_first_natural_order_and_hidden_left_out(self):
        for name in ('第10章.docx', '第2章.docx', '.git/config', '~$第2章.docx', 'b.txt'):
            self.write(name)
        (self.disk / 'A 子文件夹').mkdir()
        if os.name == 'nt':
            hidden = self.write('隐藏.txt'); os.system(f'attrib +h "{hidden}"')
        data = self.files.listing(str(self.disk))
        self.assertEqual([v['name'] for v in data['items']], ['A 子文件夹', 'b.txt', '第2章.docx', '第10章.docx'])
        self.assertEqual(data['items'][0]['kind'], 'folder'); self.assertEqual(data['items'][2]['type'], 'word')
        self.assertEqual(data['crumbs'][-1]['path'], str(self.disk)); self.assertEqual(data['folder']['kind'], 'folder')
        self.assertEqual(len(data['items'][1]['id']), 24); self.assertNotIn('secret', json.dumps(data))

    def test_newest_first_filter_and_pages(self):
        old, new = self.write('old.pdf'), self.write('new.pdf')
        os.utime(old, (time.time() - 3600, time.time() - 3600))
        archive = self.disk / 'archive'; archive.mkdir(); os.utime(archive, (time.time() - 7200, time.time() - 7200))
        # newest first with the folders among the files: what was just downloaded is at the top
        self.assertEqual([v['name'] for v in self.files.listing(str(self.disk), 'time')['items']], ['new.pdf', 'old.pdf', 'archive'])
        self.assertEqual([v['name'] for v in self.files.listing(str(self.disk))['items']], ['archive', 'new.pdf', 'old.pdf'])
        self.assertEqual([v['name'] for v in self.files.listing(str(self.disk), query='OLD')['items']], ['old.pdf'])
        for i in range(pc_files.PAGE + 5):
            self.write(f'many/{i:03}.txt')
        first = self.files.listing(str(self.disk / 'many'))
        self.assertTrue(first['has_more']); self.assertEqual(len(first['items']), pc_files.PAGE)
        rest = self.files.listing(str(self.disk / 'many'), offset=first['next_offset'])
        self.assertEqual(len(rest['items']), 5); self.assertFalse(rest['has_more'])

    def test_only_this_computers_disks(self):
        for bad in ('', 'relative\\path', '\\\\server\\share\\x', 'Q:\\nothing' if os.name == 'nt' else '/proc/../x'):
            with self.assertRaises(pc_files.FileError):
                self.files.listing(bad)
        with self.assertRaises(pc_files.FileError) as gone:
            self.files.listing(str(self.disk / 'missing'))
        self.assertEqual(gone.exception.status, 404)

    def test_places_start_at_the_conversation(self):
        (self.root / 'Downloads').mkdir(exist_ok=True)
        rows = self.files.places(str(self.disk))['items']
        self.assertEqual(rows[0], {'name': '对话文件夹', 'path': str(self.disk), 'kind': 'conversation'})
        self.assertIn('downloads', [v['kind'] for v in rows]); self.assertIn('drive', [v['kind'] for v in rows])
        self.assertNotIn('inbox', [v['kind'] for v in rows])  # nothing came from the phone yet


class AttachTests(FilesTestCase):
    def ref(self, path):
        return self.files.entry(Path(path))

    def test_describe_says_what_each_is(self):
        doc = self.write('合同.docx', b'x' * 87040); folder = self.disk / '图纸'; folder.mkdir()
        for name in ('1.dwg', '2.dwg'):
            (folder / name).write_bytes(b'1')
        (folder / 'old').mkdir()
        text = pc_files.describe([self.files.resolve(self.ref(doc)), self.files.resolve(self.ref(folder))])
        self.assertEqual(text, '附带的文件（都在这台电脑上，请直接打开）：\n'
                               f'- {doc}（Word，85 KB）\n- {folder}（文件夹，2 个文件、1 个子文件夹）')

    def test_forged_and_gone_are_refused(self):
        doc = self.write('a.pdf'); ref = self.ref(doc)
        for forged in ({**ref, 'path': str(self.disk / 'other.pdf')}, {**ref, 'kind': 'folder'}, {**ref, 'id': '0' * 24}):
            with self.assertRaises(chats.ChatError):
                self.files.resolve(forged)
        doc.unlink()
        with self.assertRaises(pc_files.FileGone) as gone:
            self.files.resolve(ref)
        self.assertTrue(gone.exception.not_submitted); self.assertIn('a.pdf', str(gone.exception))

    def test_the_message_carries_paths_after_its_text(self):
        refs = References(SimpleNamespace(catalog=lambda: []), self.root, files=self.files)
        doc = self.write('报价单.xlsx', b'1' * 3000)
        text, native = refs.compose('claude', 'x', '看看总价', [self.ref(doc)])
        self.assertTrue(text.startswith('看看总价\n\n附带的文件（都在这台电脑上，请直接打开）：\n- ' + str(doc)))
        self.assertEqual(native, [])
        self.assertTrue(refs.compose('deepseek', 'x', '', [self.ref(doc)])[0].startswith('请查看附带的文件。\n\n附带的文件'))

    def test_twenty_files_besides_eight_others(self):
        refs = References(SimpleNamespace(catalog=lambda: []), self.root, files=self.files)
        many = [self.ref(self.write(f'{i}.txt')) for i in range(pc_files.MAX_FILES + 1)]
        self.assertEqual(refs.resolve('codex', 'x', many[:-1])['files'], pc_files.MAX_FILES)
        with self.assertRaises(chats.ChatError):
            refs.resolve('codex', 'x', many)

    def test_a_picture_on_the_computer_is_read_for_the_photo_path(self):
        png = self.write('截图.png', b'\x89PNG...')
        self.assertEqual(self.files.picture(self.ref(png)), ('截图.png', b'\x89PNG...'))
        with self.assertRaises(pc_files.FileError):
            self.files.picture(self.ref(self.write('a.gif')))
        with patch.object(pc_files, 'MAX_PICTURE', 3), self.assertRaises(pc_files.FileError):
            self.files.picture(self.ref(png))


class PhoneFileTests(FilesTestCase):
    def up(self, name, data):
        return self.files.upload(name, io.BytesIO(data).read, len(data), 'claude', 'local_x')

    def test_written_into_todays_folder_under_its_own_name(self):
        ref = self.up('发票.pdf', b'%PDF-1')
        path = Path(ref['path'])
        self.assertEqual(path.parent, self.inbox / time.strftime('%Y-%m-%d')); self.assertEqual(path.read_bytes(), b'%PDF-1')
        self.assertTrue(ref['from_phone']); self.assertEqual(len(ref['upload']), 32)
        self.assertEqual(Path(self.up('发票.pdf', b'2')['path']).name, '发票 (2).pdf')
        line = self.files.resolve(ref); self.assertTrue(line['from_phone'])
        self.assertIn('（PDF，6 字节，从手机传来）', pc_files.describe([line]))
        self.assertEqual(self.files.places()['items'][0]['kind'], 'inbox')

    def test_names_windows_can_keep(self):
        for raw, kept in (('..\\..\\a.txt', 'a.txt'), ('CON.txt', '_CON.txt'), ('a<b>?.txt', 'a_b__.txt'), ('.env', '_.env'), ('', '文件')):
            self.assertEqual(pc_files.safe_name(raw), kept)

    def test_an_upload_cut_short_leaves_nothing(self):
        with self.assertRaises(pc_files.FileError):
            self.files.upload('a.txt', io.BytesIO(b'abc').read, 10)
        self.assertEqual(list((self.inbox / time.strftime('%Y-%m-%d')).iterdir()), [])
        with self.assertRaises(pc_files.FileError):
            self.files.upload('big.bin', io.BytesIO(b'').read, pc_files.MAX_UPLOAD + 1)

    def test_taken_off_before_sending_is_deleted_sent_is_kept(self):
        kept, dropped = self.up('kept.txt', b'1'), self.up('dropped.txt', b'2')
        refs = References(SimpleNamespace(catalog=lambda: []), self.root, files=self.files)
        refs.compose('claude', 'x', '看看', [kept])
        self.assertEqual(self.files.remove_upload(kept['upload']), {'ok': True, 'retained': True})
        self.assertEqual(self.files.remove_upload(dropped['upload']), {'ok': True})
        self.assertTrue(Path(kept['path']).exists()); self.assertFalse(Path(dropped['path']).exists())

    def test_a_week_later_unsent_ones_go_unless_changed(self):
        stale, edited, sent = self.up('stale.txt', b'1'), self.up('edited.txt', b'2'), self.up('sent.txt', b'3')
        self.files.mark_used([sent['upload']])
        data = json.loads((self.root / 'phone-files.json').read_text(encoding='utf-8'))
        for item in data.values():
            item['created'] -= pc_files.KEEP_UNSENT + 60
        (self.root / 'phone-files.json').write_text(json.dumps(data), encoding='utf-8')
        Path(edited['path']).write_bytes(b'changed on the PC')
        self.files.cleanup(force=True)
        self.assertFalse(Path(stale['path']).exists()); self.assertTrue(Path(edited['path']).exists()); self.assertTrue(Path(sent['path']).exists())

    def test_the_upload_route_streams_the_body(self):
        import remote
        handler = object.__new__(remote.Handler); handler.path = '/api/files/upload?name=%E8%AE%A1%E5%88%92.md&app=codex&id=t1'
        handler._authorized = lambda: True; handler.headers = {'Content-Length': '5'}; handler.rfile = io.BytesIO(b'hello')
        handler.server = SimpleNamespace(machine={'voice': False}, files=self.files); handler._json = Mock()
        handler.do_POST()
        ref = handler._json.call_args.args[0]
        self.assertEqual(ref['name'], '计划.md'); self.assertEqual(Path(ref['path']).read_bytes(), b'hello')
        handler.headers = {'Content-Length': str(pc_files.MAX_UPLOAD + 1)}; handler.rfile = io.BytesIO(b''); handler._json = Mock()
        handler.do_POST(); self.assertEqual(handler._json.call_args.args[1], 413)


class SendTests(FilesTestCase):
    def test_deepseek_sends_files_alone_and_still_refuses_skills(self):
        import deepseek_control as d
        client = Mock(); client.call.return_value = {'accepted': True}
        bridge = d.Bridge(client, str(self.root / 'ds'), links=d.ParentLinks(self.root / 'links.jsonl'))
        bridge.references = References(SimpleNamespace(catalog=lambda: []), self.root, files=self.files)
        ref = self.files.entry(self.write('需求.md'))
        with patch.object(bridge, 'find', return_value={}):
            bridge.send({'id': 'session-1', 'text': '', 'attachments': [], 'references': [ref], 'request_id': 'a' * 32})
            content = client.call.call_args.args[1]['request']['content']
            self.assertEqual(content[0]['type'], 'text'); self.assertIn(str(self.disk / '需求.md'), content[0]['text'])
            with self.assertRaises(d.DeepSeekError):
                bridge.send({'id': 'session-1', 'text': 'x', 'references': [{'kind': 'skill', 'app': 'deepseek', 'id': 's'}], 'request_id': 'b' * 32})

    def test_codex_sends_files_alone(self):
        from codex_control import Bridge
        bridge = Bridge(); bridge.data_root = self.root / 'attachments'
        bridge.references = References(SimpleNamespace(catalog=lambda: []), self.root, files=self.files)
        state = {'threadRuntimeStatus': {'type': 'idle'}, 'latestCollaborationMode': {'mode': 'default', 'settings': {'model': 'test', 'reasoning_effort': 'low'}}}
        bridge.snapshot = Mock(return_value=({'id': 't'}, 'owner', state))
        bridge.validate_settings = Mock(return_value={'model': 'test', 'effort': 'low', 'mode': 'default'})
        pipe = SimpleNamespace(call=Mock(return_value={'result': {}})); bridge._pipe = lambda: pipe
        ref = self.files.entry(self.write('数据.csv'))
        with patch('chats.require_send_desktop'):
            bridge.send({'id': 't', 'request_id': 'files-only-00001', 'text': '', 'references': [ref]})
        text = pipe.call.call_args.args[1]['turnStart']['request']['input'][0]['text']
        self.assertTrue(text.startswith('请查看附带的文件。')); self.assertIn(str(self.disk / '数据.csv') + '（表格，', text)


if __name__ == '__main__':
    unittest.main()
