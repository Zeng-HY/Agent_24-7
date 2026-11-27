package com.pocketagentdesk.teleply

import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 11-27 S1/S5/S2/S3 on Android (design §4.1–4.5): steering by default, the waiting line, ending only the running
 * command, and the phone→computer / computer timing that `client_prev` carries to the next send.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class SpeedSteerTest {
    private val key = ChatKey("account", "a".repeat(32), "chat")

    // 11-27 S1: a tap while running steers; the long press offers queue only when the assistant offers both.
    @Test fun sendSteersWhileRunningAndOffersQueueOnlyWhenBothAreSupported() {
        val both = composerSendPlan(running = true, sendModes = listOf("send", "steer", "queue"), queueAvailable = true)
        assertEquals(SendRun.Steer, both.run)
        assertEquals("发送（插话）", both.label)
        assertTrue(both.longPressQueues)

        val steerOnly = composerSendPlan(running = true, sendModes = listOf("send", "steer"), queueAvailable = false)
        assertEquals(SendRun.Steer, steerOnly.run)
        assertEquals("发送（插话）", steerOnly.label)
        assertFalse(steerOnly.longPressQueues)

        val queueOnly = composerSendPlan(running = true, sendModes = listOf("send", "queue"), queueAvailable = true)
        assertEquals(SendRun.Queue, queueOnly.run)
        assertEquals("发送并排队", queueOnly.label)
        assertFalse(queueOnly.longPressQueues)

        val idle = composerSendPlan(running = false, sendModes = listOf("send", "steer", "queue"), queueAvailable = true)
        assertEquals(SendRun.Send, idle.run)
        assertEquals("发送", idle.label)
        assertFalse(idle.longPressQueues)

        // Running and refusing to take anything keeps the button inert, as before.
        val none = composerSendPlan(running = true, sendModes = emptyList(), queueAvailable = false)
        assertEquals(SendRun.Send, none.run)
    }

    // 11-27 S5: the waiting line is for an accepted steer only, and says the assistant's own name.
    @Test fun waitingLineBelongsToAcceptedSteerSendsOnly() {
        fun record(label: String, intent: String?) = Submission(
            "r1", key.scope, key.device, app = "codex", chat = key.chat, text = "插话", action = "send", turn = "t",
            body = JSONObject().put("intent", intent ?: "").toString(), label = label,
        )
        assertEquals(record("已接收", "steer"), waitingSteer(listOf(record("已接收", "steer"))))
        assertNull(waitingSteer(listOf(record("已接收", "queue"))))
        assertNull(waitingSteer(listOf(record("已送达", "steer"))))
        assertNull(waitingSteer(listOf(record("已接收", "steer").copy(action = "stop"))))
        assertEquals("等 Codex 做完这一步再插进去 · 已等 12 秒", steerWaitingText("Codex", 12))
    }

    // 11-27 S2: the button's conditions and the confirmation's exact words.
    @Test fun killButtonNeedsARunningCommandThatMayBeKilledAndTheCapability() {
        fun raw(command: String?, kill: Boolean? = true) = JSONObject()
            .put("command", command?.let { JSONObject(it) } ?: JSONObject.NULL)
            .apply { if (kill != null) put("capabilities_now", JSONObject().put("kill_command", kill)) }

        assertTrue(canKillCommand(raw("""{"running":true,"since_ms":1,"can_kill":true}""")))
        assertFalse(canKillCommand(raw("""{"running":true,"since_ms":1,"can_kill":false}""")))
        assertFalse(canKillCommand(raw("""{"running":false,"since_ms":1,"can_kill":true}""")))
        // An older computer: no command at all, or no kill_command in its table.
        assertFalse(canKillCommand(raw(null)))
        assertFalse(canKillCommand(raw("""{"running":true,"since_ms":1,"can_kill":true}""", kill = null)))
        assertFalse(canKillCommand(raw("""{"running":true,"since_ms":1,"can_kill":true}""", kill = false)))
        assertEquals(
            "Codex 正在跑的这条命令会被结束，它的结果作废；你的话会马上交给 Codex。",
            killCommandConfirmText("Codex"),
        )
    }

    // 11-27 S3: the network part is the round trip less the computer's own time, never negative.
    @Test fun networkAndSpeedTextSubtractTheComputersOwnTime() {
        assertEquals(600L, networkMs(3_800L, 3_200L))
        assertEquals(0L, networkMs(100L, 300L))
        assertEquals("手机→电脑 0.6 秒 · 电脑处理 3.2 秒", speedNetworkText(SendSpeed(1, 3_800L, 3_200L, 600L)))
        assertEquals("手机→电脑 0.0 秒 · 电脑处理 0.3 秒", speedNetworkText(SendSpeed(1, 100L, 300L, 0L)))
        assertNull("an older computer gives no computer time, so no network time", speedNetworkText(SendSpeed(1, 800L, null, 0L)))
    }

    // 11-27 S3 (design §6.2): the first send carries the phone's time; the next carries the first one's numbers.
    @Test fun sendCarriesClientSentThenThePreviousRequestNumbers() = runTest {
        val store = SpeedStore()
        val api = TimingApi()
        val c = ChatController(backgroundScope, store)
        c.bind(key, api, true, false) { }
        runCurrent()
        assertTrue("bound and ready", c.state.value.ready)
        assertTrue("control read", c.state.value.control.available)

        c.edit("first")
        runCurrent()
        assertEquals("draft", "first", c.state.value.draft)
        assertFalse("not running", c.state.value.control.running)
        c.send()
        repeat(10) { runCurrent() }
        assertEquals("sends", 1, api.bodies.size)
        val first = api.bodies[0]
        assertTrue(first.has("client_sent_ms"))
        assertFalse(first.has("client_prev"))
        assertEquals("已接收", c.state.value.submissions.single().label)
        assertEquals(250L, c.state.value.lastSpeed?.serverMs)
        assertTrue((c.state.value.lastSpeed?.networkMs ?: -1) >= 0)

        c.edit("second")
        runCurrent()
        c.send()
        repeat(10) { runCurrent() }
        assertEquals(2, api.bodies.size)
        val prev = api.bodies[1].getJSONObject("client_prev")
        assertEquals(first.getString("request_id"), prev.getString("request_id"))
        assertEquals(250L, prev.getLong("server_ms"))
        assertTrue(prev.getLong("roundtrip_ms") >= 0)
    }

    // 11-27 S3 + §6.2: 重发 keeps the original body's timing fields; it must not look like another request.
    @Test fun resendKeepsTheOriginalTimingFields() = runTest {
        val store = SpeedStore()
        val originalPrev = JSONObject().put("request_id", "r0").put("roundtrip_ms", 900L).put("server_ms", 300L)
        val body = JSONObject()
            .put("id", key.chat).put("request_id", "r1").put("text", "原来的话").put("intent", "auto")
            .put("client_sent_ms", 111L).put("client_prev", originalPrev)
        store.records["r1"] = Submission(
            "r1", key.scope, key.device, app = "codex", chat = key.chat, text = "原来的话", action = "send",
            turn = "", body = body.toString(), label = MissingLabel, created = 1L,
        )
        val api = ResendApi()
        val c = ChatController(backgroundScope, store)
        c.bind(key, api, true, false) { }
        repeat(10) { runCurrent() }
        c.resend(c.state.value.submissions.single { it.request == "r1" })
        repeat(10) { runCurrent() }
        val sent = api.bodies.single()
        assertEquals(111L, sent.getLong("client_sent_ms"))
        assertEquals("r0", sent.getJSONObject("client_prev").getString("request_id"))
        assertEquals(900L, sent.getJSONObject("client_prev").getLong("roundtrip_ms"))
        assertEquals(300L, sent.getJSONObject("client_prev").getLong("server_ms"))
    }

    // 11-27 S2: kill-command goes to the computer's route, shows its fixed success line, and its refusal's reason.
    @Test fun killCommandShowsItsSuccessOrTheComputersReason() = runTest {
        val record = Submission(
            "r1", key.scope, key.device, app = "codex", chat = key.chat, text = "插话", action = "send",
            turn = "t", body = JSONObject().put("intent", "steer").toString(), label = "已接收",
        )
        for ((fail, expected, isError) in listOf(
            Triple(false, "已结束命令，正在插话…", false),
            Triple(true, "钩子没被信任", true),
        )) {
            val api = KillApi(fail)
            val c = ChatController(backgroundScope, persistent = SpeedStore())
            c.bind(key, api, true, false) { }
            runCurrent()
            assertTrue(canKillCommand(JSONObject(c.state.value.control.raw)))
            c.killCommand(record)
            repeat(10) { runCurrent() }
            assertEquals(listOf("kill-command"), api.routes)
            assertEquals(expected, c.state.value.killNote)
            assertEquals(isError, c.state.value.killFailed)
        }
    }

    // The demo world has a conversation where the waiting line and the kill button are both visible at once.
    @Test fun demoSteerStoryHasTheWaitingCommandAndCanEndIt() = runTest {
        val api = FixtureApi()
        val device = "a".repeat(32)
        assertTrue(api.world.firstPage().any { it.id == FixtureSteerStory.CHAT })
        val control = api.control(device, FixtureSteerStory.CHAT, true)
        assertTrue(control.running)
        assertTrue(canKillCommand(JSONObject(control.raw)))
        assertEquals("accepted", api.receipt(device, FixtureSteerStory.CHAT, FixtureSteerStory.REQUEST).string("state"))
        val killed = api.command(device, "kill-command", JSONObject().put("id", FixtureSteerStory.CHAT))
        assertTrue(killed.optBoolean("ok"))
        assertTrue(api.world.steerKilled)
        assertFalse(canKillCommand(JSONObject(api.control(device, FixtureSteerStory.CHAT, true).raw)))
    }

    private class SpeedStore : ReaderStore by TestStore() {
        val drafts = mutableMapOf<ChatKey, String>()
        val records = mutableMapOf<String, Submission>()
        override suspend fun draft(key: ChatKey) = drafts[key].orEmpty()
        override suspend fun draft(key: ChatKey, text: String) { drafts[key] = text }
        override suspend fun submissions(key: ChatKey) = records.values.filter { it.scope == key.scope && it.device == key.device && it.chat == key.chat }
        override suspend fun submission(value: Submission) { records[value.request] = value }
        override suspend fun begin(value: Submission) { submission(value); draft(ChatKey(value.scope, value.device, value.chat), "") }
    }

    private class TimingApi : TestApi() {
        val bodies = mutableListOf<JSONObject>()
        override suspend fun control(device: String, chat: String, fresh: Boolean) = Control(available = true)
        override fun events(device: String, chat: String) = emptyFlow<LiveFrame>()
        override suspend fun command(device: String, route: String, body: JSONObject): JSONObject {
            bodies += JSONObject(body.toString())
            return JSONObject().put("request_id", body.string("request_id")).put("delivery_state", "accepted").put("server_ms", 250)
        }
    }

    private class ResendApi : TestApi() {
        val bodies = mutableListOf<JSONObject>()
        override suspend fun control(device: String, chat: String, fresh: Boolean) = Control(available = true)
        override fun events(device: String, chat: String) = emptyFlow<LiveFrame>()
        override suspend fun receipt(device: String, chat: String, request: String) =
            JSONObject().put("request_id", request).put("state", "unknown").put("missing", true)
        override suspend fun command(device: String, route: String, body: JSONObject): JSONObject {
            bodies += JSONObject(body.toString())
            return JSONObject().put("request_id", body.string("request_id")).put("delivery_state", "accepted")
        }
    }

    private class KillApi(private val fail: Boolean) : TestApi() {
        val routes = mutableListOf<String>()
        override suspend fun control(device: String, chat: String, fresh: Boolean) = parseControl(JSONObject(
            """{"available":true,"running":true,"active_turn_id":"t","command":{"running":true,"since_ms":1,"can_kill":true},"capabilities_now":{"kill_command":true}}""",
        ))
        override fun events(device: String, chat: String) = emptyFlow<LiveFrame>()
        override suspend fun command(device: String, route: String, body: JSONObject): JSONObject {
            routes += route
            if (fail) throw ServiceFailure(409, detail = "钩子没被信任", notSubmitted = true)
            return JSONObject().put("ok", true).put("killed", true).put("server_ms", 40)
        }
    }
}
