"""Phone-size check that the page shows only the desktop apps this computer has (10-20), against mock APIs; never
touches real chats.

For each kind of computer (window.MACHINE.apps, as remote.py puts it into the page): the filter chips above the list
(no row when one app is left), the new-conversation sheet's app buttons (no row when one is left, and the picked app is
one that is there), DeepSeek alone opening its own sheet from 新建, and with no app found the list and 新建 saying so.
Each kind gets a fresh browser, so a draft one leaves in the page's storage cannot steer the next.
"""
import json
from urllib.parse import urlsplit
from playwright.sync_api import TimeoutError as Timeout, sync_playwright
from motion_check import handle, ORIGIN, HERE

ROWS = {app: {'app': app, 'id': f'{app}-1', 'title': f'{app} 示例对话', 'folder': 'demo', 'cwd': 'D:/work/demo',
              'updated': 1_792_420_000_000, 'status': 'idle', 'preview': ''} for app in ('codex', 'claude', 'deepseek')}
NAMES = {'codex': 'Codex', 'claude': 'Claude', 'deepseek': 'DeepSeek'}
# apps; chips beside 全部 (None: no row); the sheet's app buttons (None: no row); what 新建 opens
CASES = [
    (['codex', 'claude', 'deepseek'], ['codex', 'claude', 'deepseek'], ['Codex', 'Claude', 'DeepSeek'], 'newSheet'),
    (['codex', 'claude'], ['codex', 'claude'], ['Codex', 'Claude'], 'newSheet'),
    (['codex', 'deepseek'], ['codex', 'deepseek'], ['Codex', 'DeepSeek'], 'newSheet'),
    (['claude', 'deepseek'], ['claude', 'deepseek'], ['Claude', 'DeepSeek'], 'newSheet'),
    (['codex'], None, None, 'newSheet'),
    (['claude'], None, None, 'newSheet'),
    (['deepseek'], None, None, 'deepseekNew'),
    ([], None, None, 'toast'),
]
CHIPS = """(() => { const row = document.querySelector('.conversation-home .chips');
  if (getComputedStyle(row).display === 'none') return null;
  return [...row.querySelectorAll('.chip[data-app]')].filter(c => c.dataset.app !== 'all' && getComputedStyle(c).display !== 'none')
    .map(c => c.dataset.app); })()"""
SHEET = """(() => { const row = document.querySelector('#newSheet .new-apps');
  const shown = row.hidden ? null : [...row.children].filter(b => !b.hidden).map(b => b.textContent.trim());
  const picked = ['newCodex', 'newClaude'].filter(id => document.getElementById(id).getAttribute('aria-checked') === 'true')
    .map(id => document.getElementById(id).textContent.trim());
  return {shown, picked}; })()"""


def check(browser, apps, chips, buttons, opens):
    problems, errors = [], []

    def route(r, req):
        path = urlsplit(req.url).path
        if path == '/':
            facts = json.dumps({'name': '测试电脑', 'apps': apps, 'voice': False}, ensure_ascii=False)
            html = (HERE / 'remote.html').read_text(encoding='utf-8').replace('<!--machine-->', f'<script>window.MACHINE={facts};</script>')
            return r.fulfill(status=200, content_type='text/html', body=html)
        if path == '/api/chats':  # the service lists only the apps this computer has
            rows = [ROWS[a] for a in apps]
            return r.fulfill(status=200, content_type='application/json',
                             body=json.dumps({'items': rows, 'total': len(rows), 'has_more': False, 'next_cursor': None}, ensure_ascii=False))
        return handle(r, req)

    context = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
    page = context.new_page()
    page.route('**/*', route); page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(ORIGIN)
    page.wait_for_function("window.newChatUI && !document.querySelector('#convList').textContent.includes('读取中')")
    seen = page.evaluate(CHIPS)
    if seen != chips:
        problems.append(f'chips {seen}, wanted {chips}')
    listed = page.evaluate("[...document.querySelectorAll('#convList .conv')].length")
    if listed != len(apps):
        problems.append(f'{listed} rows in the list, wanted {len(apps)}')
    if not apps and '没找到' not in page.locator('#convList').inner_text():
        problems.append('the empty list does not say no desktop app was found')

    def waited(condition, problem):  # a wait that runs out is a finding, not the end of the run
        try:
            page.wait_for_function(condition, timeout=8000)
            return True
        except Timeout:
            problems.append(problem)
            return False

    page.locator('header button[aria-label="新建对话"]').click()
    if opens == 'newSheet':
        if waited("getComputedStyle(document.getElementById('newSheet')).display !== 'none'", 'the new-conversation sheet did not open'):
            sheet = page.evaluate(SHEET)
            if sheet['shown'] != buttons:
                problems.append(f"sheet buttons {sheet['shown']}, wanted {buttons}")
            installed = [NAMES[a] for a in apps if a != 'deepseek']
            if len(sheet['picked']) != 1 or sheet['picked'][0] not in installed:
                problems.append(f"picked {sheet['picked']}, wanted one of {installed}")
    elif opens == 'deepseekNew':
        waited("getComputedStyle(document.getElementById('deepseekNew')).display !== 'none'", "新建 did not open DeepSeek's sheet")
        if page.evaluate("getComputedStyle(document.getElementById('newSheet')).display") != 'none':
            problems.append('the Codex/Claude sheet opened on a computer with DeepSeek alone')
    else:
        waited("document.getElementById('toast').textContent.includes('没找到')", '新建 did not say no desktop app was found')
        if page.evaluate("getComputedStyle(document.getElementById('newSheet')).display") != 'none':
            problems.append('the new-conversation sheet opened with no desktop app')
    if not page.evaluate('document.documentElement.scrollWidth <= innerWidth'):
        problems.append('the page is wider than the phone')
    problems += [f'page error: {e}' for e in errors]
    context.close()
    return problems


def main():
    failed = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel='chrome')
        for apps, chips, buttons, opens in CASES:
            problems = check(browser, apps, chips, buttons, opens)
            print(('FAIL ' if problems else 'PASS ') + (' + '.join(apps) or 'no desktop app'), *problems, sep='\n    ' if problems else '')
            failed += problems
        browser.close()
    assert not failed, failed
    print('app visibility ui check: ok')


if __name__ == '__main__':
    main()
