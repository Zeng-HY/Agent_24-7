package com.pocketagentdesk.teleply

import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import java.util.Locale
import org.json.JSONObject

/**
 * Built-in fallback manifests for the three legacy assistants and per-computer catalog cache (plan §3.1, §6.1, §6.3).
 *
 * Brand names and colours of the built-in three are always kept aligned with the App's own assets so that
 * Codex, Claude and DeepSeek look identical before and after migration (Codex mark #1E222A light / #EEEEEE dark,
 * Codex badge #111111; Claude #D97757; DeepSeek #4D6BFE).
 */
@Immutable
data class AgentCatalogSnapshot(
    val agents: List<AgentInfo>,
    val fromServer: Boolean = false,
    val version: String = "",
) {
    private val byId: Map<String, AgentInfo> = agents.associateBy { it.id }

    /** Assistant ids in manifest order. */
    val order: List<String> = agents.map { it.id }

    fun get(id: String): AgentInfo? = byId[id]

    fun info(id: String): AgentInfo = byId[id] ?: AgentInfo.generic(id)

    operator fun contains(id: String): Boolean = id in byId

    fun name(id: String, locale: Locale = Locale.getDefault()): String =
        byId[id]?.displayName(locale)?.ifBlank { id } ?: id

    fun can(id: String, check: (AgentCapabilities) -> Boolean): Boolean = check(info(id).caps)

    /** 此刻能力（第二批设计 A1）：说明书加上最近一次控制态的 capabilities_now；老电脑就是说明书。 */
    fun capsAt(id: String, control: JSONObject?): AgentCapabilities = capsNow(info(id).caps, control)

    /** 做不到的原因（控制态的 capability_notes）；没有就空字符串。 */
    fun noteAt(id: String, control: JSONObject?, capability: String): String = capsNote(control, capability)

    fun sendModes(id: String): List<String> = info(id).caps.sendModes

    fun params(id: String): AgentParams = info(id).params

    fun cardLayout(id: String): String = info(id).ui.cardLayout

    fun icon(id: String): AgentIcon = info(id).icon

    /** Mark tint colour for light or dark theme. Unknown assistants get neutral grey. */
    fun color(id: String, dark: Boolean): Color {
        val entry = info(id)
        val hex = if (dark) entry.colorDark else entry.color
        return parseHexColor(hex) ?: if (dark) NeutralDark else NeutralLight
    }

    /** List row badge fill colour. Unknown assistants get neutral grey. */
    fun badgeColor(id: String): Color {
        val entry = info(id)
        return parseHexColor(entry.badgeColor) ?: parseHexColor(entry.color) ?: NeutralLight
    }

    /**
     * Keeps backend-provided display names from `/api/chat/projects` for any assistant not already in this snapshot
     * (for example, when `/api/agents` was unavailable or did not include a row's source yet).
     */
    fun withTreeNames(tree: JSONObject): AgentCatalogSnapshot {
        val extras = mutableListOf<AgentInfo>()
        tree.rows("apps") { it }.forEach { group ->
            val id = group.string("app").trim()
            if (isValidAgentId(id) && id !in byId && extras.none { it.id == id }) {
                val label = group.string("name").ifBlank { id }
                extras += AgentInfo.generic(id).copy(name = AgentName(label, label))
            }
        }
        return if (extras.isEmpty()) this else copy(agents = agents + extras)
    }

    companion object {
        val NeutralLight = Color(0xFF6B7280)
        val NeutralDark = Color(0xFF9CA3AF)

        private val BuiltinCodex = AgentInfo(
            id = "codex",
            name = AgentName("Codex", "Codex"),
            order = 10,
            color = "#1E222A",
            colorDark = "#EEEEEE",
            badgeColor = "#111111",
            icon = AgentIcon("builtin", "codex"),
            legacy = true,
            minProtocol = 1,
            caps = AgentCapabilities(
                list = true,
                read = true,
                search = true,
                open = true,
                stop = true,
                queue = true,
                steer = true,
                approve = true,
                answer = true,
                new = true,
                newProjectless = true,
                newPermission = false,
                archive = true,
                restore = true,
                delete = true,
                usage = true,
                waiting = true,
                attachments = true,
                slashCommands = true,
                settings = listOf("model", "effort"),
                sendModes = listOf("send", "steer", "queue"),
                statuses = listOf("running", "waiting", "idle", "unknown"),
            ),
            params = AgentParams(stateTimeoutS = 40L, sendTimeoutS = 60L, openTimeoutS = 45L, newTimeoutS = 60L, refreshMs = 2500L),
            ui = AgentUi("codex.v1", "等你处理"),
        )

        private val BuiltinClaude = AgentInfo(
            id = "claude",
            name = AgentName("Claude", "Claude"),
            order = 20,
            color = "#D97757",
            colorDark = "#D97757",
            badgeColor = "#D97757",
            icon = AgentIcon("builtin", "claude"),
            legacy = true,
            minProtocol = 1,
            caps = AgentCapabilities(
                list = true,
                read = true,
                search = true,
                open = true,
                stop = true,
                queue = false,
                steer = true,
                approve = true,
                answer = true,
                new = true,
                newProjectless = true,
                newPermission = false,
                archive = true,
                restore = true,
                delete = false,
                usage = true,
                waiting = true,
                attachments = true,
                slashCommands = true,
                settings = listOf("model", "effort", "permission", "mode"),
                sendModes = listOf("send", "steer"),
                statuses = listOf("running", "waiting", "idle", "unknown"),
            ),
            params = AgentParams(stateTimeoutS = 20L, sendTimeoutS = 60L, openTimeoutS = 45L, newTimeoutS = 70L, refreshMs = 5000L),
            ui = AgentUi("claude.v1", "等待你处理"),
        )

        private val BuiltinDeepSeek = AgentInfo(
            id = "deepseek",
            name = AgentName("DeepSeek", "DeepSeek"),
            order = 30,
            color = "#4D6BFE",
            colorDark = "#4D6BFE",
            badgeColor = "#4D6BFE",
            icon = AgentIcon("builtin", "deepseek"),
            legacy = true,
            minProtocol = 1,
            caps = AgentCapabilities(
                list = true,
                read = true,
                search = true,
                open = true,
                stop = true,
                queue = true,
                steer = true,
                approve = true,
                answer = true,
                new = true,
                newProjectless = false,
                newPermission = true,
                archive = true,
                restore = true,
                delete = false,
                usage = false,
                waiting = true,
                attachments = true,
                slashCommands = true,
                settings = listOf("model", "permission"),
                sendModes = listOf("send", "steer", "queue"),
                statuses = listOf("running", "waiting", "idle", "unknown"),
            ),
            params = AgentParams(stateTimeoutS = 40L, sendTimeoutS = 60L, openTimeoutS = 45L, newTimeoutS = 60L, refreshMs = 2500L),
            ui = AgentUi("deepseek.v1", "等待你处理"),
        )

        val BuiltinAgents: List<AgentInfo> = listOf(BuiltinCodex, BuiltinClaude, BuiltinDeepSeek)
        private val BuiltinById: Map<String, AgentInfo> = BuiltinAgents.associateBy { it.id }

        /** Offline / legacy-computer fallback containing the three built-in assistants. */
        val Builtin: AgentCatalogSnapshot = AgentCatalogSnapshot(BuiltinAgents, fromServer = false)

        /**
         * Normalises server manifests so the three built-in assistants always keep the App's own brand name,
         * mark colours, badge colour and built-in vector icon (plan §6.3, user decision 2026-11-24).
         */
        fun fromServer(agents: List<AgentInfo>, version: String = ""): AgentCatalogSnapshot {
            val normalized = agents
                .map { agent ->
                    val builtin = BuiltinById[agent.id]
                    if (builtin != null) {
                        agent.copy(
                            name = builtin.name,
                            color = builtin.color,
                            colorDark = builtin.colorDark,
                            badgeColor = builtin.badgeColor,
                            icon = builtin.icon,
                        )
                    } else {
                        agent
                    }
                }
                .sortedWith(compareBy<AgentInfo>({ it.order }, { it.id }))
            return AgentCatalogSnapshot(normalized, fromServer = true, version = version)
        }
    }
}

/**
 * Per-computer cache of assistant manifests fetched from `GET /api/agents`.
 * Invalidates automatically when `/api/status` reports a different computer version, and falls back to
 * [AgentCatalogSnapshot.Builtin] when an older computer returns 404.
 */
class AgentCatalog {
    private val entries = mutableMapOf<String, AgentCatalogSnapshot>()
    private val versions = mutableMapOf<String, String>()
    private val unifiedUnsupported = mutableSetOf<String>()

    @Synchronized
    fun get(device: String): AgentCatalogSnapshot? = entries[device]

    @Synchronized
    fun forDevice(device: String?): AgentCatalogSnapshot =
        if (device.isNullOrBlank()) AgentCatalogSnapshot.Builtin else entries[device] ?: AgentCatalogSnapshot.Builtin

    @Synchronized
    fun put(device: String, agents: List<AgentInfo>?, version: String = ""): AgentCatalogSnapshot {
        val effectiveVersion = version.ifBlank { versions[device].orEmpty() }
        if (effectiveVersion.isNotBlank()) versions[device] = effectiveVersion
        unifiedUnsupported.remove(device)
        val snapshot = if (agents != null) {
            AgentCatalogSnapshot.fromServer(agents, effectiveVersion)
        } else {
            AgentCatalogSnapshot.Builtin.copy(version = effectiveVersion)
        }
        entries[device] = snapshot
        return snapshot
    }

    /** Remembers that [device] returned a route-missing 404 (`没有这个地址`) for `/api/agents/<id>/...`. */
    @Synchronized
    fun markUnifiedUnsupported(device: String) {
        unifiedUnsupported += device
    }

    /**
     * True when [device] is already known to have no unified routes: either `GET /api/agents` returned 404
     * (`fromServer == false`), or a unified route returned `404 {"error":"没有这个地址"}`.
     */
    @Synchronized
    fun shouldSkipUnified(device: String): Boolean {
        if (device in unifiedUnsupported) return true
        val existing = entries[device]
        return existing != null && !existing.fromServer
    }

    @Synchronized
    fun updateVersion(device: String, statusVersion: String): Boolean {
        if (statusVersion.isBlank()) return false
        val previous = versions[device].orEmpty()
        if (previous.isBlank()) {
            versions[device] = statusVersion
            entries[device]?.let { entries[device] = it.copy(version = statusVersion) }
            return false
        }
        if (previous == statusVersion) return false
        versions[device] = statusVersion
        unifiedUnsupported.remove(device)
        entries.remove(device)
        return true
    }

    @Synchronized
    fun needsRefresh(device: String, statusVersion: String = ""): Boolean {
        if (device !in entries) return true
        val previous = versions[device].orEmpty()
        return statusVersion.isNotBlank() && previous.isNotBlank() && previous != statusVersion
    }

    @Synchronized
    fun clear(device: String? = null) {
        if (device == null) {
            entries.clear()
            versions.clear()
            unifiedUnsupported.clear()
        } else {
            entries.remove(device)
            versions.remove(device)
            unifiedUnsupported.remove(device)
        }
    }

    /**
     * Loads the manifest list for [device], using the cache unless [force] is true or [statusVersion] changed.
     * Falls back to [AgentCatalogSnapshot.Builtin] if `GET /api/agents` returns null (404 / old computer).
     */
    suspend fun load(
        device: String,
        api: ReadApi,
        statusVersion: String = "",
        force: Boolean = false,
    ): AgentCatalogSnapshot {
        if (!force) {
            val cached = get(device)
            if (cached != null && !needsRefresh(device, statusVersion)) {
                if (statusVersion.isNotBlank()) {
                    synchronized(this) {
                        if (versions[device].isNullOrBlank()) {
                            versions[device] = statusVersion
                            entries[device] = cached.copy(version = statusVersion)
                        }
                    }
                    return get(device) ?: cached
                }
                return cached
            }
        }
        val fetched = api.agents(device)
        return put(device, fetched, statusVersion)
    }
}

/** Compose local providing the active computer's assistant catalog (defaults to the three built-ins). */
val LocalAgentCatalog = staticCompositionLocalOf { AgentCatalogSnapshot.Builtin }
