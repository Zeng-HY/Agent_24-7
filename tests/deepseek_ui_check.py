"""Phone-size integration against mock Harness APIs; never touches real chats.

10-20: the conversation is laid out as Codex's and Claude's — ＋ / model / permission in the message box, 停止这一轮 in the
title bar, 发送会立即补充给这一轮 with 排队稍后发送 while a turn runs, the queue in a tray, a question or an approval as one
strip above the box that opens a sheet.
"""
import json
from urllib.parse import urlsplit,parse_qs
from playwright.sync_api import sync_playwright
from motion_check import handle, ORIGIN, HERE

def main():
    posts=[];errors=[]
    state={'available':True,'running':True,'turn_id':'3','settings':{'provider':'deepseek-account','model':'deepseek-flash','reasoningEffort':'high'},
        'permission':'workspace-write','permission_name':'工作区内修改','queued':[{'id':'q1','text':'做完后整理成表格'}],
        'questions':[{'callId':'call','questions':[{'id':'q','question':'选择测试选项','options':[{'label':'甲','description':'第一项'},{'label':'乙'}]}]}],
        'interactions':[{'eventId':'approval','agentId':'d1','event':'approval/request','request':{'toolName':'pwsh','reason':'测试批准'}}], 'inbox':{},
        'subagents':[{'id':'c1','label':'答 quote-0009 至 0022','running':False,'mode':'continuable','created':0}]}
    presets={'options':[{'value':'read-only','name':'仅可查看','description':'只读','confirm':False},{'value':'workspace-write','name':'工作区内修改','description':'改工作区','confirm':False},
                        {'value':'danger-full-access','name':'完全权限','description':'不经批准','confirm':True}]}
    def route(r,req):
        path=urlsplit(req.url).path
        def reply(v,status=200):r.fulfill(status=status,content_type='application/json',body=json.dumps(v))
        if path=='/':
            html=(HERE/'remote.html').read_text(encoding='utf-8').replace('<!--machine-->','<script>window.MACHINE={apps:["codex","claude","deepseek"],voice:false};</script>')
            return r.fulfill(status=200,content_type='text/html',body=html)
        if path=='/api/deepseek/state':return reply(state)
        if path=='/api/deepseek/permissions':return reply({**presets,'current':state['permission']})
        if path=='/api/chat' and parse_qs(urlsplit(req.url).query).get('id',[''])[0]=='d1':
            return reply({'app':'deepseek','id':'d1','title':'DeepSeek Test','folder':'x','status':'idle','runtime':{'model':'deepseek-flash'},
                'messages':[{'id':'subagent:c1','role':'subagent','child':'c1','label':'答 quote-0009 至 0022','status':'done','order':1,'time':'2026-10-19T12:00:00+00:00','text':'子智能体：答 quote-0009 至 0022'},
                            {'id':'2','role':'assistant','text':'完成','order':2,'time':'2026-10-19T12:01:00+00:00'}],
                'subagents':[{'id':'c1','label':'答 quote-0009 至 0022','running':False,'mode':'continuable','created':0}],
                'has_more':False,'next_cursor':None,'has_newer':False,'size':2,'total':2})
        if path=='/api/deepseek/models':return reply({'groups':[{'id':'deepseek-account','models':[{'id':'deepseek-flash','name':'DeepSeek Flash','reasoning':{'efforts':[{'id':'high','name':'高'},{'id':'max','name':'最高'}]}}]}]})
        if path.startswith('/api/deepseek/') and req.method=='POST':
            body=json.loads(req.post_data);posts.append((path,body))
            if path.endswith('/answer'):state['questions']=[]
            if path.endswith('/approval'):state['interactions']=[]
            if path.endswith('/queue'):state['queued']=[]
            if path.endswith('/permission'):state['permission']=body['preset'];state['permission_name']='完全权限';return reply({'accepted':True,'text':'已切换为「完全权限」'})
            if path.endswith('/create'):return reply({'app':'deepseek','id':'d2','title':'new','folder':'test'})
            return reply({'accepted':True,'text':'已处理'})
        return handle(r,req)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,channel='chrome');page=browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
        page.route('**/*',route);page.on('pageerror',lambda e:errors.append(str(e)));page.goto(ORIGIN);page.wait_for_function('!!window.deepseekUI')
        page.evaluate("openConv({app:'deepseek',id:'d1',title:'DeepSeek Test',status:'running'})")
        page.locator('.sub-card').first.wait_for()
        assert '答 quote-0009 至 0022' in page.locator('.sub-card').first.inner_text()
        page.wait_for_function("!document.getElementById('deepseekSubBar').hidden")
        assert '子智能体 1 个' in page.locator('#deepseekSubBar').inner_text()
        page.locator('#deepseekSubBar').click()
        page.wait_for_function("!!document.querySelector('#deepseekSubList .codex-card')")
        assert '答 quote-0009 至 0022' in page.locator('#deepseekSubList').inner_text()
        page.evaluate("closeSheet('deepseekSubList')")
        # the message box carries ＋, the model and the permission; 停止这一轮 sits in the title bar
        page.wait_for_function("document.getElementById('deepseekModel').textContent==='DeepSeek Flash · 高'")
        assert page.locator('#deepseekComposerTools').is_visible() and page.locator('#deepseekPermission').inner_text()=='工作区内修改'
        assert page.locator('#deepseekStop').is_visible() and not page.locator('#deepseekBar').count(), 'the old row of bare words is gone'
        # while the turn runs: what ↑ does, 排队稍后发送, and the queue tray
        assert page.locator('#deepseekRun .run-hint').inner_text()=='发送会立即补充给这一轮'
        assert '做完后整理成表格' in page.locator('#deepseekQueue').inner_text()
        # a question and an approval: one strip, then the sheet
        pill=page.locator('#cvOpts .ask-pill');pill.wait_for();assert '共 2 项' in pill.inner_text(),pill.inner_text()
        pill.click();page.wait_for_function("overlays.some(o=>o.id==='deepseekAskSheet')")
        page.locator('#deepseekAskSheet .option-card',has_text='甲').click();assert not posts
        page.get_by_role('button',name='提交答案',exact=True).click()
        page.wait_for_function("!document.querySelector('#deepseekAskSheet .option-card')")
        assert posts[-1][1]['answers']==[{'id':'q','selected':['甲']}]
        gap=page.evaluate("(()=>{const [a,b]=[...document.querySelectorAll('#deepseekAskSheet .ds-actions button')].map(n=>n.getBoundingClientRect());return b.left-a.right;})()")
        assert gap>=8,f'approval buttons {gap}px apart'
        page.get_by_role('button',name='仅允许本次',exact=True).click();page.wait_for_function("!document.querySelector('#cvOpts .ask-pill')")
        assert posts[-1][1]['event_id']=='approval' and posts[-1][1]['choice']=='allowed-once'
        # the queued message handed to the running turn
        page.locator('#deepseekQueue button',has_text='立即补充').click();page.wait_for_function("document.getElementById('deepseekQueue').hidden")
        assert posts[-1]==('/api/deepseek/queue',{'id':'d1','item_id':'q1','action':'steer'})
        page.locator('#cvText').fill('hello');page.locator('#cvBtn').click();page.wait_for_function("document.querySelector('#cvText').value===''")
        assert posts[-1][0]=='/api/deepseek/send' and posts[-1][1]['intent']=='steer'
        page.locator('#cvText').fill('later');page.locator('#deepseekQueueSend').click();page.wait_for_function("document.querySelector('#cvText').value===''")
        assert posts[-1][1]['intent']=='queue'
        page.locator('#deepseekModel').click();page.get_by_role('radio',name='最高',exact=True).click();page.wait_for_function("!overlays.some(x=>x.id==='deepseekModels')")
        assert posts[-1][1]['settings']=={'provider':'deepseek-account','model':'deepseek-flash','reasoningEffort':'max'}
        # 完全权限 asks first, then goes through with confirmed
        page.locator('#deepseekPermission').click();page.get_by_role('radio',name='完全权限').click()
        page.wait_for_function("overlays.some(x=>x.id==='confirmSheet')");page.locator('#confirmSheet button.big').click()
        page.wait_for_function("!overlays.some(x=>x.id==='deepseekPermissions')")
        assert posts[-1]==('/api/deepseek/permission',{'id':'d1','preset':'danger-full-access','confirmed':True})
        page.wait_for_function("document.getElementById('deepseekPermission').classList.contains('is-full')")
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.evaluate("newChatUI.open({app:'deepseek',folder:'D:/Projects/示例项目'})")
        page.get_by_role('button',name='创建对话',exact=True).click();page.wait_for_function("cur?.id==='d2'")
        assert sum(path.endswith('/create') for path,_ in posts)==1
        assert not errors,errors
        browser.close()
    print('DeepSeek phone UI: composer like Codex/Claude, ask sheet, spaced approval, queue tray, model, permission with confirm, creation, no overflow PASS')

if __name__=='__main__':main()
