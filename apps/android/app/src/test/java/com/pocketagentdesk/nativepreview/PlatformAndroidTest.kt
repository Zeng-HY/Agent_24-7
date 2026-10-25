package com.pocketagentdesk.nativepreview

import android.Manifest
import android.app.*
import android.app.job.JobScheduler
import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.runBlocking
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
    @Test fun permissionDenialNeverSchedulesWork()=runBlocking {
        shadowOf(context).denyPermissions(Manifest.permission.POST_NOTIFICATIONS)
        val api=TestApi();val store=TestStore(Preferences(origin="https://example.invalid/",scope="owner"))
        val manager=WatchManager(context,store) { api }
        try { manager.enable(store.prefs.origin,ChatKey("owner",api.a.id,"chat"));fail() } catch(_:IllegalStateException) { }
        assertNull(manager.state.value);assertTrue(context.getSystemService(JobScheduler::class.java).allPendingJobs.isEmpty())
    }
}
