package com.pocketagentdesk.teleply

import org.json.JSONObject

/**
 * 遥应通知's stream in pure Kotlin (design-2 §1.3, §3.4): the five messages the relay sends, what this phone remembers of
 * them, and what the notifications and the lock-screen cards should show. Nothing here touches Android, so the rules
 * (a step's words, three cards at most, a computer that went offline, a conversation that is gone) are unit-tested
 * directly; the service and the notifier only carry them out.
 */
const val PushOfflineCardMillis = 30L * 60 * 1000

data class PushComputer(val device: String, val label: String, val online: Boolean)

data class PushChat(
    val device: String,
    val label: String,
    val app: String,
    val chat: String,
    val title: String,
    val state: String,
    val since: Long? = null,
    val turn: Long? = null,
    val ended: Long? = null,
    val step: String? = null,
    val automation: Boolean = false,
) {
    /** One conversation is one notification tag, and one live card (design-2 §3.4: `device|app|chat`). */
    val key: String get() = "$device|$app|$chat"
}

/** A notice the relay wrote for this phone (design-2 §1.3.4); the words are already in the phone's language. */
data class PushNotice(
    val device: String,
    val app: String,
    val chat: String,
    val kind: String,
    val title: String,
    val subtitle: String,
    val body: String,
    val loud: Boolean,
    val key: String = if (device.isBlank()) "test" else "$device|$app|$chat",
) {
    val group: String get() = device
}

sealed interface PushMessage {
    val seq: Long
    val boot: String

    data class Hello(override val seq: Long, override val boot: String, val computers: List<PushComputer>, val conversations: List<PushChat>) : PushMessage
    data class Conversation(override val seq: Long, override val boot: String, val conversation: PushChat) : PushMessage
    data class Notice(override val seq: Long, override val boot: String, val notice: PushNotice) : PushMessage
    data class Computer(override val seq: Long, override val boot: String, val computer: PushComputer) : PushMessage
    data class Test(override val seq: Long, override val boot: String, val title: String, val body: String) : PushMessage
    data class Unknown(override val seq: Long, override val boot: String, val type: String) : PushMessage
}

/** Reads the relay's text frames; a frame that is not one of them, or has no seq/boot, is null and simply skipped. */
object PushProtocol {
    fun parse(raw: String): PushMessage? = runCatching { parse(JSONObject(raw)) }.getOrNull()

    fun parse(json: JSONObject): PushMessage? {
        val type = json.string("type")
        if (type.isBlank()) return null
        val boot = json.string("boot")
        val seq = if (json.has("seq") && !json.isNull("seq")) json.optLong("seq") else -1L
        if (seq < 0 || boot.isBlank()) return null
        return when (type) {
            "hello" -> PushMessage.Hello(seq, boot,
                json.rows("computers") { computer(it) },
                json.rows("conversations") { chat(it) })
            "conversation" -> PushMessage.Conversation(seq, boot, chat(json))
            "notice" -> PushMessage.Notice(seq, boot, notice(json))
            "computer" -> PushMessage.Computer(seq, boot, computer(json))
            "test" -> PushMessage.Test(seq, boot, json.string("title").ifBlank { "遥应" }, json.string("body"))
            else -> PushMessage.Unknown(seq, boot, type)
        }
    }

    private fun number(json: JSONObject, key: String): Long? =
        if (json.has(key) && !json.isNull(key)) json.optLong(key) else null

    private fun computer(json: JSONObject) = PushComputer(json.string("device"), json.string("label"), json.optBoolean("online"))

    private fun chat(json: JSONObject) = PushChat(
        device = json.string("device"),
        label = json.string("label"),
        app = json.string("app"),
        chat = json.string("chat"),
        title = json.string("title").ifBlank { "未命名对话" },
        state = json.string("state"),
        since = number(json, "since"),
        turn = number(json, "turn"),
        ended = number(json, "ended"),
        step = json.string("step").takeIf { it.isNotBlank() },
        automation = json.optBoolean("automation"),
    )

    private fun notice(json: JSONObject) = PushNotice(
        device = json.string("device"),
        app = json.string("app"),
        chat = json.string("chat"),
        kind = json.string("kind"),
        title = json.string("title").ifBlank { "遥应" },
        subtitle = json.string("subtitle"),
        body = json.string("body"),
        loud = if (json.has("loud") && !json.isNull("loud")) json.optBoolean("loud") else true,
    )
}

/** What this phone knows from the stream: the relay boot and place, its computers, and its live conversations. */
data class PushModel(
    val boot: String = "",
    val lastSeq: Long = 0,
    val computers: Map<String, PushComputer> = emptyMap(),
    val chats: Map<String, PushChat> = emptyMap(),
    val offlineAt: Map<String, Long> = emptyMap(),
) {
    fun onlineCount(): Int = computers.values.count { it.online }

    fun computerCount(): Int = computers.size

    /**
     * Applies one message. Hello is the whole picture and replaces computers and conversations; everything after it
     * changes one row. A conversation with state `gone` (the relay's snapshot found it ended) leaves no card behind.
     * [now] is the phone's clock, used only to remember when a computer went offline.
     */
    fun apply(message: PushMessage, now: Long): PushModel {
        fun seq(): Long = if (message.boot == boot) maxOf(lastSeq, message.seq) else message.seq
        val next = when (message) {
            is PushMessage.Hello -> copy(
                boot = message.boot,
                lastSeq = message.seq,
                computers = message.computers.associateBy { it.device },
                chats = message.conversations.filter { it.state != "gone" }.associateBy { it.key },
                offlineAt = offlineMarks(message.computers, now),
            )
            is PushMessage.Conversation -> {
                val chat = message.conversation
                val chats = if (chat.state == "gone") this.chats - chat.key else this.chats + (chat.key to chat)
                copy(boot = message.boot, lastSeq = seq(), chats = chats)
            }
            is PushMessage.Computer -> {
                val computer = message.computer
                val offlineAt = if (computer.online) this.offlineAt - computer.device
                else this.offlineAt + (computer.device to (this.offlineAt[computer.device] ?: now))
                copy(
                    boot = message.boot,
                    lastSeq = seq(),
                    computers = this.computers + (computer.device to computer),
                    offlineAt = offlineAt,
                )
            }
            is PushMessage.Notice -> copy(boot = message.boot, lastSeq = seq())
            is PushMessage.Test -> copy(boot = message.boot, lastSeq = seq())
            is PushMessage.Unknown -> copy(boot = message.boot, lastSeq = seq())
        }
        return next
    }

    private fun offlineMarks(computers: List<PushComputer>, now: Long): Map<String, Long> =
        computers.filter { !it.online }.associate { it.device to (offlineAt[it.device] ?: now) }

    /**
     * The lock-screen cards (design-2 §3.4): one per working or waiting conversation, the newest three, the rest counted.
     * A conversation on an offline computer says 电脑离线 and is dropped after 30 minutes; done, failed and gone have no
     * card (they are ordinary notices instead).
     */
    fun liveCards(now: Long, limit: Int = 3): PushLiveCards {
        val live = chats.values.filter { it.state == "working" || it.state == "waiting" }
            .sortedWith(compareByDescending<PushChat> { it.since ?: 0L }.thenByDescending { it.turn ?: 0L }.thenByDescending { it.ended ?: 0L })
        val shown = mutableListOf<PushLiveCard>()
        var overflow = 0
        for (chat in live) {
            val offline = computers[chat.device]?.online == false
            if (offline) {
                val since = offlineAt[chat.device] ?: now
                if (now - since >= PushOfflineCardMillis) continue
            }
            if (shown.size >= limit) { overflow += 1; continue }
            shown += PushLiveCard(
                device = chat.device,
                app = chat.app,
                chat = chat.chat,
                title = chat.title,
                body = if (offline) "电脑离线" else pushLiveBody(chat),
                subText = listOf(pushAppLabel(chat.app), chat.label).filter { it.isNotBlank() }.joinToString(" · "),
                startedAt = ((chat.turn ?: chat.since ?: 0L) * 1000L),
                key = chat.key,
            )
        }
        return PushLiveCards(shown, overflow)
    }
}

/** One lock-screen card as the notifier draws it (design-2 §3.4.2). */
data class PushLiveCard(val device: String, val app: String, val chat: String, val title: String, val body: String, val subText: String, val startedAt: Long, val key: String)

/** The cards to show and how many working conversations did not fit (the relay's "还有 N 个在干活"). */
data class PushLiveCards(val cards: List<PushLiveCard>, val overflow: Int)

/**
 * When the next 电脑离线 card is due to go, after [now]; null when no computer is offline or all their half hours have
 * already passed. The service waits for this to take the card away when no other message comes.
 */
fun PushModel.nextOfflineExpiry(now: Long): Long? =
    offlineAt.values.map { it + PushOfflineCardMillis }.filter { it > now }.minOrNull()

/** 「在干活 · 编辑文件」/「在干活 · 跑命令」/「在干活 · 搜索」/「在干活 · 读文件」/「在等你」 (design-2 §3.4.2). */
fun pushLiveBody(chat: PushChat): String = when (chat.state) {
    "waiting" -> "在等你"
    "working" -> "在干活" + (pushStepText(chat.step)?.let { " · $it" } ?: "")
    else -> ""
}

/** The relay's step word or its English name, as one of the four the design names; other words are shown as sent. */
fun pushStepText(step: String?): String? = when (step?.trim()?.lowercase().orEmpty()) {
    "", "null" -> null
    "edit", "editing", "write", "writing", "file", "files" -> "编辑文件"
    "shell", "command", "commands", "exec", "run", "running", "tool" -> "跑命令"
    "search", "searching", "grep", "find" -> "搜索"
    "read", "reading" -> "读文件"
    else -> step?.trim()
}

/** Codex / Claude / DeepSeek as the app's own pages name them; any other source keeps its own name. */
fun pushAppLabel(app: String): String = when (app) {
    "codex" -> "Codex"
    "claude" -> "Claude"
    "deepseek" -> "DeepSeek"
    "" -> ""
    else -> app.replaceFirstChar { if (it.isLowerCase()) it.titlecase() else it.toString() }
}

/** 「还有 N 个对话」: a device's group summary, N being the notices behind the first (design-2 §3.4.1). */
fun pushGroupSummary(count: Int): String = "还有 ${(count - 1).coerceAtLeast(0)} 个对话"

/** 「还有 N 个在干活」: the one card that stands for the working conversations that did not fit. */
fun pushOverflowTitle(count: Int): String = "还有 $count 个在干活"

/** 5, 10, 20, 40, 60, 120, 300 seconds, then 300 for as long as it takes (design-2 §3.3). */
val PushRetrySeconds = longArrayOf(5, 10, 20, 40, 60, 120, 300)

fun pushRetryMillis(attempt: Int): Long = PushRetrySeconds[attempt.coerceIn(0, PushRetrySeconds.lastIndex)] * 1000L

/** The test notice (design-2 §1.3.6): one ordinary notice, so the switch, the channel and the phone's settings are seen. */
fun pushTestNotice(message: PushMessage.Test) = PushNotice(
    device = "",
    app = "",
    chat = "test",
    kind = "test",
    title = message.title.ifBlank { "遥应" },
    subtitle = "试推一条",
    body = message.body,
    loud = true,
)

/**
 * 「Codex 定时任务」's three choices (复核 2026-11-24): the computer's own reminder rule, only failures, or nothing.
 * "codex" means the same rule the computer already uses, not "notify everything".
 */
val PushAutomationChoices: List<Pair<String, String>> = listOf(
    "codex" to "跟 Codex 一样",
    "failed" to "只推失败的",
    "off" to "不推",
)

/** The line under the three choices, the same words as the computer's web page. */
fun pushAutomationExplanation(): String =
    "跟 Codex 一样：Codex 在电脑上提醒的才推；任务在 Codex 里设了『只在失败时通知』的，成功不推。"

/**
 * The computer's `GET notify` carries `automations` as a plain string in its first version ("codex" / "failed" / "off");
 * an object with `mode` is accepted too, and no key at all (an older computer) hides the group.
 */
fun pushAutomationMode(notify: JSONObject?): String? {
    val value = notify?.opt("automations") ?: return null
    return when (value) {
        is String -> value.trim().takeIf { it.isNotEmpty() }
        is JSONObject -> value.optString("mode").trim().takeIf { it.isNotEmpty() }
        else -> null
    }
}

/** One shown notification as NotificationManager reports it: which group and tag it has (for counting a device's notices). */
data class PushShownNotification(val group: String?, val tag: String?)

/** The tag of a device's group summary, which is not counted among its conversation notices. */
fun pushGroupSummaryTag(device: String): String = "summary:$device"

/**
 * How many conversation notices of [device] are still in the shade. The system's own list is used, so a notification
 * the user swiped away stops counting; the summary itself and other groups (the live cards, 试推) are left out.
 */
fun pushGroupNoticeCount(shown: List<PushShownNotification>, device: String): Int =
    if (device.isBlank()) 0
    else shown.count { it.group == device && it.tag != pushGroupSummaryTag(device) }

