package com.pocketagentdesk.nativepreview

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The rules taken over from the web in 0.7: voice placement, speed records, preview paths, list children, message cards. */
class ParityLogicTest {
    @Test fun voiceWordsGoWhereTheCursorWasAsTheWebPutsThem() {
        assertEquals("你好世界", placeDictation("你好", "世界", 2).draft)
        assertEquals("hello world", placeDictation("hello", "world", 5).draft)
        assertEquals("abc\nx", placeDictation("abc\n", "x", 4).draft)
        assertEquals("ab\none\ntwo", placeDictation("ab", "one\ntwo", 2).draft)
        // A selection is replaced; the words start after the separator.
        val replaced = placeDictation("abcdef", "X", 2, 4)
        assertEquals("ab Xef", replaced.draft)
        assertEquals(3, replaced.at)
        assertEquals("X", placeDictation("", "X", 9).draft)
    }

    @Test fun wavHeaderIs16kMono() {
        val wav = wavBytes(ShortArray(8) { it.toShort() })
        assertEquals(44 + 16, wav.size)
        assertEquals("RIFF", String(wav, 0, 4))
        assertEquals("WAVE", String(wav, 8, 4))
        assertEquals(16000, java.nio.ByteBuffer.wrap(wav, 24, 4).order(java.nio.ByteOrder.LITTLE_ENDIAN).int)
        assertEquals(2, pcmBytes(ShortArray(1) { 0x0102 }).size)
        assertEquals(0x02.toByte(), pcmBytes(ShortArray(1) { 0x0102 })[0])
    }

    @Test fun speedRecordsSayWhatTheWebSays() {
        assertEquals("服务端未成功", speedOutcome(JSONObject().put("ok", false)))
        assertEquals("服务端未成功", speedOutcome(JSONObject().put("accepted", false)))
        assertEquals("服务端未成功", speedOutcome(JSONObject().put("error", "不行")))
        assertEquals("送达未确认", speedOutcome(JSONObject().put("state", "unconfirmed")))
        assertEquals("请求完成", speedOutcome(JSONObject().put("ok", true)))
        assertEquals("消息提交：0.412 秒 · 1.20 MB · 请求完成（切过后台）", speedText(SpeedRecord(1, "12:00:00", "消息提交", 412, 1_200_000, "请求完成", true, true)))
        assertEquals("消息提交", Diagnostics.Labels["/api/codex/send"])
        assertEquals(null, Diagnostics.Labels["/api/chat"])
    }

    @Test fun diagnosticsKeepTenAndForgetWhenTurnedOff() {
        Diagnostics.setForTest(true)
        repeat(12) { Diagnostics.finish(Diagnostics.start("消息提交"), 0, "请求完成") }
        assertEquals(10, Diagnostics.records.value.size)
        val late = Diagnostics.start("消息提交")
        Diagnostics.clear()
        Diagnostics.finish(late, 0, "请求完成")
        assertTrue("a request from before 清空记录 is not recorded", Diagnostics.records.value.isEmpty())
        Diagnostics.setForTest(false)
        assertEquals(null, Diagnostics.start("消息提交"))
    }

    @Test fun previewResourcesAreExactListedPathsBesideThePage() {
        assertTrue(relativeResource("images/logo.png"))
        assertTrue(relativeResource("../logo.png"))
        assertFalse(relativeResource("/etc/passwd"))
        assertFalse(relativeResource("C:/x.png"))
        assertFalse(relativeResource("https://example.invalid/a.png"))
        assertFalse(relativeResource("a.png?x=1"))
        assertEquals("d:/fixture/images/logo.png", normalizePath("D:\\fixture\\images\\Logo.PNG".replace("Logo.PNG", "logo.png")))
        assertEquals("d:/fixture/logo.png", normalizePath("D:/fixture/report/../logo.png"))
        assertEquals("d:/a/b", normalizePath("D://a/./b/"))
    }

    @Test fun listRowsCarryTheirChildren() {
        val row = parseChat(JSONObject("""{"app":"deepseek","id":"p","title":"父对话","status":"idle","child_count":3,"child_running":1,
            "children":[{"app":"deepseek","id":"sa-1","title":"检查日志","status":"running","kind":"subagent","parent":"p"}]}"""))
        assertEquals(3, row.childCount)
        assertEquals(1, row.childRunning)
        assertEquals("subagent", row.children.single().kind)
        assertEquals("p", row.children.single().parent)
        val group = parseChat(JSONObject("""{"app":"deepseek","id":"ungrouped","title":"未分组的会话","group":true,"child_count":2}"""))
        assertTrue(group.group)
        assertEquals("deepseek:ungrouped", chatKey(group))
    }

    @Test fun claudeCardsKeepTheirFields() {
        val next = parseMessage(JSONObject("""{"id":"x","role":"next","text":"t","tool_id":"wrap-1","recap":"做完了","ask":"接下来？","open":true,"actions":[{"label":"继续","message":"继续"}]}"""))
        val d = JSONObject(next.details)
        assertEquals("wrap-1", d.string("tool_id"))
        assertTrue(d.optBoolean("open"))
        assertEquals("继续", d.getJSONArray("actions").getJSONObject(0).string("label"))
        val task = JSONObject(parseMessage(JSONObject("""{"id":"y","role":"task","text":"t","title":"整理","brief":"说明","offer":false}""")).details)
        assertEquals("整理", task.string("title"))
        val plan = JSONObject(parseMessage(JSONObject("""{"id":"z","role":"plan","text":"计划 1/2","items":[{"text":"a","status":"completed"},{"text":"b","status":"pending"}]}""")).details)
        assertEquals(2, plan.getJSONArray("items").length())
        val forwarded = JSONObject(parseMessage(JSONObject("""{"id":"u","role":"user","text":"t","origin":"other_chat"}""")).details)
        assertEquals("other_chat", forwarded.string("origin"))
    }

    @Test fun codexPlanCardOnlyEnrichesItsOwnRecord() {
        val raw = JSONObject().put("plan", JSONObject().put("id", "plan-1").put("text", "1. 读代码").put("ready", true))
        assertEquals("plan-1", codexPlanFor(raw, Message("plan-1", "assistant", "1. 读代码"))?.string("id"))
        assertEquals(null, codexPlanFor(raw, Message("other", "assistant", "别的")))
        assertEquals("plan-1", codexPlanFor(raw, Message("m", "assistant", "x", details = """{"source_id":"plan-1"}"""))?.string("id"))
        assertEquals(null, codexPlanFor(JSONObject(), Message("plan-1", "assistant", "x")))
    }

    @Test fun claudeButtonsHaveTheirOwnIdentity() {
        assertEquals("claude/next:wrap-1", actionIdentity("claude/next", JSONObject().put("tool_id", "wrap-1").put("index", 0)))
        assertEquals("claude/task:整理", actionIdentity("claude/task", JSONObject().put("title", "整理").put("button", "start")))
    }
}
