package com.pocketagentdesk.teleply

import kotlinx.coroutines.*
import kotlinx.coroutines.test.*
import org.junit.*
import org.junit.Assert.*

class TestStore(var prefs:Preferences=Preferences()):ReaderStore {
    /** Whether the move off the old default (10-31, moveService) ran. */
    var moved=false
    override suspend fun preferences()=prefs
    override suspend fun setOrigin(origin:String) { prefs=Preferences(origin=origin) }
    override suspend fun appearance(theme:String,dynamic:Boolean) { prefs=prefs.copy(theme=theme,dynamic=dynamic) }
    override suspend fun selection(scope:String,device:String,chat:String,title:String) { prefs=prefs.copy(scope=scope,device=device,chat=chat,title=title) }
    override suspend fun serviceMoved()=moved
    override suspend fun serviceMoved(origin:String?) { if(origin!=null) prefs=prefs.copy(origin=origin);moved=true }
}
open class TestApi:ReadApi {
    val a=Computer("a".repeat(32),"A",true);val b=Computer("b".repeat(32),"B",true)
    var ownerDevices=listOf(a,b);var expired=false;var reset=false;var delayA=false
    /** The pages read, as (conversation, message the page was read around): null around is the latest page. */
    val pages=mutableListOf<Pair<String,String?>>()
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
        if(before==null) pages+=chat to around
        return if(before==null) Page(listOf(Message("m2","assistant","same"),Message("m3","assistant","same")),"m2",true) else Page(listOf(Message("m1","user","older"),Message("m2","assistant","updated")),reset=reset)
    }
    override suspend fun message(device:String,chat:String,message:String)=Message(message,"assistant","full")
    override suspend fun search(device:String,chat:String,query:String,cursor:String?)=Page<Message>(emptyList())
    /** 删除账号: "test" is the password; [refusal], when set, is how the service or the network turns it down instead. */
    var refusal:Exception?=null;var deleted=false
    override suspend fun deleteAccount(password:String) { if(expired) throw ServiceFailure(401);refusal?.let { throw it };if(password!="test") throw ServiceFailure(400,detail="当前密码错误");deleted=true;expired=true }
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
        // Opened at its latest messages, as every conversation (10-27).
        assertEquals("notification-chat" to null,api.pages.last());assertNull(vm.state.value.anchor)
    }
    @Test fun notificationCannotSwitchServiceOrAccountScope()=runTest(dispatcher) {
        val vm=ready();val origin=vm.state.value.origin
        vm.openNotification(WatchTarget("https://different.invalid/",ChatKey("other","b".repeat(32),"foreign"),"untrusted"));advanceUntilIdle()
        assertEquals(origin,vm.state.value.origin);assertNull(vm.state.value.chat);assertNotNull(vm.state.value.error)
    }
    private val dispatcher=StandardTestDispatcher()
    @Before fun setup() { Dispatchers.setMain(dispatcher) }
    @After fun cleanup() { Dispatchers.resetMain() }
    private suspend fun TestScope.ready(api:TestApi=TestApi(),store:TestStore=TestStore(),accountDeleted:()->Unit={}):ReaderViewModel {
        val vm=ReaderViewModel(store,accountDeleted=accountDeleted) { api };advanceUntilIdle();vm.connect("https://example.invalid");advanceUntilIdle();vm.login("fixture","test");advanceUntilIdle();vm.select(api.a);advanceUntilIdle();return vm
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
        val api=TestApi();val vm=ready(api);vm.open(vm.state.value.chats.first());advanceUntilIdle()
        // The page taken down for 登录 kept where it stood, in memory, for this same read.
        val key=ChatKey(vm.state.value.scope,api.a.id,vm.state.value.chat!!.id);val read=vm.state.value.scrollRevision
        vm.keepPlace(ReadingPlace(key,read,2,"m3",42))
        api.expired=true;vm.older();advanceUntilIdle()
        assertEquals(Screen.Login,vm.state.value.screen);assertEquals(2,vm.state.value.messages.size)
        api.pages.clear();vm.login("same","test");advanceUntilIdle();assertEquals(Screen.Reading,vm.state.value.screen)
        // Back on the same read: nothing read again, so the page goes back where it stood.
        assertTrue(api.pages.isEmpty());assertEquals(read,vm.state.value.scrollRevision);assertEquals(42,vm.placeFor(key,read)?.offset)
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
    /** 10-27 ("保持每次点开对话都在最新的地方"): every opening reads the latest page; a place is kept for the same read only. */
    @Test fun everyOpeningReadsTheLatestPageAndKeepsNoPlaceAcrossOpenings()=runTest(dispatcher) {
        val api=TestApi();val vm=ready(api);val chat=vm.state.value.chats.first()
        vm.open(chat);advanceUntilIdle()
        val key=ChatKey(vm.state.value.scope,api.a.id,chat.id);val first=vm.state.value.scrollRevision
        vm.keepPlace(ReadingPlace(key,first,2,"m3",40))
        assertEquals(40,vm.placeFor(key,first)?.offset);assertNull(vm.placeFor(key.copy(chat="other"),first))
        vm.back();advanceUntilIdle();vm.open(chat);advanceUntilIdle()
        assertTrue(vm.state.value.scrollRevision>first);assertNull(vm.state.value.anchor)
        assertNull(vm.placeFor(key,vm.state.value.scrollRevision))
        vm.latest();advanceUntilIdle()
        assertEquals(3,api.pages.size);assertTrue(api.pages.all { it==chat.id to null })
    }
    /** A search hit is still read around the message found and shown there (web jump). */
    @Test fun aSearchHitIsStillShownWhereItIs()=runTest(dispatcher) {
        val api=TestApi();val vm=ready(api);vm.open(vm.state.value.chats.first());advanceUntilIdle()
        val read=vm.state.value.scrollRevision
        vm.jump(Message("m2","assistant","same"));advanceUntilIdle()
        assertEquals("chat-${api.a.id}" to "m2",api.pages.last());assertEquals("m2",vm.state.value.anchor?.message);assertEquals(read+1,vm.state.value.scrollRevision)
        vm.latest();advanceUntilIdle()
        assertEquals("chat-${api.a.id}" to null,api.pages.last());assertNull(vm.state.value.anchor)
    }
    @Test fun emptySearchIsAnEmptyResultNotAnError()=runTest(dispatcher) {
        val vm=ready();vm.open(vm.state.value.chats.first());advanceUntilIdle();vm.searchHistory("missing");advanceUntilIdle();assertTrue(vm.state.value.searched);assertTrue(vm.state.value.hits.isEmpty());assertNull(vm.state.value.error)
    }
    @Test fun processRestartOpensOnlyTheVerifiedComputerAndAtTheLatest()=runTest(dispatcher) {
        val api=TestApi();val store=TestStore(Preferences(origin="https://example.invalid/",scope="stored",device=api.a.id,chat="restored"))
        val vm=ReaderViewModel(store) { api };advanceUntilIdle()
        assertEquals(Screen.Reading,vm.state.value.screen);assertEquals("restored",vm.state.value.chat?.id)
        assertNull(vm.state.value.anchor);assertEquals(listOf("restored" to null),api.pages)
    }
    @Test fun expiredSessionAfterProcessRestartCanResumeVerifiedReading()=runTest(dispatcher) {
        val api=TestApi();api.expired=true
        val store=TestStore(Preferences(origin="https://example.invalid/",scope="stored",device=api.a.id,chat="restored"))
        val vm=ReaderViewModel(store) { api };advanceUntilIdle();assertEquals(Screen.Login,vm.state.value.screen)
        vm.login("fixture","test");advanceUntilIdle()
        assertEquals(Screen.Reading,vm.state.value.screen);assertNull(vm.state.value.anchor);assertEquals(listOf("restored" to null),api.pages)
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
        vm.open(vm.state.value.chats.first());advanceUntilIdle()
        assertEquals(original,store.prefs)
    }

    /** 删除账号: turned down, the service's words go to the dialog and nothing changes; done, it ends as 退出登录 does. */
    @Test fun deletingTheAccountSignsOutAsLogoutDoesAndSaysSo()=runTest(dispatcher) {
        var gone=0
        val api=TestApi();val store=TestStore();val vm=ready(api,store) { gone++ };vm.open(vm.state.value.chats.first());advanceUntilIdle()
        val said=mutableListOf<String>()
        vm.deleteAccount("wrong") { said+=it };advanceUntilIdle()
        api.refusal=ServiceFailure(429,"rate_limited","请在 31 秒后重试");vm.deleteAccount("test") { said+=it };advanceUntilIdle()
        api.refusal=java.io.IOException("offline");vm.deleteAccount("test") { said+=it };advanceUntilIdle()
        assertEquals(listOf("当前密码错误","请在 31 秒后重试","连接失败，请检查网络和服务地址后重试。"),said)
        assertFalse(api.deleted);assertEquals(Screen.Reading,vm.state.value.screen);assertNotNull(vm.state.value.account);assertNull(vm.state.value.error)
        assertEquals(0,gone)
        api.refusal=null;vm.deleteAccount("test") { said+=it };advanceUntilIdle()
        assertTrue(api.deleted);assertEquals(3,said.size);assertEquals("账号已删除",vm.state.value.accountNote)
        // The background check goes with the account (accountDeleted); 退出登录 below leaves it.
        assertEquals(1,gone)
        // The same phone after 退出登录: 登录 on the same service, nothing of the account or of where it was.
        val other=TestApi();val otherStore=TestStore();val out=ready(other,otherStore) { gone++ };out.open(out.state.value.chats.first());advanceUntilIdle()
        out.logout();advanceUntilIdle();assertEquals(1,gone)
        assertEquals(out.state.value,vm.state.value.copy(accountNote=null));assertEquals(Screen.Login,vm.state.value.screen);assertNull(vm.state.value.account)
        assertEquals(otherStore.prefs.copy(scope=""),store.prefs.copy(scope=""))
    }
    @Test fun aSignInThatRanOutGoesToLoginInsteadOfDeleting()=runTest(dispatcher) {
        var gone=0;val api=TestApi();val vm=ready(api) { gone++ };val said=mutableListOf<String>()
        api.expired=true;vm.deleteAccount("test") { said+=it };advanceUntilIdle()
        assertTrue(said.isEmpty());assertFalse(api.deleted);assertEquals(0,gone)
        assertEquals(Screen.Login,vm.state.value.screen);assertTrue(vm.state.value.expired);assertNull(vm.state.value.accountNote)
    }
    /** 10-31: on the default service (nothing saved) a notice opens its conversation, the address written either way. */
    @Test fun aNoticeOnTheDefaultServiceOpensItsConversation()=runTest(dispatcher) {
        val api=TestApi();val vm=ReaderViewModel(TestStore()) { api };advanceUntilIdle()
        vm.login("owner","test");advanceUntilIdle();vm.select(api.a);advanceUntilIdle()
        assertEquals(DefaultOrigin,vm.state.value.origin)
        vm.openNotification(WatchTarget("https://app.pocketagentdesk.com/",ChatKey(vm.state.value.scope,api.b.id,"noticed"),"token"));advanceUntilIdle()
        assertNull(vm.state.value.error);assertEquals("noticed",vm.state.value.chat?.id);assertEquals(api.b.id,vm.state.value.device?.id)
    }

    /** 10-31: a phone that saved the old default's IP starts on the domain, still signed in and where it was; only once. */
    @Test fun theOldDefaultMovesToTheDomainSignedInAndWhereItWas()=runTest(dispatcher) {
        val api=TestApi();val vault=MemoryCookieVault();val asked=mutableListOf<String>();val watched=mutableListOf<Pair<String,String>>()
        val store=TestStore(Preferences(origin="https://8.166.15.235/",scope="stored",device=api.a.id,chat="restored"))
        vault.write("https://8.166.15.235/","signed-in")
        val vm=ReaderViewModel(store,prepare={ moveService(store,vault) { from,to -> watched+=from to to } }) { origin -> asked+=origin;api };advanceUntilIdle()
        assertEquals(listOf("https://app.pocketagentdesk.com/"),asked);assertEquals("https://app.pocketagentdesk.com/",vm.state.value.origin)
        assertEquals(Screen.Reading,vm.state.value.screen);assertEquals("restored",vm.state.value.chat?.id);assertEquals("stored",store.prefs.scope)
        assertEquals("signed-in",vault.read("https://app.pocketagentdesk.com/"));assertNull(vault.read("https://8.166.15.235/"))
        assertEquals(listOf("https://8.166.15.235/" to "https://app.pocketagentdesk.com/"),watched)
        // The IP set again by hand (开发者选项 → 服务地址) stays, at the next start too.
        vm.connect(OldDefaultOrigin);advanceUntilIdle();vault.write("https://8.166.15.235/","signed-in-there")
        val again=ReaderViewModel(store,prepare={ moveService(store,vault) }) { api };advanceUntilIdle()
        assertEquals("https://8.166.15.235/",again.state.value.origin);assertEquals("signed-in-there",vault.read("https://8.166.15.235/"))
    }
    /** Nothing saved meant the default: it stays the default, now the domain, and the sign-in made on the IP goes along. */
    @Test fun nothingSavedFollowsTheDefaultToTheDomainWithItsSignIn()=runTest(dispatcher) {
        val vault=MemoryCookieVault();val store=TestStore();vault.write("https://8.166.15.235/","signed-in")
        val vm=ReaderViewModel(store,prepare={ moveService(store,vault) }) { TestApi() };advanceUntilIdle()
        assertEquals(DefaultOrigin,vm.state.value.origin);assertEquals("",store.prefs.origin);assertTrue(store.moved)
        assertEquals("signed-in",vault.read("https://app.pocketagentdesk.com/"));assertNull(vault.read("https://8.166.15.235/"))
    }
    @Test fun anotherServiceStaysAsItWas()=runTest(dispatcher) {
        val vault=MemoryCookieVault();val store=TestStore(Preferences(origin="https://example.invalid/"));val watched=mutableListOf<String>()
        vault.write("https://example.invalid/","mine");vault.write("https://8.166.15.235/","old")
        val vm=ReaderViewModel(store,prepare={ moveService(store,vault) { from,_ -> watched+=from } }) { TestApi() };advanceUntilIdle()
        assertEquals("https://example.invalid/",vm.state.value.origin);assertTrue(store.moved);assertTrue(watched.isEmpty())
        assertEquals("mine",vault.read("https://example.invalid/"));assertEquals("old",vault.read("https://8.166.15.235/"));assertNull(vault.read("https://app.pocketagentdesk.com/"))
    }
    /** A move that fails (the phone's storage) does not keep the app from starting, and is tried again at the next start. */
    @Test fun aMoveThatFailsStartsAllTheSame()=runTest(dispatcher) {
        val broken=object:CookieVault { override fun read(origin:String):String?=throw IllegalStateException("keystore");override fun write(origin:String,cookie:String?)=Unit }
        val store=TestStore();val vm=ReaderViewModel(store,prepare={ moveService(store,broken) }) { TestApi() };advanceUntilIdle()
        assertEquals(DefaultOrigin,vm.state.value.origin);assertEquals(Screen.Devices,vm.state.value.screen);assertFalse(store.moved)
    }
}
