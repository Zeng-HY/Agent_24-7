"""Real phone-size UI with intercepted APIs. Never creates or sends a desktop conversation."""
import json,sys
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
from playwright.sync_api import sync_playwright
from motion_check import handle,ORIGIN


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,channel='chrome')
        for app in ('codex','claude'):
            context=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
            state={'phase':'creating','posts':0,'drafts':0,'telemetry':[],'preview_calls':[]}
            errors=[]
            messages={'failed':'明确未发送','unconfirmed':'Codex 未完成操作：thread-follower-start-turn-timeout'}
            def route(r,req):
                path=urlsplit(req.url).path
                if 'new%3A' in req.url or ('/api/' in path and 'new:' in (req.post_data or '')):state['preview_calls'].append(req.url)
                def reply(v,status=200):r.fulfill(status=status,content_type='application/json',body=json.dumps(v))
                if path=='/api/chat/new/draft':state['drafts']+=1;return reply({'request_id':'%032x'%state['drafts']})  # each draft its own
                if path=='/api/chat/new':state['posts']+=1;return reply({'request_id':json.loads(req.post_data)['request_id'],'state':'creating','message':'正在创建对话'})
                if path=='/api/chat/new/timing':state['telemetry'].append(json.loads(req.post_data));return reply({'ok':True})
                if path=='/api/chat/new/state':
                    if state['phase']=='offline':return r.abort('internetdisconnected')
                    rid=parse_qs(urlsplit(req.url).query)['request_id'][0]
                    return reply({'request_id':rid,'app':app,'id':'new-test','title':'测试消息','folder':'','state':state['phase'],'not_submitted':state['phase']=='failed','message':messages.get(state['phase'],'正在创建对话'),'timing':{'total_ms':2300,'stages':[{'name':'create','label':'创建对话','ms':2000}],'active':None if state['phase']=='accepted' else {'name':'desktop_owner','label':'等待桌面接管','ms':300},'complete':state['phase']=='accepted'}})
                return handle(r,req)
            context.route('**/*',route);page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(ORIGIN);page.wait_for_function('!!window.newChatUI')
            page.evaluate('(app)=>openNewSheet({app,projectless:true})',app)
            page.locator('#newText').fill('手机计时测试，不重复发送。')
            page.locator('#newBtn').click();page.wait_for_function("cur?.id.startsWith('new:')")
            page.wait_for_function("document.querySelector('#newInlineStatus')?.textContent.includes('创建')")
            assert state['posts']==1
            assert page.evaluate('overlays.length')==0
            assert page.locator('#cvMsgs').inner_text().count('手机计时测试，不重复发送。')==1
            assert page.locator('#newInlineStatus').evaluate('(n)=>getComputedStyle(n).fontSize')=='12px'
            assert page.locator('#newTiming').count()==0
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            if len(sys.argv)>1 and app=='codex':
                page.wait_for_timeout(550);page.screenshot(path=sys.argv[1])
            page.locator('#cvText').fill('下一条草稿 @test')
            assert page.locator('#cvBtn').is_disabled()
            # Completing in place preserves the next draft and does not add a second navigation.
            history_before=page.evaluate('history.length')
            page.locator('#cvText').dispatch_event('compositionstart');state['phase']='accepted'
            page.wait_for_function("JSON.parse(localStorage.getItem('lbr_new_jobs_v1')||'[]').some(j=>j.pending?.state==='accepted')")
            assert page.evaluate("cur.id.startsWith('new:')"), 'handoff interrupted IME composition'
            page.locator('#cvText').dispatch_event('compositionend')
            page.wait_for_function("cur?.id==='new-test'")
            assert page.locator('#cvText').input_value()=='下一条草稿 @test'
            assert page.evaluate('history.length')==history_before
            assert page.locator('#newInlineStatus').count()==0
            assert not json.loads(page.evaluate("localStorage.getItem('lbr_new_chat_v1')")).get('pending')
            assert json.loads(page.evaluate("localStorage.getItem('lbr_new_jobs_v1')"))==[]
            assert len(state['telemetry'])==1
            # A new pending conversation remains inspectable after navigating away and reloading.
            state['phase']='creating'
            page.evaluate('(app)=>openNewSheet({app,projectless:true})',app)
            page.locator('#newText').fill('保留草稿');page.locator('#newBtn').click()
            page.wait_for_function("cur?.id.startsWith('new:')")
            page.wait_for_function("document.querySelector('#newInlineStatus')?.textContent.includes('创建')")
            assert state['posts']==2
            page.reload();page.wait_for_function("cur?.id.startsWith('new:')")
            assert page.locator('#cvMsgs').inner_text().count('保留草稿')==1
            page.evaluate("openConv({app:'codex',id:'c2',title:'别的对话',folder:'',status:'idle'})")
            page.locator('#cvText').fill('创建还没结束，也能给其他对话发文字')
            assert page.locator('#cvBtn').is_enabled(), 'pending creation blocked a different conversation'
            state['phase']='accepted';page.wait_for_function("document.querySelector('#newJobDock').textContent.includes('已就绪')")
            assert page.evaluate('cur.id')=='c2'
            page.locator('#cvText').fill('其他对话仍能发文字')
            assert page.locator('#cvBtn').is_enabled()
            assert page.locator('#newJobDock').evaluate('(n)=>getComputedStyle(n).position')=='static'
            page.evaluate('closeConv(true)')
            page.locator('#newJobDock').click();page.wait_for_function("cur?.id==='new-test'")
            assert state['posts']==2
            # Failure appears under the bubble; restoring the first message is explicit.
            state['phase']='creating';page.evaluate('(app)=>openNewSheet({app,projectless:true})',app)
            page.locator('#newText').fill('失败时保留');page.locator('#newBtn').click()
            page.wait_for_function("cur?.id.startsWith('new:')");state['phase']='failed'
            page.wait_for_function("document.querySelector('#newInlineStatus')?.textContent.includes('没发出去')")
            page.locator('#newInlineStatus').click();page.locator('#newRestore').click()
            assert page.locator('#newText').input_value()=='失败时保留';assert page.locator('#newText').is_visible()
            assert state['posts']==3
            # 10-16: whatever becomes of a first message, the sheet is free again at once (10-15 19:09 one left
            # unconfirmed held it for good); two can be under way, and one that went wrong can be removed.
            page.evaluate("closeSheet('newSheet')");state['phase']='unconfirmed'
            page.evaluate('(app)=>openNewSheet({app,projectless:true})',app)
            page.locator('#newText').fill('结果未确认');page.locator('#newBtn').click()
            page.wait_for_function("document.querySelector('#newInlineStatus')?.textContent.includes('尚未确认')")
            page.evaluate('(app)=>openNewSheet({app,projectless:true})',app);page.wait_for_function("overlays.some(v=>v.id==='newSheet')")
            for part in ('#newText','#newAdd','#newFolderChoice','#newModelChoice'):assert page.locator(part).is_enabled(),part
            assert page.locator('#newText').input_value()==''
            page.locator('#newText').fill('又一个新对话');page.locator('#newBtn').click()
            page.wait_for_function("cur?.id.startsWith('new:')&&document.querySelector('#cvMsgs').innerText.includes('又一个新对话')")
            assert state['posts']==5;assert len(json.loads(page.evaluate("localStorage.getItem('lbr_new_jobs_v1')")))==2
            page.evaluate('closeConv(true)');page.wait_for_function("document.querySelectorAll('#newJobDock button').length===2")
            page.locator('#newJobDock button',has_text='结果未确认').click();page.wait_for_function("overlays.some(v=>v.id==='newJobSheet')")
            assert 'thread-follower-start-turn-timeout' in page.locator('#newJobStatus').inner_text()
            assert page.locator('#newCheck').is_visible() and not page.locator('#newRestore').is_visible()
            page.locator('#newDismiss').click();page.wait_for_function("overlays.some(v=>v.id==='confirmSheet')")
            page.locator('#confirmSheet button',has_text='确定').click()
            page.wait_for_function("document.querySelectorAll('#newJobDock button').length===1&&!overlays.length")
            assert '又一个新对话' in page.locator('#newJobDock').inner_text() and '结果未确认' not in page.locator('#newJobDock').inner_text()
            assert state['posts']==5
            # A page from before 10-16 kept its request inside the draft and stayed locked: it becomes a job of its own.
            page.evaluate("""(app)=>{localStorage.setItem('lbr_new_chat_v1',JSON.stringify({app,folder:'',projectless:true,label:'',text:'旧版卡住的',references:[],images:[],request_id:'b'.repeat(32),
                pending:{state:'unconfirmed',message:'Codex 未完成操作：thread-follower-start-turn-timeout'},settings:{}}));localStorage.setItem('lbr_new_jobs_v1','[]');}""",app)
            page.reload();page.wait_for_function("[...document.querySelectorAll('#newJobDock button')].some(b=>b.textContent.includes('旧版卡住的'))")
            page.evaluate('(app)=>openNewSheet({app,projectless:true})',app);page.wait_for_function("overlays.some(v=>v.id==='newSheet')")
            assert page.locator('#newText').is_enabled() and page.locator('#newText').input_value()==''
            assert not state['preview_calls'],state['preview_calls']
            assert not errors,errors
            print(app+': immediate chat, inline status, draft handoff, no duplicate, background, reload, failure recovery, free sheet, remove, old draft PASS')
            context.close()
        browser.close()


if __name__=='__main__':main()
