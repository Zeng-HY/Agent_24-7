package com.pocketagentdesk.teleply

import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.UUID
import org.json.JSONArray
import org.json.JSONObject

/**
 * 用量 (11-17): what the computer said about Codex's and Claude's limits (usage_limits.py) and the words the phone
 * shows for it. Everything here is plain Kotlin so the JVM tests can check the sentences without a screen.
 */

/** One limit: which one, how much of it is used, and when it resets ([resetsAt] seconds; Claude only names a time). */
data class UsageWindow(
    val kind: String = "",
    val name: String = "",
    val usedPercent: Int = 0,
    val resetsAt: Long? = null,
    val resetsText: String = "",
)

/** One of Codex's reset credits; [expiresAt] null: it does not expire. */
data class ResetCredit(val id: String = "", val title: String = "", val expiresAt: Long? = null)

/**
 * Codex's usage. [source] is "live" (its app-server, just now) or "records" (as of its last answer); [resets] false
 * means the computer did not know the reset credits, which the records never carry. [credits] null: only the count is
 * known.
 */
data class CodexUsage(
    val available: Boolean = false,
    val reason: String = "",
    val source: String = "",
    val asOf: Long = 0,
    val plan: String = "",
    val windows: List<UsageWindow> = emptyList(),
    val reached: String? = null,
    val resets: Boolean = false,
    val resetsAvailable: Int? = null,
    val credits: List<ResetCredit>? = null,
    val liveError: String = "",
)

/** Claude's usage: one limit, the one its button shows; [text] is that button's words as Claude wrote them. */
data class ClaudeUsage(
    val available: Boolean = false,
    val reason: String = "",
    val text: String = "",
    val windows: List<UsageWindow> = emptyList(),
    val minimized: Boolean = false,
)

/** GET /api/usage whole; [now] is the computer's clock, so "a minute ago" does not depend on the phone's. */
data class UsageReport(
    val codex: CodexUsage = CodexUsage(),
    val claude: ClaudeUsage = ClaudeUsage(),
    val now: Long = 0,
)

fun parseUsage(json: JSONObject) = UsageReport(
    codex = parseCodexUsage(json.optJSONObject("codex") ?: JSONObject()),
    claude = parseClaudeUsage(json.optJSONObject("claude") ?: JSONObject()),
    now = json.optLong("now"),
)

fun parseCodexUsage(json: JSONObject): CodexUsage {
    val resets = json.optJSONObject("resets")
    return CodexUsage(
        available = json.optBoolean("available"),
        reason = json.string("reason"),
        source = json.string("source"),
        asOf = json.optLong("as_of"),
        plan = json.string("plan"),
        windows = parseWindows(json.optJSONArray("windows")),
        reached = json.string("reached").ifBlank { null },
        resets = resets != null,
        resetsAvailable = resets?.let { if (it.has("available") && !it.isNull("available")) it.optInt("available") else null },
        credits = resets?.let { if (it.isNull("items")) null else parseCredits(it.optJSONArray("items")) },
        liveError = json.string("live_error"),
    )
}

fun parseClaudeUsage(json: JSONObject) = ClaudeUsage(
    available = json.optBoolean("available"),
    reason = json.string("reason"),
    text = json.string("text"),
    windows = parseWindows(json.optJSONArray("windows")),
    minimized = json.optBoolean("minimized"),
)

private fun parseWindows(array: JSONArray?): List<UsageWindow> = (0 until (array?.length() ?: 0)).mapNotNull { index ->
    array!!.optJSONObject(index)?.let { window ->
        UsageWindow(
            kind = window.string("kind"),
            name = window.string("name"),
            usedPercent = window.optInt("used_percent").coerceIn(0, 100),
            resetsAt = if (window.has("resets_at") && !window.isNull("resets_at")) window.optLong("resets_at") else null,
            resetsText = window.string("resets_text"),
        )
    }
}

private fun parseCredits(array: JSONArray?): List<ResetCredit> = (0 until (array?.length() ?: 0)).mapNotNull { index ->
    array!!.optJSONObject(index)?.let { credit ->
        ResetCredit(
            id = credit.string("id"),
            title = credit.string("title"),
            expiresAt = if (credit.has("expires_at") && !credit.isNull("expires_at")) credit.optLong("expires_at") else null,
        )
    }
}

private val ClockText = DateTimeFormatter.ofPattern("HH:mm")

private fun at(millis: Long, zone: ZoneId) = Instant.ofEpochMilli(millis).atZone(zone)

/** 今天 20:54 重置（还有 1 天 10 小时）; an hour already gone says so instead, and the records add when they catch up. */
fun resetLine(window: UsageWindow, source: String, nowMs: Long, zone: ZoneId): String {
    val resetsAt = window.resetsAt ?: return ""
    val left = resetsAt * 1000 - nowMs
    if (left <= 0) return "已过重置时间" + if (source == "records") "，等电脑上 Codex 下一次回话就会更新" else ""
    return dayLabel(resetsAt * 1000, nowMs, zone) + " " + at(resetsAt * 1000, zone).format(ClockText) + " 重置" + remainingText(left)
}

private fun dayLabel(millis: Long, nowMs: Long, zone: ZoneId): String {
    val day = at(millis, zone).toLocalDate()
    val today = at(nowMs, zone).toLocalDate()
    return when (day) {
        today -> "今天"
        today.plusDays(1) -> "明天"
        else -> "${day.monthValue}月${day.dayOfMonth}日"
    }
}

private fun remainingText(left: Long): String {
    val minutes = left / 60_000
    if (minutes < 1) return "（马上）"
    val days = minutes / 1440
    val hours = (minutes % 1440) / 60
    val rest = minutes % 60
    return when {
        days > 0 -> "（还有 $days 天" + (if (hours > 0) " $hours 小时" else "") + "）"
        hours > 0 -> "（还有 $hours 小时" + (if (rest > 0) " $rest 分" else "") + "）"
        else -> "（还有 $rest 分钟）"
    }
}

/** 刚从 Codex 读到 / {n} 分钟前从 Codex 读到, or where the records stood and what they cannot know. */
fun sourceLine(source: String, asOf: Long, nowMs: Long, zone: ZoneId): String = when (source) {
    "live" -> if (nowMs - asOf < 60_000) "刚从 Codex 读到" else "${(nowMs - asOf) / 60_000} 分钟前从 Codex 读到"
    "records" -> "来自电脑上 Codex 最近一次回话（${at(asOf, zone).format(ClockText)}）。之后在别处用掉的，这里还没算上。"
    else -> ""
}

/**
 * 确认框's words, one sentence a line: what it does, which credit (when one was tapped), and a warning while the
 * limits are nowhere near spent.
 */
fun confirmText(credit: ResetCredit?, windows: List<UsageWindow>, zone: ZoneId): String {
    val lines = mutableListOf("会马上恢复 Codex 的用量限额。用掉就没了，不能撤回。")
    if (credit != null) {
        val expiry = credit.expiresAt?.let { "${at(it * 1000, zone).monthValue}月${at(it * 1000, zone).dayOfMonth}日 到期" }
            ?: "不会过期"
        lines += "这次用：${credit.title.ifBlank { "用量重置" }}，$expiry"
    }
    val tightest = windows.maxByOrNull { it.usedPercent }
    if (tightest != null && windows.all { it.usedPercent < 90 }) {
        lines += "现在${tightest.name}还剩 ${100 - tightest.usedPercent}%，还没用完，现在用可能浪费。"
    }
    return lines.joinToString("\n")
}

/**
 * One reset attempt's request id: the same one until the computer gives a final answer, so a retry after an answer
 * that never arrived reuses the idempotency key instead of using a second credit.
 */
class ResetAttempt(private val create: () -> String = { UUID.randomUUID().toString() }) {
    private var number: String? = null
    fun id(): String = number ?: create().also { number = it }
    fun done() { number = null }
    /** Whether the same request id must be kept: the computer may have used the credit, or never answered at all. */
    fun keepsId(e: Throwable): Boolean = when (e) {
        is ServiceFailure -> e.code == "reset_unconfirmed"
        else -> true
    }
}
