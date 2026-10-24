"""Real UI and synthetic event chains only. No live service or conversations."""
from pathlib import Path
import mimetypes
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
from motion_check import handle,ORIGIN
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/conversation-candidate';OUT.mkdir(parents=True,exist_ok=True)
def route(r):
    path=urlsplit(r.request.url).path
    if path=='/api/chat/files':return r.fulfill(json={'items':[{'id':'fixture','index':0,'message_id':'md','name':'image.png','kind':'image','state':'current'}]})
    if path=='/api/file':return r.fulfill(path=str(ROOT/'static/icon-192.png')) if (ROOT/'static/icon-192.png').exists() else r.fulfill(status=404)
    f=ROOT/'static'/path.lstrip('/')
    if f.is_file():return r.fulfill(path=str(f),content_type=mimetypes.guess_type(f.name)[0] or 'application/octet-stream')
    return handle(r,r.request)
with sync_playwright() as p:
    for engine in ('chromium','webkit'):
        browser=getattr(p,engine).launch(**({'channel':'chrome'} if engine=='chromium' else {}))
        page=browser.new_page(viewport={'width':390,'height':844},has_touch=True);page.route('**/*',route)
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.emulate_media(reduced_motion='reduce');page.goto(ORIGIN);page.wait_for_function('window.interactionUI');page.locator('.conv').first.click();page.wait_for_timeout(350)
        page.evaluate("""()=>{readingUI.pauseStream();cur={app:'codex',id:'candidate',status:'running'};
          const m=(id,order,text='same')=>({id,order,text,role:'user',client_request_id:id});
          let a=messageProjection.merge([], [m('B',20)]);a=messageProjection.merge(a,[m('A',10)]);a=messageProjection.merge(a,[m('B',20),m('A',10)]);
          if(a.map(x=>x.id).join()!=='A,B')throw Error('source order');
          const settled=messageProjection.merge([{id:'live',role:'assistant',text:'public',streaming:true,order:2}],[{id:'stored',role:'assistant',text:'public',projection_aliases:['live'],order:2}]);
          if(settled.length!==1||settled[0].display_id!=='live')throw Error('live alias');
          if(messageProjection.merge([],[{id:'live',source_id:'same',order:1},{id:'stored',source_id:'same',order:1}]).length!==1)throw Error('batch alias');
          if(messageProjection.matches(m('A',10),{rid:'B',text:'same'}))throw Error('text matching');
          renderMsgs([m('base',0,'base')]);
          workspaceUI.capture(cur,{request_id:'send-A',started:100,text:'same'},{originalText:'same',transport:'codex'});renderMsgs(currentMessages);
          workspaceUI.capture(cur,{request_id:'send-B',started:200,text:'same'},{originalText:'same',transport:'codex'});renderMsgs(currentMessages);
          window.nodeA=document.querySelector('[data-key="outbox:send-A"]');
          renderMsgs([m('base',0,'base'),{...m('persist-B',20),client_request_id:'send-B'}]);
          let keys=[...document.querySelectorAll('#cvMsgs>[data-key]')].map(n=>n.dataset.key);
          if(keys.indexOf('outbox:send-A')>keys.indexOf('outbox:send-B'))throw Error('late A jumped');
          renderMsgs([m('base',0,'base'),{...m('persist-B',20),client_request_id:'send-B'},{...m('persist-A',10),client_request_id:'send-A'}]);
          if(document.querySelector('[data-key="outbox:send-A"]')!==nodeA)throw Error('identity replaced');
          cur={app:'codex',id:'segments',status:'running'};interactionUI.meta({activity_turns:{t:{started_at:Date.now()-95000,status:'running',pauses:[]}},activity_current:'t'});
          renderMsgs([{id:'u',role:'user',text:'A'},{id:'c1',role:'assistant',phase:'commentary',activity_turn:'t',text:'前半段'},{id:'v',role:'user',text:'B',time:new Date().toISOString()},{id:'c2',role:'assistant',phase:'commentary',activity_turn:'t',text:'后半段'},{id:'final',role:'assistant',text:'final'}]);
          if(document.querySelectorAll('.activity-group').length!==2)throw Error('segments');
          if(document.querySelectorAll('.activity-progress').length!==2)throw Error('nested progress');
          if(interactionUI.formatDuration(59)!=='59秒'||interactionUI.formatDuration(95)!=='1分35秒'||interactionUI.formatDuration(3725)!=='1小时02分05秒')throw Error('duration');
        }""")
        page.locator('.activity-heading').last.click();page.evaluate('renderMsgs(currentMessages)');assert page.locator('.activity-body').last.is_hidden()
        page.evaluate(r"""()=>{cur={app:'codex',id:'markdown',status:'idle'};renderMsgs([{id:'md',role:'assistant',text:'# Title\n\n- first\n- **second**\n\n<details><summary>Details</summary>\n\nparagraph\n\n</details>\n\n```sh\n'+ 'x'.repeat(500)+'\n```\n\n| A | B |\n|---|---|\n|'+ 'long'.repeat(100)+'|value|\n\n<script>window.BAD=1</script><img src=x onerror=window.BAD=1>\n\n[bad](javascript:alert(1))'}]);}""")
        assert page.locator('#cvMsgs ul li').count()==2
        assert page.locator('#cvMsgs details').count()==1
        assert not page.evaluate('!!window.BAD')
        assert page.evaluate(r"assistantMarkdown('```html\n<proposed_plan>\n```').markdown.includes('<proposed_plan>')")
        assert page.evaluate(r"""()=>{const n=document.createElement('div');n.innerHTML=md('命令 `echo "a b"`',true);const b=n.querySelector('.inline-copy');return b&&JSON.parse(b.dataset.copyFragment)==='echo "a b"';}""")
        assert page.evaluate("$('cvMsgs').scrollWidth<=$('cvMsgs').clientWidth+1"),page.evaluate("[...document.querySelectorAll('#cvMsgs *')].filter(n=>n.getBoundingClientRect().right>innerWidth).map(n=>n.className)")
        page.locator('.code-lines').click();assert page.locator('.code-wrap').evaluate('(n)=>n.classList.contains("original-lines")')
        assert page.locator('.code-copy').evaluate('(n)=>JSON.parse(n.dataset.copyFragment).length')==501
        page.evaluate("""()=>{keyboardCut=480;$('convView').style.height='480px';viewportBox();keyboardCheck();if($('convView').style.height!==innerHeight+'px')throw Error('viewport stale');}""")
        for theme in ('light','dark'):
            page.evaluate('TeleplyTheme.set',theme);page.screenshot(path=str(OUT/(engine+'-'+theme+'.png')))
        assert not errors,errors
        browser.close()
print('candidate identity, segmentation, Markdown, overflow, viewport checks passed')
