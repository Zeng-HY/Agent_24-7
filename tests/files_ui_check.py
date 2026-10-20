"""＋ → 手机上的文件 / 电脑上的文件 at phone size, against faked APIs (10-20). Never sends to a real conversation.

Run from this folder:  .venv\\Scripts\\python.exe tests\\files_ui_check.py [DIR for screenshots]
The reload taken while an upload is held makes Playwright print a CancelledError for that request; that is expected.
"""
import json
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from playwright.sync_api import sync_playwright
import motion_check as fixture

DEMO = 'D:\\Projects\\demo'
FS = {DEMO: [('资料', None), ('报价单.xlsx', 12000), ('截图.png', 300000), ('合同.docx', 87000)],
      DEMO + '\\资料': [('需求说明.pdf', 2_000_000)],
      'C:\\Users\\me\\Downloads': [('发票.pdf', 500_000)]}
TYPES = {'.xlsx': 'excel', '.png': 'image', '.docx': 'word', '.pdf': 'pdf'}


def entry(folder, name, size):
    path = folder.rstrip('\\') + '\\' + name
    kind = 'folder' if size is None else 'file'
    return {'kind': kind, 'app': 'pc', 'id': 'tok:' + path, 'name': name, 'path': path, 'size': size,
            'modified': int(time.time() * 1000) - 3600_000, 'type': 'folder' if size is None else TYPES.get(Path(name).suffix, 'other')}


def listing(path):
    path = path.replace('/', '\\').rstrip('\\') or path
    rows = FS.get(path, FS[DEMO])
    parts = path.split('\\')
    crumbs = [{'name': p, 'path': '\\'.join(parts[:i + 1]) + ('\\' if i == 0 else '')} for i, p in enumerate(parts)]
    return {'path': path, 'folder': entry('\\'.join(parts[:-1]) or parts[0], parts[-1], None), 'parent': '\\'.join(parts[:-1]) or None,
            'crumbs': crumbs, 'items': [entry(path, n, s) for n, s in rows], 'total': len(rows), 'offset': 0,
            'next_offset': len(rows), 'has_more': False, 'truncated': False, 'sort': 'name'}


def main():
    shots = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    calls = {'send': [], 'chat_send': [], 'deepseek_send': [], 'new': [], 'image': [], 'upload': [], 'remove': [], 'photo': []}
    mode = {'hold': False, 'fail': False}
    held = []

    def route(r, req):
        u = urlsplit(req.url); path, q = u.path, parse_qs(u.query)
        body = json.loads(req.post_data or '{}') if req.method == 'POST' and 'upload' not in path else {}
        def out(v, status=200): r.fulfill(status=status, content_type='application/json', body=json.dumps(v, ensure_ascii=False))
        if path == '/api/files/places':
            here = q.get('folder', [DEMO])[0] or None
            rows = ([{'name': '对话文件夹', 'path': here.replace('/', '\\'), 'kind': 'conversation'}] if here else [])
            return out({'items': rows + [{'name': '下载', 'path': 'C:\\Users\\me\\Downloads', 'kind': 'downloads'},
                                         {'name': 'C 盘', 'path': 'C:\\', 'kind': 'drive'}, {'name': 'D 盘', 'path': 'D:\\', 'kind': 'drive'}]})
        if path == '/api/files/list': return out(listing(q['path'][0]))
        if path == '/api/files/image':
            calls['image'].append(body); ref = body['ref']
            return out({'id': 'p%031d' % len(calls['image']), 'name': ref['name'], 'original_size': ref['size'], 'width': 10, 'height': 10,
                        'url': '/api/codex/image?id=x', 'thumbnail': '/api/codex/image?thumb=1&id=x'})
        if path == '/api/files/upload':
            name = q['name'][0]; calls['upload'].append(name)
            if mode['fail']: return out({'error': '电脑上的磁盘满了'}, 500)
            ref = {'kind': 'file', 'app': 'pc', 'id': 'tok:up:' + name, 'name': name, 'size': len(req.post_data_buffer or b''),
                   'path': 'C:\\Users\\me\\Downloads\\手机传来的文件\\2026-10-20\\' + name, 'type': 'pdf', 'modified': 0,
                   'upload': '%032x' % len(calls['upload']), 'from_phone': True}
            if mode['hold']: held.append((r, ref)); return
            return out(ref)
        if path == '/api/files/remove': calls['remove'].append(body); return out({'ok': True})
        if path == '/api/codex/upload':
            calls['photo'].append(q.get('name', [''])[0])
            return out({'id': 'f%031d' % len(calls['photo']), 'name': q.get('name', ['照片'])[0], 'original_size': 10, 'width': 10, 'height': 10,
                        'url': '/api/codex/image?id=y', 'thumbnail': '/api/codex/image?thumb=1&id=y'})
        if path == '/api/codex/state':
            return out({'available': True, 'running': False, 'questions': [], 'queued': [], 'images': [], 'plan': None, 'queue_available': True,
                        'settings': {'model': 'gpt-5', 'effort': 'high', 'mode': 'default', 'service_tier': None}, 'catalog': {'models': []}})
        if path == '/api/codex/send':
            calls['send'].append(body); return out({'ok': True, 'accepted': True, 'delivery_state': 'accepted', 'text': '已交给 Codex'})
        if path == '/api/chat/send':
            calls['chat_send'].append(body); return out({'ok': True, 'offset': 0, 'check_text': 'x', 'text': '已提交'})
        if path == '/api/chat/check': return out({'delivered': True})
        if path == '/api/deepseek/state':
            return out({'available': True, 'running': False, 'turn_id': '1', 'settings': {}, 'queued': [], 'questions': [], 'interactions': [], 'inbox': {}, 'subagents': []})
        if path == '/api/deepseek/send': calls['deepseek_send'].append(body); return out({'accepted': True, 'text': '已交给 DeepSeek'})
        if path == '/api/deepseek/permissions': return out({'options': [], 'current': ''})
        if path == '/api/chat/new/draft': return out({'request_id': 'a' * 32})
        if path == '/api/chat/new': calls['new'].append(body); return out({'request_id': body['request_id'], 'state': 'creating', 'message': '正在创建对话'})
        if path == '/api/chat/new/state': return out({'request_id': 'a' * 32, 'state': 'creating', 'message': '正在创建对话', 'timing': None})
        return fixture.handle(r, req)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel='chrome')
        ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        ctx.route('**/*', route)
        page = ctx.new_page(); errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(fixture.ORIGIN); page.wait_for_function('!!window.filesUI && !!window.newChatUI')
        files = lambda: page.locator('#referenceChips .reference-chip.is-file')

        # -- a Codex conversation: ＋ lists both, the sheet starts in the conversation's folder
        page.evaluate('c=>openConv(c)', fixture.fake_chat('codex', 'c6')); page.wait_for_function("cur?.id==='c6'")
        page.locator('#addImageBtn').click(); page.wait_for_function("overlays.some(o=>o.id==='attachmentMenu')")
        rows = page.locator('#attachmentMenu .menu-row').all_inner_texts()
        assert rows == ['拍照', '从相册选择', '手机上的文件', '电脑上的文件', '引用对话', '使用技能'], rows
        page.locator('#pickPcFiles').click(); page.wait_for_function("overlays.some(o=>o.id==='pcFiles')")
        page.wait_for_function("document.querySelectorAll('#pcfList .pcf-row').length===4")
        assert page.locator('#pcfCrumbs').inner_text().replace('\n', '').endswith('demo')
        assert page.locator('#pcfPlaces button[aria-current=true]').inner_text() == '对话文件夹'
        assert page.locator('#pcfList .pcf-row').first.inner_text().startswith('资料')  # folders first
        for name in ('报价单.xlsx', '截图.png'):
            page.locator('#pcfList .pcf-row', has_text=name).click()
        page.locator('#pcfList .pcf-row', has_text='资料').click()
        page.wait_for_function("[...document.querySelectorAll('#pcfList .pcf-row')].some(n=>n.textContent.includes('需求说明.pdf'))")
        page.locator('#pcfList .pcf-row', has_text='需求说明.pdf').click()
        assert page.locator('#pcfAdd').inner_text() == '添加 3 个文件'
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        box = page.locator('#pcFiles .box').bounding_box(); assert box['y'] >= 0 and box['y'] + box['height'] <= 844 + 1, box
        if shots: page.wait_for_timeout(400); page.screenshot(path=str(shots / 'pc_files_sheet.png'))
        page.locator('#pcfAdd').click(); page.wait_for_function("!overlays.some(o=>o.id==='pcFiles')")
        page.wait_for_function("document.querySelectorAll('#referenceChips .reference-chip.is-file').length===2")
        page.wait_for_function("document.querySelectorAll('#attachmentPreviews .attachment-tile').length===1")
        assert calls['image'] and calls['image'][0]['ref']['name'] == '截图.png' and calls['image'][0]['app'] == 'codex'
        assert files().all_inner_texts()[0].startswith('📄 报价单.xlsx')
        if shots: page.wait_for_timeout(600); page.screenshot(path=str(shots / 'pc_files_chips.png'))
        assert page.locator('#cvBtn').is_enabled(), 'files alone should be sendable'
        page.locator('#cvBtn').click(); page.wait_for_function('!sending')
        sent = calls['send'][-1]
        assert sent['text'] == '' and [r['name'] for r in sent['references']] == ['报价单.xlsx', '需求说明.pdf'], sent
        assert sent['attachments'] == ['p%031d' % 1] and all(r['path'].startswith(DEMO) for r in sent['references'])
        assert files().count() == 0
        print('PASS codex: ＋ order, sheet starts in the conversation folder, picks across folders, a picture goes as a photo, files alone send')

        # -- a whole folder, then taken off again (nothing on the computer to delete)
        page.locator('#addImageBtn').click(); page.locator('#pickPcFiles').click()
        page.wait_for_function("document.querySelectorAll('#pcfList .pcf-row').length===4")
        page.locator('#pcfList .pcf-row', has_text='资料').click()
        page.wait_for_function("document.getElementById('pcfFolder').textContent.includes('资料')")
        page.locator('#pcfFolder').click(); page.wait_for_function("document.querySelectorAll('#referenceChips .reference-chip.is-file').length===1")
        assert files().first.inner_text().startswith('📁 资料')
        files().first.get_by_role('button', name='去掉 资料').click(); assert files().count() == 0 and not calls['remove']
        print('PASS a whole folder is one chip; taking it off deletes nothing')

        # -- from the phone: the photo goes with the photos, the PDF goes up first and holds the send until it is there
        mode['hold'] = True
        page.locator('#addImageBtn').click()
        with page.expect_file_chooser() as chooser:
            page.locator('#pickPhoneFiles').click()
        chooser.value.set_files([{'name': '发票.pdf', 'mimeType': 'application/pdf', 'buffer': b'%PDF-1.4 test'},
                                 {'name': '照片.jpg', 'mimeType': 'image/jpeg', 'buffer': b'\xff\xd8\xff test'}])
        page.wait_for_function("document.querySelectorAll('#attachmentPreviews .attachment-tile').length===1")
        page.wait_for_function("document.querySelector('#referenceChips .reference-chip.is-file .chip-progress')")
        for _ in range(50):  # the tile and the chip show before their requests arrive
            if calls['photo'] and calls['upload']: break
            page.wait_for_timeout(100)
        assert calls['photo'] == ['照片.jpg'] and calls['upload'] == ['发票.pdf'], (calls['photo'], calls['upload'])
        page.locator('#cvText').fill('这是发票')
        assert page.locator('#cvBtn').is_disabled(), 'send while a file is going up'
        if shots: page.wait_for_timeout(600); page.screenshot(path=str(shots / 'phone_file_uploading.png'))
        rr, ref = held.pop(); rr.fulfill(status=200, content_type='application/json', body=json.dumps(ref, ensure_ascii=False))
        page.wait_for_function("!document.querySelector('#referenceChips .chip-progress')")
        assert page.locator('#cvBtn').is_enabled()
        files().first.get_by_role('button', name='去掉 发票.pdf').click()
        for _ in range(20):
            if calls['remove']: break
            page.wait_for_timeout(100)
        assert calls['remove'] == [{'upload': ref['upload']}], calls['remove']
        print('PASS phone: photo with the photos, file up first, send held until it is there, taken off is deleted on the computer')

        # -- a failed upload, 重试; one cut by a reload comes back failed and goes again from the browser's copy
        mode.update(hold=False, fail=True)
        page.locator('#addImageBtn').click()
        with page.expect_file_chooser() as chooser:
            page.locator('#pickPhoneFiles').click()
        chooser.value.set_files([{'name': '清单.txt', 'mimeType': 'text/plain', 'buffer': '第一行'.encode()}])
        page.wait_for_function("document.querySelector('#referenceChips .reference-chip.is-failed')")
        assert '磁盘满了' in page.evaluate("localStorage.getItem('lbr_references_codex:c6')")
        mode['fail'] = False; files().first.get_by_role('button', name='重新上传 清单.txt').click()
        page.wait_for_function("!document.querySelector('#referenceChips .reference-chip.is-failed')&&!document.querySelector('#referenceChips .chip-progress')")
        files().first.get_by_role('button', name='去掉 清单.txt').click()
        mode['hold'] = True
        page.locator('#addImageBtn').click()
        with page.expect_file_chooser() as chooser:
            page.locator('#pickPhoneFiles').click()
        chooser.value.set_files([{'name': '会议纪要.docx', 'mimeType': 'application/octet-stream', 'buffer': b'PK test'}])
        page.wait_for_function("document.querySelector('#referenceChips .chip-progress')")
        held.clear(); page.reload(); page.wait_for_function('!!window.filesUI')
        page.evaluate('c=>openConv(c)', fixture.fake_chat('codex', 'c6'))
        page.wait_for_function("document.querySelector('#referenceChips .reference-chip.is-failed')")
        mode['hold'] = False; files().first.get_by_role('button', name='重新上传 会议纪要.docx').click()
        page.wait_for_function("!document.querySelector('#referenceChips .reference-chip.is-failed')&&!document.querySelector('#referenceChips .chip-progress')")
        assert calls['upload'][-1] == '会议纪要.docx'
        files().first.get_by_role('button', name='去掉 会议纪要.docx').click()
        print('PASS a failed upload goes again with 重试; a reload mid-upload keeps the file and goes again from the browser')

        # -- Claude and DeepSeek send files alone through their own routes
        page.evaluate('c=>openConv(c)', fixture.fake_chat('claude', 'c3')); page.wait_for_function("cur?.id==='c3'")
        page.locator('#claudeReferenceAdd').click(); page.locator('#pickPcFiles').click()
        page.wait_for_function("document.querySelectorAll('#pcfList .pcf-row').length===4")
        page.locator('#pcfList .pcf-row', has_text='合同.docx').click(); page.locator('#pcfAdd').click()
        page.wait_for_function("document.querySelectorAll('#referenceChips .reference-chip.is-file').length===1")
        page.locator('#cvBtn').click(); page.wait_for_function('!sending')
        assert calls['chat_send'][-1]['references'][0]['name'] == '合同.docx' and calls['chat_send'][-1]['text'] == ''
        page.evaluate("openConv({app:'deepseek',id:'d1',title:'DeepSeek Test',status:'idle'})"); page.wait_for_function("cur?.id==='d1'")
        page.locator('#deepseekAdd').click(); page.locator('#pickPcFiles').click()
        page.wait_for_function("document.querySelectorAll('#pcfList .pcf-row').length===4")
        page.locator('#pcfList .pcf-row', has_text='报价单.xlsx').click(); page.locator('#pcfAdd').click()
        page.wait_for_function("document.querySelectorAll('#referenceChips .reference-chip.is-file').length===1")
        page.locator('#cvBtn').click(); page.wait_for_function('!sending')
        ds = calls['deepseek_send'][-1]; assert ds['references'][0]['name'] == '报价单.xlsx' and ds['text'] == '', ds
        print('PASS claude and deepseek send files alone')

        # -- a new conversation: both rows on its ＋, files and a picture in the first message
        page.evaluate('closeConv(true)'); page.evaluate("openNewSheet({app:'codex',folder:'D:/Projects/示例项目'})")
        page.wait_for_function("overlays.some(o=>o.id==='newSheet')")
        page.locator('#newAdd').click(); page.wait_for_function("overlays.some(o=>o.id==='newAddMenu')")
        rows = page.locator('#newAddMenu .menu-row').all_inner_texts()
        assert rows == ['拍照', '从相册选择', '手机上的文件', '电脑上的文件', '引用对话', '使用技能'], rows
        page.locator('#newPcFiles').click(); page.wait_for_function("overlays.some(o=>o.id==='pcFiles')")
        page.wait_for_function("document.querySelectorAll('#pcfList .pcf-row').length===4")
        assert page.locator('#pcfPlaces button[aria-current=true]').inner_text() == '对话文件夹'
        for name in ('合同.docx', '截图.png'):
            page.locator('#pcfList .pcf-row', has_text=name).click()
        page.locator('#pcfAdd').click(); page.wait_for_function("!overlays.some(o=>o.id==='pcFiles')&&overlays.some(o=>o.id==='newSheet')")
        page.wait_for_function("document.querySelectorAll('#newRefs .reference-chip.is-file').length===1&&document.querySelectorAll('#newImages .attachment-tile').length===1")
        assert calls['image'][-1].get('draft') == 'a' * 32
        assert page.locator('#newBtn').is_enabled()
        if shots: page.wait_for_timeout(600); page.screenshot(path=str(shots / 'new_chat_files.png'))
        page.locator('#newBtn').click(); page.wait_for_function("cur?.id?.startsWith('new:')")
        for _ in range(50):  # the preview opens before the request goes
            if calls['new']: break
            page.wait_for_timeout(100)
        first = calls['new'][-1]
        assert [r['name'] for r in first['references']] == ['合同.docx'] and len(first['attachments']) == 1, first
        print('PASS new conversation: ＋ order, files and a picture in the first message')
        assert not errors, errors
        print('PASS no JavaScript errors')
        browser.close()


if __name__ == '__main__':
    main()
