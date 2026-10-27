package com.pocketagentdesk.teleply

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/** Pure logic behind the conversation page: ask bar, chip labels, list times and labels (spec 4.1, 4.3). */
class ChatUiLogicTest {
    @Test fun askBarFollowsEachSource() {
        val codex=pendingCards("codex",JSONObject("""{"questions":[{"status":"pending","questions":[{"question":"选哪个？"}]},{"status":"answered","questions":[{"question":"旧问题"}]}]}"""))
        assertEquals(listOf("选哪个？"),codex.map { it.summary })
        val claude=pendingCards("claude",JSONObject("""{"prompt":{"title":"格式？","progress":"1/2","choices":[{"label":"要点"}]}}"""))
        assertEquals("1/2",claude.single().progress)
        val deepseek=pendingCards("deepseek",JSONObject("""{"interactions":[{"event":"approval/request","eventId":"e","request":{"toolName":"shell"}},{"event":"user-questions/request","request":{"callId":"c","questions":[{"question":"补充？"}]}}]}"""))
        assertEquals(2,deepseek.single().count);assertTrue(deepseek.single().summary.contains("shell"))
        assertTrue(pendingCards("deepseek",JSONObject("""{"interactions":[]}""")).isEmpty())
    }
    /**
     * Claude's plan options are its question's own buttons, so they show only without a question (web askParts; user
     * 10-27): before Windows dev.23 the computer sent both, and a second card of raw button names showed.
     */
    @Test fun claudeHasItsQuestionOrElseItsPlanOptions() {
        val both=JSONObject("""{"prompt":{"title":"格式？","progress":"1/2","choices":[{"label":"要点","pressed":true}]},"actions":[{"name":"要点 每条一行","token":"t"}]}""")
        assertTrue(claudeAsks(both));assertEquals(listOf(PendingCard("choice","格式？","1/2")),pendingCards("claude",both))
        val bare=JSONObject("""{"prompt":{},"actions":[{"label":"执行","token":"t"}]}""")
        assertFalse(claudeAsks(bare));assertEquals(listOf(PendingCard("actions","计划与执行选项")),pendingCards("claude",bare))
        assertEquals(listOf("choice"),pendingCards("claude",JSONObject("""{"prompt":{"nav":[{"name":"Submit","label":"提交"}]}}""")).map { it.kind })
        assertTrue(pendingCards("claude",JSONObject()).isEmpty())
        assertTrue(pendingCards("claude",JSONObject("""{"prompt":null,"actions":[]}""")).isEmpty())
    }
    /**
     * Windows dev.24 writes "✓ " before a ticked option of a question that takes several, for apps that do not show
     * `pressed`; shown chosen here, it goes. The PC's Other is a part of its own or null, never true (iPhone 0.5.2).
     */
    @Test fun aTickedClaudeOptionIsMarkedOnceAndOtherIsAPart() {
        assertEquals("要点",claudeChoiceLabel(JSONObject("""{"label":"✓ 要点","pressed":true}""")))
        assertEquals("✓ 完成",claudeChoiceLabel(JSONObject("""{"label":"✓ 完成","pressed":false}""")))
        assertEquals("段落",claudeChoiceLabel(JSONObject("""{"label":"段落","pressed":null}""")))
        assertTrue(claudeTakesOther(JSONObject("""{"other":{"name":"Other","token":"t"}}""")))
        assertTrue(claudeTakesOther(JSONObject("""{"other":true}""")))
        assertFalse(claudeTakesOther(JSONObject("""{"other":null}""")))
        assertFalse(claudeTakesOther(JSONObject()))
    }
    @Test fun chipsShowNextMessageSettingsForCodex() {
        val raw=JSONObject("""{"settings":{"model":"m1","effort":"medium","mode":"default"},"catalog":{"models":[{"id":"m1","name":"模型一"},{"id":"m2","name":"模型二"}]}}""")
        assertEquals(Triple("模型一 · 中","普通执行",false),chipLabels("codex",raw,JSONObject()))
        val saved=JSONObject().put("settings",JSONObject().put("model","m2").put("effort","high").put("mode","plan"))
        assertEquals(Triple("模型二 · 高","计划",true),chipLabels("codex",raw,saved))
        assertEquals("工作区内修改",chipLabels("deepseek",JSONObject("""{"settings":{"model":"v4"},"permission_name":"工作区内修改"}"""),JSONObject()).second)
    }
    @Test fun listTimesAndLabelsMatchTheWeb() {
        val now=1_792_843_200_000L
        assertEquals("刚刚",agoLabel(now-30_000,now));assertEquals("5 分钟前",agoLabel(now-300_000,now));assertEquals("",agoLabel(0,now))
        assertEquals("● 运行中",statusLabel("running"));assertEquals("等待你处理",statusLabel("waiting"));assertEquals("状态不明",statusLabel(""))
    }
    /**
     * 10-27: what each row needs from the rows around it, worked out once per page (each row used to walk the page on
     * every redraw): runs of steps share one fold whose first step has the header, and only the run after your latest
     * message, with nothing but steps and events after it, is the one at work.
     */
    @Test fun timelineRowsKnowTheirRunOfStepsOnce() {
        val messages=listOf(
            Message("u1","user","先读代码"),
            Message("s1","tool","读取"),Message("s2","assistant","想一想",phase="commentary"),
            Message("a1","assistant","读完了"),
            Message("u2","user","再改"),
            Message("s3","tool","修改"),Message("e1","event","已停止"),Message("s4","assistant","接着想",phase="thinking"),
        )
        val rows=timelineRows(messages)
        assertEquals(messages.size,rows.size)
        assertEquals(TimelineRow("user","s1",true,2,false),rows[1]);assertEquals(TimelineRow("tool","s1",false,2,false),rows[2])
        assertEquals("assistant",rows[3].previousRole);assertEquals("",rows[0].previousRole)
        // After the latest message of yours: s3 alone (an event ends a run), then s4, the last thing on the page.
        assertEquals(TimelineRow("user","s3",true,1,true),rows[5]);assertEquals(TimelineRow("event","s4",true,1,true),rows[7])
        // An answer after the steps: they are done.
        assertFalse(timelineRows(messages+Message("a2","assistant","改好了"))[7].lastGroup)
        assertTrue(timelineRows(emptyList()).isEmpty())
    }
    /** 10-27: the parsed Markdown is kept for whole pages, bounded by characters, the least recently used going first. */
    @Test fun markdownCacheHoldsAWholePageAndLetsTheOldestGo() {
        val cache=MarkdownCache()
        val page=(1..60).map { i -> "## 消息 $i\n"+"字".repeat(5_990) }
        val parsed=page.map(cache::document)
        assertEquals(60,cache.size());page.forEachIndexed { i,source -> assertSame(parsed[i],cache.document(source)) }
        val small=MarkdownCache(10,100)
        val a=small.document("a".repeat(40));small.document("b".repeat(40));small.document("a".repeat(40))
        small.document("c".repeat(40))
        // b was the least recently used: it went, a stayed.
        assertEquals(2,small.size());assertEquals(80L,small.characters());assertSame(a,small.document("a".repeat(40)))
    }
    @Test fun runtimeCountsReadInWan() {
        // 会话状态 (spec 0.4 §4.3): from ten thousand on, 万 with one decimal, no trailing .0.
        assertEquals("9999",wan(9_999));assertEquals("16.9万",wan(169_421));assertEquals("82.8万",wan(828_400));assertEquals("20万",wan(200_000))
        assertEquals("中",effortName("medium"));assertEquals("custom",effortName("custom"))
    }
}
