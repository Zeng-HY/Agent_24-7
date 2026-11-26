package com.pocketagentdesk.teleply

import java.nio.charset.Charset
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.*
import org.json.JSONObject
import org.junit.Test
import org.junit.Assert.*

private class WorkspaceStore:ReaderStore by TestStore() {
    val values=mutableMapOf<Pair<ChatKey,String>,String>()
    override suspend fun detail(key:ChatKey,kind:String)=values[key to kind]
    override suspend fun detail(key:ChatKey,kind:String,value:String) { values[key to kind]=value }
}
private class WorkspaceApi:ReadApi by FixtureApi() {
    var submits=0;var answers=0;var reads=0;var stateReads=0;var catalogs=0;var freshCatalogs=0;var uncertain=false;var stale=false
    var body:JSONObject?=null
    override suspend fun detail(device:String,route:String,query:Map<String,String?>,body:JSONObject?):JSONObject {
        if(route=="chat/new/draft") return JSONObject().put("request_id","a".repeat(32))
        if(route=="chat/new") { submits++;this.body=body;if(uncertain) throw java.io.IOException("timeout");return JSONObject().put("request_id",body!!.string("request_id")).put("state","accepted").put("app","codex").put("id","new") }
        if(route=="chat/new/state") { reads++;assertEquals("a".repeat(32),query["request_id"]);return JSONObject().put("request_id","a".repeat(32)).put("state","accepted").put("app","codex").put("id","new") }
        if(route=="deepseek/approval") { answers++;if(body!!.string("event_id")=="old") throw ServiceFailure(409,detail="操作已撤回、已处理或连接已变化，请刷新（批准请求已失效）");return JSONObject().put("submitted",true) }
        if(route=="claude/catalog") { catalogs++;if(body!!.optBoolean("fresh")) freshCatalogs++;return JSONObject().put("model_id","opus").put("model",org.json.JSONArray().put(JSONObject().put("name","Opus").put("selected",true))) }
        return JSONObject()
    }
    override suspend fun control(device:String,chat:String,fresh:Boolean):Control {
        stateReads++
        val raw=JSONObject("""{"available":true,"questions":[{"id":"q","status":"pending","answer_revision":"${if(stale) "v2" else "v1"}"}]}""")
        return parseControl(raw)
    }
    override suspend fun command(device:String,route:String,body:JSONObject):JSONObject {
        answers++;this.body=body
        if(uncertain) throw java.io.IOException("timeout")
        // The computer checks the answer against the question as it is now (codex_control answer).
        if(stale && body.string("answer_revision")!="v2") throw ServiceFailure(400,detail="答案已在其他设备更新，请刷新核对后再修改")
        return JSONObject().put("request_id",body.string("request_id")).put("accepted",true)
    }
}
/** Claude as the computer reads it: [asking] a question with an option, else nothing waiting; a press's reply may be [lost]. */
private class ClaudePressApi:ReadApi by FixtureApi() {
    var asking=true;var lost=true;var presses=0
    override suspend fun detail(device:String,route:String,query:Map<String,String?>,body:JSONObject?):JSONObject {
        if(route=="claude/choose") { presses++;if(lost) throw java.io.IOException("timeout");return JSONObject().put("ok",true).put("text","已在电脑上点选") }
        return JSONObject()
    }
    override suspend fun control(device:String,chat:String,fresh:Boolean):Control {
        val raw=JSONObject().put("available",true)
        if(asking) raw.put("prompt",JSONObject("""{"title":"选哪个？","choices":[{"label":"甲","token":"t1"}],"nav":[]}"""))
        return parseControl(raw)
    }
}
@OptIn(ExperimentalCoroutinesApi::class)
class WorkspaceControllerTest {
    /** 10-27: a Claude press whose reply was lost. 核对上次操作 reads Claude again and settles it with what it found; nothing is pressed again. */
    @Test fun aLostClaudePressIsCheckedAndSettledWithoutPressingAgain()=runTest {
        val claude=key.copy(app="claude");val api=ClaudePressApi();val shown=mutableListOf<JSONObject>()
        val c=WorkspaceController(backgroundScope,WorkspaceStore());c.stateRead={ _,raw -> shown+=raw };c.bind(claude,api,false);runCurrent()
        c.action("claude/choose",JSONObject().put("token","t1"),local=claudePress("choice"));runCurrent()
        val pending=JSONObject(c.state.value.saved).getJSONObject("pending_action")
        assertEquals("unknown",pending.string("status"));assertTrue(pending.optLong("at")>0);assertEquals("choice",pending.getJSONObject("local").string("what"))
        assertFalse(pending.getJSONObject("body").has("local"))
        assertEquals("没收到电脑的回复，上次操作的结果还没确认；不会自动重试。",c.state.value.error)
        c.checkAction();runCurrent()
        assertEquals("电脑上的 Claude 还在等你选；上次那一下可能没送到，请再选一次。",c.state.value.result)
        assertEquals("done",JSONObject(c.state.value.saved).getJSONObject("pending_action").string("status"))
        assertEquals(1,api.presses);assertEquals(1,shown.size);assertNull(c.state.value.error);assertFalse(c.state.value.busy);assertFalse(c.state.value.checking)
        // Settled, the same option can be pressed again.
        api.lost=false;c.action("claude/choose",JSONObject().put("token","t1"),local=claudePress("choice"));runCurrent()
        assertEquals(2,api.presses);assertNull(c.state.value.error)
        // Lost again, and this time nothing waits on the computer any more.
        api.lost=true;c.action("claude/choose",JSONObject().put("token","t2"),local=claudePress("choice"));runCurrent()
        api.asking=false;c.checkAction();runCurrent()
        assertEquals("电脑上已经没有在等的选项，上次的选择已处理。",c.state.value.result);assertEquals(3,api.presses)
        assertEquals(2,JSONObject(c.state.value.saved).getJSONArray("action_history").length())
    }
    /** 10-27: past the 2 minutes the computer takes the token, or kept without a time, a press goes quietly on the next state read. */
    @Test fun aStaleClaudePressGoesQuietlyOnTheNextStateRead()=runTest {
        val claude=key.copy(app="claude");val store=WorkspaceStore()
        fun stored(at:Long?)=JSONObject().put("pending_action",JSONObject().put("route","claude/choose").put("body",JSONObject().put("token","t1").put("request_id","r1")).put("status","unknown").apply { if(at!=null) put("at",at) }).toString()
        for(at in listOf(null,System.currentTimeMillis()-ClaudePressLife-1_000)) {
            store.values[claude to "workspace"]=stored(at)
            val c=WorkspaceController(backgroundScope,store);c.bind(claude,ClaudePressApi(),false);runCurrent()
            c.claudeStateRead(claude);runCurrent()
            val pending=JSONObject(c.state.value.saved).getJSONObject("pending_action")
            assertEquals("done",pending.string("status"));assertEquals("expired",pending.string("settled"));assertEquals("",c.state.value.result)
            assertEquals("done",JSONObject(store.values[claude to "workspace"]!!).getJSONObject("pending_action").string("status"))
        }
        // A press of a moment ago may still land: it stays to be checked.
        store.values[claude to "workspace"]=stored(System.currentTimeMillis())
        val fresh=WorkspaceController(backgroundScope,store);fresh.bind(claude,ClaudePressApi(),false);runCurrent()
        fresh.claudeStateRead(claude);runCurrent()
        assertEquals("unknown",JSONObject(fresh.state.value.saved).getJSONObject("pending_action").string("status"))
        // Codex and DeepSeek actions are not Claude presses: they wait for their own check.
        val codex=WorkspaceStore();codex.values[key to "workspace"]=stored(null).replace("claude/choose","codex/answer")
        val other=WorkspaceController(backgroundScope,codex);other.bind(key,ClaudePressApi(),false);runCurrent()
        other.claudeStateRead(key);runCurrent()
        assertEquals("unknown",JSONObject(other.state.value.saved).getJSONObject("pending_action").string("status"))
    }
    /** What a checked Claude press came to: a stop, a 立即补充, plan options; a press kept before 10-27 reads as a choice. */
    @Test fun whatACheckedClaudePressCameTo() {
        fun found(press:JSONObject,raw:String)=claudePressFound(JSONObject().put("local",press),parseControl(JSONObject(raw)))
        assertEquals("电脑上的 Claude 还在运行；上次的停止可能没送到，需要的话请再点一次。",found(claudePress("stop"),"""{"running":true}"""))
        assertEquals("电脑上的 Claude 已经停下了。",found(claudePress("stop"),"""{"running":false}"""))
        assertEquals("这条消息还在电脑上排队；上次的立即补充可能没送到，可以再点一次。",found(claudePress("steer","q1"),"""{"queued":[{"id":"q1","text":"x","token":"t"}]}"""))
        assertEquals("这条消息已经不在电脑上排队了，上次的立即补充已处理。",found(claudePress("steer","q1"),"""{"queued":[]}"""))
        assertEquals("电脑上的 Claude 还在等你选；上次那一下可能没送到，请再选一次。",claudePressFound(JSONObject(),parseControl(JSONObject("""{"actions":[{"name":"Yes","token":"t"}]}"""))))
    }
    /**
     * 10-28: Word and Excel are drawn on the phone from the file itself, with no PDF asked for. PowerPoint, the old .ppt
     * and a Word file over 20 MB show as the PDF the computer's Office makes (10-27); the page and its buttons are there
     * meanwhile.
     */
    @Test fun wordAndExcelShowOnThePhoneAndPowerPointAsTheComputersPdf()=runTest {
        val gate=CompletableDeferred<Unit>();val asked=mutableListOf<String>();val fetched=mutableListOf<String>();var fails:Exception?=null
        val api=object:ReadApi by FixtureApi() {
            override suspend fun detail(device:String,route:String,query:Map<String,String?>,body:JSONObject?):JSONObject {
                assertEquals("file/meta",route)
                return JSONObject().put("kind","download").put("size",if(query["file"]=="big") PreviewLimit+1 else 12).put("state","current").apply { if(query["file"]!="plain") put("preview","pdf") }
            }
            override suspend fun download(device:String,chat:String,file:String):ByteArray { fetched+=file;return "PK$file".toByteArray() }
            override suspend fun filePdf(device:String,chat:String,file:String,limit:Long):ByteArray {
                asked+=file;assertEquals(PreviewLimit,limit);gate.await();fails?.let { throw it };return "%PDF".toByteArray()
            }
        }
        val c=WorkspaceController(backgroundScope,WorkspaceStore());c.bind(key,api,false);runCurrent()
        // Word and Excel: the file itself, drawn here; the computer's offer of a PDF is kept for when the phone cannot.
        c.file(JSONObject().put("id","doc").put("name","报告.docx"));runCurrent()
        assertEquals("phone",JSONObject(c.state.value.data).string("preview"));assertTrue(JSONObject(c.state.value.data).optBoolean("pdf"))
        assertEquals("PKdoc",String(c.state.value.preview!!));assertFalse(c.state.value.converting);assertFalse(c.state.value.busy)
        c.file(JSONObject().put("id","sheet").put("name","预算.XLSX"));runCurrent()
        assertEquals("phone",JSONObject(c.state.value.data).string("preview"));assertEquals("PKsheet",String(c.state.value.preview!!))
        assertEquals(listOf("doc","sheet"),fetched);assertEquals(emptyList<String>(),asked)
        // PowerPoint: the computer's PDF; the page and its buttons at once.
        c.file(JSONObject().put("id","slides").put("name","汇报.pptx"));runCurrent()
        assertTrue(c.state.value.converting);assertFalse(c.state.value.busy);assertNull(c.state.value.preview)
        assertEquals("pdf",JSONObject(c.state.value.data).string("preview"));assertEquals("download",JSONObject(c.state.value.data).string("kind"))
        gate.complete(Unit);runCurrent()
        assertFalse(c.state.value.converting);assertEquals("%PDF",String(c.state.value.preview!!));assertEquals("",c.state.value.previewNote)
        // A Word file past the 15 MB limit is not fetched and not drawn (11-26): the failure page says why, no PDF.
        c.file(JSONObject().put("id","big").put("name","大报告.docx"));runCurrent()
        assertEquals("failed",JSONObject(c.state.value.data).string("preview"));assertEquals(OfficeTooLargeNote,c.state.value.previewNote)
        assertNull(c.state.value.preview);assertFalse(c.state.value.converting)
        // The computer cannot: its words, no preview, and nothing else held up.
        fails=ServiceFailure(500,detail="电脑上的 PowerPoint 没有响应");c.file(JSONObject().put("id","deck").put("name","旧汇报.ppt"));runCurrent()
        assertEquals("没能转成 PDF：电脑上的 PowerPoint 没有响应",c.state.value.previewNote);assertNull(c.state.value.preview)
        assertNull(c.state.value.error);assertFalse(c.state.value.converting);assertFalse(c.state.value.busy)
        // Leaving the page drops what it said.
        c.close();assertEquals("",c.state.value.previewNote)
        // No "preview": as before, no PDF asked for.
        c.file(JSONObject().put("id","plain").put("name","数据.bin"));runCurrent()
        assertEquals(listOf("slides","deck"),asked);assertFalse(JSONObject(c.state.value.data).has("preview"));assertFalse(c.state.value.converting)
        assertEquals(listOf("doc","sheet"),fetched)
    }
    /**
     * 11-26: a Word or Excel file docx-preview cannot draw shows the failure page, with its same-named PDF when the
     * answer listed one; the computer's own PDF is not asked for by itself any more.
     */
    @Test fun aFileThePhoneCannotDrawShowsTheFailurePage()=runTest {
        val asked=mutableListOf<String>()
        val pdf=JSONObject().put("id","pdf").put("name","坏了.pdf").put("kind","pdf").put("size",12)
        val api=object:ReadApi by FixtureApi() {
            override suspend fun detail(device:String,route:String,query:Map<String,String?>,body:JSONObject?):JSONObject {
                if(route=="chat/files") return JSONObject().put("items",org.json.JSONArray().put(pdf))
                return JSONObject().put("kind","download").put("size",12).put("state","current")
            }
            override suspend fun download(device:String,chat:String,file:String)="PK".toByteArray()
            override suspend fun filePdf(device:String,chat:String,file:String,limit:Long):ByteArray { asked+=file;return "%PDF".toByteArray() }
        }
        val c=WorkspaceController(backgroundScope,WorkspaceStore());c.bind(key,api,false);runCurrent()
        c.file(JSONObject().put("id","offered").put("name","坏了.docx").put("linked",true));runCurrent()
        assertEquals("phone",JSONObject(c.state.value.data).string("preview"))
        c.officeFailed();runCurrent()
        val failed=JSONObject(c.state.value.data)
        assertEquals("failed",failed.string("preview"));assertEquals("",c.state.value.previewNote);assertNull(c.state.value.preview)
        assertEquals("坏了.pdf",failed.optJSONObject("pdf_file")?.string("name"))
        assertEquals(emptyList<String>(),asked)
        // Once per page: a second title from the dead page changes nothing.
        c.officeFailed();runCurrent();assertEquals(emptyList<String>(),asked)
        // A file that did not come from an answer (the computer's file browser) looks for no PDF.
        c.file(JSONObject().put("id","alone").put("name","坏了.xlsx"));runCurrent()
        c.officeFailed();runCurrent()
        assertEquals("failed",JSONObject(c.state.value.data).string("preview"));assertFalse(JSONObject(c.state.value.data).has("pdf_file"))
    }
    /** 11-26: a Word or Excel file whose body is over 8 MB is not drawn; only the zip's directory is read for that. */
    @Test fun aWordFileTooBigToDrawShowsTheFailurePageWithoutTheComputersPdf()=runTest {
        val big=madeUpZip("word/document.xml" to (OfficeBodyLimit.toInt()+1024))
        val fetched=mutableListOf<String>();val asked=mutableListOf<String>()
        val api=object:ReadApi by FixtureApi() {
            override suspend fun detail(device:String,route:String,query:Map<String,String?>,body:JSONObject?):JSONObject =
                JSONObject().put("kind","download").put("size",big.size).put("state","current").put("preview","pdf")
            override suspend fun download(device:String,chat:String,file:String):ByteArray { fetched+=file;return big }
            override suspend fun filePdf(device:String,chat:String,file:String,limit:Long):ByteArray { asked+=file;return "%PDF".toByteArray() }
        }
        val c=WorkspaceController(backgroundScope,WorkspaceStore());c.bind(key,api,false);runCurrent()
        c.file(JSONObject().put("id","big").put("name","大文档.docx"));runCurrent()
        assertEquals("failed",JSONObject(c.state.value.data).string("preview"))
        assertEquals(OfficeTooLargeNote,c.state.value.previewNote);assertNull(c.state.value.preview)
        assertEquals(listOf("big"),fetched);assertEquals(emptyList<String>(),asked)
        // Excel: its worksheets' XML added up.
        val sheets=madeUpZip("xl/worksheets/sheet1.xml" to (5*1024*1024),"xl/worksheets/sheet2.xml" to (4*1024*1024))
        val excel=object:ReadApi by FixtureApi() {
            override suspend fun detail(device:String,route:String,query:Map<String,String?>,body:JSONObject?):JSONObject =
                JSONObject().put("kind","download").put("size",sheets.size).put("state","current")
            override suspend fun download(device:String,chat:String,file:String)=sheets
        }
        c.bind(key,excel,false);runCurrent()
        c.file(JSONObject().put("id","excel").put("name","大表格.xlsx"));runCurrent()
        assertEquals("failed",JSONObject(c.state.value.data).string("preview"));assertEquals(OfficeTooLargeNote,c.state.value.previewNote)
    }
    /**
     * 11-26: with the phone's cache, a Word file is drawn from its kept copy — its path, streamed by the page — and is
     * not held as a ByteArray in the page's state; its same-named PDF from the answer is found for the failure page.
     */
    @Test fun aWordFileIsDrawnFromItsKeptFileNotFromBytes()=runBlocking {
        val dir=java.nio.file.Files.createTempDirectory("teleply-office").toFile()
        val small=madeUpZip("word/document.xml" to 2048,"word/styles.xml" to 100)
        val big=madeUpZip("word/document.xml" to (OfficeBodyLimit.toInt()+1024))
        var content=small
        val api=object:ReadApi by FixtureApi() {
            override suspend fun detail(device:String,route:String,query:Map<String,String?>,body:JSONObject?):JSONObject = when(route) {
                "file/meta" -> JSONObject().put("kind","download").put("size",content.size).put("state","current")
                "chat/files" -> JSONObject().put("items",org.json.JSONArray(FixtureWorld.FILES))
                else -> JSONObject()
            }
            override suspend fun downloadTo(device:String,chat:String,file:String,output:java.io.OutputStream) { output.write(content) }
            override suspend fun download(device:String,chat:String,file:String)=content
        }
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined)
        val c=WorkspaceController(scope,TestStore());c.mediaDir=dir;c.bind(key,api,false)
        withTimeout(5000) { c.state.first { it.ready } }
        try {
            c.file(JSONObject().put("id","doc").put("name","报告.docx").put("v","v1"))
            val drawn=withTimeout(5000) { c.state.first { it.pane=="file" && !it.busy } }
            assertEquals("phone",JSONObject(drawn.data).string("preview"))
            assertNull("nothing whole in the page's state",drawn.preview)
            val kept=java.io.File(drawn.previewFile!!)
            assertTrue(kept.isFile);assertEquals(small.size.toLong(),kept.length())
            // The demo's big Word, from an answer: the failure page and that answer's same-named PDF.
            content=big
            c.file(JSONObject().put("id","fp-bigdoc").put("name","大文档.docx").put("v","v2").put("linked",true))
            val failed=withTimeout(5000) { c.state.first { it.pane=="file" && !it.busy && JSONObject(it.data).string("preview")=="failed" } }
            assertEquals(OfficeTooLargeNote,failed.previewNote);assertNull(failed.preview)
            assertEquals("大文档.pdf",JSONObject(failed.data).optJSONObject("pdf_file")?.string("name"))
        } finally {
            scope.cancel();dir.deleteRecursively()
        }
    }
    @Test fun wordAndExcelAreTheFilesThePhoneDraws() {
        assertEquals("word",phoneOffice("报告.docx"));assertEquals("word",phoneOffice("模板.DOTX"))
        assertEquals("sheet",phoneOffice("预算.xls"));assertEquals("sheet",phoneOffice("数据.csv"));assertEquals("sheet",phoneOffice("宏.xlsm"))
        assertEquals("sheet",phoneOffice("数据.tsv"));assertEquals("sheet",phoneOffice("数据.TSV"));assertEquals("sheet",phoneOffice("数据.CSV"))
        listOf("汇报.pptx","旧.doc","旧.ppt","说明.pdf","没有扩展名","点.").forEach { assertNull(it,phoneOffice(it)) }
    }
    /**
     * 11-16: a CSV or TSV is a table on the phone from the file itself, whether the computer calls it text or a
     * download. The phone reads its bytes and its encoding and does not ask for the computer's text, which cannot read
     * a GBK file.
     */
    @Test fun csvShowsAsATableFromTheFileItselfWhicheverKindTheComputerGives()=runTest {
        val text="编号,问题\r\n01,\"第一段\n- **依据**：a,b\"\r\n02,第二行"
        val bytes=text.toByteArray(Charsets.UTF_8)
        val routes=mutableListOf<String>();val fetched=mutableListOf<String>()
        val api=object:ReadApi by FixtureApi() {
            var kind="text"
            override suspend fun detail(device:String,route:String,query:Map<String,String?>,body:JSONObject?):JSONObject {
                routes+=route
                return if(route=="file/meta") JSONObject().put("kind",kind).put("size",bytes.size) else JSONObject().put("text","电脑的原文")
            }
            override suspend fun download(device:String,chat:String,file:String):ByteArray { fetched+=file;return bytes }
        }
        val c=WorkspaceController(backgroundScope,WorkspaceStore());c.bind(key,api,false);runCurrent()
        for((id,kind) in listOf("csv" to "text","csv-download" to "download")) {
            api.kind=kind
            c.file(JSONObject().put("id",id).put("name","去重问题清单.csv"));runCurrent()
            val data=JSONObject(c.state.value.data)
            assertEquals("phone",data.string("preview"));assertEquals("csv",data.string("sheet"))
            assertEquals(text,c.state.value.result);assertArrayEquals(bytes,c.state.value.preview)
            assertFalse(c.state.value.busy);assertNull(c.state.value.error)
        }
        // The computer's text is never asked for: it only knows UTF-8 and UTF-16.
        assertEquals(listOf("file/meta","file/meta"),routes);assertEquals(listOf("csv","csv-download"),fetched)
    }
    /** 11-16: a CSV saved by Chinese Excel is GBK; the phone reads it as GB18030, as the computer cannot. */
    @Test fun aGbkCsvIsReadOnThePhone()=runTest {
        val text="编号,问题\n01,中文格子\n02,第二行"
        val bytes=text.toByteArray(Charset.forName("GB18030"))
        val api=object:ReadApi by FixtureApi() {
            override suspend fun detail(device:String,route:String,query:Map<String,String?>,body:JSONObject?):JSONObject =
                JSONObject().put("kind","text").put("size",bytes.size)
            override suspend fun download(device:String,chat:String,file:String)=bytes
        }
        val c=WorkspaceController(backgroundScope,WorkspaceStore());c.bind(key,api,false);runCurrent()
        c.file(JSONObject().put("id","gbk").put("name","问题清单.csv"));runCurrent()
        assertEquals(text,c.state.value.result);assertEquals("phone",JSONObject(c.state.value.data).string("preview"))
        assertArrayEquals(text.toByteArray(),c.state.value.preview)
    }
    /** 11-16: a CSV whose table cannot be drawn shows its source, and never asks the computer for a PDF it has not got. */
    @Test fun aCsvTheTableCannotDrawFallsBackToTheSourceNotToTheComputersPdf()=runTest {
        val text="编号,问题\n01,中文"
        val bytes=text.toByteArray(Charsets.UTF_8)
        val asked=mutableListOf<String>()
        val api=object:ReadApi by FixtureApi() {
            override suspend fun detail(device:String,route:String,query:Map<String,String?>,body:JSONObject?):JSONObject =
                JSONObject().put("kind","download").put("size",bytes.size).put("preview","pdf")
            override suspend fun download(device:String,chat:String,file:String)=bytes
            override suspend fun filePdf(device:String,chat:String,file:String,limit:Long):ByteArray { asked+=file;return "%PDF".toByteArray() }
        }
        val c=WorkspaceController(backgroundScope,WorkspaceStore());c.bind(key,api,false);runCurrent()
        c.file(JSONObject().put("id","csv").put("name","去重问题清单.csv"));runCurrent()
        c.officeFailed();runCurrent()
        assertEquals(emptyList<String>(),asked)
        assertEquals("failed",JSONObject(c.state.value.data).string("preview"));assertNull(c.state.value.preview)
        assertEquals(text,c.state.value.result);assertEquals("表格显示不了，下面是原文",c.state.value.previewNote)
        assertFalse(c.state.value.converting)
    }
    /** 核对上次操作 with nothing open left the page busy for good: every later action and state poll waited on it. */
    @Test fun checkingTheLastActionLeavesThePageFree()=runTest {
        val api=WorkspaceApi().apply { uncertain=true };val c=WorkspaceController(backgroundScope,WorkspaceStore());c.bind(key,api,false);runCurrent()
        c.action("codex/answer",JSONObject("""{"question_id":"q","answers":{"a":["A"]}}"""),JSONObject("""{"id":"q","answer_revision":"v1"}"""));runCurrent()
        c.checkAction();runCurrent()
        assertEquals("回答回执：unknown",c.state.value.result);assertFalse(c.state.value.busy);assertFalse(c.state.value.checking)
        assertEquals("unknown",JSONObject(c.state.value.saved).getJSONObject("pending_action").string("status"))
    }
    @Test fun computerFileOpensDownloadWithoutChangingReferencesOrDraft()=runTest {
        val api=object:ReadApi by FixtureApi() {
            override suspend fun detail(device:String,route:String,query:Map<String,String?>,body:JSONObject?):JSONObject {
                assertEquals("file/meta",route);assertEquals("pc.ticket.signature",query["file"])
                return JSONObject("""{"kind":"download","size":12,"state":"current"}""")
            }
        }
        val c=WorkspaceController(backgroundScope,WorkspaceStore());c.bind(key,api,false);runCurrent();c.edit("first_message","draft");runCurrent()
        c.computerFile(JSONObject("""{"id":"reference","download_id":"pc.ticket.signature","name":"报告.xlsx","kind":"file"}"""));runCurrent()
        assertEquals("file",c.state.value.pane);assertEquals("draft",JSONObject(c.state.value.saved).string("first_message"))
        assertEquals(0,c.sendExtras().getJSONArray("references").length())
        assertEquals("pc.ticket.signature",JSONObject(c.state.value.data).string("id"));assertNull(c.state.value.error)
    }
    @Test fun previewFailureStillAllowsOriginalFileDownload()=runTest {
        val api=object:ReadApi by FixtureApi() {
            override suspend fun detail(device:String,route:String,query:Map<String,String?>,body:JSONObject?):JSONObject {
                if(route=="file/text") throw java.io.IOException("bad encoding")
                return JSONObject("""{"kind":"text","size":12}""")
            }
        }
        val c=WorkspaceController(backgroundScope,WorkspaceStore());c.bind(key,api,false);runCurrent()
        c.file(JSONObject("""{"id":"file","name":"报告.txt"}"""));runCurrent()
        assertNull(c.state.value.error);assertFalse(c.state.value.busy);assertTrue(c.state.value.transfer.contains("仍可"))
    }
    @Test fun skillRetryForcesBothRoutesAndKeepsDraft()=runTest {
        for(chat in listOf("chat","@new")) {
            val requests=mutableListOf<Pair<String,Map<String,String?>>>()
            val api=object:ReadApi by FixtureApi() {
                override suspend fun detail(device:String,route:String,query:Map<String,String?>,body:JSONObject?):JSONObject {
                    requests+=route to query
                    return JSONObject("""{"items":[],"scan_status":"partial","scan_id":"one"}""")
                }
            }
            val c=WorkspaceController(backgroundScope,WorkspaceStore());c.bind(key.copy(chat=chat),api,false);runCurrent()
            c.edit("first_message","保留正文");c.addReference(JSONObject("""{"kind":"skill","id":"chosen"}"""));runCurrent()
            c.panel("skill");runCurrent();c.refresh("skill","中文",fresh=true);runCurrent()
            val request=requests.last();assertEquals(if(chat=="@new") "chat/new/references" else "composer/references",request.first)
            assertEquals("1",request.second["fresh"]);assertEquals("中文",request.second["query"]);assertEquals("0",request.second["offset"])
            assertEquals("保留正文",JSONObject(c.state.value.saved).string("first_message"))
            assertEquals(1,c.sendExtras().getJSONArray("references").length())
        }
    }
    @Test fun lateSkillResponseCannotOverwriteNewPanel()=runTest {
        val pending=CompletableDeferred<Unit>()
        val api=object:ReadApi by FixtureApi() {
            override suspend fun detail(device:String,route:String,query:Map<String,String?>,body:JSONObject?):JSONObject {
                if(query["kind"]=="skill") withContext(NonCancellable) { pending.await() }
                return JSONObject("""{"items":[{"name":"old"}]}""")
            }
        }
        val c=WorkspaceController(backgroundScope,WorkspaceStore());c.bind(key,api,false);runCurrent()
        c.panel("skill");runCurrent();c.panel("new");pending.complete(Unit);runCurrent()
        assertEquals("new",c.state.value.pane);assertEquals("{}",c.state.value.data)
    }
    @Test fun missingSnapshotImageBlocksSendInsteadOfSilentlyOmitting()=runTest {
        val c=WorkspaceController(backgroundScope,WorkspaceStore());c.bind(key,WorkspaceApi(),false);runCurrent()
        c.restoreSent(key,JSONObject("""{"attachments":["gone"],"references":[]}"""));runCurrent()
        assertThrows(IllegalArgumentException::class.java) { c.sendExtras() }
        assertEquals("failed",JSONObject(c.state.value.saved).rows("uploads") { it }.single().string("status"))
    }
    private val key=ChatKey("owner","a".repeat(32),"chat")
    @Test fun sourceIsolationAndInterruptedUploadBlockSend()=runTest {
        val store=WorkspaceStore();store.values[key to "workspace"]="""{"uploads":[{"local":"u","status":"uploading","image":true}]}"""
        val c=WorkspaceController(backgroundScope,store);val api=WorkspaceApi();c.bind(key,api,false);runCurrent()
        assertThrows(IllegalArgumentException::class.java) { c.sendExtras() }
        assertEquals("failed",JSONObject(c.state.value.saved).rows("uploads") { it }.single().string("status"))
        c.bind(key.copy(app="deepseek"),api,false);runCurrent();assertEquals(0,c.sendExtras().getJSONArray("attachments").length())
    }
    @Test fun referencesUseIdentityAndPersistAcrossRecreation()=runTest {
        val store=WorkspaceStore();val api=WorkspaceApi();val c=WorkspaceController(backgroundScope,store);c.bind(key,api,false);runCurrent()
        c.addReference(JSONObject("""{"kind":"chat","id":"one","title":"same"}"""));c.addReference(JSONObject("""{"kind":"chat","id":"two","title":"same"}"""));runCurrent()
        assertEquals(2,c.sendExtras().getJSONArray("references").length())
        val restored=WorkspaceController(backgroundScope,store);restored.bind(key,api,false);runCurrent();assertEquals(2,restored.sendExtras().getJSONArray("references").length())
    }
    /** 0.8 (web 10-16): 创建并发送 hands the draft over as one job and the sheet starts afresh, keeping the project. */
    @Test fun createHandsOneJobAndStartsTheSheetAfresh()=runTest {
        val store=WorkspaceStore();val api=WorkspaceApi();val c=WorkspaceController(backgroundScope,store);val new=key.copy(chat="@new")
        val made=mutableListOf<NewJob>();c.created={ made+=it }
        c.bind(new,api,false);runCurrent();c.edit("folder","D:/p");c.edit("first_message","fixed test");runCurrent()
        c.create();c.create();runCurrent()
        assertEquals(1,made.size);assertEquals("a".repeat(32),made.single().request)
        // The sheet sends nothing itself: the job does, outside it.
        assertEquals(0,api.submits)
        val body=JSONObject(made.single().body);assertEquals("fixed test",body.string("text"));assertEquals("D:/p",body.string("folder"))
        val left=JSONObject(store.values[new to "workspace"]!!)
        assertEquals("",left.string("first_message"));assertEquals("D:/p",left.string("folder"));assertFalse(left.has("new_id"))
    }
    /** A job's reply lost on the way is only looked up afterwards, never sent again; jobs stay on the phone. */
    @Test fun jobIsSentOnceAndALostReplyIsOnlyChecked()=runTest {
        val store=WorkspaceStore();val api=WorkspaceApi().apply { uncertain=true }
        val jobs=NewChatJobs(backgroundScope,store);jobs.pause={}
        jobs.bind("owner","a".repeat(32),api,false);jobs.foreground(true);runCurrent()
        val job=NewJob("a".repeat(32),"codex","D:/p",false,"p","fixed test",body=JSONObject().put("request_id","a".repeat(32)).toString(),pending=JSONObject().put("state","creating").toString())
        jobs.submit(job);runCurrent()
        assertEquals(1,api.submits);assertEquals(1,api.reads)
        assertEquals("accepted",jobs.jobs.value.single().state);assertEquals("new",jobs.jobs.value.single().createdId)
        val again=NewChatJobs(backgroundScope,store);again.bind("owner","a".repeat(32),api,false);runCurrent()
        assertEquals("a".repeat(32),again.jobs.value.single().request)
    }
    /** 0.8: an answer goes at once; the computer turns a stale one away, and it may then be tried again. */
    @Test fun staleAnswerIsTurnedAwayByTheComputerWithoutAStateRead()=runTest {
        val api=WorkspaceApi();val c=WorkspaceController(backgroundScope,WorkspaceStore());c.bind(key,api,false);runCurrent()
        c.edit("answers:q:v1","""{"a":["A"]}""");runCurrent();assertEquals(0,api.answers)
        api.stale=true;c.action("codex/answer",JSONObject().put("question_id","q").put("answer_revision","v1"),JSONObject("""{"id":"q","answer_revision":"v1"}"""));runCurrent()
        assertEquals(1,api.answers);assertEquals(0,api.stateReads);assertTrue(c.state.value.error!!.contains("更新"))
        assertNull(JSONObject(c.state.value.saved).optJSONObject("pending_action"))
    }
    @Test fun uncertainAnswerIsPersistedAndSameActionNotReplayed()=runTest {
        val store=WorkspaceStore();val api=WorkspaceApi().apply { uncertain=true };val c=WorkspaceController(backgroundScope,store);c.bind(key,api,false);runCurrent()
        val card=JSONObject("""{"id":"q","answer_revision":"v1"}""");val body=JSONObject("""{"question_id":"q","answers":{"a":["A"]}}""")
        c.action("codex/answer",body,card);runCurrent();c.action("codex/answer",body,card);runCurrent()
        assertEquals(1,api.answers);assertEquals("unknown",JSONObject(store.values[key to "workspace"]!!).getJSONObject("pending_action").string("status"))
    }
    /** 11-16: a Codex approval answers through codex/answer with its one decision and the card's revision. */
    @Test fun aCodexApprovalSendsTheOneDecision()=runTest {
        val api=WorkspaceApi();val c=WorkspaceController(backgroundScope,WorkspaceStore());c.bind(key,api,false);runCurrent()
        val card=JSONObject("""{"id":"approval:t:r","answer_revision":"v1"}""")
        c.action("codex/answer",JSONObject().put("question_id","approval:t:r").put("answer_revision","v1")
            .put("answers",JSONObject().put("decision",org.json.JSONArray().put("accept"))),card);runCurrent()
        assertEquals(1,api.answers);assertEquals(0,api.stateReads)
        assertEquals("accept",api.body!!.getJSONObject("answers").getJSONArray("decision").getString(0))
    }
    @Test fun filesOnlySnapshotKeepsUploadIdentityAndClearsOnlySubmitted()=runTest {
        val store=WorkspaceStore();store.values[key to "workspace"]="""{"uploads":[{"local":"u","status":"ready","image":false,"meta":{"kind":"file","id":"signed-file","upload":"upload-id"}}]}"""
        val c=WorkspaceController(backgroundScope,store);c.bind(key,WorkspaceApi(),false);runCurrent();val snapshot=c.sendExtras()
        assertEquals("signed-file",snapshot.getJSONArray("references").getJSONObject(0).string("id"))
        c.addReference(JSONObject("""{"kind":"chat","id":"new-ref"}"""));runCurrent();c.clearSent(key,snapshot);runCurrent()
        assertEquals("new-ref",c.sendExtras().getJSONArray("references").getJSONObject(0).string("id"))
    }
    @Test fun approvalTheComputerTurnsAwayLeavesNothingToCheck()=runTest {
        val api=WorkspaceApi();val c=WorkspaceController(backgroundScope,WorkspaceStore());c.bind(key.copy(app="deepseek"),api,false);runCurrent()
        c.action("deepseek/approval",JSONObject().put("event_id","old").put("choice","allowed-once"));runCurrent()
        assertEquals(1,api.answers);assertEquals(0,api.stateReads)
        assertTrue(c.state.value.error!!.contains("失效"));assertNull(JSONObject(c.state.value.saved).optJSONObject("pending_action"))
    }
    /** 电脑上打开 reads the state again at once, so the chips and the send button follow (10-27, web openOnPC). */
    @Test fun openOnComputerReadsTheStateAgain()=runTest {
        var fails=false
        val routes=mutableListOf<String>()
        val api=object:ReadApi by FixtureApi() {
            override suspend fun detail(device:String,route:String,query:Map<String,String?>,body:JSONObject?):JSONObject {
                routes+=route
                if(fails) throw ServiceFailure(409,"device_offline")
                return JSONObject().put("ok",true).put("text","已在电脑上打开「会话」")
            }
        }
        var changes=0
        val c=WorkspaceController(backgroundScope,WorkspaceStore());c.changed={ changes++ };c.bind(key,api,false);runCurrent()
        c.openOnComputer();runCurrent()
        assertEquals(listOf("chat/open"),routes);assertEquals(1,changes)
        assertEquals("已在电脑上打开「会话」",c.state.value.result);assertFalse(c.state.value.busy)
        // Not opened: why, and nothing read again.
        fails=true;c.openOnComputer();runCurrent()
        assertEquals(1,changes);assertEquals("电脑已离线，请稍后刷新电脑列表。",c.state.value.error);assertFalse(c.state.value.busy)
    }
    /** 10-27 (as on the iPhone): a file an answer links to opens the page of the file the computer lists by that path. */
    @Test fun aFileLinkInAnAnswerOpensThePageOfTheListedFileOnly()=runTest {
        val api=object:ReadApi by FixtureApi() {
            override suspend fun detail(device:String,route:String,query:Map<String,String?>,body:JSONObject?):JSONObject {
                if(route=="chat/files") return JSONObject().put("items",org.json.JSONArray(FixtureWorld.FILES)
                    .put(JSONObject().put("id","dot").put("name","x.md").put("path","D:\\a\\.claude\\x.md").put("kind","text").put("state","current"))
                    .put(JSONObject().put("id","gone").put("name","old.md").put("path","D:\\a\\old.md").put("kind","text").put("state","missing")))
                if(route=="file/text") return JSONObject().put("text","# 说明")
                return JSONObject().put("kind","text").put("size",12)
            }
        }
        val c=WorkspaceController(backgroundScope,WorkspaceStore());c.bind(key,api,false);runCurrent()
        c.openLinkedFile("d:/FIXTURE/说明.md");runCurrent()
        assertEquals("file",c.state.value.pane);assertEquals("fixture-md",JSONObject(c.state.value.data).string("id"))
        // Its page goes back to the conversation (linked); the file's text stays with the page, out of the status line.
        assertTrue(JSONObject(c.state.value.data).optBoolean("linked"));assertEquals("# 说明",c.state.value.result)
        c.close();assertEquals("",c.state.value.result)
        c.file(JSONObject().put("id","fixture-md").put("name","说明.md"));runCurrent()
        assertEquals("# 说明",c.state.value.result)
        c.panel("files");assertEquals("",c.state.value.result)
        c.close()
        // The reader dropped the backslash before ".claude": still that file.
        c.openLinkedFile("D:\\a.claude\\x.md");runCurrent()
        assertEquals("dot",JSONObject(c.state.value.data).string("id"))
        c.close()
        c.openLinkedFile("D:\\fixture\\secret.txt");runCurrent()
        assertNull(c.state.value.pane);assertTrue(c.state.value.error!!.contains("不在电脑列出的对话文件里"))
        c.openLinkedFile("D:\\a\\old.md");runCurrent()
        assertNull(c.state.value.pane);assertEquals("文件已移动或删除",c.state.value.error)
    }
    /** A picture's preview (10-27) goes with its row: removed, or sent with the message. */
    @Test fun aPicturePreviewGoesWithItsRow()=runTest {
        val folder=java.io.File(java.nio.file.Files.createTempDirectory("tp").toFile(),PhotoFolder).apply { mkdirs() }
        val removed=java.io.File(folder,"a.jpg").apply { writeText("a") };val sent=java.io.File(folder,"b.jpg").apply { writeText("b") }
        val stranger=java.io.File(folder.parentFile,"c.jpg").apply { writeText("c") }
        val store=WorkspaceStore()
        store.values[key to "workspace"]=JSONObject().put("uploads",org.json.JSONArray()
            .put(JSONObject().put("local","l1").put("name","a.jpg").put("image",true).put("status","ready").put("preview",removed.path).put("meta",JSONObject().put("id","m1")))
            .put(JSONObject().put("local","l2").put("name","b.jpg").put("image",true).put("status","ready").put("preview",sent.path).put("meta",JSONObject().put("id","m2")))
            .put(JSONObject().put("local","l3").put("name","c.jpg").put("image",true).put("status","ready").put("preview",stranger.path).put("meta",JSONObject().put("id","m3")))).toString()
        val c=WorkspaceController(backgroundScope,store);c.bind(key,FixtureApi(),false);runCurrent()
        c.removeUpload("l1");runCurrent()
        assertFalse(removed.exists());assertTrue(sent.exists())
        c.clearSent(key,JSONObject().put("attachments",org.json.JSONArray().put("m2").put("m3")));runCurrent()
        assertFalse(sent.exists())
        // Only a file in the previews' folder is ever deleted.
        assertTrue(stranger.exists())
        assertTrue(JSONObject(c.state.value.saved).rows("uploads") { it }.isEmpty())
    }
    /**
     * A picture sent with a message (10-27, as on the iPhone): its small copy and the whole one are fetched from the
     * computer once and kept by its id; one gone from the computer leaves no file, and only the whole one says why.
     */
    @Test fun aSentPictureIsFetchedOnceAndKeptByItsId()=runTest {
        val caches=java.nio.file.Files.createTempDirectory("tc").toFile()
        val api=FixtureApi();val c=WorkspaceController(backgroundScope,WorkspaceStore());c.bind(key,api,false);runCurrent()
        val picture=SentPicture("fixture-picture-1","截图.png")
        val small=c.sentPicture(caches,picture,false)!!;val whole=c.sentPicture(caches,picture,true)!!
        assertEquals(java.io.File(caches,"$SentPictureFolder/fixture-picture-1/small.png").path,small)
        assertEquals(java.io.File(caches,"$SentPictureFolder/fixture-picture-1/whole.png").path,whole)
        assertTrue(java.io.File(whole).length()>0);assertEquals(2,api.world.pictureReads)
        assertEquals(small,c.sentPicture(caches,picture,false));assertEquals(whole,c.sentPicture(caches,picture,true))
        assertEquals(2,api.world.pictureReads);assertNull(c.state.value.error)
        val gone=object:ReadApi by FixtureApi() {
            override suspend fun sentPicture(device:String,id:String,small:Boolean,output:java.io.OutputStream) { output.write(1);throw ServiceFailure(404) }
        }
        c.bind(key.copy(chat="other"),gone,false);runCurrent()
        assertNull(c.sentPicture(caches,SentPicture("gone","x.png"),false));assertNull(c.state.value.error)
        assertNull(c.sentPicture(caches,SentPicture("gone","x.png"),true));assertEquals("电脑上已经没有这张图片了",c.state.value.error)
        assertTrue(java.io.File(caches,"$SentPictureFolder/gone").listFiles().orEmpty().isEmpty())
    }
    /** 0.8 (web savedCatalog): the menu shows the kept list at once and asks without fresh; 刷新 asks with it. */
    @Test fun claudeListShowsKeptCopyAndReadsTheDesktopOnlyOnRefresh()=runTest {
        val store=WorkspaceStore();val api=WorkspaceApi();val claude=key.copy(app="claude")
        val c=WorkspaceController(backgroundScope,store);c.bind(claude,api,false);runCurrent()
        c.loadChoices(model="opus");runCurrent()
        assertEquals(1,api.catalogs);assertEquals(0,api.freshCatalogs)
        // Kept on the phone: a later binding shows it before the computer answers.
        val other=WorkspaceController(backgroundScope,store);other.bind(claude,api,false);runCurrent()
        other.loadChoices(model="opus")
        assertNotNull(JSONObject(other.state.value.choices).optJSONObject("source_catalog"))
        runCurrent();other.loadChoices(fresh=true,model="opus");runCurrent()
        assertEquals(3,api.catalogs);assertEquals(1,api.freshCatalogs)
        // A conversation never opened borrows the list of another on the same model.
        val third=WorkspaceController(backgroundScope,store);third.bind(claude.copy(chat="third"),api,false);runCurrent()
        third.loadChoices(model="opus")
        assertTrue(JSONObject(third.state.value.choices).getJSONObject("source_catalog").optBoolean("borrowed"))
    }
    @Test fun createObeysCatalogProjectlessAndPermissionCapabilities()=runTest {
        val strict=FixtureWorld.TESTING_AGENT.copy(
            id="strict_bot",
            name=AgentName("严格助手","Strict Bot"),
            caps=FixtureWorld.TESTING_AGENT.caps.copy(newProjectless=false,newPermission=true),
        )
        val flexible=FixtureWorld.TESTING_AGENT.copy(
            id="flex_bot",
            name=AgentName("自由助手","Flex Bot"),
            caps=FixtureWorld.TESTING_AGENT.caps.copy(newProjectless=true,newPermission=false),
        )
        val snapshot=AgentCatalogSnapshot.fromServer(AgentCatalogSnapshot.BuiltinAgents+strict+flexible)
        val made=mutableListOf<NewJob>()
        val api=WorkspaceApi()
        val c=WorkspaceController(backgroundScope,WorkspaceStore()).apply { catalog={ snapshot };created={ made+=it } }
        // strict_bot requires a workspace folder when newProjectless=false.
        c.bind(key.copy(app="strict_bot",chat="@new"),api,false);runCurrent()
        c.edit("first_message","hello");runCurrent()
        c.create();runCurrent()
        assertTrue(made.isEmpty())
        assertTrue(c.state.value.error!!.contains("要选一个工作区"))
        c.edit("folder","D:/ws");c.edit("new_permission","workspace");runCurrent()
        c.create();runCurrent()
        assertEquals(1,made.size)
        val strictBody=JSONObject(made.last().body)
        assertEquals("strict_bot",strictBody.string("app"))
        assertEquals("workspace",strictBody.string("permission"))
        assertFalse(strictBody.optBoolean("projectless"))
        // flex_bot allows projectless creation and omits permission when newPermission=false.
        c.bind(key.copy(app="flex_bot",chat="@new"),api,false);runCurrent()
        c.edit("first_message","hello flex");c.edit("new_permission","full");runCurrent()
        c.create();runCurrent()
        assertEquals(2,made.size)
        val flexBody=JSONObject(made.last().body)
        assertEquals("flex_bot",flexBody.string("app"))
        assertTrue(flexBody.optBoolean("projectless"))
        assertFalse(flexBody.has("permission"))
    }
    @Test fun unknownOrGenericAgentDoesNotQueryClaudeOrDeepSeekChoices()=runTest {
        val routes=mutableListOf<String>()
        val api=object:ReadApi by FixtureApi() {
            override suspend fun detail(device:String,route:String,query:Map<String,String?>,body:JSONObject?):JSONObject {
                routes+=route;return JSONObject()
            }
        }
        val snapshot=AgentCatalogSnapshot.fromServer(AgentCatalogSnapshot.BuiltinAgents+FixtureWorld.TESTING_AGENT)
        val c=WorkspaceController(backgroundScope,WorkspaceStore()).apply { catalog={ snapshot } }
        for(app in listOf("testing","mystery_bot")) {
            c.bind(key.copy(app=app),api,false);runCurrent()
            c.loadChoices(fresh=true,model="m1");runCurrent()
        }
        assertTrue(routes.isEmpty())
    }
}
