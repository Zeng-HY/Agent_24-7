package com.pocketagentdesk.nativepreview

import org.json.JSONObject

data class ChatKey(val scope: String, val device: String, val chat: String, val app:String="codex")
data class Control(val available: Boolean = false, val running: Boolean = false, val turn: String = "", val queueAvailable: Boolean = false, val queued: List<Queued> = emptyList(), val turns: Map<String,String> = emptyMap(), val questions: Boolean = false, val raw:String="{}")
data class Queued(val id: String, val text: String, val status: String)
fun mergeControl(previous:Control,incoming:Control):Control {
    val terminal=setOf("completed","interrupted","failed")
    val turns=incoming.turns.mapValues { (id,status) -> previous.turns[id]?.takeIf { it in terminal } ?: status }
    val staleRunning=incoming.running && previous.turns[incoming.turn] in terminal
    return incoming.copy(running=incoming.running && !staleRunning,turn=if(staleRunning) "" else incoming.turn,turns=turns)
}
fun parseControl(j: JSONObject) = Control(j.optBoolean("available"), j.optBoolean("running"), j.string("active_turn_id").ifBlank { j.string("turn_id") }, j.optBoolean("queue_available"), j.rows("queued") { Queued(it.string("id"),it.string("text"),it.string("status")) }, j.rows("recent_turns") { it.getString("id") to it.string("status") }.toMap(), j.rows("questions") { it }.isNotEmpty() || j.optJSONObject("prompt")!=null || j.rows("interactions") { it }.isNotEmpty(),j.toString())
data class LiveFrame(val seq: Long, val snapshot: Boolean, val messages: List<Message>, val control: Control?)
class StreamReducer(private val chat: String,private val app:String="codex") {
    private var seq = 0L
    fun accept(j: JSONObject): LiveFrame? {
        require(j.optInt("protocol") == 1 && j.string("app") == app && j.string("id") == chat) { "实时协议或会话身份不匹配" }
        val n=j.getLong("seq")
        if(n<=seq) return null
        val snapshot=j.string("type")=="snapshot"
        require(if(seq==0L) snapshot && n==1L else !snapshot && j.string("type")=="update" && n==seq+1) { "实时序号不连续" }
        val page=if(snapshot) j.getJSONObject("chat") else j
        if(snapshot) require(page.string("id")==chat && page.string("app")==app)
        val frame=LiveFrame(n,snapshot,page.rows("messages",::parseMessage),if(app=="codex" && j.has("control")) j.optJSONObject("control")?.let(::parseControl) ?: Control() else null)
        seq=n
        return frame
    }
}
fun mergeLive(old: List<Message>, incoming: List<Message>): List<Message> {
    val aliases=incoming.flatMap { it.aliases }.toSet()
    val merged=mergeMessages(old.filter { it.id !in aliases },incoming,false)
    return if(merged.all { it.order!=null }) merged.sortedBy { it.order } else merged
}
fun receiptLabel(state: String, result: JSONObject, action: String): String = when {
    state=="cancelled" -> "已取消排队"
    state=="rejected" -> "未接收"
    state=="queued" -> "已排队"
    state=="accepted" && action=="stop" -> "停止请求已接收，等待轮次确认"
    state=="accepted" && result.optJSONObject("evidence")?.string("source")=="conversation_record" -> "已送达"
    state=="accepted" -> "已接收"
    else -> "送达状态待确认"
}
