package com.pocketagentdesk.teleply

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/**
 * 此刻能力（第二批 A1/A2）：说明书的 capabilities 加上最近一次控制态的 capabilities_now。
 * 老电脑没有 capabilities_now 时和改前完全一样；有就逐键收窄，没写的键等于说明书，列表取交集。
 */
class AgentCapsTest {
    private val codex = AgentCapabilities(
        list = true, read = true, search = true, open = true, stop = true, queue = true, steer = true,
        approve = true, answer = true, new = true, newProjectless = true, newPermission = false,
        archive = true, restore = true, delete = true, usage = true, waiting = true,
        attachments = true, slashCommands = true, skills = true,
        settings = listOf("model", "effort", "mode"), sendModes = listOf("send", "steer", "queue"),
        statuses = listOf("running", "waiting", "idle", "unknown"),
    )

    @Test fun withoutCapabilitiesNowTheManifestIsUnchanged() {
        val old = JSONObject("""{"available":true,"running":true,"settings":{"model":"x"}}""")
        assertEquals(codex, capsNow(codex, old))
        assertEquals(codex, capsNow(codex, null))
        assertFalse(hasCapsNow(old))
        assertTrue(hasCapsNow(JSONObject("""{"capabilities_now":{}}""")))
        assertEquals("", capsNote(old, "approve"))
    }

    @Test fun aKeyLeftOutEqualsTheManifest() {
        val caps = capsNow(codex, JSONObject("""{"capabilities_now":{"stop":false}}"""))
        assertFalse(caps.stop)
        assertTrue(caps.approve)                      // 没写 = 说明书
        assertEquals(codex.sendModes, caps.sendModes)
        assertEquals(codex.settings, caps.settings)
        assertEquals(codex.statuses, caps.statuses)
    }

    @Test fun aFalseCapabilityCannotBecomeTrue() {
        val caps = capsNow(AgentCapabilities(approve = false, answer = true), JSONObject("""{"capabilities_now":{"approve":true,"answer":false}}"""))
        assertFalse(caps.approve)
        assertFalse(caps.answer)
    }

    @Test fun listsOnlyNarrow() {
        val caps = capsNow(codex, JSONObject("""{"capabilities_now":{"settings":["model"],"send_modes":[],"statuses":["idle","running"]}}"""))
        assertEquals(listOf("model"), caps.settings)
        assertEquals(emptyList<String>(), caps.sendModes)
        // 取交集，按说明书的顺序
        assertEquals(listOf("running", "idle"), caps.statuses)
        val widened = capsNow(AgentCapabilities(sendModes = listOf("send")), JSONObject("""{"capabilities_now":{"send_modes":["send","queue"]}}"""))
        assertEquals(listOf("send"), widened.sendModes)
    }

    @Test fun aNoteIsReadFromCapabilityNotes() {
        val raw = JSONObject("""{"capabilities_now":{"approve":false},"capability_notes":{"approve":"远程电脑上的 Codex 钩子没被信任","answer":"   "}}""")
        assertEquals("远程电脑上的 Codex 钩子没被信任", capsNote(raw, "approve"))
        assertEquals("", capsNote(raw, "answer"))     // 只有空白算没有
        assertEquals("", capsNote(raw, "stop"))
    }

    @Test fun skillsComeFromTheManifestWhenItSaysSo() {
        val old = AgentCapabilities(list = true, read = true, slashCommands = true)
        assertNull(old.skills)                        // 老电脑的说明书里没有这个键
        // 「引用技能」：说明书有 skills 就按此刻能力，没有就沿用旧规则（DeepSeek 布局不显示）
        assertTrue(skillsAvailable(old, "codex.v1"))
        assertFalse(skillsAvailable(old, "deepseek.v1"))
        assertFalse(skillsAvailable(AgentCapabilities(slashCommands = true, skills = false), "codex.v1"))
        assertTrue(skillsAvailable(AgentCapabilities(slashCommands = false, skills = true), "deepseek.v1"))
        // 此刻能力可以把它收窄
        val narrowed = capsNow(AgentCapabilities(skills = true), JSONObject("""{"capabilities_now":{"skills":false}}"""))
        assertFalse(skillsAvailable(narrowed, "codex.v1"))
        // 说明书是 false 的不会被放大
        val widened = capsNow(AgentCapabilities(skills = false), JSONObject("""{"capabilities_now":{"skills":true}}"""))
        assertEquals(false, widened.skills)
    }

    @Test fun theModeButtonFollowsEachKindOfComputer() {
        val modelOnly = AgentCapabilities(settings = listOf("model", "effort"))
        // 老电脑（没有 capabilities_now）：Codex 布局照旧显示，其他布局只看 settings
        assertTrue(modeAvailable(modelOnly, "codex.v1", live = false))
        assertFalse(modeAvailable(modelOnly, "generic.v1", live = false))
        assertTrue(modeAvailable(AgentCapabilities(settings = listOf("model", "permission")), "claude.v1", live = false))
        // 有 capabilities_now：只看此刻 settings，Codex 布局不再单独放行
        assertFalse(modeAvailable(modelOnly, "codex.v1", live = true))
        assertTrue(modeAvailable(AgentCapabilities(settings = listOf("model", "mode")), "codex.v1", live = true))
        assertTrue(modeAvailable(AgentCapabilities(settings = listOf("permission")), "generic.v1", live = true))
    }

    @Test fun theManifestParsesSkillsOnlyWhenTheKeyIsThere() {
        val withKey = parseAgentInfo(JSONObject("""{"id":"testing","name":{"zh":"测试助手","en":"Test"},"capabilities":{"skills":true}}"""))
        assertEquals(true, withKey?.caps?.skills)
        val withFalse = parseAgentInfo(JSONObject("""{"id":"testing","name":{"zh":"测试助手","en":"Test"},"capabilities":{"skills":false}}"""))
        assertEquals(false, withFalse?.caps?.skills)
        val oldComputer = parseAgentInfo(JSONObject("""{"id":"codex","name":{"zh":"Codex","en":"Codex"},"capabilities":{"slash_commands":true}}"""))
        assertNull(oldComputer?.caps?.skills)         // 老电脑：保持 null，界面沿用旧规则
    }

    @Test fun theCatalogReadsTheControlStateForEachConversation() {
        val catalog = AgentCatalogSnapshot.fromServer(listOf(
            parseAgentInfo(JSONObject("""{"id":"testing","name":{"zh":"测试助手","en":"Test"},"capabilities":{"approve":true,"answer":true,"skills":true,"settings":["model","effort"],"send_modes":["send"]}}"""))!!,
        ))
        assertEquals(listOf("send"), catalog.capsAt("testing", JSONObject("""{"available":true}""")).sendModes)
        val narrowed = catalog.capsAt("testing", JSONObject("""{"capabilities_now":{"send_modes":[],"approve":false}}"""))
        assertEquals(emptyList<String>(), narrowed.sendModes)
        assertFalse(narrowed.approve)
        assertTrue(narrowed.answer)
        assertEquals("请在电脑上处理", catalog.noteAt("testing", JSONObject("""{"capabilities_now":{"approve":false}}"""), "approve").ifBlank { "请在电脑上处理" })
        assertEquals("钩子没信任", catalog.noteAt("testing", JSONObject("""{"capability_notes":{"approve":"钩子没信任"}}"""), "approve"))
    }
}
