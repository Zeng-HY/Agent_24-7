"""Real UI, synthetic code/tool records; never connects to a live conversation."""
from pathlib import Path
from urllib.parse import urlsplit
import mimetypes
from playwright.sync_api import sync_playwright
from motion_check import handle,ORIGIN
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/code-panels';OUT.mkdir(parents=True,exist_ok=True)
COMMAND='Get-Content "D:/示例/中文 (1).txt"\r\n'+'\n'.join(f'Write-Output "line {i} '+('long-code-'*32)+'"' for i in range(60))
RESULT='Exception: fixture only\r\n'+'\n'.join(f'结果 {i}: '+('output '*30) for i in range(90))
SOURCE='\n'.join(f'代码 {i}: '+('value '*25) for i in range(75))+'\n'
TEXT='普通正文与 `行内代码`。\n\n```markdown\n'+SOURCE+'```\n\n```text\n请根据给定材料写一段简洁提示词。\n```'

def route(r):
    path=urlsplit(r.request.url).path;f=ROOT/'static'/path.lstrip('/')
    if f.is_file():return r.fulfill(path=str(f),content_type=mimetypes.guess_type(f.name)[0] or 'application/octet-stream')
    return handle(r,r.request)

with sync_playwright() as p:
    for engine in ('chromium','webkit'):
        browser=getattr(p,engine).launch(**({'channel':'chrome'} if engine=='chromium' else {}))
        page=browser.new_page(viewport={'width':390,'height':844},has_touch=True);page.route('**/*',route);errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)));page.emulate_media(reduced_motion='reduce');page.goto(ORIGIN);page.wait_for_function('window.interactionUI');page.locator('.conv').first.click()
        page.evaluate('''v=>{clearTimeout(convTimer);readingUI.pauseStream();cur={app:'codex',id:'code-panels',status:'running'};
          window.panelRows=[{id:'u',role:'user',text:'脱敏面板测试',order:0},{id:'reply',role:'assistant',text:v.text,order:1},
          {id:'tool-failed',role:'tool',activity_turn:'panel',text:'执行脚本',detail:v.command,result:v.result,tool_status:'failed',order:2},
          {id:'tool-empty',role:'tool',activity_turn:'panel',text:'git status',detail:'git status',tool_status:'completed',order:3}];
          interactionUI.meta({activity_current:'panel',activity_turns:{panel:{status:'running',started_at:Date.now()}}});renderMsgs(panelRows);
          Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async t=>window.copied=t}});
          document.querySelector('#cvText').value='保留草稿';}''',{'text':TEXT,'command':COMMAND,'result':RESULT})
        page.wait_for_function("document.querySelectorAll('.code-wrap').length===5")
        tool=page.locator('[data-message-id="tool-failed"]');tool.locator('summary').click()
        page.wait_for_function("document.querySelector('[data-message-id=\"tool-failed\"]').open")
        assert tool.locator('.code-wrap').count()==2
        assert tool.locator('.activity-error').inner_text()=='执行失败'
        assert tool.locator('.activity-mark').inner_text()!='!'
        assert '操作未完成，展开查看结果' not in page.locator('#cvMsgs').inner_text()
        assert page.locator('[data-message-id="tool-empty"] .code-wrap').count()==1
        command=tool.locator('[data-panel-key="command"]');result=tool.locator('[data-panel-key="result"]')
        for panel,raw in ((command,COMMAND),(result,RESULT)):
            panel.get_by_role('button',name='复制原文').click();assert page.evaluate('copied')==raw
        reply=page.locator('.reply-text .code-wrap').first
        reply.get_by_role('button',name='复制原文').click();assert page.evaluate('copied')==SOURCE
        assert page.locator('.reply-text>p code').inner_text()=='行内代码'
        # Independent scroll offsets and line-mode must survive both render pathways.
        command.get_by_role('button',name='保持原始行').click()
        command.locator('pre').evaluate('(n)=>{n.scrollTop=160;n.scrollLeft=80}')
        result.locator('pre').evaluate('(n)=>n.scrollTop=240')
        reply.locator('pre').evaluate('(n)=>n.scrollTop=180');page.wait_for_timeout(60)
        page.evaluate(r'''()=>{panelRows[2].result+='\n新增结果';panelRows[1].text+='\n\n新增段落';renderMsgs(panelRows)}''')
        page.wait_for_timeout(80)
        assert command.locator('.code-lines').inner_text()=='自动换行'
        assert command.locator('pre').evaluate('(n)=>n.scrollTop')==160
        assert command.locator('pre').evaluate('(n)=>n.scrollLeft')==80
        assert result.locator('pre').evaluate('(n)=>n.scrollTop')==240
        assert reply.locator('pre').evaluate('(n)=>n.scrollTop')==180, page.evaluate("[...codePanels.capture(document.querySelector('.reply-text'))]")
        # Explicit tool and group collapse retain their own internal positions.
        tool.locator('summary').click();page.wait_for_timeout(30);tool.locator('summary').click();page.wait_for_timeout(50)
        assert result.locator('pre').evaluate('(n)=>n.scrollTop')==240
        page.locator('.activity-heading').click();page.locator('.activity-heading').click();page.wait_for_timeout(60)
        assert result.locator('pre').evaluate('(n)=>n.scrollTop')==240
        assert tool.evaluate('(n)=>n.open')
        # Direct streaming markdown refresh preserves its bounded scroll body too.
        page.evaluate("()=>updateMarkdown(document.querySelector('.reply-text'),panelRows[1].text+'\\nmore',true)")
        assert reply.locator('pre').evaluate('(n)=>n.scrollTop')==180
        page.evaluate(r"v=>updateMarkdown(document.querySelector('.reply-text'),'```markdown\n'+v+'追加中的代码行',true)",SOURCE)
        assert reply.locator('pre').evaluate('(n)=>n.scrollTop')==180
        for width,height in ((390,844),(844,390),(1280,900)):
            page.set_viewport_size({'width':width,'height':height})
            for theme in ('light','dark'):
                page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                bg='rgb(245, 245, 245)' if theme=='light' else 'rgb(30, 30, 30)'
                edge='rgb(227, 227, 227)' if theme=='light' else 'rgb(51, 51, 51)'
                assert command.evaluate('(n)=>getComputedStyle(n).backgroundColor')==bg
                assert command.evaluate('(n)=>getComputedStyle(n).borderTopColor')==edge
                assert command.evaluate('(n)=>getComputedStyle(n).borderRadius')=='12px'
                assert result.locator('pre').evaluate('(n)=>getComputedStyle(n).fontSize')=='13px'
                assert result.locator('pre').evaluate('(n)=>n.clientHeight')<=min(320,height*.45)+1
                assert result.locator('pre').evaluate('(n)=>n.scrollHeight>n.clientHeight')
                assert tool.locator('.activity-error').evaluate('(n)=>getComputedStyle(n).color')==tool.locator('summary').evaluate('(n)=>getComputedStyle(n).color')
                for b in tool.locator('.code-head button').all():assert b.bounding_box()['height']>=44
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert page.locator('#cvMsgs').evaluate('(n)=>n.scrollWidth<=n.clientWidth')
                result.scroll_into_view_if_needed();page.screenshot(path=str(OUT/f'{engine}-{width}-{theme}.png'))
        assert page.locator('#cvText').input_value()=='保留草稿'
        assert not errors,errors
        browser.close();print(engine+': panel boundaries, clipboard, independent scrolling, refresh/collapse, 6 layouts passed')
