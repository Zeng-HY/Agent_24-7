package com.pocketagentdesk.nativepreview

import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import org.json.JSONObject
import org.junit.Test
import org.junit.Assume.assumeTrue
import org.junit.Assert.*
import org.junit.runner.RunWith
import java.util.UUID

/** Explicitly opted-in device tests. Never use browser/old-app credentials or log server bodies. */
@RunWith(AndroidJUnit4::class)
class RealServiceDeviceTest {
    private suspend fun connection():Triple<RelayApi,Preferences,String> {
        val args=InstrumentationRegistry.getArguments()
        val target=args.getString("teleplyRealThread").orEmpty()
        assumeTrue("Requires a user-designated disposable thread",target.isNotBlank())
        val app=InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as NativeApplication
        val p=app.store.preferences()
        require(p.origin.startsWith("https://") && p.device.isNotBlank())
        val api=RelayApi(p.origin,app.vault)
        require(api.account().devices.any { it.id==p.device && it.connectable })
        api.select(p.device)
        return Triple(api,p,target)
    }
    @Test fun authenticatedReadOnly()=runBlocking {
        val (api,p,target)=connection()
        try {
            assertTrue(api.config().isNotBlank())
            assertTrue(api.chats(p.device,"",null).items.isNotEmpty())
            val history=api.history(p.device,target)
            assertTrue(history.items.isNotEmpty())
            if(history.hasMore) assertTrue(api.history(p.device,target,before=history.cursor).items.isNotEmpty())
            api.search(p.device,target,"Teleply",null)
            val frame=withTimeout(30000) { api.events(p.device,target).first() }
            assertTrue(frame.snapshot);assertEquals(1L,frame.seq)
            assertTrue(api.control(p.device,target).available)
        } finally { api.close() }
    }
    @Test fun explicitlyAuthorizedChatActions()=runBlocking {
        assumeTrue(InstrumentationRegistry.getArguments().getString("teleplyAllowWrites")=="true")
        val (api,p,target)=connection()
        fun id()=UUID.randomUUID().toString()
        fun body(rid:String,text:String,intent:String,turn:String="")=JSONObject().put("id",target).put("request_id",rid).put("text",text).put("intent",intent).apply { if(turn.isNotBlank()) put("expected_turn",turn) }
        try {
            require(!api.control(p.device,target).running) { "Test thread must be idle before starting" }
            val start=id()
            val sent=api.command(p.device,"send",body(start,"Teleply Android phase 2 authorized disposable-session test. Please use clock.sleep to wait 45 seconds, then reply only TELEPLY_PHASE2_OK. Do not read or change files, browse, or message other chats.","auto"))
            assertEquals(start,sent.string("request_id"));assertEquals("accepted",sent.string("delivery_state"))
            assertEquals("accepted",api.receipt(p.device,target,start).string("state"))
            val running=withTimeout(15000) { var c=api.control(p.device,target);while(!c.running) { delay(500);c=api.control(p.device,target) };c }
            val steer=id()
            val supplemented=api.command(p.device,"send",body(steer,"Teleply immediate supplement check: keep waiting as requested; no other work.","steer",running.turn))
            assertEquals("accepted",supplemented.string("delivery_state"))
            val queued=id()
            assertTrue(running.queueAvailable)
            assertEquals("queued",api.command(p.device,"send",body(queued,"Teleply disposable queue test; this item will be cancelled.","queue",running.turn)).string("delivery_state"))
            assertTrue(api.control(p.device,target).queued.any { it.id==queued })
            val cancel=id()
            assertEquals("cancelled",api.command(p.device,"queue-action",JSONObject().put("id",target).put("request_id",cancel).put("message_id",queued).put("action","cancel")).string("delivery_state"))
            assertFalse(api.control(p.device,target).queued.any { it.id==queued })
            val stop=id()
            assertTrue(api.command(p.device,"stop",JSONObject().put("id",target).put("operation_id",stop).put("turn_id",running.turn)).optBoolean("accepted"))
            withTimeout(20000) { while(api.control(p.device,target).running) delay(500) }
            assertEquals("accepted",api.receipt(p.device,target,stop).string("state"))
        } finally { api.close() }
    }
}
