"""Isolated browser checks: real UI, synthetic transcripts, no live sessions."""
from pathlib import Path
from urllib.parse import urlsplit
import mimetypes
from playwright.sync_api import sync_playwright
from motion_check import handle, ORIGIN
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/interaction-check';OUT.mkdir(parents=True,exist_ok=True)
def route(r):
    path=urlsplit(r.request.url).path
    name=path.rsplit('/',1)[-1]
    if path=='/api/chat/diff':return r.fulfill(json={'path':'theme.css','scope':'file','hunks':['@@ -1,2 +1,2 @@\n-old\n+new\n same'],'next':None})
    if (ROOT/'static'/name).is_file():return r.fulfill(path=str(ROOT/'static'/name),content_type=mimetypes.guess_type(name)[0] or 'application/octet-stream')
    return handle(r,r.request)
with sync_playwright() as p:
    for engine in ('chromium','webkit'):
        browser=getattr(p,engine).launch(**({'channel':'chrome'} if engine=='chromium' else {}))
        for width,height in [(390,844),(844,390),(1280,900)]:
            context=browser.new_context(viewport={'width':width,'height':height},has_touch=True)
            context.route('**/*',route);page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(ORIGIN+'/');page.wait_for_function('window.interactionUI');page.wait_for_selector('.conv')
            page.get_by_role('button',name='列表显示选项').click();page.wait_for_timeout(300)
            assert page.locator('#displayMenu').evaluate('(n)=>n.getBoundingClientRect().bottom<=innerHeight+1')
            page.locator('#displayMenu button').first.click();page.get_by_role('button',name='按项目',exact=True).click()
            page.keyboard.press('Escape');page.wait_for_timeout(250)
            assert page.locator('.display-group').count()>0
            page.locator('.conv').first.click();page.wait_for_timeout(500)
            page.evaluate("""() => {
                window.readingUI.pauseStream?.(); cur.status='running';
                interactionUI.meta({activity_turns:{test:{started_at:Date.now()-19000,status:'running'}}});
                renderMsgs([{id:'u',role:'user',text:'测试'}, {id:'t',role:'tool',activity_turn:'test',text:'修改 theme.css',tool_status:'completed',changes:[{path:'theme.css',ref:'r',added:1,removed:1}]}, {id:'n',role:'assistant',phase:'commentary',activity_turn:'test',text:'检查主题'}]);
            }""")
            assert page.locator('.activity-group').count()==1
            assert '19秒' in page.locator('.activity-clock').inner_text() or '20秒' in page.locator('.activity-clock').inner_text()
            page.locator('.file-change').click();page.wait_for_selector('.diff-line.add')
            assert page.locator('.diff-line.delete').inner_text().endswith('-old')
            assert page.locator('#diffSheet').evaluate('(n)=>n.getBoundingClientRect().width<=innerWidth+1')
            page.wait_for_timeout(350);page.screenshot(path=str(OUT/f'diff-{engine}-{width}.png'))
            page.get_by_role('button',name='差异显示选项',exact=True).click()
            page.get_by_role('button',name='自动换行',exact=True).click()
            assert 'wrap' in page.locator('.diff-content').get_attribute('class')
            if width>=1024:
                page.get_by_role('button',name='左右对照',exact=True).click()
                assert page.locator('.diff-side').is_visible()
            page.keyboard.press('Escape');page.wait_for_timeout(180)
            page.get_by_role('button',name='返回',exact=True).click();page.wait_for_timeout(220)
            page.evaluate("TeleplyTheme.set('dark')")
            page.wait_for_timeout(350);page.screenshot(path=str(OUT/f'activity-dark-{engine}-{width}.png'))
            page.locator('.activity-heading').click()
            assert page.locator('.activity-body').is_hidden()
            page.evaluate('renderMsgs(currentMessages)')
            assert page.locator('.activity-body').is_hidden()
            page.emulate_media(reduced_motion='reduce')
            assert not errors,errors
            context.close()
        browser.close()
print('interaction UI checks passed')
