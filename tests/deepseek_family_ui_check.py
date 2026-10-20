"""Phone-size check of a conversation's children folding under it (10-20), against mock APIs; never touches real chats.

A DeepSeek conversation carries its children (a subagent, one-shot sessions a script started from it): one fold row
under it opens and closes them, 再显示 fetches past the first page, a script's session opens itself and a subagent
opens its conversation (its own record is not readable). DeepSeek's sessions in no workspace are one row,
未分组的会话, that opens and closes the same way. Open folds survive a reload.
"""
import json
from urllib.parse import urlsplit, parse_qs
from playwright.sync_api import sync_playwright
from motion_check import handle, ORIGIN, HERE

MOTHER = 'session-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'


def kid(i, kind='script', status='idle'):
    return {'app': 'deepseek', 'id': f'k{i:03}', 'title': '子任务 0001 至 0010' if kind == 'subagent' else f'batch_step_{i}',
            'kind': kind, 'parent': MOTHER, 'cwd': f'G:/runs/k{i}', 'folder': f'k{i}', 'updated': 1_792_420_000_000 - i * 1000, 'status': status}


def items():
    kids = [kid(0, 'subagent', 'running'), *[kid(i, status='running' if i == 1 else 'idle') for i in range(1, 30)]]
    stray = [{'app': 'deepseek', 'id': f's{i}', 'title': f'batch_worker_{i}', 'kind': 'script', 'parent': '', 'cwd': '',
              'folder': f'w{i}', 'updated': 1_792_419_000_000 - i, 'status': 'idle'} for i in range(2)]
    return [
        {'app': 'deepseek', 'id': MOTHER, 'title': '# 任务：批量处理 100 条', 'folder': 'demo_workspace', 'cwd': 'D:/work/demo',
         'updated': 1_792_420_000_000, 'status': 'idle', 'preview': '对照表已生成', 'children': kids, 'child_count': 35, 'child_running': 2},
        {'app': 'deepseek', 'id': 'ungrouped', 'group': True, 'title': '未分组的会话', 'folder': '', 'cwd': '', 'updated': 1_792_419_000_000,
         'status': 'idle', 'preview': '不在 DeepSeek 工作区里，多是脚本或命令行开的一次性会话', 'children': stray, 'child_count': 2, 'child_running': 0},
        {'app': 'deepseek', 'id': 'session-eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee', 'title': '网页改版方案研究', 'folder': 'site_redesign',
         'cwd': 'D:/work/site', 'updated': 1_792_418_000_000, 'status': 'running', 'preview': ''},
    ]


def main():
    errors, asked = [], []

    def route(r, req):
        url = urlsplit(req.url); path, q = url.path, parse_qs(url.query)
        def reply(v): r.fulfill(status=200, content_type='application/json', body=json.dumps(v, ensure_ascii=False))
        if path == '/':
            html = (HERE / 'remote.html').read_text(encoding='utf-8').replace(
                '<!--machine-->', '<script>window.MACHINE={apps:["codex","claude","deepseek"],voice:false};</script>')
            return r.fulfill(status=200, content_type='text/html', body=html)
        if path == '/api/chats':
            v = items(); return reply({'items': v, 'total': len(v), 'has_more': False, 'next_cursor': None})
        if path == '/api/chats/children':
            asked.append((q['id'][0], int(q['offset'][0])))
            return reply({'items': [kid(i) for i in range(30, 35)], 'total': 35, 'offset': 30})
        if path == '/api/deepseek/state':
            return reply({'available': True, 'running': False, 'settings': {}, 'questions': [], 'interactions': [], 'inbox': {}, 'subagents': []})
        if path == '/api/chat':
            cid = q.get('id', [''])[0]
            return reply({'app': 'deepseek', 'id': cid, 'title': cid, 'folder': 'x', 'status': 'idle', 'runtime': {}, 'messages': [],
                          'subagents': [], 'has_more': False, 'next_cursor': None, 'has_newer': False, 'size': 0, 'total': 0})
        return handle(r, req)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel='chrome')
        page = browser.new_page(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        page.route('**/*', route); page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(ORIGIN); page.wait_for_function("document.querySelectorAll('#convList .conv').length >= 3")

        fold = page.locator('.conv-fold')
        assert fold.inner_text().strip() == '子对话 35 个 · 2 个运行中', fold.inner_text()
        assert page.locator('.conv-child').count() == 0, 'children start folded'
        bucket = page.locator('.conv-group')
        assert bucket.get_attribute('aria-expanded') == 'false' and '2 个' in bucket.inner_text()

        fold.click(); page.wait_for_function("document.querySelectorAll('.conv-child').length === 30")
        assert page.locator('.conv-fold').inner_text().strip().startswith('收起子对话')
        more = page.locator('.conv-more'); assert more.inner_text().strip() == '再显示 5 个（共 35 个）', more.inner_text()
        more.click(); page.wait_for_function("document.querySelectorAll('.conv-child').length === 35 && !document.querySelector('.conv-more')")
        assert asked == [(MOTHER, 30)], asked
        assert '子智能体' in page.locator('.conv-child').first.inner_text()

        page.locator('.conv-child').nth(1).click(); page.wait_for_function("cur && cur.id === 'k001'")  # a script's session: itself
        page.evaluate('closeConv()'); page.wait_for_function('!cur')
        page.locator('.conv-child').first.click(); page.wait_for_function(f"cur && cur.id === '{MOTHER}'")  # a subagent: its conversation
        page.evaluate('closeConv()'); page.wait_for_function('!cur')

        page.locator('.conv-group').click(); page.wait_for_function("document.querySelector('.conv-group').getAttribute('aria-expanded') === 'true'")
        assert page.locator('.conv-child').count() == 37, page.locator('.conv-child').count()
        page.reload(); page.wait_for_function("document.querySelectorAll('.conv-child').length === 32")  # both folds stay open (30 + 2)
        page.locator('.conv-fold').click(); page.wait_for_function("document.querySelectorAll('.conv-child').length === 2")

        unlabelled = page.evaluate("[...document.querySelectorAll('#convList .conv')].filter(r => !r.querySelector(':scope > label.tap-label')).length")
        assert unlabelled == 0, f'{unlabelled} rows without the tap label'
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors, errors
        browser.close()
    print('deepseek family ui check: ok')


if __name__ == '__main__':
    main()
