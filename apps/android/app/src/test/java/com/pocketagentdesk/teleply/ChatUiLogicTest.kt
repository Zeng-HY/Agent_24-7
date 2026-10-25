package com.pocketagentdesk.teleply

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/** Pure logic behind the conversation page: ask bar, chip labels, list times and labels (spec 4.1, 4.3). */
class ChatUiLogicTest {
    @Test fun askBarFollowsEachSource() {
        val codex=pendingCards("codex",JSONObject("""{"questions":[{"status":"pending","questions":[{"question":"选哪个？"}]},{"status":"answered","questions":[{"question":"旧问题"}]}]}"""))
        assertEquals(listOf("选哪个？"),codex.map { it.summary })
        val claude=pendingCards("claude",JSONObject("""{"prompt":{"title":"格式？","progress":"1/2","choices":[]}}"""))
        assertEquals("1/2",claude.single().progress)
        val deepseek=pendingCards("deepseek",JSONObject("""{"interactions":[{"event":"approval/request","eventId":"e","request":{"toolName":"shell"}},{"event":"user-questions/request","request":{"callId":"c","questions":[{"question":"补充？"}]}}]}"""))
        assertEquals(2,deepseek.single().count);assertTrue(deepseek.single().summary.contains("shell"))
        assertTrue(pendingCards("deepseek",JSONObject("""{"interactions":[]}""")).isEmpty())
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
    @Test fun runtimeCountsReadInWan() {
        // 会话状态 (spec 0.4 §4.3): from ten thousand on, 万 with one decimal, no trailing .0.
        assertEquals("9999",wan(9_999));assertEquals("16.9万",wan(169_421));assertEquals("82.8万",wan(828_400));assertEquals("20万",wan(200_000))
        assertEquals("中",effortName("medium"));assertEquals("custom",effortName("custom"))
    }
}
