package com.pocketagentdesk.teleply

import kotlinx.coroutines.*
import kotlinx.coroutines.test.*
import org.junit.*
import org.junit.Assert.*

class TestStore(var prefs:Preferences=Preferences()):ReaderStore {
    val positions=mutableMapOf<Triple<String,String,String>,ReadingPosition>()
    override suspend fun preferences()=prefs
    override suspend fun setOrigin(origin:String) { prefs=Preferences(origin=origin) }
    override suspend fun appearance(theme:String,dynamic:Boolean) { prefs=prefs.copy(theme=theme,dynamic=dynamic) }
    override suspend fun selection(scope:String,device:String,chat:String,title:String) { prefs=prefs.copy(scope=scope,device=device,chat=chat,title=title) }
    override suspend fun position(scope:String,device:String,chat:String)=positions[Triple(scope,device,chat)]
    override suspend fun save(position:ReadingPosition) { positions[Triple(position.scope,position.device,position.chat)]=position }
}
open class TestApi:ReadApi {
    val a=Computer("a".repeat(32),"A",true);val b=Computer("b".repeat(32),"B",true)
    var ownerDevices=listOf(a,b);var expired=false;var reset=false;var delayA=false
    override suspend fun config()="test"
    override suspend fun login(name:String,password:String) { expired=false }
    override suspend fun account():Account { if(expired) throw ServiceFailure(401); return Account(ownerDevices,"") }
    override suspend fun select(device:String)=Unit
    override suspend fun chats(device:String,query:String,cursor:String?):Page<Chat> {
        if(delayA && device==a.id) withContext(NonCancellable) { delay(1000) }
        if(expired) throw ServiceFailure(401)
        return Page(listOf(Chat("chat-$device",if(query.isEmpty()) device else query)),if(cursor==null) "more" else null,cursor==null)
    }
    override suspend fun history(device:String,chat:String,before:String?,around:String?,count:Int):Page<Message> {
        if(expired) throw ServiceFailure(401)
        return if(before==null) Page(listOf(Message("m2","assistant","same"),Message("m3","assistant","same")),"m2",true) else Page(listOf(Message("m1","user","older"),Message("m2","assistant","updated")),reset=reset)
    }
    override suspend fun message(device:String,chat:String,message:String)=Message(message,"assistant","full")
    override suspend fun search(device:String,chat:String,query:String,cursor:String?)=Page<Message>(emptyList())
    override fun close()=Unit
}
@OptIn(ExperimentalCoroutinesApi::class)
class ReaderViewModelTest {
    @Test fun notificationRechecksDeviceAndResumesAfterSameOwnerLogin()=runTest(dispatcher) {
        val api=TestApi();val vm=ready(api)
        val key=ChatKey(vm.state.value.scope,api.b.id,"notification-chat")
        api.expired=true;vm.openNotification(WatchTarget(vm.state.value.origin,key,"local-token"));advanceUntilIdle()
        assertEquals(Screen.Login,vm.state.value.screen)
        vm.login("same","test");advanceUntilIdle()
        assertEquals(api.b.id,vm.state.value.device!!.id);assertEquals("notification-chat",vm.state.value.chat!!.id)
    }
    @Test fun notificationCannotSwitchServiceOrAccountScope()=runTest(dispatcher) {
        val vm=ready();val origin=vm.state.value.origin
        vm.openNotification(WatchTarget("https://different.invalid/",ChatKey("other","b".repeat(32),"foreign"),"untrusted"));advanceUntilIdle()
        assertEquals(origin,vm.state.value.origin);assertNull(vm.state.value.chat);assertNotNull(vm.state.value.error)
    }
    private val dispatcher=StandardTestDispatcher()
    @Before fun setup() { Dispatchers.setMain(dispatcher) }
    @After fun cleanup() { Dispatchers.resetMain() }
    private suspend fun TestScope.ready(api:TestApi=TestApi(),store:TestStore=TestStore()):ReaderViewModel {
        val vm=ReaderViewModel(store) { api };advanceUntilIdle();vm.connect("https://example.invalid");advanceUntilIdle();vm.login("fixture","test");advanceUntilIdle();vm.select(api.a);advanceUntilIdle();return vm
    }
    @Test fun paginationUsesIdsAndKeepsEqualTextMessages()=runTest(dispatcher) {
        val vm=ready();vm.open(vm.state.value.chats.first());advanceUntilIdle();vm.older();advanceUntilIdle()
        assertEquals(listOf("m1","m2","m3"),vm.state.value.messages.map { it.id });assertEquals("updated",vm.state.value.messages[1].text)
    }
    @Test fun longMessageCopiesWholeAndStaysWholeOnceOpened()=runTest(dispatcher) {
        // The computer cuts a message over 6000 characters (the user's prompt of 7545, 10-27).
        val api=object:TestApi() {
            override suspend fun history(device:String,chat:String,before:String?,around:String?,count:Int)=Page(listOf(Message("long","user","前半",truncated=true,length=4)))
            override suspend fun message(device:String,chat:String,message:String)=Message(message,"user","前半后半",length=4)
        }
        val vm=ready(api);vm.open(vm.state.value.chats.first());advanceUntilIdle()
        val cut=vm.state.value.messages.single();assertTrue(cut.truncated)
        var copied:String?=null;vm.whole(cut) { copied=it.text };advanceUntilIdle()
        assertEquals("前半后半",copied);assertTrue(vm.state.value.messages.single().truncated)
        vm.expand(cut);advanceUntilIdle();assertEquals("前半后半",vm.state.value.messages.single().text)
        vm.latest();advanceUntilIdle()
        val again=vm.state.value.messages.single();assertEquals("前半后半",again.text);assertFalse(again.truncated)
    }
    @Test fun expiredLoginPreservesReadingAndSameOwnerRestores()=runTest(dispatcher) {
        val api=TestApi();val vm=ready(api);vm.open(vm.state.value.chats.first());advanceUntilIdle();vm.saveAnchor("m2",42);advanceUntilIdle()
        api.expired=true;vm.older();advanceUntilIdle()
        assertEquals(Screen.Login,vm.state.value.screen);assertEquals(42,vm.state.value.anchor?.offset);assertEquals(2,vm.state.value.messages.size)
        vm.login("same","test");advanceUntilIdle();assertEquals(Screen.Reading,vm.state.value.screen);assertEquals(42,vm.state.value.anchor?.offset)
    }
    @Test fun differentOwnerCannotReadPreviousSnapshot()=runTest(dispatcher) {
        val api=TestApi();val vm=ready(api);vm.open(vm.state.value.chats.first());advanceUntilIdle();val scope=vm.state.value.scope
        api.expired=true;vm.older();advanceUntilIdle();api.ownerDevices=listOf(api.b);vm.login("another","test");advanceUntilIdle()
        assertTrue(vm.state.value.messages.isEmpty());assertNull(vm.state.value.device);assertNotEquals(scope,vm.state.value.scope);assertEquals(Screen.Devices,vm.state.value.screen)
    }
    @Test fun lateOldComputerResultCannotContaminateNewComputer()=runTest(dispatcher) {
        val api=TestApi();val vm=ready(api);api.delayA=true;vm.searchChats("late");runCurrent();vm.select(api.b);advanceUntilIdle()
        assertEquals(api.b,vm.state.value.device);assertEquals(api.b.id,vm.state.value.chats.single().title);assertFalse(vm.state.value.busy)
    }
    @Test fun resetPaginationDoesNotMergeInvalidPage()=runTest(dispatcher) {
        val api=TestApi();val vm=ready(api);vm.open(vm.state.value.chats.first());advanceUntilIdle();api.reset=true;vm.older();advanceUntilIdle()
        assertEquals(2,vm.state.value.messages.size);assertTrue(vm.state.value.error!!.contains("历史位置已变化"))
    }
    @Test fun returnGoesToListAndDoesNotIssueCommands()=runTest(dispatcher) {
        val vm=ready();vm.open(vm.state.value.chats.first());advanceUntilIdle();vm.back();advanceUntilIdle();assertEquals(Screen.Chats,vm.state.value.screen);assertNull(vm.state.value.chat)
    }
    @Test fun anchorScopedToAccountComputerAppAndChat()=runTest(dispatcher) {
        val store=TestStore();val vm=ready(store=store);vm.open(vm.state.value.chats.first());advanceUntilIdle();vm.saveAnchor("m2",17);advanceUntilIdle()
        val pos=store.positions.values.single();assertEquals(vm.state.value.scope,pos.scope);assertEquals("codex",pos.app);assertEquals(vm.state.value.device!!.id,pos.device)
    }
    @Test fun emptySearchIsAnEmptyResultNotAnError()=runTest(dispatcher) {
        val vm=ready();vm.open(vm.state.value.chats.first());advanceUntilIdle();vm.searchHistory("missing");advanceUntilIdle();assertTrue(vm.state.value.searched);assertTrue(vm.state.value.hits.isEmpty());assertNull(vm.state.value.error)
    }
    @Test fun processRestartRestoresOnlyVerifiedComputerAndStoredAnchor()=runTest(dispatcher) {
        val api=TestApi();val store=TestStore(Preferences(origin="https://example.invalid/",scope="stored",device=api.a.id,chat="restored"))
        store.save(ReadingPosition("stored",api.a.id,chat="restored",message="m2",offset=81))
        val vm=ReaderViewModel(store) { api };advanceUntilIdle()
        assertEquals(Screen.Reading,vm.state.value.screen);assertEquals(81,vm.state.value.anchor?.offset)
    }
    @Test fun expiredSessionAfterProcessRestartCanResumeVerifiedReading()=runTest(dispatcher) {
        val api=TestApi();api.expired=true
        val store=TestStore(Preferences(origin="https://example.invalid/",scope="stored",device=api.a.id,chat="restored"))
        store.save(ReadingPosition("stored",api.a.id,chat="restored",message="m2",offset=63))
        val vm=ReaderViewModel(store) { api };advanceUntilIdle();assertEquals(Screen.Login,vm.state.value.screen)
        vm.login("fixture","test");advanceUntilIdle()
        assertEquals(Screen.Reading,vm.state.value.screen);assertEquals(63,vm.state.value.anchor?.offset)
    }
    @Test fun serviceThatDoesNotAnswerKeepsTheAddressPageAndTheSavedPlace()=runTest(dispatcher) {
        val api=TestApi();val store=TestStore()
        val down=object:TestApi() { override suspend fun accountConfig():org.json.JSONObject=throw java.io.IOException("no route") }
        val vm=ReaderViewModel(store) { origin -> if("down" in origin) down else api };advanceUntilIdle()
        vm.login("fixture","test");advanceUntilIdle();vm.select(api.a);advanceUntilIdle()
        val saved=store.prefs
        vm.serviceSettings();vm.connect("https://down.invalid");advanceUntilIdle()
        assertEquals(Screen.Service,vm.state.value.screen);assertEquals("连不上这个服务，请检查地址和网络后重试。",vm.state.value.error);assertEquals(saved,store.prefs)
        // The same service again opens as at launch, back on the computer it was on.
        vm.connect(DefaultOrigin);advanceUntilIdle()
        assertEquals(Screen.Chats,vm.state.value.screen);assertEquals(api.a.id,vm.state.value.device?.id);assertEquals(saved.scope,vm.state.value.scope)
    }
    @Test fun leavingTheDemoStartsOverOnTheSavedService()=runTest(dispatcher) {
        val api=TestApi();val store=TestStore();val vm=ReaderViewModel(store) { api };advanceUntilIdle()
        vm.fixture();vm.login("fixture","fixture");advanceUntilIdle()
        vm.select(vm.state.value.account!!.devices.first { it.connectable });advanceUntilIdle()
        vm.logout();advanceUntilIdle()
        assertEquals(Preferences(),store.prefs) // the demo saves nothing
        vm.back();advanceUntilIdle()
        assertFalse(vm.state.value.fixture);assertEquals(DefaultOrigin,vm.state.value.origin);assertEquals(Screen.Devices,vm.state.value.screen)
    }
    /** 打开新建对话 (web): the conversation Codex made is read first, five messages, then opened; one not there leaves the page with why. */
    @Test fun aConversationCodexMadeIsReadThenOpened()=runTest(dispatcher) {
        val reads=mutableListOf<Pair<String,Int>>()
        val api=object:TestApi() {
            override suspend fun history(device:String,chat:String,before:String?,around:String?,count:Int):Page<Message> {
                reads+=chat to count
                if(chat=="gone") throw ServiceFailure(404)
                return super.history(device,chat,before,around,count)
            }
        }
        val vm=ready(api);vm.open(vm.state.value.chats.first());advanceUntilIdle()
        val page=vm.state.value.chat;reads.clear()
        vm.openCreated("gone");advanceUntilIdle()
        assertEquals(page,vm.state.value.chat);assertEquals(Screen.Reading,vm.state.value.screen)
        assertEquals("暂时无法打开这个对话：记录或电脑已不可用，请刷新列表。",vm.state.value.error)
        reads.clear()
        vm.openCreated("made");advanceUntilIdle()
        assertEquals(listOf("made" to 5,"made" to 60),reads)
        assertEquals("made",vm.state.value.chat?.id);assertEquals("codex",vm.state.value.app);assertNull(vm.state.value.error)
        assertEquals(listOf("m2","m3"),vm.state.value.messages.map { it.id })
    }
    @Test fun failedRefreshDoesNotEraseReadMessages()=runTest(dispatcher) {
        val api=TestApi();val vm=ready(api);vm.open(vm.state.value.chats.first());advanceUntilIdle()
        val before=vm.state.value.messages;api.expired=true;vm.latest();advanceUntilIdle()
        assertEquals(before,vm.state.value.messages)
    }

    @Test fun demoDoesNotOverwriteRealSessionRecovery()=runTest(dispatcher) {
        val api=TestApi();val store=TestStore();val vm=ready(api,store);val original=store.prefs
        vm.fixture();vm.login("fixture","fixture");advanceUntilIdle()
        vm.select(vm.state.value.account!!.devices.first());advanceUntilIdle()
        vm.open(vm.state.value.chats.first());advanceUntilIdle();vm.saveAnchor("m2",22);advanceUntilIdle()
        assertEquals(original,store.prefs);assertTrue(store.positions.isEmpty())
    }

}
