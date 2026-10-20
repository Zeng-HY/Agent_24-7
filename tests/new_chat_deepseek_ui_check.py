"""Phone-size check of a new DeepSeek conversation from the shared new-conversation sheet (10-20), against mock APIs;
never touches real chats.

DeepSeek is one of the three buttons like Codex and Claude: picking it lists DeepSeek's workspaces (no 无项目, no skills)
and its models with their steps; the first message goes in one request (app deepseek, the workspace, the model); a job
that failed before anything happened goes again with 继续发送 under the same request, once; then the conversation opens.
A workspace's ＋ in the sidebar opens this same sheet with DeepSeek and that workspace picked.
"""
import json
from urllib.parse import urlsplit, parse_qs
from playwright.sync_api import sync_playwright
from motion_check import handle, ORIGIN, HERE

RID = 'd' * 32
WORKSPACE = {'path': 'D:/work/demo_workspace', 'name': 'demo', 'sources': ['DeepSeek 工作区']}
PROJECT = {'path': 'D:/Projects/notes_app', 'name': 'notes_app', 'sources': ['Codex 项目']}
MODELS = {'models': [{'id': 'deepseek-account/deepseek-flash', 'label': 'DeepSeek-V4.1-Flash',
                      'efforts': [{'id': 'off', 'label': '关'}, {'id': 'high', 'label': '高'}], 'default_effort': 'high'}], 'note': ''}


def main():
    errors, posts, retries = [], [], []
    phase = {'now': 'creating'}

    def route(r, req):
        url = urlsplit(req.url); path, q = url.path, parse_qs(url.query)
        def reply(v): r.fulfill(status=200, content_type='application/json', body=json.dumps(v, ensure_ascii=False))
        if path == '/':
            html = (HERE / 'remote.html').read_text(encoding='utf-8').replace(
                '<!--machine-->', '<script>window.MACHINE={apps:["codex","claude","deepseek"],voice:false};</script>')
            return r.fulfill(status=200, content_type='text/html', body=html)
        if path == '/api/chat/folders':
            return reply({'items': [WORKSPACE] if q.get('app') == ['deepseek'] else [PROJECT]})
        if path == '/api/chat/new/options':
            return reply(MODELS if q.get('app') == ['deepseek'] else {'models': [], 'note': ''})
        if path == '/api/chat/new/draft':
            return reply({'request_id': RID})
        if path == '/api/chat/new':
            posts.append(json.loads(req.post_data)); return reply({'request_id': RID, 'state': 'creating', 'message': '正在创建对话…'})
        if path == '/api/chat/new/retry':
            retries.append(json.loads(req.post_data)); phase['now'] = 'accepted'; return reply({'request_id': RID, 'state': 'creating'})
        if path == '/api/chat/new/timing':
            return reply({'ok': True})
        if path == '/api/chat/new/state':
            if phase['now'] == 'failed':
                return reply({'request_id': RID, 'app': 'deepseek', 'state': 'failed', 'not_submitted': True, 'title': '新对话', 'folder': 'demo',
                              'message': 'DeepSeek 没有回应，请确认电脑上的 DeepSeek Harness 开着'})
            if phase['now'] == 'accepted':
                return reply({'request_id': RID, 'app': 'deepseek', 'state': 'accepted', 'id': 'session-new', 'title': '新对话', 'folder': 'demo',
                              'message': '首条消息已送达'})
            return reply({'request_id': RID, 'app': 'deepseek', 'state': 'creating', 'title': '新对话', 'folder': 'demo', 'message': '正在创建对话…'})
        if path == '/api/deepseek/state':
            return reply({'available': True, 'running': False, 'status': 'idle', 'settings': {}, 'questions': [], 'interactions': [], 'inbox': {},
                          'subagents': [], 'queued': []})
        if path == '/api/chat' and q.get('id') == ['session-new']:
            return reply({'app': 'deepseek', 'id': 'session-new', 'title': '新对话', 'folder': 'demo', 'status': 'idle', 'runtime': {},
                          'messages': [{'id': '1', 'role': 'user', 'text': '你好', 'order': 1, 'time': '2026-10-20T08:00:00+00:00'}],
                          'subagents': [], 'has_more': False, 'next_cursor': None, 'has_newer': False, 'size': 1, 'total': 1})
        return handle(r, req)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel='chrome')
        page = browser.new_page(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        page.route('**/*', route); page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(ORIGIN); page.wait_for_function('!!window.newChatUI')

        # the three buttons in the shared sheet; DeepSeek's own sheet is gone
        page.locator('header button[aria-label="新建对话"]').click(); page.wait_for_function("overlays.some(v => v.id === 'newSheet')")
        assert page.evaluate("[...document.querySelectorAll('#newSheet .new-apps button')].filter(b => !b.hidden).map(b => b.textContent)") == ['Codex', 'Claude', 'DeepSeek']
        assert page.evaluate("!document.getElementById('deepseekNew')"), 'the old DeepSeek sheet is still on the page'
        page.locator('#newDeepseek').click()
        page.wait_for_function("document.getElementById('newFolderName').textContent === 'demo'")  # its workspace, not a Codex project
        assert page.evaluate("document.getElementById('newDeepseek').getAttribute('aria-checked')") == 'true'

        # its workspaces only: no 无项目
        page.locator('#newFolderChoice').click(); page.wait_for_function("document.querySelectorAll('#newPickerResults .new-pick-row').length >= 1")
        rows = page.evaluate("[...document.querySelectorAll('#newPickerResults .new-pick-row')].map(b => b.firstChild.textContent)")
        assert rows == ['demo'], rows
        page.evaluate("closeSheet('newPicker')")
        # no skills for DeepSeek
        assert page.evaluate("getComputedStyle(document.getElementById('newSkillRef')).display") == 'none'

        # its models and steps
        page.locator('#newModelChoice').click(); page.get_by_role('radio', name='DeepSeek-V4.1-Flash').click()
        page.wait_for_function("[...document.querySelectorAll('#newEffortRows button')].map(b => b.textContent).join() === '关,高'")
        page.locator('#newEffortRows button', has_text='高').click(); page.locator('#newModelDone').click()
        page.wait_for_function("document.getElementById('newModelName').textContent === 'DeepSeek-V4.1-Flash · 高'")

        # one request: the conversation and its first message
        page.locator('#newText').fill('你好'); phase['now'] = 'failed'; page.locator('#newBtn').click()
        page.wait_for_function("document.querySelector('#newInlineStatus')?.textContent.includes('没发出去')")
        assert len(posts) == 1, posts
        body = posts[0]
        assert (body['app'], body['folder'], body['text'], body['settings']) == ('deepseek', 'D:/work/demo_workspace', '你好',
                                                                                 {'model': 'deepseek-account/deepseek-flash', 'effort': 'high'}), body
        assert not body.get('projectless')

        # 继续发送 goes again under the same request, once, and the conversation opens
        page.locator('#newInlineStatus').click(); page.wait_for_function("overlays.some(v => v.id === 'newJobSheet')")
        page.locator('#newRetry').click()
        page.wait_for_function("!document.getElementById('newOpen').hidden", timeout=15000)  # the sheet stays open: 打开对话
        page.locator('#newOpen').click()
        page.wait_for_function("cur?.app === 'deepseek' && cur?.id === 'session-new'", timeout=15000)
        assert retries == [{'request_id': RID}], retries
        assert len(posts) == 1, 'a second creation request was sent'

        # a workspace's ＋ in the sidebar opens the same sheet with DeepSeek and that workspace
        page.evaluate("closeConv(true)")
        page.evaluate("newChatUI.open({app: 'deepseek', folder: 'D:/work/demo_workspace', name: 'demo'})")
        page.wait_for_function("overlays.some(v => v.id === 'newSheet')")
        assert page.evaluate("document.getElementById('newDeepseek').getAttribute('aria-checked')") == 'true'
        page.wait_for_function("document.getElementById('newFolderName').textContent === 'demo'")
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors, errors
        browser.close()
    print('new DeepSeek conversation ui check: shared sheet, workspaces only, no skills, models, one request, continue once, opens; sidebar + PASS')


if __name__ == '__main__':
    main()
