package com.pocketagentdesk.teleply

import androidx.compose.ui.graphics.Color
import java.util.Locale
import org.json.JSONArray
import org.json.JSONObject

/**
 * What one desktop assistant's manifest says (plan §2.2, §6.1).
 * Pure schema and parsing only — no assistant names are hardcoded here.
 */

/** Legal assistant id: matches computer and relay validation (`^[a-z][a-z0-9_-]{0,31}$`). */
val ValidAgentId = Regex("^[a-z][a-z0-9_-]{0,31}$")

fun isValidAgentId(value: String): Boolean = ValidAgentId.matches(value)

data class AgentName(val zh: String, val en: String) {
    fun localized(locale: Locale = Locale.getDefault()): String {
        val preferZh = locale.language.equals("zh", ignoreCase = true)
        val first = if (preferZh) zh else en
        val second = if (preferZh) en else zh
        return first.ifBlank { second }
    }
}

data class AgentIcon(
    val kind: String = "builtin",
    val key: String = "generic",
    val path: String = "",
    val etag: String = "",
)

data class AgentCapabilities(
    val list: Boolean = false,
    val read: Boolean = false,
    val search: Boolean = false,
    val open: Boolean = false,
    val stop: Boolean = false,
    val queue: Boolean = false,
    val steer: Boolean = false,
    val approve: Boolean = false,
    val answer: Boolean = false,
    val new: Boolean = false,
    val newProjectless: Boolean = false,
    val newPermission: Boolean = false,
    val archive: Boolean = false,
    val restore: Boolean = false,
    val delete: Boolean = false,
    val usage: Boolean = false,
    val waiting: Boolean = false,
    val attachments: Boolean = false,
    val slashCommands: Boolean = false,
    /** 说明书里有没有写 skills（第二批设计 A2）：老电脑没有这个键，保持 null 让界面沿用旧规则。 */
    val skills: Boolean? = null,
    val settings: List<String> = emptyList(),
    val sendModes: List<String> = emptyList(),
    val statuses: List<String> = listOf("running", "waiting", "idle", "unknown"),
)

data class AgentParams(
    val stateTimeoutS: Long = 40L,
    val sendTimeoutS: Long = 60L,
    val openTimeoutS: Long = 45L,
    val newTimeoutS: Long = 60L,
    val refreshMs: Long = 2500L,
    val maxImages: Int = 5,
    val maxImageBytes: Long = 50L * 1024L * 1024L,
    val maxText: Int = 20_000,
)

data class AgentUi(
    val cardLayout: String = "generic.v1",
    val waitingText: String = "等待你处理",
)

data class AgentInfo(
    val id: String,
    val name: AgentName = AgentName(id, id),
    val order: Int = 1000,
    val color: String = GenericAgentColorHex,
    val colorDark: String = GenericAgentDarkColorHex,
    val badgeColor: String = color,
    val icon: AgentIcon = AgentIcon("builtin", "generic"),
    val legacy: Boolean = false,
    val minProtocol: Int = 2,
    val caps: AgentCapabilities = AgentCapabilities(),
    val params: AgentParams = AgentParams(),
    val ui: AgentUi = AgentUi(),
) {
    fun displayName(locale: Locale = Locale.getDefault()): String = name.localized(locale).ifBlank { id }

    companion object {
        const val GenericAgentColorHex = "#6B7280"
        const val GenericAgentDarkColorHex = "#9CA3AF"

        /** Safe read-only fallback for an unknown assistant id (plan §3.4): never crashes, never impersonates a known one. */
        fun generic(id: String): AgentInfo = AgentInfo(
            id = id,
            name = AgentName(id, id),
            order = Int.MAX_VALUE,
            color = GenericAgentColorHex,
            colorDark = GenericAgentDarkColorHex,
            badgeColor = GenericAgentColorHex,
            icon = AgentIcon("builtin", "generic"),
            legacy = false,
            minProtocol = 2,
            caps = AgentCapabilities(
                list = true,
                read = true,
                statuses = listOf("running", "waiting", "idle", "unknown"),
            ),
            params = AgentParams(),
            ui = AgentUi("generic.v1", "等待你处理"),
        )
    }
}

/** Parses `#RRGGBB` or `#AARRGGBB` into a Compose [Color]; null on any malformed string. */
fun parseHexColor(hex: String): Color? {
    val clean = hex.trim().removePrefix("#")
    val value = when (clean.length) {
        6 -> clean.toLongOrNull(16)?.let { 0xFF000000L or it }
        8 -> clean.toLongOrNull(16)
        else -> null
    } ?: return null
    return Color(value)
}

private fun JSONArray?.stringList(): List<String> =
    if (this == null) emptyList() else (0 until length()).mapNotNull { optString(it, "").takeIf(String::isNotBlank) }

fun parseAgentInfo(json: JSONObject): AgentInfo? {
    val id = json.string("id").trim()
    if (!isValidAgentId(id)) return null
    val nameObj = json.optJSONObject("name")
    val zh = nameObj?.string("zh")?.ifBlank { null } ?: json.string("name").ifBlank { id }
    val en = nameObj?.string("en")?.ifBlank { null } ?: zh
    val color = json.string("color").ifBlank { AgentInfo.GenericAgentColorHex }
    val colorDark = json.string("color_dark").ifBlank { color }
    val iconObj = json.optJSONObject("icon")
    val icon = if (iconObj != null) {
        AgentIcon(
            kind = iconObj.string("kind").ifBlank { "builtin" },
            key = iconObj.string("key").ifBlank { "generic" },
            path = iconObj.string("path"),
            etag = iconObj.string("etag"),
        )
    } else {
        AgentIcon("builtin", "generic")
    }
    val capsObj = json.optJSONObject("capabilities") ?: JSONObject()
    val caps = AgentCapabilities(
        list = capsObj.optBoolean("list", true),
        read = capsObj.optBoolean("read", true),
        search = capsObj.optBoolean("search", false),
        open = capsObj.optBoolean("open", false),
        stop = capsObj.optBoolean("stop", false),
        queue = capsObj.optBoolean("queue", false),
        steer = capsObj.optBoolean("steer", false),
        approve = capsObj.optBoolean("approve", false),
        answer = capsObj.optBoolean("answer", false),
        new = capsObj.optBoolean("new", false),
        newProjectless = capsObj.optBoolean("new_projectless", false),
        newPermission = capsObj.optBoolean("new_permission", false),
        archive = capsObj.optBoolean("archive", false),
        restore = capsObj.optBoolean("restore", false),
        delete = capsObj.optBoolean("delete", false),
        usage = capsObj.optBoolean("usage", false),
        waiting = capsObj.optBoolean("waiting", false),
        attachments = capsObj.optBoolean("attachments", false),
        slashCommands = capsObj.optBoolean("slash_commands", false),
        skills = if (capsObj.has("skills")) capsObj.optBoolean("skills", false) else null,
        settings = capsObj.optJSONArray("settings").stringList(),
        sendModes = capsObj.optJSONArray("send_modes").stringList(),
        statuses = capsObj.optJSONArray("statuses").stringList().ifEmpty { listOf("running", "waiting", "idle", "unknown") },
    )
    val paramsObj = json.optJSONObject("params") ?: JSONObject()
    val params = AgentParams(
        stateTimeoutS = paramsObj.optLong("state_timeout_s", 40L).coerceAtLeast(1L),
        sendTimeoutS = paramsObj.optLong("send_timeout_s", 60L).coerceAtLeast(1L),
        openTimeoutS = paramsObj.optLong("open_timeout_s", 45L).coerceAtLeast(1L),
        newTimeoutS = paramsObj.optLong("new_timeout_s", 60L).coerceAtLeast(1L),
        refreshMs = paramsObj.optLong("refresh_ms", 2500L).coerceAtLeast(250L),
        maxImages = paramsObj.optInt("max_images", 5).coerceAtLeast(0),
        maxImageBytes = paramsObj.optLong("max_image_bytes", 50L * 1024L * 1024L).coerceAtLeast(0L),
        maxText = paramsObj.optInt("max_text", 20_000).coerceAtLeast(1),
    )
    val uiObj = json.optJSONObject("ui") ?: JSONObject()
    val ui = AgentUi(
        cardLayout = uiObj.string("card_layout").ifBlank { "generic.v1" },
        waitingText = uiObj.string("waiting_text").ifBlank { "等待你处理" },
    )
    return AgentInfo(
        id = id,
        name = AgentName(zh, en),
        order = if (json.has("order") && !json.isNull("order")) json.optInt("order", 1000) else 1000,
        color = color,
        colorDark = colorDark,
        badgeColor = color,
        icon = icon,
        legacy = json.optBoolean("legacy", false),
        minProtocol = json.optInt("min_protocol", 2),
        caps = caps,
        params = params,
        ui = ui,
    )
}

fun parseAgentsResponse(json: JSONObject): List<AgentInfo> {
    val seen = mutableSetOf<String>()
    return json.rows("agents") { parseAgentInfo(it) }
        .filterNotNull()
        .filter { seen.add(it.id) }
        .sortedWith(compareBy<AgentInfo>({ it.order }, { it.id }))
}
