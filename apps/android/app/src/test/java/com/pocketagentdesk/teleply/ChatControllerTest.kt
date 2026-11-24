package com.pocketagentdesk.teleply

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.test.*
import org.json.JSONObject
import org.junit.Test
import org.junit.Assert.*

private class DraftStore:ReaderStore by TestStore() {
    val drafts=mutableMapOf<ChatKey,String>()
    val records=mutableMapOf<String,Submission>()
    override suspend fun draft(key:ChatKey)=drafts[key].orEmpty()
    override suspend fun draft(key:ChatKey,text:String) { drafts[key]=text }
    override suspend fun submissions(key:ChatKey)=records.values.filter { it.scope==key.scope && it.device==key.device && it.chat==key.chat }
    override suspend fun submission(value:Submission) { records[value.request]=value }
    override suspend fun begin(value:Submission) { submission(value);draft(ChatKey(value.scope,value.device,value.chat),"") }
}
private class CommandApi:TestApi() {
    var sends=0;var receipts=0;var unknown=false
    val gate=CompletableDeferred<Unit>()
    override suspend fun control(device:String,chat:String,fresh:Boolean)=Control(available=true,running=true,turn="turn",queueAvailable=true)
    override suspend fun command(device:String,route:String,body:JSONObject):JSONObject {
        sends++;gate.await()
        if(unknown) throw java.io.IOException("timeout")
        return JSONObject().put("request_id",body.string("request_id")).put("delivery_state","accepted")
    }
    override suspend fun receipt(device:String,chat:String,request:String):JSONObject { receipts++;return JSONObject().put("state","unknown") }
}
@OptIn(ExperimentalCoroutinesApi::class)
class ChatControllerTest {
    @Test fun disconnectReconnectAndBackgroundCancelSubscription()=runTest {
        var connections=0;var cancellations=0
        val api=object:TestApi() {
            override suspend fun control(device:String,chat:String,fresh:Boolean)=Control(available=true)
            override fun events(device:String,chat:String)=flow {
                connections++
                if(connections==1) throw java.io.IOException("disconnect")
                try { emit(LiveFrame(1,true,listOf(Message("m","assistant",chat)),null));awaitCancellation() }
                finally { cancellations++ }
            }
        }
        val frames=mutableListOf<LiveFrame>();val c=ChatController(backgroundScope,DraftStore())
        c.bind(key,api,true,false) { frames+=it };runCurrent();assertEquals(1,connections)
        advanceTimeBy(1000);runCurrent();assertEquals(2,connections);assertEquals(1,frames.size)
        c.bind(key,api,false,false) { frames+=it };runCurrent();assertEquals(1,cancellations)
        c.bind(key.copy(device="b".repeat(32),chat="other"),api,true,false) { frames+=it };runCurrent()
        assertEquals("other",frames.last().messages.single().text)
        assertEquals("other",c.state.value.key!!.chat)
    }
    private val key=ChatKey("account","a".repeat(32),"chat")
    /** 0.8 (web claude-ui.js): a fresh read on entering, then polls every 5 s that may use the computer's last read. */
    @Test fun claudePollsEveryFiveSecondsWithoutFreshReadsAndNotDuringATap()=runTest {
        val reads=mutableListOf<Boolean>()
        val api=object:TestApi() {
            override suspend fun control(device:String,chat:String,fresh:Boolean):Control { reads+=fresh;return Control(available=true) }
            override fun events(device:String,chat:String)=flow<LiveFrame> { awaitCancellation() }
        }
        val c=ChatController(backgroundScope,DraftStore())
        c.bind(key.copy(app="claude"),api,true,false) {};runCurrent()
        assertEquals(listOf(true),reads)
        advanceTimeBy(10_001);runCurrent()
        assertEquals(listOf(true,false,false),reads)
        c.pollPaused={ true };advanceTimeBy(10_000);runCurrent()
        assertEquals(3,reads.size)
    }
    /**
     * 10-27 (the iPhone redrew a long DeepSeek conversation on every poll): a poll that finds nothing new leaves the page
     * as it was; every read is told on, for a Claude press that can no longer land.
     */
    @Test fun pollsWithNothingNewChangeNothingAndEachReadIsTold()=runTest {
        var state="""{"available":true,"running":false}"""
        val api=object:TestApi() {
            override suspend fun control(device:String,chat:String,fresh:Boolean)=parseControl(JSONObject(state))
            override fun events(device:String,chat:String)=flow<LiveFrame> { awaitCancellation() }
        }
        val reads=mutableListOf<ChatKey>();val c=ChatController(backgroundScope,DraftStore());c.seen={ reads+=it }
        c.bind(key.copy(app="deepseek"),api,true,false) {};runCurrent()
        val emitted=mutableListOf<ComposerState>();backgroundScope.launch { c.state.collect { emitted+=it } };runCurrent()
        val before=emitted.size
        advanceTimeBy(7_501);runCurrent()
        assertEquals(before,emitted.size);assertEquals(4,reads.size)
        state="""{"available":true,"running":true}""";advanceTimeBy(2_500);runCurrent()
        assertEquals(before+1,emitted.size);assertTrue(c.state.value.control.running);assertEquals(5,reads.size)
    }
    @Test fun deepseekPollsEveryTwoAndAHalfSeconds()=runTest {
        val reads=mutableListOf<Boolean>()
        val api=object:TestApi() {
            override suspend fun control(device:String,chat:String,fresh:Boolean):Control { reads+=fresh;return Control(available=true) }
            override fun events(device:String,chat:String)=flow<LiveFrame> { awaitCancellation() }
        }
        val c=ChatController(backgroundScope,DraftStore())
        c.bind(key.copy(app="deepseek"),api,true,false) {};runCurrent()
        advanceTimeBy(5_001);runCurrent()
        assertEquals(listOf(true,false,false),reads)
    }
    @Test fun doubleClickAndLateReceiptNeverClearNewDraft()=runTest {
        val store=DraftStore();val api=CommandApi();val c=ChatController(backgroundScope,store)
        c.bind(key,api,true,false) {};runCurrent();c.edit("first");runCurrent();c.send();c.send();runCurrent()
        assertEquals(1,api.sends);assertEquals("first",store.records.values.single().text)
        c.edit("new draft");runCurrent();api.gate.complete(Unit);runCurrent()
        assertEquals("new draft",c.state.value.draft);assertEquals("new draft",store.drafts[key]);assertEquals("已接收",c.state.value.submissions.single().label)
    }
    @Test fun timeoutRestartOnlyQueriesOriginalAndRetainsSnapshot()=runTest {
        val store=DraftStore();val api=CommandApi();api.unknown=true;api.gate.complete(Unit)
        val c=ChatController(backgroundScope,store);c.bind(key,api,true,false) {};runCurrent();c.edit("snapshot");runCurrent();c.send();runCurrent()
        assertEquals("送达状态待确认",c.state.value.submissions.single().label)
        val recovered=ChatController(backgroundScope,store);recovered.bind(key,api,true,false) {};runCurrent()
        assertEquals(1,api.sends);assertTrue(api.receipts>0);assertEquals("snapshot",recovered.state.value.submissions.single().text)
    }
    @Test fun identitySwitchRejectsLateReceiptAndDraftLeaks()=runTest {
        val store=DraftStore();val api=CommandApi();val c=ChatController(backgroundScope,store)
        c.bind(key,api,true,false) {};runCurrent();c.edit("private");runCurrent();c.send();runCurrent()
        c.bind(key.copy(scope="another"),api,true,false) {};runCurrent();api.gate.complete(Unit);runCurrent()
        assertEquals("",c.state.value.draft);assertTrue(c.state.value.submissions.isEmpty());assertEquals("account",store.records.values.single().scope)
    }
    /** 10-27 (web sendConv): Claude's message goes while the computer shows another conversation; Codex's waits. */
    @Test fun claudeSendsWhileTheComputerShowsAnotherConversationAndCodexWaits()=runTest {
        for(app in listOf("claude","codex")) {
            var sends=0
            val api=object:TestApi() {
                override suspend fun control(device:String,chat:String,fresh:Boolean)=parseControl(JSONObject("""{"available":false,"running":true,"active_turn_id":"turn","reason":"电脑上没有打开这个对话","settings":{"model":"opus"}}"""))
                override fun events(device:String,chat:String)=flow<LiveFrame> { awaitCancellation() }
                override suspend fun command(device:String,route:String,body:JSONObject):JSONObject { sends++;return JSONObject().put("request_id",body.string("request_id")).put("delivery_state","accepted") }
            }
            val c=ChatController(backgroundScope,DraftStore())
            c.bind(key.copy(app=app),api,true,false) {};runCurrent()
            assertFalse(c.state.value.control.available)
            c.edit("照样发出去");runCurrent();c.send();runCurrent()
            assertEquals(app,if(app=="claude") 1 else 0,sends)
            assertEquals(app,if(app=="claude") "" else "照样发出去",c.state.value.draft)
            // Stopping still needs the conversation in front on the computer.
            c.stop();runCurrent()
            assertEquals(app,if(app=="claude") 1 else 0,sends)
        }
    }
    @Test fun backgroundDisablesCommandsAndRestoresDraft()=runTest {
        val store=DraftStore();val api=CommandApi();val c=ChatController(backgroundScope,store)
        c.bind(key,api,true,false) {};runCurrent();c.edit("中文草稿");runCurrent();c.bind(key,api,false,false) {};runCurrent();c.send();runCurrent()
        assertEquals(0,api.sends)
        val recovered=ChatController(backgroundScope,store);recovered.bind(key,api,true,false) {};runCurrent();assertEquals("中文草稿",recovered.state.value.draft)
    }
    /**
     * 第二批 A2：有 capabilities_now 时计划模式看此刻 settings 里有没有 mode；老电脑（没有这个字段）保持 Codex 布局的旧规则。
     */
    @Test fun planModeFollowsCapabilitiesNow()=runTest {
        // 这一版电脑的说明书里有 mode（第一批把 mode 写进了 Codex 的 settings）。
        val codex=parseAgentInfo(JSONObject("""{"id":"codex","name":{"zh":"Codex","en":"Codex"},"legacy":true,"capabilities":{"list":true,"read":true,"stop":true,"approve":true,"answer":true,"settings":["model","effort","mode"],"send_modes":["send","steer","queue"]},"ui":{"card_layout":"codex.v1"}}"""))!!
        val catalog=AgentCatalogSnapshot.fromServer(listOf(codex))
        for((state,expected) in listOf(
            """{"available":true,"running":false,"settings":{"model":"x"},"capabilities_now":{"settings":["model","effort"]}}""" to 0,
            """{"available":true,"running":false,"settings":{"model":"x"},"capabilities_now":{"settings":["model","mode"]}}""" to 1,
            """{"available":true,"running":false,"settings":{"model":"x"}}""" to 1,
        )) {
            var sends=0
            val api=object:TestApi() {
                override suspend fun control(device:String,chat:String,fresh:Boolean)=parseControl(JSONObject(state))
                override fun events(device:String,chat:String)=flow<LiveFrame> { awaitCancellation() }
                override suspend fun command(device:String,route:String,body:JSONObject):JSONObject { sends++;return JSONObject().put("request_id",body.string("request_id")) }
            }
            val c=ChatController(backgroundScope,DraftStore());c.catalog={ catalog }
            c.bind(key,api,true,false) {};runCurrent()
            c.executePlan("plan-1");runCurrent()
            assertEquals(state,expected,sends)
        }
    }
    /** 第二批 A1：此刻能力说不能发时（send_modes 为空），发送不发出去，草稿留着。 */
    @Test fun sendingStopsWhenCapabilitiesNowTakesEverySendModeAway()=runTest {
        var sends=0
        val api=object:TestApi() {
            override suspend fun control(device:String,chat:String,fresh:Boolean)=parseControl(JSONObject(
                """{"available":true,"running":false,"capabilities_now":{"send_modes":[]},"capability_notes":{"send":"这台电脑的 Codex 没在运行"}}"""))
            override fun events(device:String,chat:String)=flow<LiveFrame> { awaitCancellation() }
            override suspend fun command(device:String,route:String,body:JSONObject):JSONObject { sends++;return JSONObject() }
        }
        val c=ChatController(backgroundScope,DraftStore());c.catalog={ AgentCatalogSnapshot.Builtin }
        c.bind(key,api,true,false) {};runCurrent()
        c.edit("发不出去");runCurrent();c.send();runCurrent()
        assertEquals(0,sends);assertEquals("发不出去",c.state.value.draft)
        assertEquals("这台电脑的 Codex 没在运行",capsNote(JSONObject(c.state.value.control.raw),"send"))
    }
}
