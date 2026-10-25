package com.pocketagentdesk.nativepreview

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import org.json.JSONObject
import org.json.JSONArray
import org.junit.Test
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.runner.RunWith
import java.util.UUID

/** Runs only with explicit per-run permission. Never writes to a discovered working chat. */
@RunWith(AndroidJUnit4::class)
class RealPhase3DeviceTest {
    @Test fun recoverOriginalAttachmentReceiptWithoutResending()=runBlocking {
        val rid=InstrumentationRegistry.getArguments().getString("teleplyRecoverRequest").orEmpty();assumeTrue(rid.isNotBlank())
        val (api,p,target)=connect()
        try { assertEquals("accepted",api.receipt(p.device,target,rid).string("state"));assertTrue(api.history(p.device,target).items.any { it.role=="assistant" && it.text.contains("PHASE3_FILES_OK") }) } finally { api.close() }
    }
    private suspend fun connect():Triple<RelayApi,Preferences,String> {
        val args=InstrumentationRegistry.getArguments()
        assumeTrue(args.getString("teleplyPhase3Writes")=="true")
        val target=args.getString("teleplyRealThread").orEmpty();require(target.isNotBlank())
        val app=InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as NativeApplication
        val prefs=app.store.preferences();val api=RelayApi(prefs.origin,app.vault)
        require(api.account().devices.any { it.id==prefs.device && it.connectable });api.select(prefs.device)
        return Triple(api,prefs,target)
    }
    @Test fun uploadFixedImageAndTextThenSend()=runBlocking {
        val (api,p,target)=connect()
        try {
            require(!api.control(p.device,target).running)
            val text=api.upload(p.device,target,"teleply-phase3-fixture.txt","Teleply phase3 fixed test data. No client content.".toByteArray(),false)
            val bitmap=android.graphics.Bitmap.createBitmap(16,16,android.graphics.Bitmap.Config.ARGB_8888).apply { eraseColor(android.graphics.Color.BLUE) }
            val bytes=java.io.ByteArrayOutputStream().use { out -> bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG,100,out);out.toByteArray() };bitmap.recycle()
            val image=api.upload(p.device,target,"teleply-phase3-fixture.png",bytes,true)
            val id=UUID.randomUUID().toString()
            println("TELEPLY_ATTACHMENT_REQUEST=$id")
            try { api.command(p.device,"send",JSONObject().put("id",target).put("request_id",id).put("intent","auto").put("text","Teleply authorized phase 3 attachment test. The two attachments contain only fixed test data. Reply only PHASE3_FILES_OK. Do not use tools, read or change local files, or message other chats.").put("attachments",JSONArray().put(image.getString("id"))).put("references",JSONArray().put(text))) } catch(_:Exception) { /* Reconcile this ID, never resend. */ }
            withTimeout(30000) { while(api.receipt(p.device,target,id).string("state")!="accepted") delay(1000) }
            withTimeout(60000) { while(api.control(p.device,target).running) delay(1000) }
            assertTrue(api.history(p.device,target).items.any { it.role=="assistant" && it.text.contains("PHASE3_FILES_OK") })
        } finally { api.close() }
    }
    @Test fun explicitAnswerUsesLiveQuestionIdentity()=runBlocking {
        val (api,p,target)=connect();var ownedTurn=""
        try {
            require(!api.control(p.device,target).running)
            val id=UUID.randomUUID().toString()
            println("TELEPLY_QUESTION_REQUEST=$id")
            try { api.command(p.device,"send",JSONObject().put("id",target).put("request_id",id).put("intent","auto").put("text","Teleply authorized native question test. Call request_user_input_async now with one question named Teleply phase3 test, options Test A and Test B. Then use clock.sleep for 45 seconds so the native phone can answer. Do not change files or message chats. After receiving the answer reply only PHASE3_ANSWER_OK.")) } catch(_:Exception) { assertEquals("accepted",api.receipt(p.device,target,id).string("state")) }
            val card=withTimeout(45000) {
                var found:JSONObject?=null
                while(found==null) { val control=api.control(p.device,target);if(ownedTurn.isBlank()) ownedTurn=control.turn;found=JSONObject(control.raw).rows("questions") { it }.firstOrNull { (it.string("status")=="pending" || it.optBoolean("editable")) && it.rows("questions") { q -> q.string("question") }.any { q -> q.contains("Teleply",true) } };if(found==null) delay(750) }
                found
            }
            val answers=JSONObject();card.rows("questions") { it }.forEach { q -> val label=q.rows("options") { it }.firstOrNull()?.string("label") ?: "Test A";answers.put(q.getString("id"),JSONArray().put(label)) }
            val rid=UUID.randomUUID().toString()
            val response=api.command(p.device,"answer",JSONObject().put("id",target).put("request_id",rid).put("question_id",card.string("id")).put("answer_revision",card.string("answer_revision")).put("answers",answers))
            assertTrue(response.optBoolean("accepted"));assertEquals("accepted",api.receipt(p.device,target,rid).string("state"))
        } finally {
            if(ownedTurn.isNotBlank()) runCatching { val c=api.control(p.device,target);if(c.running && c.turn==ownedTurn) api.command(p.device,"stop",JSONObject().put("id",target).put("operation_id",UUID.randomUUID().toString()).put("turn_id",ownedTurn)) }
            api.close()
        }
    }
    @Test fun createOneProjectlessTestConversationAndRecoverSameRequest()=runBlocking {
        assumeTrue(InstrumentationRegistry.getArguments().getString("teleplyAllowCreate")=="true")
        val (api,p,_)=connect()
        try {
            val rid=api.detail(p.device,"chat/new/draft",body=JSONObject()).getString("request_id")
            val body=JSONObject().put("request_id",rid).put("app","codex").put("projectless",true).put("text","Teleply authorized phase 3 disposable creation test. Reply only PHASE3_NEW_OK. Do not use tools, read or change any files, or message other chats.").put("attachments",JSONArray()).put("references",JSONArray())
            println("TELEPLY_CREATION_REQUEST=$rid")
            try { api.detail(p.device,"chat/new",body=body) } catch(_:Exception) { /* Original request is checked below. */ }
            val result=withTimeout(120000) {
                var current=api.detail(p.device,"chat/new/state",mapOf("request_id" to rid))
                while(current.string("state") !in listOf("accepted","failed","unconfirmed")) { delay(1000);current=api.detail(p.device,"chat/new/state",mapOf("request_id" to rid)) }
                current
            }
            assertEquals("accepted",result.string("state"));assertEquals("codex",result.string("app"));assertTrue(result.string("id").isNotBlank())
            val recovered=api.detail(p.device,"chat/new/state",mapOf("request_id" to rid));assertEquals(result.string("id"),recovered.string("id"))
            println("TELEPLY_CREATED_TEST_THREAD="+result.string("id"))
        } finally { api.close() }
    }
}
