"""Phone-size check of the steps that differ by phone (10-20), against mock APIs; never touches real chats or a real
microphone. For an iPhone, an Android phone and a computer, told apart by the browser's user agent:
- the microphone refused (getUserMedia fails with NotAllowedError): the pill says where this phone turns it back on
  (iPhone settings for Safari; Chrome's site settings on Android), and stays inside the screen, also 360 px wide;
- 设置 → 手机通知: an iPhone sees Bark only, an Android phone ntfy only (the topic and this page's address to type
  into the ntfy app, each copied by a tap), a computer both, Bark last. On Android 打开并试推一条 turns ntfy on, and
  the rows then say whether a phone is connected. Nothing runs off the 360 px screen.
Each case gets a fresh browser context.
"""
import json
from urllib.parse import urlsplit

from playwright.sync_api import TimeoutError as Timeout, sync_playwright
from motion_check import handle, ORIGIN

IPHONE = ('Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) '
          'Version/26.0 Mobile/15E148 Safari/604.1')
ANDROID = ('Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) '
           'Chrome/140.0.0.0 Mobile Safari/537.36')
# name; user agent (None: headless Chrome's own, a Windows computer); screen width; what the pill says; the channels
# shown, in order; what their notes say
CASES = [
    ('iPhone', IPHONE, 390, 'iPhone 设置 → App → Safari → 麦克风', ['bark'], ['先在 iPhone 上装 Bark']),
    ('Android', ANDROID, 360, 'Chrome 右上角 ⋮ → 设置 → 网站设置 → 麦克风', ['ntfy'], ['安卓手机用 ntfy App 收']),
    ('computer', None, 390, '在浏览器的网站设置里允许这个网址用麦克风', ['ntfy', 'bark'], ['安卓手机用 ntfy App 收', 'iPhone 用 Bark 收']),
]
REFUSE = "navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('Permission denied', 'NotAllowedError'));"
PILL = """(() => { const p = document.querySelector('.voice-pill.show'), b = p.getBoundingClientRect();
  return {text: p.textContent, inside: b.left >= 0 && b.right <= innerWidth && b.top >= 0}; })()"""
SETTINGS = """(() => {
  const groups = [...document.querySelectorAll('#settingsBody .setting-group[data-channel]')];
  const rows = c => [...document.querySelectorAll(`#settingsBody .setting-group[data-channel=${c}] .setting-row`)];
  return {channels: groups.map(g => g.dataset.channel),
    notes: [...document.querySelectorAll('#settingsBody .setting-note[data-channel]')].map(n => n.textContent),
    ntfy: rows('ntfy').map(r => r.innerText.replace(/\\s+/g, ' ').trim()),
    inside: [...document.querySelectorAll('#settingsBody .setting-row')].every(r => r.getBoundingClientRect().right <= innerWidth + 0.5),
    wide: document.documentElement.scrollWidth > innerWidth}; })()"""


def check(browser, agent, width, mic_says, channels, notes_say):
    problems, errors, posts = [], [], []
    told = {'configured': False, 'server': '', 'recent': [],
            'ntfy': {'on': False, 'topic': 'agent-remote', 'server': 'https://pc.example.ts.net', 'listening': 0, 'last_seen': ''}}

    def route(r, req):
        path = urlsplit(req.url).path
        if path == '/api/notify' and req.method == 'GET':
            return r.fulfill(status=200, content_type='application/json', body=json.dumps(told, ensure_ascii=False))
        if path in ('/api/notify/ntfy', '/api/notify/test'):
            posts.append((path, json.loads(req.post_data or '{}')))
            if path.endswith('/ntfy'):
                told['ntfy']['on'] = posts[-1][1].get('on') is True
            return r.fulfill(status=200, content_type='application/json', body=json.dumps({'ok': True, 'text': '已打开'}, ensure_ascii=False))
        return handle(r, req)

    options = {'viewport': {'width': width, 'height': 800}, 'is_mobile': True, 'has_touch': True}
    if agent:
        options['user_agent'] = agent
    context = browser.new_context(**options)
    context.add_init_script(REFUSE)
    page = context.new_page()
    page.route('**/*', route); page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(ORIGIN + '/?open=codex:c3')
    page.wait_for_function("window.voiceUI && typeof cur !== 'undefined' && cur && cur.id === 'c3'", timeout=20000)
    page.locator('.mic-btn').tap()
    try:
        page.wait_for_function("!!document.querySelector('.voice-pill.show')", timeout=8000)
        pill = page.evaluate(PILL)
        if mic_says not in pill['text']:
            problems.append(f"the refused microphone says {pill['text']!r}, wanted {mic_says!r}")
        if not pill['inside']:
            problems.append('the pill runs off the screen')
    except Timeout:
        problems.append('nothing was said when the microphone was refused')
    page.evaluate("closeConv(true); openSheet('settingsSheet')")
    page.wait_for_timeout(500)
    seen = page.evaluate(SETTINGS)
    if seen['channels'] != channels:
        problems.append(f"手机通知 shows {seen['channels']}, wanted {channels}")
    for want, note in zip(notes_say, seen['notes']):
        if want not in note:
            problems.append(f'a note says {note!r}, wanted {want!r}')
    if 'ntfy' in channels:
        if seen['ntfy'][:2] != ['主题 agent-remote', '服务器 ' + ORIGIN]:
            problems.append(f"the ntfy rows are {seen['ntfy']}, wanted the topic and {ORIGIN}")
        page.locator("#settingsBody [data-channel=ntfy] .menu-row:has-text('打开并试推一条')").tap()
        page.wait_for_timeout(600)
        after = page.evaluate(SETTINGS)
        if posts[-1:] != [('/api/notify/ntfy', {'on': True})]:
            problems.append(f'打开并试推一条 sent {posts[-1:]}')
        if after['ntfy'][:1] != ['已开 · ntfy 手机没连着'] or '现在没有手机连着' not in after['notes'][0]:
            problems.append(f"after turning ntfy on: {after['ntfy'][:1]}, {after['notes'][:1]}")
        seen = after
    if not seen['inside'] or seen['wide']:
        problems.append('a settings row runs off the screen')
    problems += [f'page error: {e}' for e in errors]
    context.close()
    return problems


def main():
    failed = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel='chrome')
        for name, *case in CASES:
            problems = check(browser, *case)
            print(('FAIL ' if problems else 'PASS ') + name, *problems, sep='\n    ' if problems else '')
            failed += problems
        browser.close()
    assert not failed, failed
    print('phone system ui check: ok')


if __name__ == '__main__':
    main()
