package com.pocketagentdesk.teleply

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/**
 * The composer when the computer shows another conversation (10-27, as on the iPhone): the computer's reason in the
 * status line, 电脑上打开 on the model chip, Claude's chips named from what was recorded (web claude-ui.js paint), and
 * Claude's effort menu safe for named levels and for a slider without a usable step.
 */
class ComposerAwayTest {
    @Test fun claudeChipsUseTheRecordedNamesWhenTheDesktopShowsNone() {
        // What the computer answers for a Claude conversation it is not showing (claude_control, 10-27).
        val recorded=JSONObject("""{"available":false,"on_screen":false,"recorded_label":"Opus 5.5","model_label":null,"effort_label":null,"mode_label":null,"settings":{"model":"claude-opus-5-5","effort":"xhigh","mode":"default"}}""")
        assertEquals(Triple("Opus 5.5 · 极高","Manual",false),chipLabels("claude",recorded,JSONObject()))
        val shown=JSONObject("""{"available":true,"model_label":"Opus 5.5","effort_label":"High","mode_label":"Plan","settings":{"model":"claude-opus-5-5"}}""")
        assertEquals(Triple("Opus 5.5 · High","计划模式",true),chipLabels("claude",shown,JSONObject()))
        // Nothing kept for the model: its id, as the web shows it; the recorded mode by the desktop's word.
        assertEquals(Triple("claude-opus-5-5 · 高","Auto",false),chipLabels("claude",JSONObject("""{"settings":{"model":"claude-opus-5-5","effort":"high","mode":"auto"}}"""),JSONObject()))
        assertEquals(Triple("x · 默认","计划模式",true),chipLabels("claude",JSONObject("""{"settings":{"model":"x","mode":"plan"}}"""),JSONObject()))
        assertEquals(Triple("模型","普通执行",false),chipLabels("claude",JSONObject(),JSONObject()))
    }
    @Test fun theModelChipOpensTheConversationOnlyWhenItIsAway() {
        val codexAway=JSONObject("""{"available":false,"reason":"电脑端尚未打开这个对话，请从右上角菜单选择「电脑上打开」后重试","settings":null}""")
        assertTrue(chipAway("codex",codexAway))
        assertEquals("电脑端尚未打开这个对话，请从右上角菜单选择「电脑上打开」后重试",awayReason("codex",codexAway))
        // Settings null: the chips fall back, the null is not taken for settings (the iPhone's trap, 10-27).
        assertEquals(Triple("模型","普通执行",false),chipLabels("codex",codexAway,JSONObject()))
        assertFalse(chipAway("codex",JSONObject("""{"available":true}""")));assertNull(awayReason("codex",JSONObject("""{"available":true}""")))
        // Not read yet: nothing to say.
        assertFalse(chipAway("codex",JSONObject()));assertNull(awayReason("codex",JSONObject()))
        assertEquals("电脑上没有打开这个对话；点「电脑上打开」后再发",awayReason("codex",JSONObject("""{"available":false}""")))
        // Claude with a recorded model keeps its menus and sends; with nothing recorded the chip opens it on the computer.
        val reason="电脑上显示的不是此 Claude 会话；请点击「电脑上打开」"
        val claudeRecorded=JSONObject().put("available",false).put("reason",reason).put("settings",JSONObject().put("model","claude-opus-5-5"))
        assertFalse(chipAway("claude",claudeRecorded));assertNull(awayReason("claude",claudeRecorded))
        val claudeBlank=JSONObject().put("available",false).put("reason",reason).put("settings",JSONObject.NULL)
        assertTrue(chipAway("claude",claudeBlank));assertEquals(reason,awayReason("claude",claudeBlank))
        assertFalse(chipAway("deepseek",JSONObject("""{"available":false}""")));assertNull(awayReason("deepseek",JSONObject("""{"available":false}""")))
        assertTrue(sendsWhileAway("claude"));assertFalse(sendsWhileAway("codex"));assertFalse(sendsWhileAway("deepseek"))
    }
    /** A null (or anything not an object) in a list the computer sent is left out, not taken for an entry or failing the read. */
    @Test fun listEntriesThatAreNotObjectsAreLeftOut() {
        val raw=JSONObject("""{"questions":[null,{"id":"q","status":"pending","questions":[null,{"question":"选哪个？"},"x"]},3]}""")
        assertEquals(listOf("q"),raw.rows("questions") { it.string("id") })
        assertEquals(listOf("选哪个？"),pendingCards("codex",raw).map { it.summary })
        assertTrue(JSONObject("""{"questions":null}""").rows("questions") { it }.isEmpty())
    }
    /** The iPhone quit on Claude's model menu (0.5.0, 10-27): named levels taken for a slider with a step of 0. */
    @Test fun claudeEffortsListNamedLevelsAndOnlyAUsableSlider() {
        fun rows(text:String)=JSONArray(text).let { a -> (0 until a.length()).map { a.getJSONObject(it) } }
        // The desktop's six named levels as read on 10-27, none selected (a list borrowed from another conversation).
        val named=claudeEfforts(rows("""[{"name":"Low"},{"name":"Medium Recommended"},{"name":"High"},{"name":"Extra"},{"name":"Max 3.5× or more usage"},{"name":"Ultracode"}]"""))
        assertEquals(listOf("Low","Medium Recommended","High","Extra","Max 3.5× or more usage","Ultracode"),named.steps.map { it.first })
        // Shown in the model chip's words (10-27: the desktop's names were cut to "Med", "Hig"); picked by the desktop's.
        assertEquals(listOf("低","中","高","极高","最高","Ultracode"),named.steps.map { it.second })
        assertNull(named.selected);assertNull(named.slider)
        assertEquals("High",claudeEfforts(rows("""[{"name":"Low","selected":false},{"name":"High","selected":true},{"name":null}]""")).selected)
        assertEquals(listOf("低","高"),claudeEfforts(rows("""[{"name":"Low"},{"name":"High"},{"name":null},{}]""")).steps.map { it.second })
        assertEquals(listOf("高","中","Turbo"),listOf(" High ","中","Turbo mode").map(::claudeEffortLabel))
        // One slider (claude_control: Effort, SliderControl): its steps by the names learnt, else the current one's label, else 第 N 档.
        val slider=claudeEfforts(rows("""[{"name":"Effort","type":"SliderControl","selected":true,"range":{"min":0,"max":4,"step":1,"value":2,"label":"High","labels":{"0":"Low"}}}]"""))
        assertEquals(listOf("0.0" to "低","1.0" to "第 2 档","2.0" to "高","3.0" to "第 4 档","4.0" to "第 5 档"),slider.steps)
        assertEquals("2.0",slider.selected);assertEquals("Effort",slider.slider?.string("name"))
        // A step of 0, below 0, missing or not a number, or no top: no steps, and the slider is not taken for a named level.
        for(range in listOf("""{"min":0,"max":5,"step":0}""","""{"min":0,"max":5,"step":-1}""","""{"min":0,"max":5}""","""{"min":null,"max":5,"step":"x"}""","""{"min":0,"step":1}""")) {
            val none=claudeEfforts(rows("""[{"name":"Effort","range":$range}]"""))
            assertTrue(range,none.steps.isEmpty());assertNotNull(range,none.slider)
        }
        // A borrowed slider has no current step; at most 20 steps are listed.
        val borrowed=claudeEfforts(rows("""[{"name":"Effort","range":{"min":0,"max":100,"step":1,"value":null}}]"""))
        assertNull(borrowed.selected);assertEquals(20,borrowed.steps.size)
        assertTrue(claudeEfforts(emptyList()).steps.isEmpty())
    }
}
