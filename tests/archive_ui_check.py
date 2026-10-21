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
    mode = {'refuse': False, 'slow': 0, 'claude': False}
    archived = [dict(v) for v in ARCHIVED]

    def route(r, req):
        path = urlsplit(req.url).path
        body = json.loads(req.post_data or '{}') if req.method == 'POST' else {}
        def out(v, status=200): r.fulfill(status=status, content_type='application/json', body=json.dumps(v, ensure_ascii=False))
        if path == '/':
            page = (fixture.HERE / 'remote.html').read_text(encoding='utf-8').replace('<!--machine-->', '<script>window.MACHINE={apps:["codex","claude","deepseek"],voice:false,name:"测试电脑"};</script>')
            if mode['claude']:
                page = page.replace('voice:false', 'claude_archive:true,voice:false')
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
            return out({'items': archived, 'problems': [], 'apps': ['codex', 'deepseek'] + (['claude'] if mode['claude'] else []), 'deletable': ['codex']})
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
        def out(key):  # how far the row is out to the left, px
            return -page.evaluate("k => new DOMMatrixReadOnly(getComputedStyle(document.querySelector('#convList .conv[data-key=\"' + k + '\"]')).transform).m41", key)
        def is_open(): return page.evaluate("!!document.querySelector('.swipe-under.open')")
        def bar_shown(): return page.evaluate("document.getElementById('archiveUndo').classList.contains('show')")
        def settle(): page.wait_for_timeout(450)
        def tap_button():  # the 归档 button of the open row
            b = page.locator('.swipe-under.open .swipe-btn').bounding_box(); finger.tap(b['x'] + b['width'] / 2, b['y'] + b['height'] / 2)
        def tap_off_list():  # the page title, off the list
            b = page.locator('header').first.bounding_box(); finger.tap(b['x'] + b['width'] / 2, b['y'] + b['height'] - 12)

        # first stop: a short slow slide settles open on the 归档 button and archives nothing
        swipe('codex:cx1', 70, steps=10, step=30); settle()
        assert is_open() and abs(out('codex:cx1') - 88) < 1, out('codex:cx1')
        assert not calls['archive'] and not bar_shown()
        if shots: page.screenshot(path=str(shots / 'swipe_open.png'))
        # a refresh meanwhile leaves it open; the list is rebuilt once it is shut
        old = page.evaluate_handle("document.querySelector('#convList .conv[data-key=\"codex:cx1\"]')")
        page.evaluate('renderConvs()'); page.wait_for_timeout(500)  # what a refresh with news does
        assert is_open() and abs(out('codex:cx1') - 88) < 1, 'a refresh shut the open row'
        # a tap on the open row shuts it and does not open the conversation
        x, y, w = box('codex:cx1'); finger.tap(x + w / 2, y); settle()
        assert not page.locator('.swipe-under').count() and abs(out('codex:cx1')) < 1 and page.evaluate('cur') is None
        assert page.evaluate("o => document.querySelector('#convList .conv[data-key=\"codex:cx1\"]') !== o", old), 'the list was not rebuilt after the row shut'
        print('PASS a short slide stops on 归档; a refresh waits; a tap shuts it without opening the conversation')

        # the hold at the button, and 归档 keeping beside the row's edge with no lag (no CSS transition on it)
        seen = {}
        def probe(name):
            seen[name] = page.evaluate("""() => { const u = document.querySelector('.swipe-under'), l = u.querySelector('.swipe-label'), r = u.nextElementSibling;
              return {out: -new DOMMatrixReadOnly(getComputedStyle(r).transform).m41, gap: l.getBoundingClientRect().left - r.getBoundingClientRect().right,
                      trans: getComputedStyle(l).transitionDuration, armed: u.classList.contains('armed')}; }""")
        x, y, w = box('deepseek:session-ds1'); sx = x + w - 30
        finger._send('touchStart', [(sx, y)])
        for d in (20, 40, 60, 80, 88, 100, 112, 118, 150, 180, 214):
            page.wait_for_timeout(40); finger._send('touchMove', [(sx - d, y)]); page.wait_for_timeout(40)
            if d in (88, 112, 150, 214): probe(d)
        page.wait_for_timeout(300); probe('still')
        if shots: page.screenshot(path=str(shots / 'swipe_armed.png'))
        finger._send('touchMove', [(sx - 60, y)]); page.wait_for_timeout(60); finger._send('touchEnd', []); settle()  # back short of the mark: open
        assert abs(seen[88]['out'] - 88) < 1.5, seen[88]
        assert 88 < seen[112]['out'] < 97, seen[112]               # 24 px of finger, about 7 of row
        assert abs(seen[150]['out'] - 129) < 2, seen[150]           # then 1:1 again, 21 px behind
        assert not seen[150]['armed'] and seen[214]['armed'] and seen['still']['armed'], seen
        assert abs(seen[150]['gap'] - 20) < 1.5 and abs(seen[214]['gap'] - 20) < 1.5, seen  # beside the edge, frame by frame
        assert all(v['trans'] in ('0s', '0s, 0s') for v in seen.values()), seen
        assert is_open() and not calls['archive'], 'dragging back short of the mark did not leave it open'
        tap_off_list(); settle(); assert not page.locator('.swipe-under').count(), 'a tap off the list left it open'
        print('PASS it holds at the button, keeps 归档 beside its edge without lag, darkens only past the mark')

        # a quick flick only opens; a touch on another row shuts it and opens nothing; a scroll shuts it too
        x, y, w = box('codex:cx3'); finger.drag([(x + w - 30 - 40 * i, y) for i in range(4)], step=12); settle()
        assert is_open() and not calls['archive'], 'a flick did more than open'
        x, y, w = box('codex:cx5'); finger.tap(x + w / 2, y); settle()
        assert not page.locator('.swipe-under').count() and page.evaluate('cur') is None
        swipe('codex:cx3', 70, steps=10, step=30); settle(); assert is_open()
        x, y, w = box('codex:cx6'); finger.drag([(x + w / 2, y + i * 14) for i in range(8)]); settle()
        assert not page.locator('.swipe-under').count(), 'a scroll left the row open'
        # a rightward drag on an open row shuts it and does not pull the drawer out
        swipe('codex:cx3', 70, steps=10, step=30); settle(); assert is_open()
        x, y, w = box('codex:cx3'); finger.drag([(x + w - 120 + 15 * i, y) for i in range(9)], step=20); settle()
        assert not page.locator('.swipe-under').count() and not page.evaluate("overlays.some(o=>o.id==='navSheet')")
        print('PASS a flick only opens; another row, a scroll or a drag back shuts it; the drawer stays put')

        # tapping 归档 archives: off to the left, a pause, the list closes up smoothly, then the bar
        swipe('codex:cx4', 70, steps=10, step=30); settle(); assert is_open()
        page.evaluate("""() => { window.__h = []; const r = document.querySelector('#convList .conv[data-key="codex:cx4"]');
          const t0 = performance.now(); (function f() { window.__h.push([performance.now() - t0, r.isConnected ? r.offsetHeight : -1,
          document.getElementById('archiveUndo').classList.contains('show')]); if (r.isConnected) requestAnimationFrame(f); })(); }""")
        tap_button()
        page.wait_for_function("!document.querySelector('#convList .conv[data-key=\"codex:cx4\"]')")
        h = page.evaluate('window.__h'); full = h[0][1]
        assert calls['archive'] == [{'app': 'codex', 'id': 'cx4'}], calls['archive']
        middle = [v for v in h if 0 < v[1] < full - 1]
        assert len(middle) >= 5, h            # the list closes up over several frames, not at once
        assert middle[0][0] > 380, middle[0]  # only after the row is off
        assert not any(v[2] for v in h if v[0] < 380), 'the bar came up before the row was off'
        assert 700 < h[-1][0] < 1200, h[-1]   # about 0.8 s in all
        page.wait_for_function("document.getElementById('archiveUndo').classList.contains('show')")
        assert '示例对话 4' in page.locator('#archiveUndo').inner_text() and not page.locator('.swipe-under').count()
        page.locator('#archiveUndo button').click()
        page.wait_for_function("!!document.querySelector('#convList .conv[data-key=\"codex:cx4\"]')")
        for _ in range(30):
            if calls['unarchive']: break
            page.wait_for_timeout(100)
        assert calls['unarchive'] == [{'app': 'codex', 'id': 'cx4'}], calls['unarchive']
        print('PASS tapping 归档 archives; the row goes, then the list closes up over', len(middle), 'frames, then 撤销 shows')

        # past the mark, letting go archives at once; a refresh keeps it off; 撤销 brings it back in its place
        def armed_shot():
            assert page.evaluate("document.querySelector('.swipe-under')?.classList.contains('armed')"), 'not armed past the mark'
        swipe('codex:cx1', 260, hold=(12, 120, armed_shot))
        page.wait_for_function("!document.querySelector('#convList .conv[data-key=\"codex:cx1\"]')")
        assert calls['archive'][-1] == {'app': 'codex', 'id': 'cx1'} and len(calls['archive']) == 2, calls['archive']
        page.wait_for_function("document.getElementById('archiveUndo').classList.contains('show')")
        assert page.locator('#archiveUndo').inner_text().startswith('对话已归档') and '部署方案' in page.locator('#archiveUndo').inner_text()
        if shots: page.wait_for_timeout(350); page.screenshot(path=str(shots / 'undo_bar.png'))
        page.evaluate('loadConvs()'); page.wait_for_timeout(400)
        assert row('codex:cx1').count() == 0, 'a refresh brought the archived row back'
        page.locator('#archiveUndo button').click()
        page.wait_for_function("!!document.querySelector('#convList .conv[data-key=\"codex:cx1\"]')")
        for _ in range(30):
            if len(calls['unarchive']) == 2: break
            page.wait_for_timeout(100)
        assert calls['unarchive'][-1] == {'app': 'codex', 'id': 'cx1'}
        assert [n for n in page.evaluate("[...document.querySelectorAll('#convList .conv')].map(n=>n.dataset.key)")][:2] == ['codex:cx1', 'deepseek:session-ds1']
        assert not bar_shown()
        print('PASS a full swipe archives with 撤销; a refresh keeps it off; 撤销 brings it back in its place')

        # a scroll and a Claude row archive nothing
        x, y, w = box('codex:cx3'); finger.drag([(x + w / 2, y + i * 14) for i in range(10)])  # a scroll
        x, y, w = box('claude:local_cl1'); finger.drag([(x + w - 30 - i * 25, y) for i in range(11)])
        page.wait_for_timeout(400)
        assert len(calls['archive']) == 2 and not page.locator('.swipe-under').count()
        assert row('claude:local_cl1').count() == 1
        print('PASS a scroll and a Claude row archive nothing')

        # a running one springs back and says why, by a full swipe or by its button; one the computer refuses slides back
        swipe('codex:cx2', 260); page.wait_for_timeout(450)
        assert row('codex:cx2').count() == 1 and len(calls['archive']) == 2 and not page.locator('.swipe-under').count()
        assert '正在运行' in page.locator('#toast').inner_text()
        page.evaluate("document.getElementById('toast').textContent=''")
        swipe('codex:cx2', 70, steps=10, step=30); settle(); tap_button(); settle()
        assert len(calls['archive']) == 2 and '正在运行' in page.locator('#toast').inner_text() and not page.locator('.swipe-under').count()
        mode['refuse'] = True; swipe('deepseek:session-ds1', 260)
        page.wait_for_function("document.getElementById('toast').textContent.includes('没归档')")
        page.wait_for_timeout(900)
        assert row('deepseek:session-ds1').count() == 1 and abs(out('deepseek:session-ds1')) < 1 and not page.locator('.swipe-under').count()
        assert calls['archive'][-1] == {'app': 'deepseek', 'id': 'session-ds1'}; mode['refuse'] = False
        assert not bar_shown()
        print('PASS a running one is not archived; a refusal slides the row back with the reason')

        # a tiny slide shuts again; a tap afterwards opens the conversation
        swipe('codex:cx5', 20, steps=5, step=30); settle()
        assert not page.locator('.swipe-under').count(), 'a 20 px slide did not shut again'
        x, y, w = box('codex:cx5'); finger.tap(x + w / 2, y)
        page.wait_for_function("cur?.id==='cx5'"); page.evaluate('closeConv(true)'); page.wait_for_timeout(300)
        swipe('codex:cx3', 20, steps=5, step=30); x, y, w = box('codex:cx4'); finger.tap(x + w / 2, y)  # while it is still going back
        page.wait_for_function("cur?.id==='cx4'"); page.evaluate('closeConv(true)'); page.wait_for_timeout(400)
        assert not page.locator('.swipe-under').count()
        print('PASS a tiny slide shuts again; a tap after a swipe, even at once, still opens the conversation')

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
        mode['claude'] = True
        page.reload()
        page.wait_for_function('!!window.archiveUI && document.querySelectorAll("#convList .conv").length>10')
        page.evaluate("""() => {
          const baseApi = api;
          api = (path, ...args) => path === '/api/chat/archive'
            ? new Promise(resolve => { window.finishArchive = () => resolve({ok:true, archived:true}); })
            : baseApi(path, ...args);
        }""")
        swipe('claude:local_cl1', 270, steps=16, step=30)
        page.wait_for_function("document.querySelector('#archiveUndo').textContent.includes('正在归档')")
        assert page.locator('#archiveUndo button').is_disabled()
        page.evaluate('finishArchive()')
        page.wait_for_function("document.querySelector('#archiveUndo').textContent.includes('对话已归档')")
        assert page.locator('#archiveUndo button').is_enabled()
        page.locator('#archiveUndo button').click()
        page.wait_for_function("!archiveUI.hidden.includes('claude:local_cl1')")
        page.wait_for_timeout(300)
        assert calls['unarchive'][-1] == {'app': 'claude', 'id': 'local_cl1'}
        archived.append({'app': 'claude', 'id': 'local_old', 'title': 'Claude 已归档测试', 'can_delete': False})
        page.evaluate('archiveUI.openArchived()')
        page.wait_for_function("document.querySelectorAll('#arcList .arc-row').length===1")
        assert page.locator('#arcList .arc-pick').is_disabled()
        assert '暂不支持删除' in page.locator('#arcNote').inner_text()
        page.locator('#arcList').get_by_role('button', name='恢复').click()
        page.wait_for_function("document.querySelector('#arcList .arc-empty')")
        assert calls['unarchive'][-1] == {'app': 'claude', 'id': 'local_old'}
        print('PASS Claude waits for readback, enables undo after success, restores archived items and disallows deletion')
        assert not errors, errors
        print('PASS no JavaScript errors')
        browser.close()


if __name__ == '__main__':
    main()
