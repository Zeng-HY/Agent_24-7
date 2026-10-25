package com.pocketagentdesk.nativepreview

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONArray
import org.json.JSONObject

/**
 * A first message sent (0.8, web new-chat-ui.js jobs, 10-16). The sheet is free again at once; the job is followed
 * here: on its own page while that is open (the message, a line under it), as a row above the list otherwise.
 * [pending] is the computer's latest word on it (chat/new and chat/new/state); [note] why it could not be asked now.
 */
data class NewJob(
    val request: String, val app: String, val folder: String, val projectless: Boolean, val label: String, val text: String,
    val references: String = "[]", val images: String = "[]", val body: String, val pending: String,
    val created: Long = System.currentTimeMillis(), val note: String = "",
) {
    /** The page shown for it until the conversation exists (web preview_id). */
    val preview get() = "new:$request"
    val state: String get() = pendingJson().string("state")
    val problem get() = state in setOf("failed", "unconfirmed")
    val createdId: String get() = pendingJson().string("id")
    val accepted get() = state == "accepted" && createdId.isNotBlank()
    fun pendingJson(): JSONObject = runCatching { JSONObject(pending) }.getOrDefault(JSONObject())
    fun json(): JSONObject = JSONObject().put("request", request).put("app", app).put("folder", folder).put("projectless", projectless).put("label", label)
        .put("text", text).put("references", JSONArray(references)).put("images", JSONArray(images)).put("body", JSONObject(body)).put("pending", pendingJson()).put("created", created)
    companion object {
        fun from(j: JSONObject) = NewJob(j.string("request"), j.string("app"), j.string("folder"), j.optBoolean("projectless"), j.string("label"), j.string("text"),
            (j.optJSONArray("references") ?: JSONArray()).toString(), (j.optJSONArray("images") ?: JSONArray()).toString(),
            (j.optJSONObject("body") ?: JSONObject()).toString(), (j.optJSONObject("pending") ?: JSONObject()).toString(), j.optLong("created"))
    }
}

/** Where a job stands, in the web's words (stateText). */
fun newJobState(job: NewJob) = when (job.state) {
    "accepted" -> "新对话已就绪"
    "failed" -> "没发出去"
    "unconfirmed" -> "尚未确认发送"
    "dispatching" -> "发送中…"
    else -> "对话创建中…"
}
/** The line under the first message on its page (web inlineText): a problem says it can be tapped. */
fun newJobInline(job: NewJob) = job.note.ifBlank {
    when (job.state) {
        "failed" -> "没发出去 · 点击处理"
        "unconfirmed" -> "尚未确认发送 · 点击核对"
        "accepted" -> ""
        else -> newJobState(job)
    }
}
/** The job sheet's line (web progressText): the step the computer is at, or what went wrong. */
fun newJobProgress(job: NewJob): String {
    val p = job.pendingJson()
    if (job.note.isNotBlank()) return job.note
    if (job.problem) return p.string("message").ifBlank { newJobState(job) }
    if (job.state == "accepted") return "首条消息已送达"
    val stage = p.optJSONObject("timing")?.optJSONObject("active")?.string("name").orEmpty()
    return when {
        stage in setOf("claude_record", "receipt", "send_ack", "late_receipt") -> "正在确认首条消息"
        stage.startsWith("send_") || stage in setOf("claude_fill", "claude_images", "claude_verify", "claude_invoke") -> "正在发送首条消息"
        stage.startsWith("desktop_") -> "正在连接电脑端"
        else -> "正在创建对话"
    }
}
/** A row above the list for a job not on screen (web dockText). */
fun newJobDock(job: NewJob) = sourceName(job.app) + " · " + newJobState(job) + " · " + job.text.replace(Regex("\\s+"), " ").trim().take(60).ifBlank { "新对话" }

/**
 * The jobs of one computer, kept on this phone until they are opened or removed (a day for one that went through).
 * Each is sent once; then the computer is asked where it stands, often while its page is open, until it is accepted or
 * failed. Nothing is ever sent again by itself: 继续发送 resends the same request, which the computer creates only once.
 */
class NewChatJobs(private val scope: CoroutineScope, private val store: ReaderStore) {
    private val mutable = MutableStateFlow<List<NewJob>>(emptyList())
    val jobs = mutable.asStateFlow()
    private var owner: ChatKey? = null
    private var api: ReadApi? = null
    private var fixture = false
    private var foreground = false
    private var loading: Job? = null
    private val timers = mutableMapOf<String, Job>()
    private val checking = mutableSetOf<String>()
    private val sending = mutableSetOf<String>()
    private val writes = Mutex()
    private val demo = mutableMapOf<ChatKey, String>()
    /** The job page on screen (its preview id): looked at every half second, and it becomes its conversation when ready. */
    var onScreen: String? = null
        set(value) { val was = field; field = value; if (value != was) jobs.value.find { it.preview == value }?.let { check(it) } }
    /** An accepted job whose page is on screen: open its conversation (the page decides whether it can now). */
    var settle: (NewJob) -> Unit = {}
    /** The wait between two looks; tests on the JVM look again at once (their main clock does not run by itself). */
    var pause: suspend (Long) -> Unit = { delay(it) }

    fun bind(scopeId: String, device: String?, service: ReadApi?, synthetic: Boolean) {
        val next = if (device == null || scopeId.isBlank()) null else ChatKey(scopeId, device, "@jobs", "all")
        api = service; fixture = synthetic
        if (next == owner) return
        timers.values.forEach { it.cancel() }; timers.clear(); loading?.cancel()
        owner = next; mutable.value = emptyList()
        if (next == null) return
        loading = scope.launch {
            val raw = try { writes.withLock { if (synthetic) demo[next] else store.detail(next, "new_jobs") } } catch (e: CancellationException) { throw e } catch (_: Exception) { null }
            val kept = runCatching { JSONArray(raw ?: "[]").let { a -> (0 until a.length()).map { NewJob.from(a.getJSONObject(it)) } } }.getOrDefault(emptyList())
            // A day on, a job that went through is in the list as its conversation (web).
            val now = System.currentTimeMillis()
            if (owner != next) return@launch
            mutable.value = kept.filter { !(it.accepted && now - it.created > 86_400_000L) } + mutable.value.filter { j -> kept.none { it.request == j.request } }
            if (foreground) mutable.value.filter { !settled(it) }.forEach { check(it) }
        }
    }
    /** Looked at while the app is in front only (web: not while the page is hidden). */
    fun foreground(on: Boolean) {
        if (on == foreground) return
        foreground = on
        if (!on) { timers.values.forEach { it.cancel() }; timers.clear() }
        else jobs.value.filter { !settled(it) }.forEach { check(it) }
    }
    private fun settled(job: NewJob) = job.state in setOf("accepted", "failed")

    /** Sends a first message once and follows it (web send). */
    fun submit(job: NewJob) {
        put(job)
        val service = api ?: return
        val k = owner ?: return
        sending += job.request
        scope.launch {
            val pending = try { service.detail(k.device, "chat/new", body = JSONObject(job.body)) }
                catch (e: CancellationException) { throw e }
                catch (e: Exception) { JSONObject().put("state", if (e is ServiceFailure && e.notSubmitted) "failed" else "unconfirmed").put("message", e.message ?: "提交结果未确认，请核对") }
            sending -= job.request
            val now = current(job.request) ?: return@launch
            val next = now.copy(pending = pending.toString(), note = "")
            put(next)
            if (next.state != "failed") check(next)
        }
    }
    /** A job 0.7 left in the sheet: followed, not sent. */
    fun adopt(job: NewJob) { if (current(job.request) == null) { put(job); if (!settled(job)) check(job) } }

    /** Asks the computer where the job stands (web check), then again in a moment while it is under way. */
    fun check(job: NewJob) {
        val service = api ?: return
        val k = owner ?: return
        val rid = job.request
        if (rid in checking || rid in sending || current(rid) == null) return
        timers.remove(rid)?.cancel()
        checking += rid
        scope.launch {
            var again = 500L
            try {
                val r = service.detail(k.device, "chat/new/state", mapOf("request_id" to rid))
                val now = current(rid) ?: return@launch
                require(r.string("request_id").let { it.isBlank() || it == rid }) { "回执身份不匹配" }
                // The computer has no submission for it: the same request may be sent on, it would not be created twice.
                val pending = if (r.string("state") == "draft") JSONObject(r.toString()).put("state", "unconfirmed").put("can_submit", true).put("message", "服务器尚无提交记录。可继续发送同一请求，不会重复创建。") else r
                val next = now.copy(pending = pending.toString(), note = "")
                put(next)
                when (next.state) {
                    "accepted" -> { if (onScreen == next.preview) settle(next); return@launch }
                    "failed" -> return@launch
                    "unconfirmed" -> again = if (System.currentTimeMillis() - next.created < 120_000) 6000 else 30_000
                    else -> if (onScreen != next.preview) again = 1500
                }
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) {
                current(rid)?.let { put(it.copy(note = "暂时无法核对，内容还在手机上；恢复连接后继续核对")) }
                again = 5000
            } finally { checking -= rid }
            val still = current(rid)
            if (still != null && !settled(still) && foreground) timers[rid] = scope.launch { pause(again); timers.remove(rid); current(rid)?.let { check(it) } }
        }
    }
    /** 继续发送 (web retry): the same request again; the computer creates it once whatever happened before. */
    fun retry(job: NewJob) {
        val service = api ?: return
        val k = owner ?: return
        val previous = job.pendingJson()
        val retryable = previous.optBoolean("can_submit") || job.state == "failed" && previous.optBoolean("not_submitted") && previous.optBoolean("can_retry", true)
        if (!retryable || job.request in sending || job.request in checking) return
        sending += job.request
        put(job.copy(pending = JSONObject(previous.toString()).put("state", "creating").put("message", "正在继续原请求…").toString(), note = ""))
        scope.launch {
            val pending = try {
                if (previous.optBoolean("can_submit")) service.detail(k.device, "chat/new", body = JSONObject(job.body))
                else service.detail(k.device, "chat/new/retry", body = JSONObject().put("request_id", job.request))
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { JSONObject(previous.toString()).put("state", "unconfirmed").put("can_submit", false).put("not_submitted", false).put("message", "继续发送的结果尚未确认，请核对结果：" + (e.message ?: "")) }
            sending -= job.request
            current(job.request)?.let { put(it.copy(pending = pending.toString())); check(it.copy(pending = pending.toString())) }
        }
    }
    /** 移除 / opened: the phone stops following it; nothing on the computer changes. */
    fun drop(job: NewJob) {
        timers.remove(job.request)?.cancel()
        mutable.update { list -> list.filter { it.request != job.request } }
        save()
    }
    fun current(request: String) = jobs.value.find { it.request == request }

    private fun put(job: NewJob) {
        mutable.update { list -> if (list.any { it.request == job.request }) list.map { if (it.request == job.request) job else it } else list + job }
        save()
    }
    private fun save() {
        val k = owner ?: return
        val value = JSONArray(jobs.value.map { it.json() }).toString()
        val synthetic = fixture
        scope.launch { try { writes.withLock { if (synthetic) demo[k] = value else store.detail(k, "new_jobs", value) } } catch (e: CancellationException) { throw e } catch (_: Exception) { } }
    }
}
