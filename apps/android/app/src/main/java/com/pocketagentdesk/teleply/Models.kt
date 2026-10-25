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
                val children: List<Chat> = emptyList(), val childCount: Int = 0, val childRunning: Int = 0)
/** [phase] is commentary / final_answer / thinking for assistant text; [request] is a user message's client_request_id. */
data class Message(val id: String, val role: String, val text: String, val truncated: Boolean = false, val kind: String = "", val status: String = "", val order: Double? = null, val aliases: List<String> = emptyList(),val details:String="{}",val phase:String="",val request:String="")
/** [meta] carries page-level fields as JSON, e.g. a conversation's title, folder, status and runtime. */
data class Page<T>(val items: List<T>, val cursor: String? = null, val hasMore: Boolean = false, val hasNewer: Boolean = false, val reset: Boolean = false, val meta: String = "{}")
fun JSONObject.string(key: String) = if (isNull(key)) "" else optString(key, "")
fun <T> JSONObject.rows(key: String, parse: (JSONObject) -> T): List<T> = optJSONArray(key)?.let { a -> (0 until a.length()).map { parse(a.getJSONObject(it)) } } ?: emptyList()
fun parseChat(j: JSONObject): Chat = Chat(j.getString("id"), j.string("title").ifBlank { "未命名对话" }, j.string("folder"), j.string("preview"), j.string("status"), j.string("app"), j.optLong("updated"),
    j.optBoolean("group"), j.string("kind"), j.string("parent"), j.string("parent_title"), j.rows("children", ::parseChat), j.optInt("child_count"), j.optInt("child_running"))
/**
 * Fields a message keeps besides its text: a tool step's title and changes; Claude's checklist (plan: items), next-step
 * box (next: tool_id, recap, ask, actions, open) and proposed task (task: title, brief, offer); a DeepSeek subagent
 * (subagent: child, label, status); a message from another conversation (origin) and thinking text.
 */
private val MessageDetails = listOf("tool","title","changes","activity_turn","items","tool_id","recap","ask","actions","blocked","open","brief","offer","label","child","status","mode","origin","thinking","source_id")
fun parseMessage(j: JSONObject) = Message(j.getString("id"), j.string("role"), j.string("text"), j.optBoolean("truncated"), j.string("kind"), j.string("tool_status"), if(j.has("order")) j.getDouble("order") else null, j.optJSONArray("projection_aliases")?.let { a -> (0 until a.length()).map { a.getString(it) } }.orEmpty(),JSONObject().apply { MessageDetails.forEach { key -> if(j.has(key)) put(key,j.get(key)) } }.toString(),j.string("phase"),j.string("client_request_id"))
fun mergeMessages(old: List<Message>, incoming: List<Message>, prepend: Boolean): List<Message> {
    // Server transcript order is authoritative. Never sort by arrival time or deduplicate by text.
    val replacements = incoming.associateBy { it.id }
    val seen = old.map { it.id }.toSet()
    val fresh = incoming.filter { it.id !in seen }.distinctBy { it.id }
    val existing = old.map { replacements[it.id] ?: it }
    return if (prepend) fresh + existing else existing + fresh
}
/** [draft] is the text found in Claude's box on the computer when that turned a send away (code desktop_draft). */
class ServiceFailure(val status: Int, val code: String = "",detail:String="",val notSubmitted:Boolean=false,val draft:String="") : Exception(when {
    status == 401 -> "登录已失效，请重新登录；当前阅读位置已保留。"
    status == 409 && code == "device_offline" || status == 503 -> "电脑已离线，请稍后刷新电脑列表。"
    status == 403 -> "服务拒绝访问，请核对服务地址或账号权限。"
    status == 404 -> "记录或电脑已不可用，请刷新列表。"
    status in 300..399 -> "服务返回了跳转，请在设置中填写正确的 HTTPS 服务地址。"
    else -> detail.take(500).ifBlank { "请求失败（HTTP $status），请核对后重试。" }
})
