package com.pocketagentdesk.teleply

import org.json.JSONArray
import org.json.JSONObject

/**
 * Deliberately synthetic, opt-in demo. Never receives or persists real credentials and never contacts a service.
 * One conversation per source shows that source's inline cards (spec 4.3): a Codex question, a Claude choice and a
 * DeepSeek approval; besides, Claude's next-step box and task card, a Codex plan, DeepSeek's children, archiving,
 * notifications, the computer's voice service and an HTML page with its picture. State lives in [FixtureWorld] so
 * that switching source keeps what was answered.
 */
class FixtureApi(private val source: String = "codex", val world: FixtureWorld = FixtureWorld()) : ReadApi {
    override fun forSource(app: String): ReadApi = FixtureApi(app, world)

    /** 开发者选项 → 示例网络 (0.9.1): the demo computer answers after a while, or cannot be reached at all. */
    private suspend fun net() {
        val network = world.network
        if (network == FixtureNetwork.Offline) throw java.io.IOException("连不上电脑（本地示例：网络已断开）")
        if (network.delay > 0) kotlinx.coroutines.delay(network.delay)
    }

    override suspend fun control(device: String, chat: String, fresh: Boolean): Control { net(); return world.control(source, chat, fresh) }

    override suspend fun detail(device: String, route: String, query: Map<String, String?>, body: JSONObject?): JSONObject { net(); return reply(device, route, query, body).also { if (body != null) lost() } }

    /** 示例网络 回复丢失 (10-27): the demo computer has done what it was asked, and its reply never reaches the phone. */
    private fun lost() { if (world.network == FixtureNetwork.LostReply) throw java.io.IOException("本地示例：电脑做了，回复在路上丢了") }

    private fun reply(device: String, route: String, query: Map<String, String?>, body: JSONObject?): JSONObject = when (route) {
        "chat/new/options" -> JSONObject("""{"models":[{"id":"fixture-model","label":"测试模型","efforts":[{"id":"medium","label":"中"}]}]}""")
        "chat/folders" -> world.folders(query["app"].orEmpty())
        "chat/new/draft" -> world.newDraft()
        "chat/new" -> world.createNew(body ?: JSONObject())
        "chat/new/state" -> world.newState(query["request_id"].orEmpty())
        "chat/new/retry" -> world.retryNew(body?.string("request_id").orEmpty())
        "composer/references", "chat/new/references" -> JSONObject().put("items", JSONArray().put(JSONObject().put("kind", query["kind"]).put("id", "fixture-reference").put("app", source).put("name", "固定引用").put("title", "固定引用")))
        "files/places" -> JSONObject("""{"items":[{"name":"固定目录","path":"D:/fixture","kind":"conversation"}]}""")
        "files/list" -> JSONObject("""{"path":"D:/fixture","items":[{"kind":"file","app":"pc","id":"fixture-file-ref","download_id":"fixture-download","name":"遥应下载测试-${System.currentTimeMillis()}.txt","path":"D:/fixture/测试.txt"}]}""")
        "chat/files" -> JSONObject().put("items", JSONArray(FixtureWorld.FILES))
        "file/meta" -> if(query["file"]=="fixture-download") JSONObject().put("kind","download").put("size","固定测试内容".toByteArray().size).put("state","current") else FixtureWorld.FILES.find { it.string("id") == query["file"] }?.let { JSONObject().put("kind", it.string("kind")).put("name", it.string("name")).put("state", "current").put("size", it.optLong("size")).apply { if (it.has("preview")) put("preview", it.string("preview")) } } ?: JSONObject("""{"kind":"text","name":"安全预览.html","state":"current","size":60}""")
        "file/text" -> JSONObject().put("text", if (query["file"] == "fixture-md") FixtureWorld.MARKDOWN_FILE else FixtureWorld.HTML_FILE)
        "chat/diff" -> JSONObject("""{"ref":"fixture-diff","path":"测试.txt","hunks":["@@ -1 +1 @@\n-旧内容\n+新内容"],"next":null}""")
        "chat/projects" -> world.tree(query["more"], device)
        "chat/open" -> world.open(body?.string("id").orEmpty())
        "chat/resolve" -> JSONObject().put("items", JSONArray())
        "chat/check" -> world.claudeCheck(body?.optLong("offset") ?: 0)
        "chats/children" -> world.children(query["id"].orEmpty(), query["offset"]?.toIntOrNull() ?: 0)
        "chat/archive" -> world.archive(body?.string("app").orEmpty(), body?.string("id").orEmpty())
        "chat/unarchive" -> world.unarchive(body?.string("app").orEmpty(), body?.string("id").orEmpty())
        "chat/archived" -> world.archived()
        "chat/delete" -> world.delete(body ?: JSONObject())
        "claude/choose" -> world.claudeChoose(body?.string("token").orEmpty())
        "claude/next" -> world.claudeNext(body?.string("label").orEmpty())
        "claude/task" -> world.claudeTask(body?.string("title").orEmpty(), body?.string("button").orEmpty())
        "claude/catalog" -> world.claudeCatalog(body?.string("id").orEmpty(), body?.optBoolean("fresh") == true)
        "claude/setting" -> world.claudeSetting(body?.string("id").orEmpty(), body?.string("kind").orEmpty(), body?.string("name").orEmpty())
        "claude/close-menu" -> JSONObject().put("ok", true)
        "deepseek/approval" -> world.deepseekApproval(body?.string("event_id").orEmpty(), body?.string("choice").orEmpty())
        "deepseek/answer" -> JSONObject().put("ok", true)
        "deepseek/models" -> JSONObject("""{"groups":[{"id":"deepseek","name":"DeepSeek","models":[{"id":"deepseek-v4","name":"DeepSeek V4","reasoning":{"efforts":[{"id":"high","name":"高"},{"id":"low","name":"低"}]}}]}]}""")
        "deepseek/permissions" -> JSONObject("""{"options":[{"value":"read","name":"仅可查看","description":"只读文件，不修改"},{"value":"workspace","name":"工作区内修改","description":"只改工作区里的文件"},{"value":"full","name":"完全权限","description":"可以修改电脑上的任何文件","confirm":true}]}""")
        "deepseek/model", "deepseek/permission" -> JSONObject().put("ok", true).put("text", "本地示例：设置已记录")
        "notify" -> world.notifyState()
        "notify/ntfy" -> world.ntfy(body?.optBoolean("on") == true)
        "notify/test" -> world.notifyTest()
        "voice/status" -> JSONObject().put("local", JSONObject().put("ready", true)).put("cloud", JSONObject().put("ready", true))
        "voice/terms" -> if (body == null) JSONObject().put("text", world.terms).put("count", world.terms.lines().count { it.isNotBlank() }) else { world.terms = body.string("text"); JSONObject().put("ok", true).put("count", world.terms.lines().count { it.isNotBlank() }) }
        "voice/tidy" -> JSONObject().put("text", FixtureWorld.TIDIED)
        "status" -> JSONObject().put("ok", true).put("ui_version", "fixture")
        else -> JSONObject()
    }

    override suspend fun voice(device: String, route: String, query: Map<String, String?>, bytes: ByteArray?, type: String): JSONObject { net(); return world.voice(route) }

    override suspend fun upload(device: String, chat: String, name: String, bytes: ByteArray, image: Boolean, draft: Boolean) =
        net().let { JSONObject() }.put("id", java.util.UUID.randomUUID().toString()).put("kind", "file").put("app", if (image) source else "pc").put("name", name).put("path", "D:/fixture/$name").put("original_size", bytes.size).put("size", bytes.size)

    override suspend fun download(device: String, chat: String, file: String) = net().let { if (file == "fixture-png") java.util.Base64.getDecoder().decode(FixtureWorld.PNG) else "固定测试内容".toByteArray() }

    // A picture sent with a message is the fixed picture too, small or whole.
    override suspend fun sentPicture(device: String, id: String, small: Boolean, output: java.io.OutputStream) { net(); world.pictureReads++; output.write(java.util.Base64.getDecoder().decode(FixtureWorld.PNG)) }

    // Word, Excel and PowerPoint as the computer's Office turns them into PDF (10-27): the Word file after a moment
    // (Office starting), the Excel one not at all, in the computer's words.
    override suspend fun filePdf(device: String, chat: String, file: String, limit: Long): ByteArray {
        net()
        world.pdfReads++
        world.pdfGate?.await() ?: run { if (world.pdfDelay > 0) kotlinx.coroutines.delay(world.pdfDelay) }
        if (file == "fixture-xlsx") throw ServiceFailure(500, detail = "本地示例：电脑上的 Excel 没有响应")
        if (file != "fixture-docx") throw ServiceFailure(404, detail = "这个文件不能转成 PDF")
        return java.util.Base64.getDecoder().decode(FixtureWorld.PDF)
    }

    override suspend fun uploadStream(device: String, chat: String, name: String, size: Long, image: Boolean, draft: Boolean, open: () -> java.io.InputStream) =
        net().let { JSONObject() }.put("id", java.util.UUID.randomUUID().toString()).put("kind", "file").put("app", if (image) source else "pc").put("name", name).put("path", "D:/fixture/$name").put("original_size", size).put("size", size)

    // 诊断测速 times these where the network would: the demo's sends show its record too.
    override suspend fun command(device: String, route: String, body: JSONObject): JSONObject {
        val timer = if (route == "send") Diagnostics.start("消息提交") else null
        return try { net(); world.command(source, route, body).also { lost(); Diagnostics.finish(timer, 0, speedOutcome(it)) } }
        catch (e: Exception) { Diagnostics.finish(timer, 0, if (e is ServiceFailure) "HTTP ${e.status}" else "网络失败"); throw e }
    }

    override suspend fun receipt(device: String, chat: String, request: String) = net().let { world.receipts[request] ?: JSONObject().put("state", "unknown") }

    override suspend fun config() = "fixture"
    override suspend fun accountConfig(): JSONObject = JSONObject().put("version", "fixture").put("email_enabled", false)
    override suspend fun login(name: String, password: String) { world.signedIn = true }
    override suspend fun logout() { world.signedIn = false }
    // The account service itself answers; 示例网络 is about the computer behind it.
    override suspend fun account(): Account { if (!world.signedIn) throw ServiceFailure(401); return Account(world.devices.toList(), "fixture@example.invalid") }
    override suspend fun select(device: String) {
        if (device == "c".repeat(32)) throw ServiceFailure(409, "device_offline")
        if (world.devices.none { it.id == device }) throw ServiceFailure(404)
    }
    override suspend fun renameDevice(device: String, label: String) { world.devices.replaceAll { if (it.id == device) it.copy(label = label) else it } }
    override suspend fun revokeDevice(device: String) { if (!world.devices.removeIf { it.id == device }) throw ServiceFailure(404) }

    override suspend fun chats(device: String, query: String, cursor: String?): Page<Chat> = chatList(device, source, query, cursor)

    override suspend fun chatList(device: String, app: String, query: String, cursor: String?, sort: String, status: String): Page<Chat> {
        net()
        if (query == "performance") return Page(listOf(Chat("performance", "长会话性能示例", "固定数据", "200条消息", "idle", "codex")))
        if (query == "error") throw ServiceFailure(503)
        if (query == "expired") throw ServiceFailure(401)
        val rows = if (cursor == null) world.firstPage() else listOf(Chat("older", "更早的对话", "测试项目", "第二页", "idle", "codex", FixtureWorld.NOW - 86_400_000L * 3))
        val has = world.appsOf(device)
        val shown = rows.filter { it.app in has && (app == "all" || it.app == app) && (query.isBlank() || it.title.contains(query) || it.folder.contains(query)) && statusMatches(it.status, status) }
        val more = cursor == null && query.isBlank()
        return Page(shown, if (more) "page2" else null, more)
    }

    private fun statusMatches(value: String, filter: String) = when (filter) {
        "running" -> value == "running"
        "waiting" -> value == "waiting"
        "done" -> value in setOf("idle", "stopped", "failed")
        else -> true
    }

    override suspend fun history(device: String, chat: String, before: String?, around: String?, count: Int): Page<Message> {
        net()
        if (chat == "performance") return Page((1..200).map { i -> Message("perf-$i", if (i % 4 == 0) "user" else "assistant", "## 固定消息 $i\n" + "这是用于滚动、锚点和字号检查的脱敏测试内容。".repeat(16) + "\n```kotlin\nval fixture = $i\n```", order = i.toDouble()) }, meta = world.meta(source, chat))
        if (before != null) return Page(listOf(Message("m0", "user", "更早的测试消息。")), meta = world.meta(source, chat))
        if (world.isCreated(chat) || chat == FixtureWorld.MADE_THREAD) return Page(world.messages(source, chat), meta = world.meta(source, chat))
        return Page(world.messages(source, chat), "m1", source == "codex", meta = world.meta(source, chat))
    }

    override suspend fun message(device: String, chat: String, message: String) = net().let { Message(message, "assistant", FixtureWorld.EXAMPLE) }
    override suspend fun search(device: String, chat: String, query: String, cursor: String?) = net().let { Page(listOf(Message("m2", "assistant", "…原生阅读示例…"))) }
    override fun close() = Unit

    private companion object {
        val A = "a".repeat(32)
        val B = "b".repeat(32)
    }
}

/**
 * 开发者选项 → 示例网络: how the demo computer answers (0.9.1), to see the app on a slow or broken connection; and since
 * 10-27 回复丢失: it does what is asked (an answer, an approval, a press of Claude's) but the reply never comes back, to
 * see 核对上次操作. Reads are answered as with 立即.
 */
enum class FixtureNetwork(val label: String, val delay: Long) { Instant("立即", 0), Normal("一般", 400), Slow("慢", 2_500), Offline("断开", 0), LostReply("回复丢失", 0) }

/** Shared state of the demo across sources: answered cards, queue, receipts, archive, notifications and voice. */
class FixtureWorld {
    val receipts = mutableMapOf<String, JSONObject>()
    @Volatile var network = FixtureNetwork.Instant
    /** The desktop apps each demo computer has (remote.py machine apps); 测试电脑 B has no Claude, like a tester's (0.9.1). */
    val apps = mutableMapOf("b".repeat(32) to listOf("codex", "deepseek"))
    fun appsOf(device: String) = apps[device] ?: listOf("codex", "claude", "deepseek")
    /** Signed in to the demo service (登录 with anything, 进入示例); its computers can be renamed or removed. */
    var signedIn = false
    val devices = mutableListOf(Computer("a".repeat(32), "测试电脑 A", true), Computer("b".repeat(32), "测试电脑 B", true), Computer("c".repeat(32), "离线电脑", false))
    /** State reads asked of the demo computer (source, conversation, fresh): polls must not ask for fresh ones. */
    val stateReads = mutableListOf<Triple<String, String, Boolean>>()
    /** Times the demo computer "opened Claude's menus" to read the model list: a fresh read, or none kept yet. */
    var desktopMenuReads = 0
    /** Pictures sent with messages the demo computer was asked for, small or whole: the phone keeps them after once. */
    var pictureReads = 0
    /** Office files the demo computer was asked to turn into PDF; how long it takes (Office starting), or what it waits for (tests). */
    var pdfReads = 0
    @Volatile var pdfDelay = 1_500L
    @Volatile var pdfGate: kotlinx.coroutines.CompletableDeferred<Unit>? = null
    private var claudeModel = "Opus 4.7"
    private var claudeEffort = "高"
    private var claudeMode = "default"
    private val claudeCatalogs = mutableMapOf<String, JSONObject>()
    /** Effort entries the demo's Claude model list shows in place of its three (tests: the desktop's named levels, a slider). */
    var claudeEfforts: JSONArray? = null
    /**
     * Conversations the demo computer is not showing (10-27): a Codex one not open there, which waits for 电脑上打开, and
     * a Claude one with its settings recorded, which takes a message all the same. 电脑上打开, a Claude message or a pick
     * in its model menu opens them there, as the computer does.
     */
    private val away = mutableSetOf(AWAY_CODEX, AWAY_CLAUDE)
    private val awaySettings = JSONObject().put("model", "claude-opus-5-5").put("effort", "high").put("mode", "auto")
    private val newRequests = mutableMapOf<String, JSONObject>()
    private var drafts = 0
    private val created = mutableListOf<Pair<Chat, String>>()
    private val queues = mutableMapOf<String, MutableMap<String, Queued>>()
    private var codexAnswered = false
    private var claudeStep = 0
    /** What is ticked in Claude's second question, which takes several: its first option to begin with. */
    private val claudePicked = mutableSetOf("t-choice-3")
    private var deepseekDecided = false
    private var running = mutableMapOf<String, Boolean>()
    private var turns = mutableMapOf<String, String>()
    private var turnCount = 0
    private var nextPressed = ""
    private val tasksDone = mutableSetOf<String>()
    private var planDone = false
    private var claudeOffset = 0L
    private val claudeChecks = mutableMapOf<Long, Int>()
    private val archivedKeys = linkedSetOf<String>()
    private val deleted = mutableSetOf<String>()
    private var ntfyOn = false
    private val recent = ArrayDeque<JSONObject>()
    var terms = "遥应\nTeleply\nCodex"
    private var voiceChunks = 0

    private fun all() = listOf(
        Chat("demo", "原生阅读示例", "测试项目", "Markdown、表格和代码", if (running["codex"] == true) "running" else "idle", "codex", NOW - 60_000),
        Chat("claude-demo", "Claude 选项示例", "测试项目", if (claudeStep < 2) "请选择发布说明的格式" else "已选好格式", if (claudeStep < 2) "waiting" else "idle", "claude", NOW - 600_000),
        Chat("deepseek-demo", "DeepSeek 批准示例", "固定测试项目", if (!deepseekDecided) "批准这一步吗？" else "已处理批准", if (!deepseekDecided) "waiting" else "running", "deepseek", NOW - 1_800_000,
            children = DEEPSEEK_CHILDREN.take(2), childCount = DEEPSEEK_CHILDREN.size, childRunning = 1),
        Chat("question", "只读问题记录", "测试项目", "问题卡在时间线里作答", "waiting", "codex", NOW - 7_200_000),
        Chat("claude-next", "Claude 下一步示例", "测试项目", "下一步按钮和任务卡片", "idle", "claude", NOW - 9_000_000),
        Chat("plan-demo", "Codex 计划示例", "测试项目", if (planDone) "已按计划开始" else "计划待确认", if (planDone && running["codex"] == true) "running" else "idle", "codex", NOW - 10_800_000),
        Chat(AWAY_CODEX, "电脑上没打开的 Codex 对话", "测试项目", "先在电脑上打开才能发", "idle", "codex", NOW - 12_000_000),
        Chat(AWAY_CLAUDE, "电脑上没在显示的 Claude 对话", "测试项目", "照样能发，电脑会先切过去", "idle", "claude", NOW - 12_600_000),
        Chat(UNGROUPED, "未分组的会话", "", "不在 DeepSeek 工作区里，多是脚本或命令行开的一次性会话", "idle", "deepseek", NOW - 14_400_000, group = true,
            children = listOf(Chat("ds-stray-1", "整理下载目录（脚本）", "", "", "idle", "deepseek", NOW - 14_400_000, kind = "script")), childCount = 1),
    )
    fun firstPage() = (created.map { it.first }.reversed() + all()).filter { "${it.app}:${it.id}" !in archivedKeys && "${it.app}:${it.id}" !in deleted }

    fun control(app: String, chat: String, fresh: Boolean): Control {
        stateReads += Triple(app, chat, fresh)
        return state(app, chat)
    }

    private fun claudeId(name: String) = if (name.startsWith("Sonnet")) "sonnet" else "opus"

    /** Claude's model list as the computer keeps it (claude_control catalog): kept unless [fresh] or the model changed. */
    fun claudeCatalog(id: String, fresh: Boolean): JSONObject {
        if (id == AWAY_CLAUDE) return awayCatalog()
        val model = claudeId(claudeModel)
        val kept = claudeCatalogs[id]
        if (kept != null && !fresh && kept.string("model_id") == model) return JSONObject(kept.toString()).put("cached", true)
        if (!fresh) claudeCatalogs.values.lastOrNull { it.string("model_id") == model }?.let { other ->
            return JSONObject(other.toString()).put("cached", true).put("borrowed", true).apply { rows("effort") { it }.forEach { it.put("selected", false) } }
        }
        desktopMenuReads++
        return catalogNow().also { claudeCatalogs[id] = it }
    }
    private fun catalogNow() = JSONObject().put("model_id", claudeId(claudeModel)).put("updated_at", NOW).put("cached", false)
        .put("model", JSONArray(listOf("Opus 4.7", "Sonnet 4.6").map { JSONObject().put("name", it).put("selected", it == claudeModel) }))
        .put("effort", claudeEfforts?.let { JSONArray(it.toString()) } ?: JSONArray(listOf("高", "中", "低").map { JSONObject().put("name", it).put("selected", it == claudeEffort) }))

    /** The away Claude conversation's list as the desktop names it: its models and six named effort levels. */
    private fun awayCatalog() = JSONObject().put("model_id", awaySettings.string("model")).put("updated_at", NOW).put("cached", true)
        .put("model", JSONArray(AWAY_MODELS.map { (id, name) -> JSONObject().put("name", name).put("selected", id == awaySettings.string("model")) }))
        .put("effort", JSONArray(AWAY_EFFORTS.map { (name, value) -> JSONObject().put("name", name).put("selected", value == awaySettings.string("effort")) }))

    /** A Claude setting applied "on the computer": the state and the list come back, nothing is read again. */
    fun claudeSetting(id: String, kind: String, name: String): JSONObject {
        if (id == AWAY_CLAUDE) {
            // The computer shows the conversation first, then makes the change there.
            away -= id
            when (kind) {
                "model" -> AWAY_MODELS.find { it.second == name }?.let { awaySettings.put("model", it.first) }
                "effort" -> AWAY_EFFORTS.find { it.first == name }?.let { awaySettings.put("effort", it.second) }
                "mode" -> awaySettings.put("mode", name)
            }
            return JSONObject().put("ok", true).put("text", "本地示例：电脑切到这个对话后换好了").put("state", JSONObject(state("claude", id).raw)).apply { if (kind != "mode") put("catalog", awayCatalog()) }
        }
        when (kind) {
            "model" -> { claudeModel = name; claudeEffort = "高" }
            "effort" -> claudeEffort = name
            "mode" -> claudeMode = name
        }
        val result = JSONObject().put("ok", true).put("text", "本地示例：已在电脑上换好").put("state", JSONObject(state("claude", id).raw))
        if (kind != "mode") result.put("catalog", catalogNow().also { claudeCatalogs[id] = it })
        return result
    }

    fun folders(app: String) = if (app == "deepseek") JSONObject("""{"items":[{"path":"D:/fixture","name":"固定测试项目","sources":["DeepSeek 工作区"]}]}""")
        else JSONObject("""{"items":[{"path":"D:/fixture","name":"固定测试项目","sources":["Codex 项目"]},{"path":"D:/fixture-docs","name":"文档项目","sources":["Claude 项目"]},{"path":"D:/fixture-site","name":"网站项目","sources":["Codex 对话"]}]}""")
    fun newDraft(): JSONObject = JSONObject().put("request_id", (++drafts).toString(16).padStart(32, '0'))

    /**
     * A first message: the demo computer creates it in three looks (opening the app, sending, done). "测试失败" (or
     * "fail", for typing on an emulator) plays one that did not go out, until 继续发送.
     */
    fun createNew(body: JSONObject): JSONObject {
        val rid = body.string("request_id")
        val fail = body.string("text") in setOf("测试失败", "fail")
        newRequests.getOrPut(rid) { JSONObject().put("body", body).put("checks", 0).put("fail", fail) }
        return if (fail) failedNew(rid) else JSONObject().put("request_id", rid).put("state", "creating").put("timing", JSONObject().put("active", JSONObject().put("name", "desktop_open")))
    }
    private fun failedNew(rid: String) = JSONObject().put("request_id", rid).put("state", "failed").put("not_submitted", true).put("can_retry", true).put("message", "本地示例：电脑上的应用没有响应，首条消息没有发出")
    fun newState(rid: String): JSONObject {
        val row = newRequests[rid] ?: return JSONObject().put("request_id", rid).put("state", "draft")
        if (row.optBoolean("fail")) return failedNew(rid)
        val n = row.optInt("checks") + 1
        row.put("checks", n)
        if (n == 1) return JSONObject().put("request_id", rid).put("state", "creating").put("timing", JSONObject().put("active", JSONObject().put("name", "desktop_open")))
        if (n == 2) return JSONObject().put("request_id", rid).put("state", "dispatching").put("timing", JSONObject().put("active", JSONObject().put("name", "send_text")))
        val body = row.getJSONObject("body")
        val made = row.optString("id").ifBlank {
            val id = "fixture-new-${created.size + 1}"
            val title = body.string("text").replace(Regex("\\s+"), " ").trim().take(30).ifBlank { "新对话" }
            created += Chat(id, title, if (body.optBoolean("projectless")) "" else body.string("folder").substringAfterLast('/'), body.string("text").take(40), "idle", body.string("app").ifBlank { "codex" }, NOW) to body.string("text")
            row.put("id", id); id
        }
        val chat = created.first { it.first.id == made }.first
        return JSONObject().put("request_id", rid).put("state", "accepted").put("app", chat.app).put("id", made).put("title", chat.title).put("folder", chat.folder)
    }
    fun retryNew(rid: String): JSONObject {
        newRequests[rid]?.put("fail", false)
        return JSONObject().put("request_id", rid).put("state", "creating").put("timing", JSONObject().put("active", JSONObject().put("name", "desktop_open")))
    }

    /**
     * The away Claude conversation as claude_control reads it: while another one is shown, from its record only (the
     * name kept for its model, no desktop labels, why); once shown, with the desktop's labels.
     */
    private fun awayClaude(shown: Boolean, run: Boolean, turn: String, queued: List<Queued>, turnMap: Map<String, String>): Control {
        val name = AWAY_MODELS.find { it.first == awaySettings.string("model") }?.second
        val raw = JSONObject().put("settings", JSONObject(awaySettings.toString())).put("recorded_label", name).put("mode_options", JSONArray(AWAY_MODES)).put("actions", JSONArray())
        if (!shown) return Control(false, false, "", false, emptyList(), emptyMap(), false, raw.put("available", false).put("on_screen", false)
            .put("model_label", JSONObject.NULL).put("effort_label", JSONObject.NULL).put("mode_label", JSONObject.NULL).put("reason", "电脑上显示的不是此 Claude 会话；请点击「电脑上打开」").toString())
        raw.put("available", true).put("on_screen", true).put("running", run).put("model_label", name).put("effort_label", AWAY_EFFORTS.find { it.second == awaySettings.string("effort") }?.first)
            .put("mode_label", DESKTOP_MODES[awaySettings.string("mode")]).put("queued", JSONArray())
        return Control(true, run, turn, true, queued, turnMap, false, raw.toString())
    }

    private fun state(app: String, chat: String): Control {
        val queued = queues[app].orEmpty().values.toList()
        val run = running[app] == true
        val turn = turns[app].orEmpty()
        val turnMap = if (turn.isBlank()) emptyMap() else mapOf(turn to if (run) "inProgress" else "interrupted")
        // Not open on the demo computer, Codex answers as codex_control does: not available, why, no settings.
        if (chat == AWAY_CODEX) return if (chat in away) Control(false, false, "", false, emptyList(), emptyMap(), false, CODEX_AWAY)
            else Control(true, run, if (run) turn else "", true, queued, turnMap, false, JSONObject(CODEX_STATE).put("questions", JSONArray()).toString())
        if (chat == AWAY_CLAUDE) return awayClaude(chat !in away, run, turn, queued, turnMap)
        // A conversation the demo just created, or Codex made from a reply, has nothing waiting in it.
        if (created.any { it.first.id == chat } || chat == MADE_THREAD) return when (app) {
            "claude" -> Control(true, false, "", true, emptyList(), emptyMap(), false, JSONObject(CLAUDE_STATE).apply { remove("prompt") }.toString())
            "deepseek" -> Control(true, false, "", true, emptyList(), emptyMap(), false, JSONObject(DEEPSEEK_STATE).put("interactions", JSONArray()).toString())
            else -> Control(true, false, "", true, emptyList(), emptyMap(), false, JSONObject(CODEX_STATE).put("questions", JSONArray()).toString())
        }
        return when (app) {
            "claude" -> {
                val raw = JSONObject(CLAUDE_STATE)
                raw.getJSONObject("settings").put("model", claudeId(claudeModel)).put("mode", claudeMode).put("effort", mapOf("高" to "high", "中" to "medium", "低" to "low")[claudeEffort] ?: claudeEffort)
                raw.put("model_label", claudeModel).put("effort_label", claudeEffort)
                    .put("mode_label", DESKTOP_MODES[claudeMode] ?: claudeMode)
                raw.put("running", run).put("stop_token", if (run) "t-stop" else "")
                raw.put("queued", JSONArray(queued.map { JSONObject().put("id", it.id).put("text", it.text).put("token", "t-steer-${it.id}") }))
                if (chat == "claude-next") {
                    // The computer shows this conversation; the task card waits there until it is dealt with.
                    raw.remove("prompt")
                    raw.put("on_screen", true).put("tasks", JSONArray(listOf(TASK_TITLE).filter { it !in tasksDone }))
                    return Control(true, run, turn, true, queued, turnMap, false, raw.toString())
                }
                when (claudeStep) {
                    0 -> Unit
                    1 -> raw.put("prompt", claudeSecond())
                    else -> raw.remove("prompt")
                }
                // As computers before Windows dev.23 sent them: the question's buttons again, by their raw names. The app
                // shows only the question (web askParts).
                raw.optJSONObject("prompt")?.let { prompt -> raw.put("actions", JSONArray(prompt.rows("choices") { JSONObject().put("name", it.string("label") + " " + it.string("description")).put("token", it.string("token")) })) }
                Control(true, run, turn, true, queued, turnMap, claudeStep < 2, raw.toString())
            }
            "deepseek" -> {
                val raw = JSONObject(DEEPSEEK_STATE)
                if (deepseekDecided) raw.put("interactions", JSONArray())
                Control(true, run, turn, true, queued, turnMap, !deepseekDecided, raw.toString())
            }
            else -> {
                val raw = JSONObject(CODEX_STATE)
                if (chat == "plan-demo") {
                    raw.put("questions", JSONArray()).put("plan", JSONObject().put("id", "plan-item-1").put("turn_id", "plan-turn").put("text", PLAN).put("ready", !planDone && running["codex"] != true))
                        .put("images", JSONArray(PLAN_PICTURES))
                    return Control(true, run, if (run) turn else "", true, queued, turnMap, false, raw.toString())
                }
                if (codexAnswered) raw.getJSONArray("questions").getJSONObject(0).put("status", "answered").put("editable", true)
                Control(true, run, if (run) turn else "", true, queued, turnMap, !codexAnswered, raw.toString())
            }
        }
    }

    fun command(app: String, route: String, body: JSONObject): JSONObject {
        val rid = body.string(if (route == "stop") "operation_id" else "request_id")
        val queue = queues.getOrPut(app) { linkedMapOf() }
        if (app == "claude" && route == "send") return claudeSend(body)
        if (body.string("plan_id").isNotBlank()) planDone = true
        val state = when {
            route == "answer" -> { codexAnswered = true; "accepted" }
            route == "stop" -> { running[app] = false; "accepted" }
            route == "queue-action" && body.string("action") == "promote" -> { queue.remove(body.string("message_id")); "accepted" }
            route == "queue-action" -> { queue.remove(body.string("message_id")); "cancelled" }
            body.string("intent") == "queue" -> { queue[rid] = Queued(rid, body.string("text"), "queued"); "queued" }
            else -> {
                if (running[app] != true) { turnCount++; turns[app] = "fixture-turn-$turnCount" }
                running[app] = true
                "accepted"
            }
        }
        val result = JSONObject().put("request_id", rid).put("accepted", true).put("delivery_state", state)
        receipts[rid] = JSONObject().put("request_id", rid).put("state", state).put("result", result)
        return result
    }

    /**
     * Claude takes a message by Enter in its box (chat/send); whether it read it is then looked for (chat/check).
     * "测试电脑草稿" (or "draft", for typing on an emulator) plays a box on the computer that already holds a letter typed
     * there, until it is replaced.
     */
    private fun claudeSend(body: JSONObject): JSONObject {
        if (body.string("text") in setOf("测试电脑草稿", "draft") && body.string("replace_draft").isBlank())
            throw ServiceFailure(400, "desktop_draft", "电脑上 Claude 的输入框里已经有「e」，没有发出", notSubmitted = true, draft = "e")
        // A conversation it was not showing, the computer opens first (Windows 0.27.0-dev.19).
        away -= body.string("id")
        claudeOffset += 100
        claudeChecks[claudeOffset] = 0
        val run = running["claude"] == true
        return JSONObject().put("ok", true).put("pressed", true).put("offset", claudeOffset).put("running", run).put("text", "已提交，等待 Claude 读取")
    }

    fun claudeCheck(offset: Long): JSONObject {
        val n = (claudeChecks[offset] ?: 0) + 1
        claudeChecks[offset] = n
        val queued = running["claude"] == true && n < 3
        return JSONObject().put("delivered", !queued && n >= 2).put("queued", queued)
    }

    /** 电脑上打开: no window opens, but a conversation the demo computer was not showing now is. */
    fun open(id: String): JSONObject {
        away -= id
        return JSONObject().put("ok", true).put("text", "本地示例：没有真的打开电脑上的窗口")
    }

    /**
     * A tap "on the computer". The first question takes one answer, so a pick goes on to the second; the second takes
     * several: a pick ticks or unticks it, and 提交 or 跳过 ends the questions, 上一题 goes back.
     */
    fun claudeChoose(token: String): JSONObject {
        when {
            token == "t-stop" -> running["claude"] = false
            token.startsWith("t-steer-") -> queues["claude"]?.remove(token.removePrefix("t-steer-"))
            claudeStep == 1 && token.startsWith("t-choice-") -> if (!claudePicked.remove(token)) claudePicked += token
            token == "t-nav-back" -> claudeStep = 0
            token.startsWith("t-choice-") || token.startsWith("t-nav-") -> claudeStep = (claudeStep + 1).coerceAtMost(2)
        }
        return JSONObject().put("ok", true).put("text", "本地示例：已在电脑上点选")
    }

    /** The second question with what is ticked: "✓ " before a ticked option's words, and 提交 only once one is. */
    private fun claudeSecond() = JSONObject(CLAUDE_SECOND).apply {
        rows("choices") { it }.forEach { choice ->
            val on = choice.string("token") in claudePicked
            choice.put("pressed", on).put("label", (if (on) "✓ " else "") + choice.string("name"))
        }
        rows("nav") { it }.find { it.string("name") == "Submit" }?.put("token", if (claudePicked.isEmpty()) JSONObject.NULL else "t-nav-submit")
    }

    fun claudeNext(label: String): JSONObject {
        if (nextPressed.isNotBlank()) throw ServiceFailure(409, detail = "这个框已经不在了：回复过了，或者已经是新的一轮。刷新看看")
        nextPressed = label
        return JSONObject().put("ok", true).put("text", "本地示例：已在电脑上点了「$label」")
    }

    fun claudeTask(title: String, button: String): JSONObject {
        if (title in tasksDone) throw ServiceFailure(409, detail = "电脑上这张任务卡片已经处理过了，或者不在了")
        tasksDone += title
        val done = mapOf("start" to "开始了", "here" to "点了「Do it here」", "dismiss" to "关掉了")[button] ?: "处理了"
        return JSONObject().put("ok", true).put("text", "本地示例：已在电脑上$done" + if (button == "start") "，新对话会出现在列表里" else "")
    }

    fun deepseekApproval(event: String, choice: String): JSONObject {
        if (event == "e-approval-1") {
            deepseekDecided = true
            if (choice == "allowed-once") running["deepseek"] = true
        }
        return JSONObject().put("ok", true)
    }

    fun children(id: String, offset: Int): JSONObject {
        val kids = if (id == "deepseek-demo") DEEPSEEK_CHILDREN else emptyList()
        return JSONObject().put("items", JSONArray(kids.drop(offset).take(50).map { child(it) })).put("total", kids.size).put("offset", offset)
    }
    private fun child(c: Chat) = JSONObject().put("app", c.app).put("id", c.id).put("title", c.title).put("updated", c.updated).put("status", c.status).put("kind", c.kind).put("parent", c.parent)

    fun archive(app: String, id: String): JSONObject {
        val row = all().find { it.app == app && it.id == id } ?: throw ServiceFailure(404)
        if (row.status == "running") throw ServiceFailure(400, detail = "这个对话正在运行，先停止这一轮再归档")
        archivedKeys += "$app:$id"
        return JSONObject().put("ok", true).put("app", app).put("id", id).put("archived", true)
    }
    fun unarchive(app: String, id: String): JSONObject {
        archivedKeys -= "$app:$id"
        return JSONObject().put("ok", true).put("app", app).put("id", id).put("archived", false)
    }
    fun archived(): JSONObject {
        val rows = all().filter { "${it.app}:${it.id}" in archivedKeys && "${it.app}:${it.id}" !in deleted }.sortedBy { listOf("codex", "deepseek", "claude").indexOf(it.app) }
        return JSONObject().put("items", JSONArray(rows.map { JSONObject().put("app", it.app).put("id", it.id).put("title", it.title).put("folder", it.folder).put("archived_at", NOW / 1000 - 120).put("can_delete", it.app == "codex") }))
            .put("problems", JSONArray()).put("apps", JSONArray(listOf("codex", "deepseek", "claude"))).put("deletable", JSONArray(listOf("codex")))
    }
    fun delete(body: JSONObject): JSONObject {
        require(body.optBoolean("confirmed")) { "删除要先在手机上确认" }
        val results = body.rows("items") { v ->
            val key = v.string("app") + ":" + v.string("id")
            if (v.string("app") == "codex" && key in archivedKeys) { deleted += key; archivedKeys -= key; JSONObject().put("app", v.string("app")).put("id", v.string("id")).put("ok", true) }
            else JSONObject().put("app", v.string("app")).put("id", v.string("id")).put("ok", false).put("error", "这种对话还不能删除")
        }
        return JSONObject().put("ok", results.all { it.optBoolean("ok") }).put("results", JSONArray(results)).put("deleted", results.count { it.optBoolean("ok") })
    }

    fun notifyState(): JSONObject = JSONObject().put("configured", false).put("server", "")
        .put("ntfy", JSONObject().put("on", ntfyOn).put("topic", "agent-remote").put("server", "https://test-pc.example.ts.net").put("listening", if (ntfyOn) 1 else 0).put("last_seen", ""))
        .put("recent", JSONArray(recent.toList()))
    fun ntfy(on: Boolean): JSONObject {
        ntfyOn = on
        if (on) remember("本地示例：试推了一条")
        return JSONObject().put("ok", true).put("text", if (on) "本地示例：已打开，刚推了一条" else "本地示例：已关掉")
    }
    fun notifyTest(): JSONObject { remember("本地示例：试推了一条"); return JSONObject().put("ok", true).put("text", "本地示例：刚推了一条，看看手机") }
    private fun remember(text: String) { recent.addFirst(JSONObject().put("time", "12:00").put("text", text)); while (recent.size > 5) recent.removeLast() }

    /** The computer's recogniser, played: the words come a few at a time, then the whole sentence. */
    fun voice(route: String): JSONObject = when (route) {
        "voice/stream/start" -> { voiceChunks = 0; JSONObject().put("sid", "fixture-voice").put("rate", VoiceRate) }
        "voice/stream/chunk" -> { voiceChunks++; val n = (voiceChunks * 2).coerceAtMost(HEARD.length); JSONObject().put("final", HEARD.take(n)).put("partial", HEARD.drop(n).take(2)) }
        "voice/stream/end" -> JSONObject().put("text", HEARD)
        "voice/stream/cancel" -> JSONObject().put("ok", true)
        "voice", "voice/stream/cloud" -> JSONObject().put("text", HEARD).put("raw", HEARD).put("tidied", false)
        else -> JSONObject()
    }

    fun isCreated(chat: String) = created.any { it.first.id == chat }
    fun meta(app: String, chat: String): String = JSONObject().put("title", firstPage().find { it.id == chat }?.title ?: if (chat == MADE_THREAD) "整理发布清单" else "固定对话").put("folder", if (app == "deepseek") "固定测试项目" else "测试项目").put("runtime", JSONObject(
        when (app) {
            "deepseek" -> """{"model":"deepseek-v4","effort":"high","model_time":${NOW / 1000 - 300},"used_tokens":212000,"context_window":256000,"percent":83,"context_state":"available","usage_time":${NOW / 1000 - 120},"source":"session"}"""
            "claude" -> """{"model":"opus","effort":"high","model_time":${NOW / 1000 - 900},"used_tokens":61000,"context_window":200000,"percent":31,"context_state":"available","usage_time":${NOW / 1000 - 600},"source":"desktop"}"""
            else -> """{"model":"fixture-model","effort":"medium","model_time":${NOW / 1000 - 60},"used_tokens":118000,"context_window":258000,"percent":46,"context_state":"available","usage_time":${NOW / 1000 - 30},"source":"session"}"""
        },
    )).toString()

    fun messages(app: String, chat: String): List<Message> = when {
        created.any { it.first.id == chat } -> created.first { it.first.id == chat }.second.let { text ->
            listOf(Message("$chat-1", "user", text.ifBlank { "请查看这些图片或引用。" }), Message("$chat-2", "assistant", "本地示例：收到，这是固定的回复。"))
        }
        chat == MADE_THREAD -> listOf(Message("made-1", "user", "把发布清单单独放到这个对话里整理。"), Message("made-2", "assistant", "好的，这个对话只整理发布清单。"))
        chat == AWAY_CODEX -> listOf(Message("w1", "user", "把上周的会议记录整理成要点。"), Message("w2", "assistant", AWAY_ANSWER))
        chat == AWAY_CLAUDE -> listOf(Message("w3", "user", "检查一下发布脚本。"), Message("w4", "assistant", "检查完了，脚本没有问题。"))
        app == "claude" && chat == "claude-next" -> listOfNotNull(
            Message("n1", "user", "把发布说明的测试补齐。", details = """{"origin":"other_chat"}"""),
            Message("n2", "assistant", "先列一下要做的几步。", phase = "commentary"),
            Message("n3", "plan", "计划 2/4", details = JSONObject().put("items", JSONArray(listOf("读现有测试" to "completed", "补发布说明的测试" to "completed", "跑一遍全部测试" to "in_progress", "更新说明文档" to "pending").map { (t, s) -> JSONObject().put("text", t).put("status", s) })).toString()),
            Message("n4", "tool", "运行 测试", details = """{"tool":"shell","title":"运行 npm test"}""", status = "completed"),
            Message("n5", "assistant", "测试补好了，全部通过。说明文档还没改。"),
            Message("n6", "next", "这一轮做完了", details = JSONObject().put("tool_id", "wrap-1").put("recap", "补了 3 个测试，全部通过；说明文档还没改。").put("ask", "接下来做什么？")
                .put("actions", JSONArray().put(JSONObject().put("label", "接着改说明文档").put("message", "接着改说明文档")).put(JSONObject().put("label", "先停在这里").put("message", "先停在这里"))).apply { if (nextPressed.isBlank()) put("open", true) }.toString()),
            if (nextPressed.isNotBlank()) Message("n7", "user", nextPressed) else null,
            Message("n8", "task", TASK_TITLE, details = JSONObject().put("tool_id", "task-1").put("title", TASK_TITLE).put("brief", "把这次改动整理成发布清单：列出新增的测试、受影响的页面、需要人工确认的地方，并附上每一项的验证方法。改完发给我看。").put("offer", false).toString()),
        )
        app == "claude" -> listOf(
            // Sent with a picture from the phone: the computer's record of that send is in the state (`images`).
            Message("c1", "user", "[图片] 帮我把这次的发布说明整理一下。", details = """{"time":"2026-10-24T11:50:00.000Z"}"""),
            Message("c2", "assistant", "我先看一下现有的文档和最近的提交。", phase = "commentary"),
            Message("c3", "tool", "读取 docs/release.md", details = """{"tool":"read","title":"读取 docs/release.md"}""", status = "completed"),
            Message("c4", "assistant", "有两种写法，请在下面选一种。", kind = "question"),
        )
        app == "deepseek" -> listOf(
            Message("d1", "user", "清理一下构建缓存。"),
            Message("d2", "assistant", "需要运行一个命令删除构建目录，等你批准。", phase = "commentary"),
            Message("subagent:sa-1", "subagent", "子智能体：检查日志", details = """{"child":"sa-1","label":"检查日志","status":"running"}"""),
        )
        chat == "plan-demo" -> listOf(
            // Sent from the phone with three pictures: Codex keeps the send's request id on the message.
            Message("p1", "user", "先给我一个计划，确认后再改。", request = "fixture-send-plan"),
            Message("p2", "assistant", "我先读一下相关代码。", phase = "commentary"),
            Message("plan-item-1", "assistant", PLAN),
        )
        else -> listOfNotNull(
            Message("m1", "user", "请展示原生 Markdown 阅读。"),
            Message("m1b", "assistant", "先读取示例文件，再整理成阅读示例。", phase = "commentary"),
            Message("m1c", "tool", "修改 测试.txt", details = """{"tool":"edit","title":"修改 测试.txt","changes":[{"path":"测试.txt","ref":"fixture-diff"}]}""", status = "completed"),
            Message("m2", "assistant", EXAMPLE),
            if (chat == "demo") Message("m2b", "assistant", MADE_ANSWER) else null,
            Message("m3", "assistant", "请选择后续方案。", kind = "question"),
        )
    }

    fun tree(more: String?, device: String = "a".repeat(32)): JSONObject {
        val extra = runCatching { JSONArray(more ?: "[]") }.getOrDefault(JSONArray())
        val codexItems = JSONArray()
        firstPage().filter { it.app == "codex" }.forEach { codexItems.put(item(it)) }
        val shownMore = (0 until extra.length()).any { extra.optJSONArray(it)?.optString(1) == "p-test" }
        if (shownMore) codexItems.put(item(Chat("older", "更早的对话", "测试项目", "", "idle", "codex", NOW - 86_400_000L * 3)))
        fun project(key: String, name: String, items: JSONArray, count: Int, projectless: Boolean = false) =
            JSONObject().put("key", key).put("name", name).put("count", count).put("folder", if (projectless) "" else "D:/fixture").put("projectless", projectless).put("updated", NOW).put("items", items)
        fun only(app: String) = JSONArray().apply { firstPage().filter { it.app == app && !it.group }.forEach { put(item(it)) } }
        return JSONObject().put("now", NOW).put(
            "apps",
            JSONArray()
                .put(JSONObject().put("app", "codex").put("name", "Codex").put("count", codexItems.length()).put("projects", JSONArray().put(project("p-test", "测试项目", codexItems, codexItems.length())).put(project("p-none", "其他对话", JSONArray(), 0, true))))
                .put(JSONObject().put("app", "claude").put("name", "Claude").put("count", only("claude").length()).put("projects", JSONArray().put(project("p-claude", "测试项目", only("claude"), only("claude").length()))))
                .put(JSONObject().put("app", "deepseek").put("name", "DeepSeek").put("count", only("deepseek").length()).put("projects", JSONArray().put(project("p-deepseek", "固定测试项目", only("deepseek"), only("deepseek").length())))),
        ).also { tree ->
            // Only the apps this computer has, even with none of their conversations (remote.py filters the same way).
            val all = tree.getJSONArray("apps"); val has = appsOf(device)
            tree.put("apps", JSONArray((0 until all.length()).map { all.getJSONObject(it) }.filter { it.string("app") in has }))
        }
    }

    private fun item(chat: Chat) = JSONObject().put("app", chat.app).put("id", chat.id).put("title", chat.title).put("folder", chat.folder).put("updated", chat.updated).put("status", chat.status)

    companion object {
        /** Fixed clock so the demo reads the same every time (2026-10-24 12:00 UTC). */
        const val NOW = 1_792_843_200_000L
        const val UNGROUPED = "ungrouped"
        const val AWAY_CODEX = "codex-away"
        const val AWAY_CLAUDE = "claude-away"
        /** The words on the desktop's mode button for the recorded modes (claude_control MODE_BUTTONS). */
        private val DESKTOP_MODES = mapOf("auto" to "Auto", "default" to "Manual", "acceptEdits" to "Accept edits", "plan" to "Plan")
        /** The away Claude conversation's models (id, name) and effort levels (name, as recorded), as the desktop lists them. */
        private val AWAY_MODELS = listOf("claude-opus-5-5" to "Opus 5.5", "claude-sonnet-5" to "Sonnet 5")
        private val AWAY_EFFORTS = listOf("Low" to "low", "Medium Recommended" to "medium", "High" to "high", "Extra" to "xhigh", "Max 3.5× or more usage" to "max", "Ultracode" to "ultra")
        private const val AWAY_MODES = """[{"name":"auto","label":"Auto"},{"name":"default","label":"Manual"},{"name":"plan","label":"Plan"}]"""
        /**
         * An answer as Codex writes them (10-27): links to files on the computer, one of them not among the conversation's
         * files, a file citation, and its memory notes, which the phone does not show.
         */
        val AWAY_ANSWER = """
整理好了，要点在 [说明.md](D:\fixture\说明.md)；原始录音 [会议录音.m4a](D:\fixture\会议录音.m4a) 不在对话文件里。

:codex-file-citation{path="D:\fixture\images\logo.png" purpose="output"}

<oai-mem-citation>
<citation_entries>
MEMORY.md:12-14|note=[meeting notes are kept as bullet points]
</citation_entries>
<rollout_ids>
01a0bef3-b1d0-79d3-b7e4-4251056b2729
</rollout_ids>
</oai-mem-citation>
""".trimIndent()
        /** A conversation Codex made from a reply (10-27): the reply names it on a line of its own. */
        const val MADE_THREAD = "fixture-made-1"
        /**
         * A reply as Codex writes it after making conversations: one made, which opens from its button, and one still
         * being made; a line inside code stays as written.
         */
        val MADE_ANSWER = """
发布清单另开了一个对话来整理；升级步骤的对话还在准备。

::created-thread{threadId="$MADE_THREAD"}
::created-thread{clientThreadId="fixture-making-2"}

```text
::created-thread{threadId="shown-as-code"}
```
""".trimIndent()
        /** codex_control's answer for a conversation no Codex window has open. */
        private const val CODEX_AWAY = """{"available":false,"reason":"电脑端尚未打开这个对话，请从右上角菜单选择「电脑上打开」后重试","settings":null}"""
        private const val TASK_TITLE = "整理发布清单"
        const val HEARD = "好的帮我把发布说明里的升级步骤补上"
        const val TIDIED = "好的，帮我把发布说明里的升级步骤补上。"

        private val DEEPSEEK_CHILDREN = listOf(
            Chat("sa-1", "检查日志", "", "", "running", "deepseek", NOW - 1_700_000, kind = "subagent", parent = "deepseek-demo", parentTitle = "DeepSeek 批准示例"),
            Chat("ds-run-1", "每日构建（脚本）", "", "", "idle", "deepseek", NOW - 3_600_000, kind = "script", parent = "deepseek-demo", parentTitle = "DeepSeek 批准示例"),
            Chat("ds-run-2", "清理缓存（脚本）", "", "", "idle", "deepseek", NOW - 7_200_000, kind = "script", parent = "deepseek-demo", parentTitle = "DeepSeek 批准示例"),
        )

        val PLAN = """
## 计划：补齐发布说明
1. 读 `docs/release.md` 和最近 10 次提交，列出缺的条目。
2. 按版本分节补写，每条改动一行。
3. 加一节「升级步骤」，写明需要人工确认的地方。
4. 跑一遍文档检查，确认链接都能打开。

改动只在 `docs/` 下，不碰代码。
""".trimIndent()

        val FILES = listOf(
            JSONObject().put("id", "fixture-html").put("name", "安全预览.html").put("path", "D:\\fixture\\安全预览.html").put("kind", "text").put("state", "current").put("size", 900),
            JSONObject().put("id", "fixture-png").put("name", "logo.png").put("path", "D:\\fixture\\images\\logo.png").put("kind", "image").put("state", "current").put("size", 462),
            JSONObject().put("id", "fixture-md").put("name", "说明.md").put("path", "D:\\fixture\\说明.md").put("kind", "text").put("state", "current").put("size", 200),
            // Office files the computer can show as PDF (10-27): the Word one converts, the Excel one fails.
            JSONObject().put("id", "fixture-docx").put("name", "发布说明.docx").put("path", "D:\\fixture\\发布说明.docx").put("kind", "download").put("state", "current").put("size", 18_432).put("preview", "pdf"),
            JSONObject().put("id", "fixture-xlsx").put("name", "预算表.xlsx").put("path", "D:\\fixture\\预算表.xlsx").put("kind", "download").put("state", "current").put("size", 9_216).put("preview", "pdf"),
        )
        /** What the demo computer's Office makes of 发布说明.docx: a valid one-page PDF (1,010 bytes). */
        const val PDF = "JVBERi0xLjQKJeLjz9MKMSAwIG9iago8PCAvVHlwZSAvQ2F0YWxvZyAvUGFnZXMgMiAwIFIgPj4KZW5kb2JqCjIgMCBvYmoKPDwgL1R5cGUgL1BhZ2VzIC9LaWRzIFszIDAgUl0gL0NvdW50IDEgPj4KZW5kb2JqCjMgMCBvYmoKPDwgL1R5cGUgL1BhZ2UgL1BhcmVudCAyIDAgUiAvTWVkaWFCb3ggWzAgMCA2MDAgNDIwXSAvUmVzb3VyY2VzIDw8IC9Gb250IDw8IC9GMSA1IDAgUiA+PiA+PiAvQ29udGVudHMgNCAwIFIgPj4KZW5kb2JqCjQgMCBvYmoKPDwgL0xlbmd0aCA0NjAgPj4Kc3RyZWFtCjAuOTMgMC45NSAxIHJnIDI0IDI0IDU1MiAzNzIgcmUgZgowLjE1IDAuMzkgMC45MiByZyAyNCAzNDAgNTUyIDU2IHJlIGYKQlQgL0YxIDIyIFRmIDEgMSAxIHJnIDQ0IDM2MCBUZCAoUmVsZWFzZSBub3RlcyAtIGRlbW8pIFRqIEVUCkJUIC9GMSAxNSBUZiAwLjEgMC4xIDAuMTIgcmcgNDQgMzAwIFRkIChDb252ZXJ0ZWQgZnJvbSBXb3JkIG9uIHRoZSBjb21wdXRlci4pIFRqIEVUCkJUIC9GMSAxNSBUZiAwLjEgMC4xIDAuMTIgcmcgNDQgMjcwIFRkICgxLiBPcGVuIGEgY29udmVyc2F0aW9uIGF0IHRoZSBsYXRlc3QgbWVzc2FnZXMuKSBUaiBFVApCVCAvRjEgMTUgVGYgMC4xIDAuMSAwLjEyIHJnIDQ0IDI0NSBUZCAoMi4gT2ZmaWNlIGZpbGVzIHNob3cgaW5saW5lIGFzIFBERi4pIFRqIEVUCkJUIC9GMSAxMSBUZiAwLjQ1IDAuNDcgMC41MiByZyA0NCA2MCBUZCAoVGVsZXBseSBsb2NhbCBkZW1vKSBUaiBFVAplbmRzdHJlYW0KZW5kb2JqCjUgMCBvYmoKPDwgL1R5cGUgL0ZvbnQgL1N1YnR5cGUgL1R5cGUxIC9CYXNlRm9udCAvSGVsdmV0aWNhID4+CmVuZG9iagp4cmVmCjAgNgowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwMTUgMDAwMDAgbiAKMDAwMDAwMDA2NCAwMDAwMCBuIAowMDAwMDAwMTIxIDAwMDAwIG4gCjAwMDAwMDAyNDcgMDAwMDAgbiAKMDAwMDAwMDc1NyAwMDAwMCBuIAp0cmFpbGVyCjw8IC9TaXplIDYgL1Jvb3QgMSAwIFIgPj4Kc3RhcnR4cmVmCjgyNwolJUVPRgo="

        val HTML_FILE = """
<script>fetch('https://example.invalid/secret').catch(() => {})</script>
<h1>固定 HTML 页面</h1>
<p>这一页在手机上按网页显示：脚本照常运行，网上的资源照常加载。</p>
<p id="script-state">脚本没有运行</p>
<script>document.getElementById('script-state').textContent = '脚本已运行'</script>
<p><img src="images/logo.png" alt="同目录下的图片"></p>
<table border="1" cellpadding="6"><tr><th>项目</th><th>结果</th></tr><tr><td>脚本</td><td>运行</td></tr><tr><td>同目录的图片</td><td>从电脑上取</td></tr></table>
<p><a href="https://developer.android.com/">点链接用浏览器打开</a></p>
""".trimIndent()

        val MARKDOWN_FILE = "# 说明\n\n这是一个 **Markdown** 文件，默认用阅读视图显示。\n\n- 第一条\n- 第二条\n\n> 也可以切到「查看源码」看原文。"

        const val PNG = "iVBORw0KGgoAAAANSUhEUgAAAGAAAAAoCAIAAACO8WhuAAABlUlEQVR42u3QhzICAAAGYM9CyB4hMyF7JDOrsreydyIzhczISNll772P4zjHcRzHOY7jOOcNPIe7/3uETys+6Tcu+Sc25ZuT+sVJ+2Snf7Ay3lmZbzFZr9Hcl2jec1T2U2TOY2TuQ0TePTP/jllwG154E1Z0HVZ8FVpyGVJ6EVx2Hlx+FsQ/ZVScMATHgZVH9KpDuvAgoHrPv2bXv3bbr27Tt37Dt2HNR7Tq3bjsLV7ykix4Ns17NM96tMy4S6dorRpam9qtfdy1Y8y1c8Sla5gqU1G7lc49Coq8n9Lb59Qnd+zvcRyQOSi67Ac77JTtdqpW2yEpebiZPCKxGRVbj4msxxusJupI6lqSptpyUmgxVWkxLTCf4ZvNlpnNlZrOF5ssFBkvFhgv5Rst5xqu5Biu8gzWuMT1TOJGuv5mmt5Wit52su5OImE3gbAXp7Mfq33A1j5kaSEIQQhCEIIQhCAEIQhBCEIQghCEIAQhCEEIQhCCEIQgBCEIQQhCEIIQhCAEIQhBCEIQghCEIAQhCEEI+m9BfzQ+a2t+SvdoAAAAAElFTkSuQmCC"

        val EXAMPLE = """
# 原生阅读示例
这是一段**固定测试数据**，用于检查阅读与返回。没有连接真实服务。

## 检查项目
- 中文段落与字号
- 局部横向滚动
  - 子列表保持层级
1. 打开对话
2. 返回列表

> 引用内容不会改变复制的原文。

```kotlin
val deviceId = "explicit-device-scope"
val message = "A deliberately long line to verify horizontal scrolling without moving the whole conversation page."
```

| 项目 | 结果 | 说明 |
| --- | --- | --- |
| 身份 | 独立 | 账号 / 电脑 / Codex / 会话 |
| 阅读 | 只读 | 没有发送与批准入口 |

[Android 开发文档](https://developer.android.com/)
""".trimIndent()

        private const val CODEX_STATE = """{"available":true,"settings":{"model":"fixture-model","effort":"medium","mode":"default","service_tier":null},"catalog":{"models":[{"id":"fixture-model","name":"测试模型","efforts":["low","medium"],"default_effort":"medium"}]},"questions":[{"id":"fixture-question","answer_revision":"v1","status":"pending","kind":"native","turn_id":"fixture-question-turn","questions":[{"id":"q1","header":"方案","question":"选择固定测试方案","options":[{"label":"方案A","description":"固定选项"},{"label":"方案B","description":"另一选项"}]}]}]}"""

        /** The computer's record of a send with pictures (state `images`, codex_control.message_images), a picture a name. */
        private fun pictures(request: String, text: String, created: Long, vararg names: String) = JSONObject().put("request_id", request).put("text", text).put("created", created).put("status", "accepted")
            .put("images", JSONArray(names.mapIndexed { i, name -> val id = "fixture-picture-$request-$i"; JSONObject().put("id", id).put("name", name).put("original_size", 462).put("width", 96).put("height", 40).put("url", "/api/codex/image?id=$id").put("thumbnail", "/api/codex/image?thumb=1&id=$id") }))

        /** The Codex plan's first message went with three pictures; Codex keeps the send's request id on it. */
        private val PLAN_PICTURES = JSONArray().put(pictures("fixture-send-plan", "先给我一个计划，确认后再改。", NOW / 1000 - 10_900, "界面草图.png", "现有页面.png", "参考.png")).toString()

        private val CLAUDE_STATE = JSONObject("""{"available":true,"settings":{"model":"opus","effort":"high","mode":"default"},"model_label":"Opus 4.7","effort_label":"高","mode_label":"Manual","mode_options":[{"name":"default","label":"Manual"},{"name":"acceptEdits","label":"Accept edits"},{"name":"plan","label":"Plan"}],"action_revision":"r1","prompt":{"title":"发布说明用哪种格式？","progress":"1 / 2","choices":[{"name":"简洁要点","label":"简洁要点","description":"每条改动一行","token":"t-choice-1","pressed":true},{"name":"完整段落","label":"完整段落","description":"按版本分节，适合对外发布","token":"t-choice-2","pressed":false}],"nav":[{"name":"Skip","label":"跳过","token":"t-nav-skip"}],"other":{"name":"Other"}}}""")
            // The first message went with a picture, 5 s before Claude wrote it down (11:50); Claude keeps no request id.
            .put("images", JSONArray().put(pictures("fixture-send-claude", "帮我把这次的发布说明整理一下。", NOW / 1000 - 605, "发布说明截图.png"))).toString()

        /**
         * Claude's second question as Windows dev.24 lays it out (claude_hooks.py prompt): it takes several, so a ticked
         * option says "✓ " before its words and 提交 has no token until one is ticked ([claudeSecond] fills those in).
         */
        private const val CLAUDE_SECOND = """{"title":"发布说明里还要附上什么？","progress":"2 / 2","choices":[{"name":"升级步骤","label":"升级步骤","description":"在末尾列出升级步骤","token":"t-choice-3","pressed":false},{"name":"已知问题","label":"已知问题","description":"列出还没修好的问题","token":"t-choice-4","pressed":false}],"nav":[{"name":"Show previous question","label":"上一题","token":"t-nav-back"},{"name":"Skip","label":"跳过","token":"t-nav-skip"},{"name":"Submit","label":"提交","token":null}],"other":{"name":"Other"}}"""

        private const val DEEPSEEK_STATE = """{"available":true,"settings":{"provider":"deepseek","model":"deepseek-v4","reasoningEffort":"high"},"permission":"workspace","permission_name":"工作区内修改","interactions":[{"event":"approval/request","eventId":"e-approval-1","request":{"toolName":"shell","reason":"rm -rf build/","displayReason":"删除 build 目录（构建缓存）"}}],"questions":[]}"""
    }
}
