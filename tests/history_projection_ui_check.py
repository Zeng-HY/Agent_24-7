"""Old phone storage + paginated history; never opens a live conversation."""
from pathlib import Path
import sys,mimetypes,json
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
from motion_check import handle,ORIGIN
ROOT=Path(__file__).resolve().parents[1]

def run(engine):
    with sync_playwright() as p:
        browser=getattr(p,engine).launch(**({'channel':'chrome'} if engine=='chromium' else {}))
        page=browser.new_page(viewport={'width':390,'height':844});page.emulate_media(reduced_motion='reduce')
        def route(r):
            path=urlsplit(r.request.url).path
            if path=='/api/chat/resolve':return r.fulfill(json={'items':[{'request_id':'old-request','status':'recorded','message_id':'old-source','order':10,'turn_id':'old-turn','evidence':'source_client_id'}]})
            file=ROOT/'static'/path.lstrip('/')
            if file.is_file():return r.fulfill(path=str(file),content_type=mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
            return handle(r,r.request)
        page.route('**/*',route)
        page.add_init_script("window.testStreams=[];window.EventSource=class{constructor(){testStreams.push(this)}addEventListener(name,fn){this.listener=fn}close(){}emit(data){this.listener({data:JSON.stringify(data)})}};")
        page.add_init_script("localStorage.setItem('lbr_outbox_v1',JSON.stringify([{rid:'old-request',app:'codex',id:'repro',started:1000,state:'delivered',receivedAt:2000,transport:'codex',text:'OLD USER MESSAGE',originalText:'OLD USER MESSAGE',images:[],body:{text:'OLD USER MESSAGE'}}]));")
        page.goto(ORIGIN);page.wait_for_function('window.interactionUI&&window.codexUI');page.locator('.conv').first.click();page.wait_for_timeout(200)
        page.evaluate("""()=>{readingUI.pauseStream();cur={app:'codex',id:'repro',status:'idle'};currentMessages=[{id:'final',role:'assistant',text:'LATEST FINAL ANSWER',order:900}];codexUI.applyState(cur,{available:false,questions:[{id:'async:old',source_id:'old-question',source_order:20,kind:'async',status:'answered',questions:[{id:'0',question:'OLD QUESTION'}],answers:{'0':['OLD ANSWER']}}]});renderMsgs(currentMessages);}""")
        assert page.locator('#cvMsgs>[data-key]').evaluate_all('(xs)=>xs.map(x=>x.dataset.key)')==['final'], 'old records returned to newest window'
        page.evaluate("workspaceUI.resolveLocations?.()")
        page.wait_for_timeout(100)
        page.evaluate("""()=>renderMsgs([{id:'old-source',client_request_id:'old-request',role:'user',text:'OLD USER MESSAGE',order:10},{id:'old-question',source_id:'old-question',role:'assistant',phase:'final_answer',text:'OLD QUESTION',order:20},{id:'middle',role:'assistant',text:'middle',order:30}])""")
        assert page.locator('#cvMsgs .user').count()==1
        assert page.locator('#cvMsgs .question-history').count()==1
        assert page.locator('#cvMsgs .question-history').get_attribute('open') is None
        page.locator('.question-history summary').click();page.evaluate('renderMsgs(currentMessages)')
        assert page.locator('.question-history').get_attribute('open') is not None
        page.evaluate("renderMsgs([{id:'final',role:'assistant',text:'LATEST FINAL ANSWER',order:900}])")
        assert page.locator('#cvMsgs .user,#cvMsgs .question-history').count()==0
        kept=page.evaluate("JSON.parse(localStorage.getItem('lbr_outbox_v1')).find(x=>x.rid==='old-request')")
        assert kept and kept['body']['text']=='OLD USER MESSAGE'
        page.evaluate(r"""()=>{cur={app:'codex',id:'styles',status:'running'};renderMsgs([{id:'progress',role:'assistant',phase:'commentary',turn_id:'t',text:'Windows `dev.12`，提交 `93aedd4`。'},{id:'tool',role:'tool',turn_id:'t',text:'@\' import subprocess '+ 'long '.repeat(80),detail:'@\'\nimport subprocess\n\'@ | python -',tool_status:'completed'},{id:'final',role:'assistant',text:'Windows `dev.12`'}]);}""")
        assert page.locator('.inline-copy').count()==0
        assert page.locator('.activity-progress code').count()==2
        metrics=page.locator('.activity-progress').evaluate('(n)=>{const s=getComputedStyle(n),c=getComputedStyle(n.querySelector("code"));return [s.fontSize,s.fontWeight,s.lineHeight,c.fontSize,c.fontWeight]}')
        assert metrics==['14px','400','21.699999px','14px','400'] or metrics==['14px','400','21.7px','14px','400'],metrics
        assert 'import subprocess' not in page.locator('.activity-title').inner_text()
        page.evaluate("""()=>{readingUI.onOpen({},cur);readingUI.resumeStream();const stream=testStreams.at(-1),base={app:'codex',id:cur.id,protocol:1};stream.emit({...base,type:'snapshot',seq:1,chat:{status:'running',messages:[{id:'live-public',role:'assistant',phase:'commentary',turn_id:'t',streaming:true,text:'VISIBLE PUBLIC TEXT',order:100}]},streaming_ids:['live-public']});window.retainedGroup=document.querySelector('.activity-group');stream.emit({...base,type:'update',seq:2,messages:[{id:'tool-arrival',role:'tool',turn_id:'t',text:'tool',order:200}],streaming_ids:['live-public'],control:{available:false,plan:{id:'old-plan',ready:false,text:'OLD PLAN'}}});stream.emit({...base,type:'update',seq:3,messages:[],streaming_ids:[]});}""")
        assert 'VISIBLE PUBLIC TEXT' in page.locator('#cvMsgs').inner_text()
        assert 'OLD PLAN' not in page.locator('#cvMsgs').inner_text()
        page.evaluate("""()=>{const stream=testStreams.at(-1);stream.emit({app:'codex',id:cur.id,protocol:1,type:'snapshot',seq:1,chat:{status:'running',messages:[]},streaming_ids:[]});stream.emit({app:'codex',id:cur.id,protocol:1,type:'update',seq:2,messages:[{id:'live-public',role:'assistant',phase:'commentary',turn_id:'t',text:'VISIBLE PUBLIC TEXT SETTLED',order:100}],streaming_ids:[]});}""")
        assert page.locator('.activity-progress').count()==1
        assert page.evaluate("!messageProjection.merge([{id:'x',streaming:true,sync_pending:true}],[{id:'x',text:'settled'}])[0].streaming")
        assert 'SETTLED' in page.locator('.activity-progress').inner_text()
        assert page.evaluate("document.querySelector('.activity-group')===retainedGroup")
        shots=ROOT/'build/history-projection-check';shots.mkdir(parents=True,exist_ok=True)
        for theme in ['light','dark']:
            page.evaluate('TeleplyTheme.set',theme)
            assert page.evaluate("$('cvMsgs').scrollWidth<=$('cvMsgs').clientWidth+1")
            page.screenshot(path=str(shots/(engine+'-'+theme+'.png')))
        page.evaluate("document.documentElement.style.webkitTextSizeAdjust='150%'")
        assert page.evaluate("$('cvMsgs').scrollWidth<=$('cvMsgs').clientWidth+1")
        browser.close()

if __name__=='__main__':
    for engine in ['chromium','webkit']:run(engine)
    print('History projection and typography checks passed')
