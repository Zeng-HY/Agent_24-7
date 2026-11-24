package com.pocketagentdesk.teleply

import org.json.JSONObject

/**
 * 此刻能力（第二批设计 A1）：说明书的 capabilities，加上最近一次控制态里的 capabilities_now。
 * 纯函数，不读网络也不碰磁盘，测试可以直接调用。
 *
 * 规则和电脑端一样：
 * - 控制态里没有 capabilities_now（老电脑）：就是说明书；
 * - 有：逐键收窄——说明书是 false 的不能变 true，列表取交集；
 * - 没写到的键：等于说明书。
 */
fun capsNow(base: AgentCapabilities, control: JSONObject?): AgentCapabilities {
    val now = control?.optJSONObject("capabilities_now") ?: return base
    fun flag(key: String, current: Boolean): Boolean = if (!now.has(key)) current else current && now.optBoolean(key, current)
    fun texts(key: String, current: List<String>): List<String> {
        val values = now.optJSONArray(key) ?: return current
        val taken = (0 until values.length()).mapNotNull { values.optString(it, "").takeIf(String::isNotBlank) }
        return current.filter { it in taken }
    }
    val skills = when {
        !now.has("skills") -> base.skills
        base.skills == false -> false
        else -> now.optBoolean("skills", false)
    }
    return base.copy(
        list = flag("list", base.list),
        read = flag("read", base.read),
        search = flag("search", base.search),
        open = flag("open", base.open),
        stop = flag("stop", base.stop),
        queue = flag("queue", base.queue),
        steer = flag("steer", base.steer),
        approve = flag("approve", base.approve),
        answer = flag("answer", base.answer),
        new = flag("new", base.new),
        newProjectless = flag("new_projectless", base.newProjectless),
        newPermission = flag("new_permission", base.newPermission),
        archive = flag("archive", base.archive),
        restore = flag("restore", base.restore),
        delete = flag("delete", base.delete),
        usage = flag("usage", base.usage),
        waiting = flag("waiting", base.waiting),
        attachments = flag("attachments", base.attachments),
        slashCommands = flag("slash_commands", base.slashCommands),
        settings = texts("settings", base.settings),
        sendModes = texts("send_modes", base.sendModes),
        statuses = texts("statuses", base.statuses),
        skills = skills,
    )
}

/** 控制态里有没有 capabilities_now：有就按此刻能力判断，没有就用说明书的老规则。 */
fun hasCapsNow(control: JSONObject?): Boolean = control?.optJSONObject("capabilities_now") != null

/** 做不到的原因，读控制态的 capability_notes；没有就空字符串。 */
fun capsNote(control: JSONObject?, capability: String): String =
    control?.optJSONObject("capability_notes")?.string(capability)?.trim().orEmpty()

/** 「引用技能」能不能显示：说明书里有 skills 就按此刻能力，老电脑（null）沿用旧规则。 */
fun skillsAvailable(caps: AgentCapabilities, layout: String): Boolean =
    caps.skills ?: (caps.slashCommands && layout != "deepseek.v1")

/** 模式按钮能不能显示：控制态里有 capabilities_now 时只看此刻 settings，老电脑连同 Codex 布局一起看。 */
fun modeAvailable(caps: AgentCapabilities, layout: String, live: Boolean): Boolean =
    if (live) "mode" in caps.settings || "permission" in caps.settings
    else "mode" in caps.settings || "permission" in caps.settings || layout == "codex.v1"
