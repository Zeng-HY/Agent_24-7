"""Phone-size check of the steps that differ by phone (10-20), against mock APIs; never touches real chats or a real
microphone. For an iPhone, an Android phone and a computer, told apart by the browser's user agent:
- the microphone refused (getUserMedia fails with NotAllowedError): the pill says where this phone turns it back on
  (iPhone settings for Safari; Chrome's site settings on Android), and stays inside the screen, also 360 px wide;
- 设置 → 手机通知 before an address is pasted: Bark is an iPhone app, so anywhere else the note says that only an
  iPhone gets the pushes.
Each case gets a fresh browser context.
"""
from playwright.sync_api import TimeoutError as Timeout, sync_playwright
from motion_check import handle, ORIGIN

IPHONE = ('Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) '
          'Version/26.0 Mobile/15E148 Safari/604.1')
ANDROID = ('Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) '
           'Chrome/140.0.0.0 Mobile Safari/537.36')
# name; user agent (None: headless Chrome's own, a Windows computer); screen width; what the pill says; what the note says
CASES = [
    ('iPhone', IPHONE, 390, 'iPhone 设置 → App → Safari → 麦克风', '先在 iPhone 上装 Bark'),
    ('Android', ANDROID, 360, 'Chrome 右上角 ⋮ → 设置 → 网站设置 → 麦克风', '目前只支持 iPhone 上的 Bark'),
    ('computer', None, 390, '在浏览器的网站设置里允许这个网址用麦克风', '目前只支持 iPhone 上的 Bark'),
]
REFUSE = "navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('Permission denied', 'NotAllowedError'));"
PILL = """(() => { const p = document.querySelector('.voice-pill.show'), b = p.getBoundingClientRect();
  return {text: p.textContent, inside: b.left >= 0 && b.right <= innerWidth && b.top >= 0}; })()"""
NOTE = "[...document.querySelectorAll('#settingsBody .setting-note')].at(-1).textContent"


def check(browser, agent, width, mic_says, note_says):
    problems, errors = [], []
    options = {'viewport': {'width': width, 'height': 800}, 'is_mobile': True, 'has_touch': True}
    if agent:
        options['user_agent'] = agent
    context = browser.new_context(**options)
    context.add_init_script(REFUSE)
    page = context.new_page()
    page.route('**/*', handle); page.on('pageerror', lambda e: errors.append(str(e)))
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
    note = page.evaluate(NOTE)
    if note_says not in note:
        problems.append(f'手机通知 says {note!r}, wanted {note_says!r}')
    if not page.evaluate('document.documentElement.scrollWidth <= innerWidth'):
        problems.append('the page is wider than the phone')
    problems += [f'page error: {e}' for e in errors]
    context.close()
    return problems


def main():
    failed = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel='chrome')
        for name, agent, width, mic_says, note_says in CASES:
            problems = check(browser, agent, width, mic_says, note_says)
            print(('FAIL ' if problems else 'PASS ') + name, *problems, sep='\n    ' if problems else '')
            failed += problems
        browser.close()
    assert not failed, failed
    print('phone system ui check: ok')


if __name__ == '__main__':
    main()
