package com.pocketagentdesk.teleply

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/** 11-26 线三: a receipt that says 电脑没收到, 重发 with the original request, 恢复草稿 taking the copy away, 核对's line. */
private class SendStore : ReaderStore by TestStore() {
    val drafts = mutableMapOf<ChatKey, String>()
    val records = mutableMapOf<String, Submission>()
    override suspend fun draft(key: ChatKey) = drafts[key].orEmpty()
    override suspend fun draft(key: ChatKey, text: String) { drafts[key] = text }
    override suspend fun submissions(key: ChatKey) = records.values.filter { it.scope == key.scope && it.device == key.device && it.chat == key.chat && it.app == key.app }
    override suspend fun submission(value: Submission) { records[value.request] = value }
    override suspend fun begin(value: Submission) { submission(value); draft(ChatKey(value.scope, value.device, value.chat, value.app), "") }
}

private class SendApi : TestApi() {
    val receipts = mutableMapOf<String, JSONObject>()
    val sent = mutableListOf<JSONObject>()
    var fail: Exception? = null
    var receiptFails = false
    var claudeDelivered = false
    var receiptGate: CompletableDeferred<Unit>? = null
    override suspend fun control(device: String, chat: String, fresh: Boolean) = Control(available = true, queueAvailable = true)
    override suspend fun command(device: String, route: String, body: JSONObject): JSONObject {
        sent += JSONObject(body.toString())
        fail?.let { throw it }
        return JSONObject().put("request_id", body.string("request_id")).put("delivery_state", "accepted")
    }
    override suspend fun receipt(device: String, chat: String, request: String): JSONObject {
        receiptGate?.await()
        if (receiptFails) throw java.io.IOException("timeout")
        return receipts[request] ?: JSONObject().put("state", "unknown")
    }
    override suspend fun detail(device: String, route: String, query: Map<String, String?>, body: JSONObject?): JSONObject =
        if (route == "chat/check") JSONObject().put("delivered", claudeDelivered).put("queued", false)
        else super.detail(device, route, query, body)
}

@OptIn(ExperimentalCoroutinesApi::class)
class SendFixesTest {
    private val key = ChatKey("account", "a".repeat(32), "chat")

    private fun body(id: String = "r1", text: String = "原来的内容") = JSONObject()
        .put("id", key.chat).put("request_id", id).put("text", text).put("intent", "auto").put("attachments", JSONArray())

    private fun record(label: String = "送达状态待确认", id: String = "r1", text: String = "原来的内容", body: JSONObject = body(id, text), key: ChatKey = this.key) =
        Submission(id, key.scope, key.device, app = key.app, chat = key.chat, text = text, action = "send", turn = "",
            body = body.toString(), label = label)

    private fun missing() = JSONObject().put("state", "unknown").put("missing", true)

    /** Design 3.1 item 1: missing is its own label; plain unknown stays 待确认; a delivered answer is not affected. */
    @Test fun aReceiptThatSaysMissingIsItsOwnLabel() {
        assertEquals(MissingLabel, receiptLabel("unknown", JSONObject(), "send", missing = true))
        assertEquals("送达状态待确认", receiptLabel("unknown", JSONObject(), "send", missing = false))
        assertEquals("送达状态待确认", receiptLabel("unknown", JSONObject(), "send"))
        assertEquals("已接收", receiptLabel("accepted", JSONObject(), "send", missing = true))
        assertEquals("未接收", receiptLabel("rejected", JSONObject(), "send", missing = true))
        // A stop is not a message the computer can say it never got.
        assertEquals("送达状态待确认", receiptLabel("unknown", JSONObject(), "stop", missing = true))
        // 核对's line comes from the receipt's own state, not from the label a send happens to have.
        assertEquals("已核对：电脑没收到", checkResultText("unknown", true, "电脑没收到"))
        assertEquals("已核对：电脑查不到这条的记录", checkResultText("unknown", false, "送达状态待确认"))
        assertEquals("已核对：电脑收到了，还在处理", checkResultText("dispatching", false, "送达状态待确认"))
        assertEquals("已核对：已停止", checkResultText("accepted", false, "已停止"))
        assertEquals("已核对：已送达", checkResultText("accepted", false, "已送达"))
        assertEquals("已核对：已送达", claudeCheckResultText(true, false))
        assertEquals("已核对：已排队", claudeCheckResultText(false, true))
        assertEquals("已核对：Claude 的记录里还没看到这条", claudeCheckResultText(false, false))
    }

    /** The three answers on a stored send: missing, unknown only, and something else. */
    @Test fun reconcileMarksMissingAndKeepsUnknownWithoutMissingAsPending() = runTest {
        val store = SendStore()
        val missingApi = SendApi().apply { receipts["r1"] = missing() }
        store.records["r1"] = record(body = body().put(ReceiptUnknownKey, true))
        val again = ChatController(backgroundScope, store)
        again.bind(key, missingApi, true, false) {}
        runCurrent()
        assertEquals(MissingLabel, again.state.value.submissions.single().label)
        assertFalse(JSONObject(again.state.value.submissions.single().body).has(ReceiptUnknownKey))

        val store2 = SendStore()
        val unknownApi = SendApi()
        store2.records["r1"] = record()
        val unknown = ChatController(backgroundScope, store2)
        unknown.bind(key, unknownApi, true, false) {}
        runCurrent()
        assertEquals("送达状态待确认", unknown.state.value.submissions.single().label)
        assertTrue(JSONObject(unknown.state.value.submissions.single().body).optBoolean(ReceiptUnknownKey))

        val store3 = SendStore()
        val acceptedApi = SendApi().apply { receipts["r1"] = JSONObject().put("state", "accepted").put("request_id", "r1") }
        store3.records["r1"] = record()
        val accepted = ChatController(backgroundScope, store3)
        accepted.bind(key, acceptedApi, true, false) {}
        runCurrent()
        assertEquals("已接收", accepted.state.value.submissions.single().label)
    }

    /** Design 3.1 item 2: 重发 uses the original request id and content, the label is 提交中 until the answer comes. */
    @Test fun resendUsesTheOriginalRequestAndContentAndKeepsTheDraft() = runTest {
        val store = SendStore()
        val original = body().put(ReceiptUnknownKey, true)
        store.records["r1"] = record(label = MissingLabel, body = original)
        val api = SendApi().apply { receipts["r1"] = missing() }
        val c = ChatController(backgroundScope, store)
        c.bind(key, api, true, false) {}
        runCurrent()
        c.edit("这行是新草稿"); runCurrent()
        c.resend(c.state.value.submissions.single())
        runCurrent()
        assertEquals(1, api.sent.size)
        assertEquals("r1", api.sent.single().string("request_id"))
        assertEquals("原来的内容", api.sent.single().string("text"))
        // The local note never goes to the computer: the body is the one it first received.
        assertFalse(api.sent.single().has(ReceiptUnknownKey))
        assertEquals("这行是新草稿", c.state.value.draft)
        assertEquals("这行是新草稿", store.drafts[key])
        assertEquals("已接收", c.state.value.submissions.single().label)
    }

    /** The computer answering 这次请求已提交过…: its sentence is shown as it wrote it, and the label is back to 待确认. */
    @Test fun resendToldItWasAlreadySubmittedShowsTheSentenceAndGoesBackToPending() = runTest {
        val store = SendStore()
        store.records["r1"] = record(label = MissingLabel)
        val api = SendApi().apply { receipts["r1"] = missing() }
        val c = ChatController(backgroundScope, store)
        c.bind(key, api, true, false) {}
        runCurrent()
        api.fail = ServiceFailure(400, "already", "这次请求已提交过，结果尚未确认；请检查对话，不会重复发送")
        c.resend(c.state.value.submissions.single())
        runCurrent()
        assertEquals("送达状态待确认", c.state.value.submissions.single().label)
        assertEquals("这次请求已提交过，结果尚未确认；请检查对话，不会重复发送", c.state.value.error)
    }

    /** Design 3.1 item 2 and 3.4: 恢复草稿 puts the words back and the copy is gone. */
    @Test fun restoreDraftTakesTheCopyAway() = runTest {
        val store = SendStore()
        store.records["r1"] = record(label = MissingLabel)
        val api = SendApi().apply { receipts["r1"] = missing() }
        val c = ChatController(backgroundScope, store)
        c.bind(key, api, true, false) {}
        runCurrent()
        c.restoreAndRemove(c.state.value.submissions.single())
        runCurrent()
        assertEquals("原来的内容", c.state.value.draft)
        assertEquals(RemovedLabel, store.records.getValue("r1").label)
        assertTrue(c.state.value.submissions.none { it.label != RemovedLabel })
    }

    /** Design 3.1 item 7: 电脑没收到 does not trip the "same words are still pending" rule. */
    @Test fun theSameWordsCanBeSentAfterTheComputerSaidItNeverGotThem() = runTest {
        val store = SendStore()
        store.records["r1"] = record(label = MissingLabel)
        val api = SendApi().apply { receipts["r1"] = missing() }
        val c = ChatController(backgroundScope, store)
        c.bind(key, api, true, false) {}
        runCurrent()
        c.edit("原来的内容"); runCurrent()
        c.send(); runCurrent()
        assertEquals(1, api.sent.size)
    }

    /** Design 3.1 item 5: 核对 shows that it runs, then one result line that goes away by itself. */
    @Test fun checkShowsProgressThenOneResultThatFades() = runTest {
        val store = SendStore()
        store.records["r1"] = record(label = MissingLabel)
        val api = SendApi().apply { receipts["r1"] = missing() }
        val c = ChatController(backgroundScope, store)
        c.bind(key, api, true, false) {}
        runCurrent()
        api.receiptGate = CompletableDeferred()
        c.check(c.state.value.submissions.single())
        runCurrent()
        assertEquals("r1", c.state.value.checking)
        assertEquals("", c.state.value.checkNote)
        api.receiptGate!!.complete(Unit)
        runCurrent()
        assertEquals("", c.state.value.checking)
        assertEquals("已核对：电脑没收到", c.state.value.checkNote)
        advanceTimeBy(4_001); runCurrent()
        assertEquals("", c.state.value.checkNote)
    }

    /** A failed 核对 keeps the copy and says so (design 3.1 item 5). */
    @Test fun aFailedCheckKeepsTheCopyAndSaysSo() = runTest {
        val store = SendStore()
        store.records["r1"] = record(label = MissingLabel)
        val api = SendApi().apply { receipts["r1"] = missing() }
        val c = ChatController(backgroundScope, store)
        c.bind(key, api, true, false) {}
        runCurrent()
        api.receiptGate = CompletableDeferred()
        c.check(c.state.value.submissions.single())
        runCurrent()
        api.receiptGate!!.completeExceptionally(java.io.IOException("timeout"))
        runCurrent()
        assertEquals("核对失败，原提交仍保留；不会自动重发。", c.state.value.error)
        assertEquals(MissingLabel, c.state.value.submissions.single().label)
    }

    /** A receipt still being processed is said in its own words, not as "查不到这条" (design 3.1 item 5). */
    @Test fun checkTellsADispatchingReceiptApart() = runTest {
        val store = SendStore()
        store.records["r1"] = record()
        val api = SendApi().apply { receipts["r1"] = JSONObject().put("state", "dispatching").put("request_id", "r1") }
        val c = ChatController(backgroundScope, store)
        c.bind(key, api, true, false) {}
        runCurrent()
        c.check(c.state.value.submissions.single())
        runCurrent()
        assertEquals("已核对：电脑收到了，还在处理", c.state.value.checkNote)
        assertEquals("送达状态待确认", c.state.value.submissions.single().label)
    }

    /** 11-26: a Claude send asks the shared delivery record first, and can be 电脑没收到 and sent again. */
    @Test fun aClaudeSendCanBeMissingAndSentAgain() = runTest {
        val claudeKey = key.copy(app = "claude")
        val store = SendStore()
        store.records["r1"] = record(label = "送达状态待确认", key = claudeKey)
        val api = SendApi().apply { receipts["r1"] = missing() }
        val c = ChatController(backgroundScope, store)
        c.bind(claudeKey, api, true, false) {}
        runCurrent()
        assertEquals(MissingLabel, c.state.value.submissions.single().label)
        c.resend(c.state.value.submissions.single())
        runCurrent()
        assertEquals(1, api.sent.size)
        assertEquals("r1", api.sent.single().string("request_id"))
    }

    /** A Claude receipt that cannot be read is no reason to fail the check: its own record is asked as before. */
    @Test fun aClaudeReceiptFailureFallsBackToItsRecord() = runTest {
        val claudeKey = key.copy(app = "claude")
        val store = SendStore()
        val b = body().put(ClaudeOffset, 100L).put(ClaudeCheckText, "原来的内容")
        store.records["r1"] = record(key = claudeKey, body = b)
        val api = SendApi().apply { receiptFails = true; claudeDelivered = true }
        val c = ChatController(backgroundScope, store)
        c.bind(claudeKey, api, true, false) {}
        runCurrent()
        assertEquals("已送达", c.state.value.submissions.single().label)
        c.check(c.state.value.submissions.single())
        runCurrent()
        assertEquals("已核对：已送达", c.state.value.checkNote)
        assertEquals(null, c.state.value.error)
    }
}
