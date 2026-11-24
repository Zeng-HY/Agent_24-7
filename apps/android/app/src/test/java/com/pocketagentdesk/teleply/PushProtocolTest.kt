package com.pocketagentdesk.teleply

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The relay's messages and what they become on the lock screen and in the shade (design-2 §1.3, §3.4), in pure Kotlin. */
class PushProtocolTest {
    private val now = 1_800_000_000_000L
    private val device = "a".repeat(32)
    private val other = "b".repeat(32)

    private fun conversation(seq: Long, state: String, chat: String = "chat-1", step: String? = null, turn: Long = 1_700_000_000L, deviceId: String = device) =
        """{"type":"conversation","seq":$seq,"boot":"1a2b3c4d","device":"$deviceId","label":"书房电脑","app":"codex","chat":"$chat","title":"修好发布脚本","state":"$state","since":1700000000,"turn":$turn,"ended":null${if (step != null) ",\"step\":\"$step\"" else ""}}"""

    @Test fun helloCarriesTheWholePicture() {
        val raw = """{"type":"hello","seq":7,"boot":"1a2b3c4d","computers":[{"device":"$device","label":"书房电脑","online":true},{"device":"$other","label":"客厅电脑","online":false}],"conversations":[{"device":"$device","label":"书房电脑","app":"codex","chat":"c1","title":"修好发布脚本","state":"working","since":1700000000,"turn":1700000005,"ended":null,"step":"edit"},{"device":"$other","label":"客厅电脑","app":"claude","chat":"c2","title":"整理说明","state":"waiting","since":1600000000,"turn":1600000009,"ended":null}]}"""
        val message = PushProtocol.parse(raw)!!
        val hello = message as PushMessage.Hello
        assertEquals(7L, hello.seq)
        assertEquals("1a2b3c4d", hello.boot)
        assertEquals(listOf("书房电脑", "客厅电脑"), hello.computers.map { it.label })
        assertEquals(false, hello.computers[1].online)
        assertEquals(listOf("working", "waiting"), hello.conversations.map { it.state })
        assertEquals("edit", hello.conversations[0].step)
        assertEquals(1700000005L, hello.conversations[0].turn)
        val model = PushModel().apply(message, now)
        assertEquals(2, model.computerCount())
        assertEquals(1, model.onlineCount())
        assertEquals(2, model.chats.size)
        assertEquals(7L, model.lastSeq)
    }

    @Test fun everyMessageKindIsReadAndGarbageIsSkipped() {
        val notice = PushProtocol.parse("""{"type":"notice","seq":8,"boot":"1a2b3c4d","device":"$device","app":"codex","chat":"c1","kind":"done","title":"修好发布脚本","subtitle":"Codex · 书房电脑","body":"这一轮做完了。","loud":false}""") as PushMessage.Notice
        assertEquals("修好发布脚本", notice.notice.title)
        assertEquals("Codex · 书房电脑", notice.notice.subtitle)
        assertEquals(false, notice.notice.loud)
        assertEquals("$device|codex|c1", notice.notice.key)
        assertEquals(device, notice.notice.group)
        // A missing loud is a normal (audible) notice.
        val loud = PushProtocol.parse("""{"type":"notice","seq":9,"boot":"1a2b3c4d","device":"$device","app":"codex","chat":"c1","kind":"failed","title":"失败","subtitle":"","body":"","loud":null}""") as PushMessage.Notice
        assertTrue(loud.notice.loud)

        val computer = PushProtocol.parse("""{"type":"computer","seq":10,"boot":"1a2b3c4d","device":"$other","label":"客厅电脑","online":false}""") as PushMessage.Computer
        assertEquals(false, computer.computer.online)
        val test = PushProtocol.parse("""{"type":"test","seq":11,"boot":"1a2b3c4d","title":"遥应","body":"试推一条：通知是好的"}""") as PushMessage.Test
        assertEquals("试推一条：通知是好的", test.body)
        val unknown = PushProtocol.parse("""{"type":"something-new","seq":12,"boot":"1a2b3c4d"}""") as PushMessage.Unknown
        assertEquals("something-new", unknown.type)

        assertNull(PushProtocol.parse("not json"))
        assertNull(PushProtocol.parse("""{"type":"notice","boot":"1a2b3c4d","device":"$device"}"""))
        assertNull(PushProtocol.parse("""{"type":"notice","seq":3,"device":"$device"}"""))
        assertNull(PushProtocol.parse("""{"seq":3,"boot":"1a2b3c4d"}"""))
        assertNull(PushProtocol.parse("""{"type":"hello","seq":-2,"boot":"1a2b3c4d"}"""))
    }

    @Test fun aConversationChangesAndGoneLeavesNoCard() {
        var model = PushModel().apply(PushProtocol.parse(conversation(1, "working"))!!, now)
        assertEquals(1, model.liveCards(now).cards.size)
        model = model.apply(PushProtocol.parse(conversation(2, "waiting"))!!, now)
        assertEquals("在等你", model.liveCards(now).cards.single().body)
        // The relay's snapshot found it ended: no card, no leftover row.
        model = model.apply(PushProtocol.parse(conversation(3, "gone"))!!, now)
        assertTrue(model.chats.isEmpty())
        assertTrue(model.liveCards(now).cards.isEmpty())
        assertEquals(3L, model.lastSeq)
    }

    @Test fun aNewRelayBootStartsFromItsOwnSeq() {
        val first = PushModel().apply(PushProtocol.parse(conversation(500, "working"))!!, now)
        assertEquals(500L, first.lastSeq)
        val newBoot = PushProtocol.parse("""{"type":"hello","seq":1,"boot":"9f8e7d6c","computers":[],"conversations":[]}""")!!
        val second = first.apply(newBoot, now)
        assertEquals("9f8e7d6c", second.boot)
        assertEquals(1L, second.lastSeq)
    }

    @Test fun theStepReadsAsOneOfTheDesignsFourWords() {
        assertEquals("编辑文件", pushStepText("edit"))
        assertEquals("跑命令", pushStepText("shell"))
        assertEquals("搜索", pushStepText("search"))
        assertEquals("读文件", pushStepText("read"))
        assertEquals("编辑文件", pushStepText(" EDITING "))
        assertEquals("整理笔记", pushStepText("整理笔记"))
        assertNull(pushStepText(null))
        assertNull(pushStepText("  "))
        val chat = PushChat(device, "书房电脑", "claude", "c1", "整理说明", "working", step = "shell")
        assertEquals("在干活 · 跑命令", pushLiveBody(chat))
        assertEquals("Claude · 书房电脑", listOf(pushAppLabel(chat.app), chat.label).joinToString(" · "))
        assertEquals("Codex", pushAppLabel("codex"))
        assertEquals("DeepSeek", pushAppLabel("deepseek"))
        assertEquals("Testing", pushAppLabel("testing"))
    }

    @Test fun cardsAreTheNewestThreeAndTheRestIsCounted() {
        var model = PushModel()
        val chats = (1..5).map { i ->
            """{"type":"conversation","seq":$i,"boot":"1a2b3c4d","device":"$device","label":"书房电脑","app":"codex","chat":"c$i","title":"对话 $i","state":"working","since":${1700000000 + i},"turn":${1700000000 + i},"ended":null}"""
        }
        for (raw in chats) model = model.apply(PushProtocol.parse(raw)!!, now)
        val cards = model.liveCards(now)
        assertEquals(3, cards.cards.size)
        assertEquals(2, cards.overflow)
        // Newest (largest since) first, and only the newest three.
        assertEquals(listOf("对话 5", "对话 4", "对话 3"), cards.cards.map { it.title })
        assertEquals(1_700_000_005_000L, cards.cards.first().startedAt)
        assertEquals("还有 2 个在干活", pushOverflowTitle(cards.overflow))
        // Waiting counts as a card too, and a finished one does not.
        model = model.apply(PushProtocol.parse(conversation(10, "done", chat = "c1"))!!, now)
        assertEquals(3, model.liveCards(now).cards.size)
        val waiting = """{"type":"conversation","seq":11,"boot":"1a2b3c4d","device":"$device","label":"书房电脑","app":"codex","chat":"c9","title":"等你选的方案","state":"waiting","since":1800000000,"turn":1800000000,"ended":null}"""
        model = model.apply(PushProtocol.parse(waiting)!!, now)
        val after = model.liveCards(now)
        assertEquals(3, after.cards.size)
        assertEquals("等你选的方案", after.cards.first().title)
        assertEquals("在等你", after.cards.first().body)
        assertEquals(listOf("对话 5", "对话 4"), after.cards.drop(1).map { it.title })
        assertEquals(2, after.overflow)
    }

    @Test fun anOfflineComputerSaysSoAndItsCardGoesAfterThirtyMinutes() {
        val hello = PushProtocol.parse("""{"type":"hello","seq":1,"boot":"1a2b3c4d","computers":[{"device":"$device","label":"书房电脑","online":false}],"conversations":[{"device":"$device","label":"书房电脑","app":"codex","chat":"c1","title":"修好发布脚本","state":"working","since":1700000000,"turn":1700000000,"ended":null,"step":"edit"}]}""")!!
        val model = PushModel().apply(hello, now)
        assertEquals("电脑离线", model.liveCards(now).cards.single().body)
        assertTrue("still a card within the half hour", model.liveCards(now + PushOfflineCardMillis - 1).cards.isNotEmpty())
        assertTrue("gone after the half hour", model.liveCards(now + PushOfflineCardMillis).cards.isEmpty())
        // Back online: the card speaks of work again, not of the computer.
        val online = model.apply(PushProtocol.parse("""{"type":"computer","seq":2,"boot":"1a2b3c4d","device":"$device","label":"书房电脑","online":true}""")!!, now + 1)
        assertEquals("在干活 · 编辑文件", online.liveCards(now + 1).cards.single().body)
    }

    @Test fun eachOfflineComputerIsTakenAwayAtItsOwnHalfHour() {
        val hello = PushProtocol.parse("""{"type":"hello","seq":1,"boot":"1a2b3c4d","computers":[{"device":"$device","label":"书房电脑","online":true},{"device":"$other","label":"客厅电脑","online":true}],"conversations":[{"device":"$device","label":"书房电脑","app":"codex","chat":"c1","title":"一","state":"working","since":1700000000,"turn":1700000000},{"device":"$other","label":"客厅电脑","app":"claude","chat":"c2","title":"二","state":"waiting","since":1700000001,"turn":1700000001}]}""")!!
        var model = PushModel().apply(hello, now)
        model = model.apply(PushProtocol.parse("""{"type":"computer","seq":2,"boot":"1a2b3c4d","device":"$device","label":"书房电脑","online":false}""")!!, now)
        model = model.apply(PushProtocol.parse("""{"type":"computer","seq":3,"boot":"1a2b3c4d","device":"$other","label":"客厅电脑","online":false}""")!!, now + 10_000)
        assertEquals(now + PushOfflineCardMillis, model.nextOfflineExpiry(now + 1))
        assertEquals(now + PushOfflineCardMillis + 10_000, model.nextOfflineExpiry(now + PushOfflineCardMillis))
        assertNull(model.nextOfflineExpiry(now + PushOfflineCardMillis + 10_000))
        // Both cards say 电脑离线 while they last.
        assertEquals(2, model.liveCards(now + 20_000).cards.size)
        assertEquals(1, model.liveCards(now + PushOfflineCardMillis + 1).cards.size)
        assertTrue(model.liveCards(now + PushOfflineCardMillis + 10_000).cards.isEmpty())
    }

    @Test fun noticesShareADevicesGroupAndOneConversationIsOneTag() {
        val one = PushNotice(device, "codex", "c1", "done", "修好发布脚本", "Codex · 书房电脑", "做完了", true)
        val two = one.copy(chat = "c2", title = "另一个")
        assertEquals(one.key, two.copy(chat = "c1").key)
        assertEquals("$device|codex|c1", one.key)
        assertEquals(device, one.group)
        assertEquals("还有 1 个对话", pushGroupSummary(2))
        assertEquals("还有 4 个对话", pushGroupSummary(5))
        val test = pushTestNotice(PushMessage.Test(9, "1a2b3c4d", "遥应", "试推一条：通知是好的"))
        assertEquals("test", test.key)
        assertEquals("试推一条", test.subtitle)
        assertEquals("试推一条：通知是好的", test.body)
    }

    @Test fun retriesAreFiveThenTenThenTwentyThenTheLongWait() {
        assertEquals(listOf(5_000L, 10_000L, 20_000L, 40_000L, 60_000L, 120_000L, 300_000L), (0..6).map(::pushRetryMillis))
        assertEquals(300_000L, pushRetryMillis(7))
        assertEquals(300_000L, pushRetryMillis(99))
        assertEquals(5_000L, pushRetryMillis(-3))
    }

    @Test fun theTestNoticeIsAnOrdinaryNotification() {
        val notice = pushTestNotice(PushMessage.Test(1, "1a2b3c4d", "", ""))
        assertEquals("遥应", notice.title)
        assertEquals("test", notice.key)
        assertTrue(notice.loud)
        assertNotNull(PushProtocol.parse("""{"type":"test","seq":1,"boot":"1a2b3c4d"}"""))
    }

    @Test fun aNoticeWithoutADeviceStillHasOneTag() {
        val notice = PushNotice("", "", "test", "test", "遥应", "", "试推一条", true)
        assertEquals("test", notice.key)
        // JSONObject numbers survive as Longs through the model, which the since uses.
        val since = PushProtocol.parse(conversation(42, "working"))!!
        assertEquals(42L, since.seq)
        assertEquals("1a2b3c4d", JSONObject("""{"boot":"1a2b3c4d"}""").string("boot"))
    }

    /** 复核 2026-11-24: the computer sends automations as a plain string; an object and a missing key are handled too. */
    @Test fun automationAnswerIsAStringOrAnObjectAndAMissingKeyHidesTheGroup() {
        assertEquals("failed", pushAutomationMode(JSONObject("""{"automations":"failed"}""")))
        assertEquals("codex", pushAutomationMode(JSONObject("""{"automations":" codex "}""")))
        assertEquals("codex", pushAutomationMode(JSONObject().put("automations", JSONObject().put("mode", "codex"))))
        assertEquals("off", pushAutomationMode(JSONObject("""{"automations":{"mode":"off"}}""")))
        assertNull("no automations key: an older computer", pushAutomationMode(JSONObject("""{"configured":false}""")))
        assertNull(pushAutomationMode(null))
        assertNull(pushAutomationMode(JSONObject().put("automations", JSONObject.NULL)))
        assertNull(pushAutomationMode(JSONObject().put("automations", 3)))
        assertNull(pushAutomationMode(JSONObject("""{"automations":""}""")))
        assertEquals(listOf("跟 Codex 一样", "只推失败的", "不推"), PushAutomationChoices.map { it.second })
        assertEquals(listOf("codex", "failed", "off"), PushAutomationChoices.map { it.first })
        assertEquals("跟 Codex 一样：Codex 在电脑上提醒的才推；任务在 Codex 里设了『只在失败时通知』的，成功不推。", pushAutomationExplanation())
    }

    /** 复核 2026-11-24: the group summary counts what is still in the shade, not what this process remembers. */
    @Test fun groupSummaryCountsOnlyTheLiveConversationNoticesOfOneComputer() {
        val shown = listOf(
            PushShownNotification(device, "c1"),
            PushShownNotification(device, "c2"),
            PushShownNotification(device, pushGroupSummaryTag(device)),
            PushShownNotification(other, "c3"),
            PushShownNotification(null, "overflow"),
            PushShownNotification(null, "test"),
        )
        assertEquals(2, pushGroupNoticeCount(shown, device))
        assertEquals(1, pushGroupNoticeCount(shown, other))
        assertEquals(0, pushGroupNoticeCount(shown, ""))
        assertEquals(0, pushGroupNoticeCount(shown.filter { it.tag == pushGroupSummaryTag(device) }, device))
        assertEquals("summary:$device", pushGroupSummaryTag(device))
        assertEquals("还有 1 个对话", pushGroupSummary(2))
    }
}
