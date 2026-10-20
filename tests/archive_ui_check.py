"""左滑归档 at phone size with real touches (DevTools), against faked APIs (10-20). Archives nothing for real.

Run from this folder:  .venv\\Scripts\\python.exe tests\\archive_ui_check.py [DIR for screenshots]
"""
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
import motion_check as fixture

NOW = int(time.time() * 1000)
ROWS = [
    {'app': 'codex', 'id': 'cx1', 'title': '部署方案', 'status': 'idle', 'updated': NOW - 60_000, 'folder': 'demo', 'preview': '最后一条回答的开头。'},
    {'app': 'deepseek', 'id': 'session-ds1', 'title': '整理表格', 'status': 'idle', 'updated': NOW - 120_000, 'folder': 'demo_workspace', 'preview': ''},
    {'app': 'claude', 'id': 'local_cl1', 'title': 'notes_app 重构', 'status': 'idle', 'updated': NOW - 180_000, 'folder': 'notes_app', 'preview': ''},
    {'app': 'codex', 'id': 'cx2', 'title': '正在跑的任务', 'status': 'running', 'updated': NOW - 240_000, 'folder': 'demo', 'preview': ''},
    *[{'app': 'codex', 'id': f'cx{i}', 'title': f'示例对话 {i}', 'status': 'idle', 'updated': NOW - i * 600_000, 'folder': 'demo', 'preview': ''} for i in range(3, 14)]]
ARCHIVED = [{'app': 'codex', 'id': 'old1', 'title': '旧的报价单', 'folder': 'demo', 'archived_at': NOW - 86_400_000, 'can_delete': True},
            {'app': 'codex', 'id': 'old2', 'title': '上周的测试', 'folder': 'demo', 'archived_at': NOW - 2 * 86_400_000, 'can_delete': True},
            {'app': 'deepseek', 'id': 'session-old', 'title': 'DeepSeek 旧对话', 'folder': 'demo_workspace', 'updated': NOW - 3 * 86_400_000, 'can_delete': False}]


def main():
    shots = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    calls = {'archive': [], 'unarchive': [], 'delete': []}
    mode = {'refuse': False, 'slow': 0}
    archived = [dict(v) for v in ARCHIVED]

    def route(r, req):
        path = urlsplit(req.url).path
        body = json.loads(req.post_data or '{}') if req.method == 'POST' else {}
        def out(v, status=200): r.fulfill(status=status, content_type='application/json', body=json.dumps(v, ensure_ascii=False))
        if path == '/':
            page = (fixture.HERE / 'remote.html').read_text(encoding='utf-8').replace('<!--machine-->', '<script>window.MACHINE={apps:["codex","claude","deepseek"],voice:false,name:"测试电脑"};</script>')
            return r.fulfill(status=200, content_type='text/html; charset=utf-8', body=page)
        if path == '/api/chats':  # the server keeps listing an archived one for a moment
            return out({'items': ROWS, 'total': len(ROWS), 'has_more': False, 'next_cursor': None})
        if path == '/api/chat/archive':
            calls['archive'].append(body)
            if mode['slow']: time.sleep(mode['slow'])
            if mode['refuse']: return out({'error': '电脑上的 Codex 正开着这个对话（或刚开过），现在归档不了。'}, 409)
            return out({'ok': True, 'archived': True})
        if path == '/api/chat/unarchive':
            calls['unarchive'].append(body); archived[:] = [v for v in archived if v['id'] != body['id']]
            return out({'ok': True, 'archived': False})
        if path == '/api/chat/archived':
            return out({'items': archived, 'problems': [], 'apps': ['codex', 'deepseek'], 'deletable': ['codex']})
        if path == '/api/chat/delete':
            calls['delete'].append(body); gone = {v['id'] for v in body['items']}; archived[:] = [v for v in archived if v['id'] not in gone]
            return out({'ok': True, 'deleted': len(gone), 'results': [{'app': v['app'], 'id': v['id'], 'ok': True} for v in body['items']]})
        return fixture.handle(r, req)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel='chrome')
        ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        ctx.route('**/*', route)
        page = ctx.new_page(); errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(fixture.ORIGIN); page.wait_for_function('!!window.archiveUI && document.querySelectorAll("#convList .conv").length>10')
        cdp = ctx.new_cdp_session(page); finger = fixture.Finger(page, cdp)
        row = lambda key: page.locator(f'#convList .conv[data-key="{key}"]')
        def box(key): b = row(key).bounding_box(); return b['x'], b['y'] + b['height'] / 2, b['width']
        def swipe(key, distance, steps=12, step=16, hold=None):
            x, y, w = box(key); start = x + w - 30
            finger.drag([(start - distance * i / steps, y + i * 0.4) for i in range(steps + 1)], step=step, hold=hold)

        # a full swipe: the row slides off, the list closes up, the bar offers 撤销, the computer is asked once
        def armed_shot():
            assert page.evaluate("document.querySelector('.swipe-under')?.classList.contains('armed')"), 'not armed past the mark'
            if shots: page.screenshot(path=str(shots / 'swipe_armed.png'))
        swipe('codex:cx1', 230, hold=(10, 120, armed_shot))
        page.wait_for_function("!document.querySelector('#convList .conv[data-key=\"codex:cx1\"]')")
        assert calls['archive'] == [{'app': 'codex', 'id': 'cx1'}], calls['archive']
        page.wait_for_function("document.getElementById('archiveUndo').classList.contains('show')")
        assert page.locator('#archiveUndo').inner_text().startswith('对话已归档')
        assert '部署方案' in page.locator('#archiveUndo').inner_text()
        assert not page.locator('.swipe-under').count()
        if shots: page.wait_for_timeout(350); page.screenshot(path=str(shots / 'undo_bar.png'))
        page.evaluate('loadConvs()'); page.wait_for_timeout(400)
        assert row('codex:cx1').count() == 0, 'a refresh brought the archived row back'
        page.locator('#archiveUndo button').click()
        page.wait_for_function("!!document.querySelector('#convList .conv[data-key=\"codex:cx1\"]')")
        for _ in range(30):
            if calls['unarchive']: break
            page.wait_for_timeout(100)
        assert calls['unarchive'] == [{'app': 'codex', 'id': 'cx1'}]
        assert [n for n in page.evaluate("[...document.querySelectorAll('#convList .conv')].map(n=>n.dataset.key)")][:2] == ['codex:cx1', 'deepseek:session-ds1']
        assert not page.evaluate("document.getElementById('archiveUndo').classList.contains('show')")
        print('PASS a full swipe archives with 撤销; a refresh keeps it off; 撤销 brings it back in its place')

        # short, slow, sideways-then-down and Claude's: nothing archived, everything back in place
        swipe('deepseek:session-ds1', 60, step=30)
        page.wait_for_timeout(400)
        assert row('deepseek:session-ds1').get_attribute('style') in (None, '', 'transform: none;'), row('deepseek:session-ds1').get_attribute('style')
        x, y, w = box('codex:cx3'); finger.drag([(x + w / 2, y + i * 14) for i in range(10)])  # a scroll
        x, y, w = box('claude:local_cl1'); finger.drag([(x + w - 30 - i * 25, y) for i in range(11)])
        page.wait_for_timeout(400)
        assert calls['archive'] == [{'app': 'codex', 'id': 'cx1'}] and not page.locator('.swipe-under').count()
        assert row('claude:local_cl1').count() == 1
        print('PASS a short swipe springs back; a scroll and a Claude row archive nothing')

        # a running one springs back and says why; one the computer refuses comes back with the reason
        swipe('codex:cx2', 240); page.wait_for_timeout(450)
        assert row('codex:cx2').count() == 1 and len(calls['archive']) == 1
        assert '正在运行' in page.locator('#toast').inner_text()
        mode['refuse'] = True; swipe('deepseek:session-ds1', 240)
        page.wait_for_function("!!document.querySelector('#convList .conv[data-key=\"deepseek:session-ds1\"]') && document.getElementById('toast').textContent.includes('没归档')")
        assert calls['archive'][-1] == {'app': 'deepseek', 'id': 'session-ds1'}; mode['refuse'] = False
        print('PASS a running one is not archived; a refusal brings the row back with the reason')

        # the lift after a swipe is not a tap; a tap afterwards opens the conversation
        swipe('codex:cx4', 50); page.wait_for_timeout(500)
        x, y, w = box('codex:cx4'); finger.tap(x + w / 2, y)
        page.wait_for_function("cur?.id==='cx4'"); page.evaluate('closeConv(true)'); page.wait_for_timeout(300)
        print('PASS a tap after a swipe still opens the conversation')

        # 设置 → 已归档对话: restore one, tick the Codex ones and delete them after the confirmation
        page.evaluate("openSheet('settingsSheet')"); page.wait_for_function("overlays.some(o=>o.id==='settingsSheet')")
        assert page.locator('#settingsBody .setting-title').first.inner_text() == '对话'
        page.locator('#archivedOpen').click(); page.wait_for_function("document.querySelectorAll('#arcList .arc-row').length===3")
        assert page.locator('#arcList .arc-row').nth(2).locator('.arc-pick').is_disabled(), 'a DeepSeek row can be ticked for deleting'
        if shots: page.wait_for_timeout(400); page.screenshot(path=str(shots / 'archived_sheet.png'))
        page.locator('#arcList .arc-row', has_text='DeepSeek 旧对话').get_by_role('button', name='恢复').click()
        page.wait_for_function("document.querySelectorAll('#arcList .arc-row').length===2")
        assert calls['unarchive'][-1] == {'app': 'deepseek', 'id': 'session-old'}
        page.locator('#arcAll').click(); assert page.locator('#arcDelete').inner_text() == '删除（2）'
        page.locator('#arcDelete').click(); page.wait_for_function("overlays.some(o=>o.id==='confirmSheet')")
        assert '找不回来' in page.locator('#confirmText').inner_text()
        page.locator('#confirmSheet button', has_text='确定').click()
        page.wait_for_function("document.querySelector('#arcList .arc-empty')")
        assert calls['delete'] == [{'items': [{'app': 'codex', 'id': 'old1'}, {'app': 'codex', 'id': 'old2'}], 'confirmed': True}], calls['delete']
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        print('PASS 已归档对话: restore; tick and delete Codex ones after the confirmation; DeepSeek only restores')
        assert not errors, errors
        print('PASS no JavaScript errors')
        browser.close()


if __name__ == '__main__':
    main()
