"""Exercise the actual phone renderer with deterministic SSE delivery."""
import json
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
from motion_check import handle,ORIGIN,HERE

def main():
    def route(r,req):
        path=urlsplit(req.url).path
        def reply(v):r.fulfill(content_type='application/json',body=json.dumps(v))
        if path=='/':return r.fulfill(content_type='text/html',body=(HERE/'remote.html').read_text(encoding='utf-8').replace('<!--machine-->','<script>window.MACHINE={apps:["deepseek"],voice:false};</script>'))
        if path=='/api/chat':return reply(dict(app='deepseek',id='d1',title='stream test',status='running',messages=[],has_more=False))
        if path=='/api/deepseek/state':return reply(dict(available=True,running=True,settings={},questions=[],interactions=[],inbox={}))
        return handle(r,req)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,channel='chrome');page=browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
        page.add_init_script('''window.sources=[];window.EventSource=class extends EventTarget{constructor(url){super();this.url=url;this.closed=false;window.sources.push(this);}close(){this.closed=true;}};window.deliver=(v)=>{const s=window.sources.findLast(x=>!x.closed);s.dispatchEvent(new MessageEvent('update',{data:JSON.stringify(v)}));};''')
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.route('**/*',route);page.goto(ORIGIN);page.wait_for_function('!!window.deepseekUI')
        page.evaluate("openConv({app:'deepseek',id:'d1',title:'stream test',status:'running'})");page.wait_for_function('window.sources.some(x=>!x.closed)')
        thought=dict(id='live:a:0',role='assistant',thinking=True,phase='commentary',streaming=True,order=100,text='思考片段。'*100)
        final=dict(id='live:a:1',role='assistant',streaming=True,order=101,text='回复正在')
        def send(seq,messages,live,opening=False):
            value=dict(type='snapshot' if opening else 'update',protocol=1,app='deepseek',id='d1',seq=seq,streaming_ids=live)
            if opening:value['chat']=dict(id='d1',app='deepseek',status='running',title='stream test',messages=messages,has_more=False)
            else:value.update(messages=messages,meta={'status':'running'})
            page.evaluate('(v)=>window.deliver(v)',value)
        send(1,[thought],['live:a:0'],True)
        box=page.locator('.thinking');box.wait_for();assert '思考中' in box.inner_text();assert box.locator('.message-actions').count()==0
        box.click();assert 'open' in box.get_attribute('class')
        page.locator('#cvText').fill('尚未发送的草稿')
        thought={**thought,'text':thought['text']+'新的思考'};send(2,[thought,final],['live:a:0','live:a:1'])
        assert 'open' in box.get_attribute('class');assert '新的思考' in box.inner_text();assert page.locator('#cvText').input_value()=='尚未发送的草稿'
        tool=dict(id='tool:call',role='tool',order=102,tool_status='running',text='正在执行：读取文件')
        send(3,[tool],['live:a:0','live:a:1']);assert '进行中' in page.locator('details.tools summary').inner_text()
        tool={**tool,'tool_status':'completed','text':'已完成：读取文件'}
        send(4,[{**thought,'id':'90:thinking','streaming':False},{**final,'id':'91','text':'最终回复','streaming':False},tool],[])
        assert page.locator('.thinking').count()==1;assert '思考过程' in box.inner_text();assert page.locator('.bub.assistant:not(.thinking)').count()==1
        assert page.locator('.bub.assistant:not(.thinking)').inner_text().count('最终回复')==1;assert '进行中' not in page.locator('details.tools summary').inner_text()
        # A reconnect baseline must replace, not append to, an old transient prefix.
        send(5,[thought],['live:a:0']);count=page.evaluate('sources.length');page.evaluate('sources.findLast(x=>!x.closed).onerror()')
        page.wait_for_function('(n)=>sources.length>n',arg=count)
        send(1,[{**thought,'text':'重新连接恢复的思考片段'}],['live:a:0'],True)
        assert page.locator('[data-key="live:a:0"]').count()==1;assert page.locator('[data-key="live:a:0"]').inner_text().count('重新连接恢复的思考片段')==1
        # Reading older messages does not jump to the streaming tail.
        older=[dict(id='old'+str(i),role='assistant',text='较早消息 '+str(i)+'。'*60,order=i) for i in range(30)]
        send(2,older,['live:a:0']);page.evaluate("document.querySelector('#cvMsgs').scrollTop=0")
        send(3,[{**thought,'text':'尾部继续更新'}],['live:a:0']);assert page.locator('#cvMsgs').evaluate('(n)=>n.scrollTop')<80
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth');assert not errors,errors
        browser.close();print('DeepSeek stream UI: live thinking/text, tool status, folding, settlement, reconnect, draft and reading position PASS')

if __name__=='__main__':main()
