package com.pocketagentdesk.teleply

import org.json.JSONObject

data class Computer(val id: String, val label: String, val connectable: Boolean)
data class Account(val devices: List<Computer>, val email: String)
/**
 * [app] is the source application ("" when a single-source list did not say); [updated] is milliseconds.
 * A row may carry [children] that fold under it (DeepSeek subagents, one-shot sessions a script started from it), with
 * [childCount] in all; a [group] row (DeepSeek's 未分组的会话) only folds and opens nothing. A child row has a [kind]
 * ("subagent" or another) and its [parent].
 */
data class Chat(val id: String, val title: String, val folder: String = "", val preview: String = "", val status: String = "", val app: String = "", val updated: Long = 0,
                val group: Boolean = false, val kind: String = "", val parent: String = "", val parentTitle: String = "",
                val children: List<Chat> = emptyList(), val childCount: Int = 0, val childRunning: Int = 0, val created: Long = 0)
/**
 * [phase] is commentary / final_answer / thinking for assistant text; [request] is a user message's client_request_id;
 * [length] is the whole message's length as the computer counts it, what 展开全文 says when [truncated].
 * [files] is the answer's file list from §5.1 of the file-preview design: an empty list too means a newer computer,
 * null means the computer is older and the phone falls back to [openLinkedFile]. [fileNotes] say why a file-like link
 * could not be given (6.4).
 */
data class Message(val id: String, val role: String, val text: String, val truncated: Boolean = false, val kind: String = "", val status: String = "", val order: Double? = null, val aliases: List<String> = emptyList(),val details:String="{}",val phase:String="",val request:String="",val length:Int=0,
                   val files: List<FileRef>? = null, val fileNotes: List<FileNote> = emptyList())
/**
 * A file an answer names (file-preview design §5.1), as the computer lists it. [view] picks how the file page shows it
 * (`image`, `svg`, `code`, …); [version] is the `v` its addresses carry; [texts] are the words a `code` or `path`
 * file was found as, so that the words themselves can open it. [via] says how it was found (link, image, presented,
 * code, path, …), which decides whether it goes in the file strip.
 */
data class FileRef(
    val id: String,
    val name: String = "",
    val path: String = "",
    val kind: String = "",
    val view: String = "",
    val size: Long = 0,
    val state: String = "",
    val version: String = "",
    val width: Int = 0,
    val height: Int = 0,
    val thumb: Boolean = false,
    val line: Int = 0,
    val lang: String = "",
    val texts: List<String> = emptyList(),
    val via: List<String> = emptyList(),
    val preview: String = "",
) {
    /** A picture that can be drawn where the answer put it (6.1): an image or SVG the computer can make a thumb of. */
    val picture: Boolean get() = thumb && (view == "image" || view == "svg")
    /** The entry a file page reads; the same keys the conversation's file list gives. */
    fun toJson(): JSONObject = JSONObject().put("id", id).put("name", name).put("path", path).put("kind", kind)
        .put("view", view).put("size", size).put("state", state).put("v", version)
        .apply {
            if (width > 0) put("w", width)
            if (height > 0) put("h", height)
            if (thumb) put("thumb", true)
            if (line > 0) put("line", line)
            if (lang.isNotBlank()) put("lang", lang)
            if (preview.isNotBlank()) put("preview", preview)
        }
}
/**
 * A link that looked like a file but cannot be given (file-preview design §5.1, 6.4). [href] is the address as the
 * answer wrote it, [reason] one of the design's reasons, [text] the computer's own words when it gave any.
 */
data class FileNote(val href: String, val reason: String, val text: String = "") {
    val short: String get() = fileNoteShort(reason)
    val full: String get() = fileNoteFull(reason, text)
}
fun parseFileRef(j: JSONObject): FileRef = FileRef(
    id = j.string("id"), name = j.string("name"), path = j.string("path"), kind = j.string("kind"),
    view = j.string("view"), size = j.optLong("size"), state = j.string("state"), version = j.string("v"),
    width = j.optInt("w"), height = j.optInt("h"), thumb = j.optBoolean("thumb"), line = j.optInt("line"),
    lang = j.string("lang"), texts = j.textStrings("texts"), via = j.textStrings("via"), preview = j.string("preview"),
)
private fun JSONObject.textStrings(key: String): List<String> = optJSONArray(key)?.let { a -> (0 until a.length()).map { a.optString(it) } } ?: emptyList()
fun parseFileNote(j: JSONObject): FileNote = FileNote(j.string("href"), j.string("reason"), j.string("text"))
/** The short grey note after a link, §6.1: the design's reason in a few words. */
fun fileNoteShort(reason: String): String = when (reason) {
    "missing" -> "文件已删除"
    "changed" -> "文件刚改过"
    "not_found" -> "找不到文件"
    "not_local" -> "网络位置"
    "denied" -> "不开放"
    "folder" -> "这是文件夹"
    "too_large" -> "文件太大"
    "unsupported" -> "不能直接显示"
    "decode" -> "读不出编码"
    "offline" -> "电脑离线"
    "old_pc" -> "电脑端版本较旧"
    "local_web" -> "电脑本机网址"
    else -> "给不了"
}
/** The whole reason, in the design's own words (§6.4), for the dialog a grey note opens. */
fun fileNoteFull(reason: String, text: String = ""): String = when (reason) {
    "missing" -> "文件已移动或删除"
    "changed" -> "文件刚改过，重新打开就是新的"
    "not_found" -> "电脑上没找到这个文件（回答写的是相对位置，在对话文件夹里没找到）"
    "not_local" -> "文件在网络位置或别的电脑上，遥应只读这台电脑自己的磁盘"
    "denied" -> "出于安全，遥应不让手机读这个文件（可能含密钥或登录信息）"
    "folder" -> "这是文件夹，可以在「电脑上的文件」里看"
    "too_large" -> text.ifBlank { "文件太大，超过手机上直接看的上限；可以保存或用其他应用打开" }
    "unsupported" -> "这种文件手机上不能直接显示；可以保存或用其他应用打开"
    "decode" -> "读不出这个文件的文字编码；可以保存后用其他应用打开"
    "offline" -> "电脑离线，连上后再试"
    "old_pc" -> "电脑端版本较旧，更新到 dev.55 或以后才能看"
    "local_web" -> "这是电脑本机的网址，手机打不开"
    else -> text.ifBlank { "这个文件现在给不了" }
}
/** [meta] carries page-level fields as JSON, e.g. a conversation's title, folder, status and runtime. */
data class Page<T>(val items: List<T>, val cursor: String? = null, val hasMore: Boolean = false, val hasNewer: Boolean = false, val reset: Boolean = false, val meta: String = "{}")
fun JSONObject.string(key: String) = if (isNull(key)) "" else optString(key, "")
/**
 * A list's objects. An entry that is not one (a null the computer wrote) is left out: taken as one, it failed the whole
 * read, or ended the app while a page drew it (the iPhone's null trap, 10-27).
 */
fun <T> JSONObject.rows(key: String, parse: (JSONObject) -> T): List<T> = optJSONArray(key)?.let { a -> (0 until a.length()).mapNotNull { a.optJSONObject(it) }.map(parse) } ?: emptyList()
fun parseChat(j: JSONObject): Chat = Chat(j.getString("id"), j.string("title").ifBlank { "未命名对话" }, j.string("folder"), j.string("preview"), j.string("status"), j.string("app"), j.optLong("updated"),
    j.optBoolean("group"), j.string("kind"), j.string("parent"), j.string("parent_title"), j.rows("children", ::parseChat), j.optInt("child_count"), j.optInt("child_running"), j.optLong("created"))
/** Whether [a] comes after [b] in the computer's order for [sort] (chat_history.py sort_key): newest first, then app, then id. */
fun sortsAfter(a: Chat, b: Chat, sort: String): Boolean {
    fun order(c: Chat) = if (sort == "created") c.created else c.updated
    return compareValuesBy(a, b, { -order(it) }, { it.app }, { it.id }) > 0
}
/**
 * Fields a message keeps besides its text: a tool step's title and changes; Claude's checklist (plan: items), next-step
 * box (next: tool_id, recap, ask, actions, open) and proposed task (task: title, brief, offer); a DeepSeek subagent
 * (subagent: child, label, status); a message from another conversation (origin) and thinking text; when the record
 * wrote it (time), which ties a Claude send's pictures to it (sentPictures).
 */
private val MessageDetails = listOf("tool","title","changes","activity_turn","items","tool_id","recap","ask","actions","blocked","open","brief","offer","label","child","status","mode","origin","thinking","source_id","time")
fun parseMessage(j: JSONObject): Message {
    val base = Message(j.getString("id"), j.string("role"), j.string("text"), j.optBoolean("truncated"), j.string("kind"), j.string("tool_status"), if(j.has("order")) j.getDouble("order") else null, j.optJSONArray("projection_aliases")?.let { a -> (0 until a.length()).map { a.getString(it) } }.orEmpty(),JSONObject().apply { MessageDetails.forEach { key -> if(j.has(key)) put(key,j.get(key)) } }.toString(),j.string("phase"),j.string("client_request_id"),j.optInt("length"))
    // §5.1: an answer carries `files`, an empty list too, once the computer knows about file previews; no field at all
    // is an older computer, and every link then goes the way it did in 1.0.10.
    if(!j.has("files") || j.isNull("files")) return base
    val files = j.optJSONArray("files")?.let { a -> (0 until a.length()).mapNotNull { a.optJSONObject(it)?.let(::parseFileRef) } }.orEmpty()
    return base.copy(files = files, fileNotes = j.rows("file_notes", ::parseFileNote))
}
fun mergeMessages(old: List<Message>, incoming: List<Message>, prepend: Boolean): List<Message> {
    // Server transcript order is authoritative. Never sort by arrival time or deduplicate by text.
    val replacements = incoming.associateBy { it.id }
    val seen = old.map { it.id }.toSet()
    val fresh = incoming.filter { it.id !in seen }.distinctBy { it.id }
    val existing = old.map { replacements[it.id] ?: it }
    return if (prepend) fresh + existing else existing + fresh
}
/** Messages 展开全文 made whole stay whole when a later read brings them cut short again, unless one has grown since (web reading-ui.js merge). */
fun keepWhole(messages: List<Message>, whole: Map<String, Message>): List<Message> =
    if (whole.isEmpty()) messages else messages.map { m -> whole[m.id]?.takeIf { m.truncated && it.length >= m.length }?.let { m.copy(text = it.text, truncated = false) } ?: m }
/** The words of 展开全文 (web reading-ui.js): with the whole length when the computer gave it. */
fun expandLabel(message: Message) = if (message.length > 0) "展开全文（${message.length} 字）" else "展开全文"
/**
 * [detail] is the computer's own words ({"error": …}), shown where a fixed sentence would say less (a file preview);
 * [draft] is the text found in Claude's box on the computer when that turned a send away (code desktop_draft).
 */
class ServiceFailure(val status: Int, val code: String = "",val detail:String="",val notSubmitted:Boolean=false,val draft:String="") : Exception(when {
    status == 401 -> "登录已失效，请重新登录；当前阅读位置已保留。"
    status == 409 && code == "device_offline" || status == 503 -> "电脑已离线，请稍后刷新电脑列表。"
    status == 403 -> "服务拒绝访问，请核对服务地址或账号权限。"
    status == 404 -> "记录或电脑已不可用，请刷新列表。"
    status in 300..399 -> "服务返回了跳转，请在设置中填写正确的 HTTPS 服务地址。"
    else -> detail.take(500).ifBlank { "请求失败（HTTP $status），请核对后重试。" }
})
