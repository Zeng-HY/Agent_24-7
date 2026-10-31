package com.pocketagentdesk.teleply

import android.Manifest
import android.app.*
import android.app.job.JobScheduler
import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.*
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk=[35],application=android.app.Application::class)
class PlatformAndroidTest {
    private val context get()=ApplicationProvider.getApplicationContext<Application>()
    @Before fun reset() { context.getSharedPreferences("native_watch",Context.MODE_PRIVATE).edit().clear().commit();shadowOf(context).grantPermissions(Manifest.permission.POST_NOTIFICATIONS) }
    @Test fun periodicWatchChecksOwnershipDeduplicatesAndRejectsStaleNonce()=runBlocking {
        var status=Control(true,true,"turn",turns=mapOf("turn" to "inProgress"))
        val api=object:TestApi() { override suspend fun control(device:String,chat:String,fresh:Boolean)=status }
        val store=TestStore(Preferences(origin="https://example.invalid/",scope="owner",device=api.a.id,chat="chat"))
        val manager=WatchManager(context,store) { api };val key=ChatKey("owner",api.a.id,"chat")
        assertNull(manager.state.value);manager.enable(store.prefs.origin,key)
        val token=manager.state.value!!.nonce;assertNotNull(manager.resolve(token));assertNull(manager.resolve("forged"))
        assertTrue(context.getSystemService(JobScheduler::class.java).allPendingJobs.single().intervalMillis>=15*60*1000L)
        status=Control(true,false,turns=mapOf("turn" to "completed"));manager.checkOnce();manager.checkOnce()
        val notifications=shadowOf(context.getSystemService(NotificationManager::class.java)).allNotifications
        assertEquals(1,notifications.size)
        val intent=shadowOf(notifications.single().contentIntent).savedIntent
        assertNull(intent.data);assertEquals(token,intent.getStringExtra(WatchManager.EXTRA));assertFalse(intent.hasExtra("origin"))
        store.prefs=store.prefs.copy(scope="other");assertNull(manager.resolve(token));manager.checkOnce();assertNull(manager.state.value)
        assertTrue(context.getSystemService(JobScheduler::class.java).allPendingJobs.isEmpty())
    }
    /** 10-31: the conversation checked on the old default goes along to the domain (moveService), its token too. */
    @Test fun aWatchOnTheOldDefaultMovesWithTheService()=runBlocking {
        val api=object:TestApi() { override suspend fun control(device:String,chat:String,fresh:Boolean)=Control(true,true,"turn") }
        val store=TestStore(Preferences(origin="https://8.166.15.235/",scope="owner",device=api.a.id,chat="chat"))
        val manager=WatchManager(context,store) { api };manager.enable(store.prefs.origin,ChatKey("owner",api.a.id,"chat"))
        val token=manager.state.value!!.nonce
        moveService(store,MemoryCookieVault(),manager::moved)
        assertEquals("https://app.pocketagentdesk.com/",store.prefs.origin);assertEquals("https://app.pocketagentdesk.com/",manager.state.value!!.origin)
        assertNotNull(manager.resolve(token))
        // Read again as at the next start; a watch elsewhere would have stayed where it was.
        assertEquals(manager.state.value,WatchManager(context,store) { api }.state.value)
        manager.moved("https://8.166.15.235/","https://elsewhere.invalid/");assertEquals("https://app.pocketagentdesk.com/",manager.state.value!!.origin)
        manager.disable()
    }
    /**
     * 10-31: on the default service (nothing saved) the check of the open conversation can be switched on; 退出登录 and a
     * refused 删除账号 leave it on, a done one switches it off.
     */
    @OptIn(ExperimentalCoroutinesApi::class)
    @Test fun theCheckWorksOnTheDefaultServiceAndEndsWithADeletedAccount() {
        val dispatcher=StandardTestDispatcher();Dispatchers.setMain(dispatcher)
        try { runTest(dispatcher) {
            val api=object:TestApi() { override suspend fun control(device:String,chat:String,fresh:Boolean)=Control(true,true,"turn") }
            val store=TestStore();val manager=WatchManager(context,store) { api }
            val vm=ReaderViewModel(store,accountDeleted=manager::disable) { api };advanceUntilIdle()
            vm.login("owner","test");advanceUntilIdle();vm.select(api.a);advanceUntilIdle();vm.open(vm.state.value.chats.first());advanceUntilIdle()
            val s=vm.state.value;assertEquals(DefaultOrigin,s.origin);assertEquals("",store.prefs.origin)
            manager.enable(s.origin,ChatKey(s.scope,api.a.id,s.chat!!.id))
            assertNotNull(manager.resolve(manager.state.value!!.nonce))
            vm.deleteAccount("wrong") {};advanceUntilIdle();assertNotNull(manager.state.value)
            vm.logout();advanceUntilIdle();assertNotNull(manager.state.value)
            vm.login("owner","test");advanceUntilIdle();vm.deleteAccount("test") {};advanceUntilIdle()
            assertTrue(api.deleted);assertNull(manager.state.value)
            assertTrue(context.getSystemService(JobScheduler::class.java).allPendingJobs.isEmpty())
        } } finally { Dispatchers.resetMain() }
    }
    @Test fun permissionDenialNeverSchedulesWork()=runBlocking {
        shadowOf(context).denyPermissions(Manifest.permission.POST_NOTIFICATIONS)
        val api=TestApi();val store=TestStore(Preferences(origin="https://example.invalid/",scope="owner"))
        val manager=WatchManager(context,store) { api }
        try { manager.enable(store.prefs.origin,ChatKey("owner",api.a.id,"chat"));fail() } catch(_:IllegalStateException) { }
        assertNull(manager.state.value);assertTrue(context.getSystemService(JobScheduler::class.java).allPendingJobs.isEmpty())
    }
}
