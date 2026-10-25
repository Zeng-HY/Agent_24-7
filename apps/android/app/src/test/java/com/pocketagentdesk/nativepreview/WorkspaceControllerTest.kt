package com.pocketagentdesk.nativepreview

import kotlinx.coroutines.*
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
@OptIn(ExperimentalCoroutinesApi::class)
class WorkspaceControllerTest {
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
}
