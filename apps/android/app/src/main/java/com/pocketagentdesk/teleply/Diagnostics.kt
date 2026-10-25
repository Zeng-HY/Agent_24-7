package com.pocketagentdesk.teleply

import android.content.Context
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONObject

/** One timed operation of 诊断测速; [notify] ones are also shown for a moment where the user is. */
data class SpeedRecord(val serial: Long, val time: String, val label: String, val ms: Long, val bytes: Long, val result: String, val background: Boolean, val notify: Boolean)

/** "消息提交：0.412 秒 · 1.20 MB · 请求完成（切过后台）", as the web writes it. */
fun speedText(r: SpeedRecord): String = r.label + "：" + "%.3f".format(Locale.ROOT, r.ms / 1000.0) + " 秒" +
    (if (r.bytes > 0) " · " + "%.2f".format(Locale.ROOT, r.bytes / 1_000_000.0) + " MB" else "") + " · " + r.result + if (r.background) "（切过后台）" else ""

/** What a timed request came to, by the web's rules: not done on the computer, delivery unconfirmed, or done. */
fun speedOutcome(json: JSONObject): String = when {
    json.string("error").isNotBlank() || json.has("ok") && !json.optBoolean("ok", true) || json.has("accepted") && !json.optBoolean("accepted", true) || json.string("state") == "failed" -> "服务端未成功"
    json.string("state") == "unconfirmed" -> "送达未确认"
    else -> "请求完成"
}

/**
 * 诊断测速 (settings, as the web's): while it is on, the requests that carry a message or a file are timed, and each
 * one is shown for a moment; 测一下连接 times three status requests. The switch is kept on this phone; the last ten
 * records live in memory only. Turning it off or 清空记录 drops the records, and requests already under way then.
 */
object Diagnostics {
    private const val Prefs = "teleply_ui"
    private const val Key = "diagnostic_speed"
    private val on = MutableStateFlow(false)
    val enabled: StateFlow<Boolean> = on.asStateFlow()
    private val list = MutableStateFlow<List<SpeedRecord>>(emptyList())
    val records: StateFlow<List<SpeedRecord>> = list.asStateFlow()
    @Volatile private var hidden = 0
    @Volatile private var generation = 0
    private var serial = 0L
    /** The web's labels, by route; files from the phone are timed here too. */
    val Labels = mapOf(
        "/api/codex/upload" to "图片上传", "/api/files/upload" to "文件上传", "/api/files/image" to "电脑图片读取",
        "/api/codex/send" to "消息提交", "/api/chat/send" to "消息提交", "/api/claude/steer" to "补充指令提交", "/api/deepseek/send" to "消息提交",
        "/api/chat/new" to "新对话提交", "/api/chat/new/retry" to "新对话重试",
    )

    class Timer internal constructor(val label: String, val start: Long, val generation: Int, val hidden: Int)

    fun load(context: Context) { on.value = context.getSharedPreferences(Prefs, Context.MODE_PRIVATE).getBoolean(Key, false) }
    fun set(context: Context, value: Boolean) {
        generation++
        list.value = emptyList()
        on.value = value
        context.getSharedPreferences(Prefs, Context.MODE_PRIVATE).edit().putBoolean(Key, value).apply()
    }
    /** Tests switch it without a context. */
    internal fun setForTest(value: Boolean) { generation++; list.value = emptyList(); on.value = value }
    fun clear() { generation++; list.value = emptyList() }
    /** The app went to the background: a request under way then is marked （切过后台）. */
    fun background() { hidden++ }

    /** Starts timing [label]; null when the switch is off or the request is not one that is timed. */
    fun start(label: String?): Timer? = if (on.value && label != null) Timer(label, System.nanoTime(), generation, hidden) else null

    fun finish(timer: Timer?, bytes: Long, result: String, notify: Boolean = true) {
        if (timer == null || timer.generation != generation || !on.value) return
        val ms = (System.nanoTime() - timer.start) / 1_000_000
        val record = synchronized(this) {
            SpeedRecord(++serial, SimpleDateFormat("HH:mm:ss", Locale.ROOT).format(Date()), timer.label, ms, bytes, result, timer.hidden != hidden, notify)
        }
        synchronized(this) { list.value = (listOf(record) + list.value).take(10) }
    }
}
