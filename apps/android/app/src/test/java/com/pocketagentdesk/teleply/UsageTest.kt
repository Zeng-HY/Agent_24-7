package com.pocketagentdesk.teleply

import java.time.LocalDateTime
import java.time.ZoneId
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 用量 (11-17): the words the phone shows for what the computer read (usage_limits.py). Pure functions only: no
 * screen, no network, and the clock is always the test's own.
 */
class UsageTest {
    private val zone = ZoneId.of("Asia/Shanghai")

    /** 10:22 on 11-17 (Beijing), the moment the hand-off's example read the computer at. */
    private fun moment(month: Int, day: Int, hour: Int, minute: Int, second: Int = 0): Long =
        LocalDateTime.of(2026, month, day, hour, minute, second).atZone(zone).toInstant().toEpochMilli()

    private val now = moment(11, 17, 10, 22)

    private fun weekly(resetsAt: Long?, used: Int = 84) =
        UsageWindow(kind = "weekly", name = "每周", usedPercent = used, resetsAt = resetsAt)

    private fun seconds(month: Int, day: Int, hour: Int, minute: Int): Long =
        LocalDateTime.of(2026, month, day, hour, minute).atZone(zone).toEpochSecond()

    // -- what the computer sent

    @Test fun theWholeAnswerIsRead() {
        val usage = parseUsage(JSONObject("""
            {"codex":{"available":true,"source":"live","as_of":1794882122354,"plan":"pro",
              "windows":[{"kind":"weekly","minutes":10080,"used_percent":84,"resets_at":1795006481,"name":"每周"}],
              "reached":null,
              "resets":{"available":1,"items":[{"id":"credit-available","title":"Full reset",
                "description":"Thanks for using Codex!","granted_at":1794000000,"expires_at":1797000000}]},
              "ordinary_usage_allowed":true},
             "claude":{"available":true,"source":"window","as_of":1794882122354,
              "text":"Usage: 35% of 5-hour limit, Resets at 12:20 PM",
              "windows":[{"kind":"5h","label":"5-hour limit","name":"5 小时","used_percent":35,"resets_at":null,
                "resets_text":"12:20"}],"minimized":false},
             "now":1794882122354}
        """.trimIndent()))
        assertEquals(84, usage.codex.windows.single().usedPercent)
        assertEquals("每周", usage.codex.windows.single().name)
        assertEquals(1795006481L, usage.codex.windows.single().resetsAt)
        assertEquals("live", usage.codex.source)
        assertNull(usage.codex.reached)
        assertTrue(usage.codex.resets)
        assertEquals(1, usage.codex.resetsAvailable)
        assertEquals("Full reset", usage.codex.credits?.single()?.title)
        assertEquals(1797000000L, usage.codex.credits?.single()?.expiresAt)
        assertEquals(35, usage.claude.windows.single().usedPercent)
        assertEquals("12:20", usage.claude.windows.single().resetsText)
        assertFalse(usage.claude.minimized)
        assertEquals(1794882122354L, usage.now)
    }

    @Test fun theRecordsCarryNoResetCreditsAndSayWhyTheyAreOld() {
        val usage = parseUsage(JSONObject("""
            {"codex":{"available":true,"source":"records","as_of":1794882122354,"plan":"pro",
              "windows":[{"kind":"weekly","minutes":10080,"used_percent":84,"resets_at":1795006481,"name":"每周"}],
              "reached":null,"resets":null,"ordinary_usage_allowed":null,
              "live_error":"读不到 Codex 的实时用量：没找到这台电脑上的 Codex"},
             "claude":{"available":false,"reason":"这台电脑没装 Claude"},"now":1794882122354}
        """.trimIndent()))
        assertFalse(usage.codex.resets)
        assertNull(usage.codex.resetsAvailable)
        assertNull(usage.codex.credits)
        assertEquals("读不到 Codex 的实时用量：没找到这台电脑上的 Codex", usage.codex.liveError)
        assertEquals("records", usage.codex.source)
    }

    @Test fun aComputerWithoutCodexSaysSo() {
        val usage = parseUsage(JSONObject("""{"codex":{"available":false,"reason":"这台电脑没装 Codex"},"claude":{"available":false,"reason":"这台电脑没装 Claude"},"now":0}"""))
        assertFalse(usage.codex.available)
        assertEquals("这台电脑没装 Codex", usage.codex.reason)
        assertFalse(usage.claude.available)
        assertTrue(usage.codex.windows.isEmpty())
    }

    @Test fun claudeWordsThePhoneCannotReadAreShownWhole() {
        val usage = parseUsage(JSONObject("""{"codex":{"available":false},"claude":{"available":true,"text":"Plan usage unavailable","windows":[],"minimized":true},"now":0}"""))
        assertTrue(usage.claude.windows.isEmpty())
        assertEquals("Plan usage unavailable", usage.claude.text)
        assertTrue(usage.claude.minimized)
    }

    // -- when it resets

    @Test fun todayTomorrowAnotherDayOrAlreadyGone() {
        assertEquals("今天 20:54 重置（还有 10 小时 32 分）", resetLine(weekly(seconds(11, 17, 20, 54)), "live", now, zone))
        assertEquals("明天 20:54 重置（还有 1 天 10 小时）", resetLine(weekly(seconds(11, 18, 20, 54)), "live", now, zone))
        assertEquals("11月21日 15:00 重置（还有 4 天 4 小时）", resetLine(weekly(seconds(11, 21, 15, 0)), "live", now, zone))
        assertEquals("已过重置时间", resetLine(weekly(seconds(11, 17, 9, 0)), "live", now, zone))
        assertEquals("已过重置时间，等电脑上 Codex 下一次回话就会更新",
            resetLine(weekly(seconds(11, 17, 9, 0)), "records", now, zone))
    }

    @Test fun theTimeLeftIsSaidInTheLongestUnitThatFits() {
        assertEquals("今天 13:34 重置（还有 3 小时 12 分）", resetLine(weekly(seconds(11, 17, 13, 34)), "live", now, zone))
        assertEquals("今天 10:47 重置（还有 25 分钟）", resetLine(weekly(seconds(11, 17, 10, 47)), "live", now, zone))
        assertEquals("今天 10:23 重置（马上）", resetLine(weekly(seconds(11, 17, 10, 23)), "live", moment(11, 17, 10, 22, 30), zone))
        assertEquals("", resetLine(weekly(null), "live", now, zone))
    }

    @Test fun whereTheNumbersCameFrom() {
        assertEquals("刚从 Codex 读到", sourceLine("live", now - 30_000, now, zone))
        assertEquals("5 分钟前从 Codex 读到", sourceLine("live", now - 5 * 60_000, now, zone))
        assertEquals("来自电脑上 Codex 最近一次回话（10:22）。之后在别处用掉的，这里还没算上。",
            sourceLine("records", now, now, zone))
        assertEquals("", sourceLine("", now, now, zone))
    }

    // -- the confirmation

    @Test fun theConfirmationSaysWhatItUsesAndWarnsWhileThereIsRoom() {
        val credit = ResetCredit(id = "credit-available", title = "Full reset", expiresAt = seconds(12, 13, 6, 48))
        assertEquals("""会马上恢复 Codex 的用量限额。用掉就没了，不能撤回。
这次用：Full reset，12月13日 到期
现在每周还剩 16%，还没用完，现在用可能浪费。""",
            confirmText(credit, listOf(weekly(null)), zone))
    }

    @Test fun aLimitNearlyGoneGetsNoWarning() {
        val credit = ResetCredit(id = "c", title = "Full reset", expiresAt = null)
        assertEquals("""会马上恢复 Codex 的用量限额。用掉就没了，不能撤回。
这次用：Full reset，不会过期""", confirmText(credit, listOf(weekly(null, used = 95)), zone))
    }

    @Test fun withoutOneCreditPickedOnlyTheFirstLineAndTheWarning() {
        assertEquals("""会马上恢复 Codex 的用量限额。用掉就没了，不能撤回。
现在每周还剩 16%，还没用完，现在用可能浪费。""", confirmText(null, listOf(weekly(null)), zone))
        assertEquals("会马上恢复 Codex 的用量限额。用掉就没了，不能撤回。", confirmText(null, emptyList(), zone))
    }

    @Test fun aCreditWithoutATitleIsCalledAUsageReset() {
        assertTrue(confirmText(ResetCredit(id = "c", title = "", expiresAt = null), emptyList(), zone)
            .contains("这次用：用量重置，不会过期"))
    }

    // -- the request id that keeps a retry from using a second credit

    @Test fun theRequestIdStaysUntilAFinalAnswer() {
        var made = 0
        val attempt = ResetAttempt { "id-${++made}" }
        assertEquals("id-1", attempt.id())
        assertEquals("id-1", attempt.id())
        assertTrue(attempt.keepsId(ServiceFailure(409, "reset_unconfirmed")))
        assertTrue(attempt.keepsId(java.io.IOException("网络断了")))
        assertTrue(attempt.keepsId(java.util.concurrent.TimeoutException()))
        assertFalse(attempt.keepsId(ServiceFailure(409, "codex_refused")))
        assertFalse(attempt.keepsId(ServiceFailure(400, "not_confirmed")))
        attempt.done()
        assertEquals("id-2", attempt.id())
    }

    /** 11-17 review: only the answers that say for certain nothing was used may drop the request id. */
    @Test fun onlyTheCodesThatSayNothingWasUsedDropTheId() {
        val attempt = ResetAttempt { "id" }
        // A 500 or a relay hiccup may hide a reset that did go through: the same id has to be sent again.
        assertTrue(attempt.keepsId(ServiceFailure(500)))
        assertTrue(attempt.keepsId(ServiceFailure(500, detail = "电脑端出错，没确认这次用成了没有，请到电脑上的 Codex 里看用量")))
        assertTrue(attempt.keepsId(ServiceFailure(502)))
        assertTrue(attempt.keepsId(ServiceFailure(504)))
        assertTrue(attempt.keepsId(ServiceFailure(409, "device_offline")))
        assertTrue(attempt.keepsId(ServiceFailure(409, "reset_unconfirmed")))
        assertTrue(attempt.keepsId(java.io.IOException("网络断了")))
        // These say for certain nothing was used.
        for (code in listOf("not_confirmed", "bad_request", "codex_unreachable", "codex_refused", "no_codex")) {
            assertFalse(code, attempt.keepsId(ServiceFailure(409, code)))
        }
    }

    @Test fun protocolTwoAgentsUsageParsesTestingAndUnknownAgents() {
        val resetMs = moment(11, 17, 13, 34)
        val usage = parseUsage(JSONObject("""
            {"codex":{"available":true,"source":"live","as_of":$now,"windows":[]},
             "claude":{"available":false,"reason":"未安装"},
             "agents":{
               "codex":{"available":true,"source":"live","as_of":$now,"windows":[]},
               "testing":{"available":true,"source":"testing","as_of":$now,
                 "windows":[{"label":"测试额度","used_percent":10,"resets_at":$resetMs}]},
               "mystery_bot":{"available":true,"source":"api","as_of":$now,
                 "windows":[{"name":"每日","used_percent":42,"resets_at":null,"resets_text":"明天 00:00"}]}
             },
             "now":$now}
        """.trimIndent()))
        assertEquals(setOf("codex", "testing", "mystery_bot"), usage.agents.keys)
        val testWin = usage.agents.getValue("testing").windows.single()
        assertEquals("测试额度", testWin.name)
        assertEquals(10, testWin.usedPercent)
        assertEquals("今天 13:34 重置（还有 3 小时 12 分）", resetLine(testWin, "testing", now, zone))
        val mysteryWin = usage.agents.getValue("mystery_bot").windows.single()
        assertEquals("每日", mysteryWin.name)
        assertEquals(42, mysteryWin.usedPercent)
        assertEquals("明天 00:00", mysteryWin.resetsText)
        // Legacy payload without "agents" still parses cleanly.
        val legacy = parseUsage(JSONObject("""{"codex":{"available":false},"claude":{"available":false},"now":$now}"""))
        assertTrue(legacy.agents.isEmpty())
    }
}
