package com.pocketagentdesk.teleply

import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.withContext
import okhttp3.*
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

interface CookieVault {
    fun read(origin: String): String?
    fun write(origin: String, cookie: String?)
}
class MemoryCookieVault : CookieVault {
    private val values = mutableMapOf<String, String>()
    @Synchronized override fun read(origin: String) = values[origin]
    @Synchronized override fun write(origin: String, cookie: String?) { if (cookie == null) values.remove(origin) else values[origin] = cookie }
}
/** A preview past what the phone draws ([limit], 20 MB): the file itself can still be saved and opened elsewhere. */
class PreviewTooLarge(val limit: Long) : Exception("转成的 PDF 超过${limit / (1024 * 1024)}MB预览上限，可保存后使用系统应用打开。")
/** A file saved or shared from the computer, at most (11-15: was 100 MB, user). A preview is read into memory: 100 MB still. */
const val DownloadLimit = 500L * 1024 * 1024
/** A thumbnail is a small WebP (§5.3); this only keeps a wrong answer from filling the phone. */
const val ThumbLimit = 16L * 1024 * 1024
fun serviceOrigin(value: String): HttpUrl {
    val url = value.trim().toHttpUrl()
    require(url.scheme == "https" && url.username.isEmpty() && url.password.isEmpty() && url.query == null && url.fragment == null && url.encodedPath == "/") { "请输入 HTTPS 服务根地址，不含账号、路径或参数。" }
    return url
}
/** Whether [a] and [b] are one service address, however written ("https://host" or "https://host/"); never for a non-address. */
fun sameService(a: String, b: String) = runCatching { serviceOrigin(a) == serviceOrigin(b) }.getOrDefault(false)
/** Protocol handshake (plan §3.3): every request carries protocol 2 and client tag; streams/images/downloads also carry query params. */
const val TeleplyProtocol = 2
fun teleplyClientTag(): String = "android/${BuildConfig.VERSION_NAME}"

/** A media stream's address and the headers the file routes carry (Cookie, protocol, client) for MediaPlayer/VideoView. */
data class MediaSource(val url: String, val headers: Map<String, String>)

interface ReadApi {
    fun forSource(app:String):ReadApi = this
    /** Assistant manifests from GET /api/agents; null when the computer does not have it (404 / legacy host). */
    suspend fun agents(device:String):List<AgentInfo>? = null
    suspend fun detail(device:String,route:String,query:Map<String,String?> = emptyMap(),body:JSONObject?=null):JSONObject = error("当前服务不支持此功能")
    suspend fun upload(device:String,chat:String,name:String,bytes:ByteArray,image:Boolean,draft:Boolean=false):JSONObject = error("上传不可用")
    suspend fun uploadStream(device:String,chat:String,name:String,size:Long,image:Boolean,draft:Boolean=false,open:()->java.io.InputStream):JSONObject = error("流式上传不可用")
    suspend fun download(device:String,chat:String,file:String):ByteArray = error("下载不可用")
    suspend fun downloadTo(device:String,chat:String,file:String,output:java.io.OutputStream) { output.write(download(device,chat,file)) }
    /** A picture the computer kept of a send (GET /api/codex/image by its id; [small]: its copy of at most 320 px). */
    suspend fun sentPicture(device:String,id:String,small:Boolean,output:java.io.OutputStream) { error("下载不可用") }
    /** A file's thumbnail for an answer or its file strip (GET /api/file/thumb, file-preview design §5.3). */
    suspend fun thumb(device:String,chat:String,file:String,width:Int,version:String):ByteArray = error("缩略图不可用")
    /** A same-folder resource a Markdown or HTML file names (GET /api/file/resource, §5.6). */
    suspend fun fileResource(device:String,chat:String,file:String,path:String):ByteArray = throw ServiceFailure(404,detail="这台电脑还不能给附属文件")
    /** A zip's listing (GET /api/file/zip, §5.7). */
    suspend fun fileZip(device:String,chat:String,file:String):JSONObject = throw ServiceFailure(404,detail="这台电脑还不能读压缩包")
    /** Where a file's bytes stream from, with the same cookie and protocol headers as every request (§6.2 audio/video). */
    suspend fun mediaSource(device:String,chat:String,file:String,version:String):MediaSource = throw ServiceFailure(404,detail="这台电脑还不能播放")
    /** A Word, Excel or PowerPoint file as the computer's Office turns it into PDF (GET /api/file/pdf, 10-27), at most [limit] bytes. */
    suspend fun filePdf(device:String,chat:String,file:String,limit:Long):ByteArray = throw ServiceFailure(404,detail="这里不能把文件转成 PDF")
    fun events(device: String, chat: String): kotlinx.coroutines.flow.Flow<LiveFrame> = kotlinx.coroutines.flow.emptyFlow()
    /** [fresh]: read the desktop now; otherwise the computer may answer from its read of the last 4 s (web state polls). */
    suspend fun control(device: String, chat: String, fresh: Boolean = true): Control = Control()
    suspend fun command(device: String, route: String, body: JSONObject): JSONObject = error("当前来源不支持操作")
    suspend fun receipt(device: String, chat: String, request: String): JSONObject = JSONObject().put("state","unknown")
    /** The computer's voice service (web voice-ui.js): raw audio up, recognised text back. */
    suspend fun voice(device:String,route:String,query:Map<String,String?> = emptyMap(),bytes:ByteArray?=null,type:String="application/octet-stream"):JSONObject = throw ServiceFailure(404,detail="这台电脑没开语音")
    suspend fun config(): String
    /** /account/config whole: the version and whether email sign-up and resets are open (web account page). */
    suspend fun accountConfig(): JSONObject = JSONObject().put("version", config())
    suspend fun login(name: String, password: String)
    /** 退出登录: the service ends the sign-in and the cookie here is dropped (web account menu). */
    suspend fun logout() {}
    /** 我的电脑's ⋯ (web device menu): a new name, or remote access taken away (the computer's files stay). */
    suspend fun renameDevice(device: String, label: String) { error("当前服务不支持重命名电脑") }
    suspend fun revokeDevice(device: String) { error("当前服务不支持移除电脑") }
    /** 删除账号 (web account menu): the password again; the account, its email, computers and notices go for good. */
    suspend fun deleteAccount(password: String) { error("当前服务不支持删除账号") }
    /** 遥应通知's phone registration (design-2 §1.1), with this phone's sign-in cookie; [token] is sha256 of its key. */
    suspend fun pushRegister(token: String, label: String, version: String, language: String): JSONObject = throw ServiceFailure(404, detail = "这个服务还没有安卓通知")
    suspend fun pushState(token: String): JSONObject = throw ServiceFailure(404, detail = "这个服务还没有安卓通知")
    suspend fun pushUnregister(token: String): JSONObject = throw ServiceFailure(404, detail = "这个服务还没有安卓通知")
    /** 试推一条: the relay pushes one notice down this phone's own WebSocket. */
    suspend fun pushTest(token: String): JSONObject = throw ServiceFailure(404, detail = "这个服务还没有安卓通知")
    suspend fun account(): Account
    suspend fun select(device: String)
    suspend fun chats(device: String, query: String, cursor: String?): Page<Chat>
    /** The web list (spec 4.1): [app] is "all" or one source; [sort] updated / created; [status] all / running / waiting / done. */
    suspend fun chatList(device: String, app: String, query: String, cursor: String?, sort: String = "updated", status: String = "all"): Page<Chat> =
        chats(device, query, cursor).let { page -> page.copy(items=page.items.map { if(it.app.isBlank()) it.copy(app=if(app=="all") "codex" else app) else it }) }
    /** [count]: the latest messages to read (web: 60 for the page, 5 to see a conversation is there before opening it). */
    suspend fun history(device: String, chat: String, before: String? = null, around: String? = null, count: Int = 60): Page<Message>
    suspend fun message(device: String, chat: String, message: String): Message
    suspend fun search(device: String, chat: String, query: String, cursor: String?): Page<Message>
    fun close()
}
class RelayApi(origin: String, private val vault: CookieVault, baseClient: OkHttpClient = OkHttpClient(),private val app:String="codex",val catalog:AgentCatalog=AgentCatalog()) : ReadApi {
    init { require(isValidAgentId(app)) { "来源应用无效" } }
    override fun forSource(app:String):ReadApi = RelayApi(root.toString(),vault,client,app,catalog)
    val root = serviceOrigin(origin)
    private val key = root.toString()
    // No automatic redirects (including same-host HTTPS -> HTTP), no browser CookieJar.
    private val client = baseClient.newBuilder().cookieJar(CookieJar.NO_COOKIES)
        .followRedirects(false).followSslRedirects(false).retryOnConnectionFailure(false)
        .connectTimeout(15, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS).callTimeout(40, TimeUnit.SECONDS).build()
    /** Saving or sharing a file: an hour in all, a minute of silence (11-15: the 40 s of every call cut big files off). */
    internal val fileClient = client.newBuilder().callTimeout(3600, TimeUnit.SECONDS).readTimeout(60, TimeUnit.SECONDS).build()
    /**
     * The notification stream (design-2 §1.2): no call limit and no read timeout, a ping every 180 s, so the phone wakes
     * for it three minutes apart. The relay answers pong itself.
     */
    internal val pushClient = client.newBuilder().callTimeout(0, TimeUnit.SECONDS).readTimeout(0, TimeUnit.SECONDS).pingInterval(180, TimeUnit.SECONDS).build()
    override fun close() { client.dispatcher.cancelAll() }
    private fun devicePath(device: String, route: String): String {
        require(Regex("[0-9a-f]{32}").matches(device)) { "电脑标识无效" }
        return "/d/$device$route"
    }
    private fun Request.Builder.withProtocolHeaders(): Request.Builder =
        header("X-Teleply-Protocol", "$TeleplyProtocol").header("X-Teleply-Client", teleplyClientTag())
    private fun HttpUrl.Builder.withProtocolQuery(): HttpUrl.Builder =
        addQueryParameter("protocol", "$TeleplyProtocol").addQueryParameter("client", teleplyClientTag())
    /** [timeout] in seconds, for the actions the computer takes long over (Claude's buttons, archiving, voice). */
    private suspend fun request(path: String, query: Map<String,String?> = emptyMap(), body: JSONObject? = null, bytes:ByteArray?=null,stream:RequestBody?=null,timeout:Long=0,type:String="application/octet-stream"): JSONObject = withContext(Dispatchers.IO) {
        val url = root.newBuilder().encodedPath(path).apply { query.forEach { (k,v) -> if (v != null) addQueryParameter(k,v) } }.build()
        val builder = Request.Builder().url(url).header("Accept", "application/json").withProtocolHeaders()
        vault.read(key)?.let { raw -> Cookie.parse(root, raw)?.takeIf { it.expiresAt > System.currentTimeMillis() }?.let { builder.header("Cookie", "${it.name}=${it.value}") } }
        if (body != null) builder.header("Origin", key.removeSuffix("/")).post(body.toString().toRequestBody("application/json; charset=utf-8".toMediaType()))
        if(bytes!=null) builder.header("Origin",key.removeSuffix("/")).post(bytes.toRequestBody(type.toMediaType()))
        if(stream!=null) builder.header("Origin",key.removeSuffix("/")).post(stream)
        val caller = if(timeout>0) client.newBuilder().callTimeout(timeout,TimeUnit.SECONDS).readTimeout(timeout,TimeUnit.SECONDS).build() else client
        val call = caller.newCall(builder.build())
        // 诊断测速 times the requests that carry a message or a file (web: the same routes, POST only).
        val timer = if(body!=null || bytes!=null || stream!=null) Diagnostics.start(Diagnostics.labelFor(path.replace(DevicePrefix,""))) else null
        val size = bytes?.size?.toLong() ?: stream?.contentLength() ?: 0L
        try { timed(call).also { answer ->
            // 11-27 S3: the computer's own part of the answer, when it says; the toast then shows 手机→电脑 and 电脑处理.
            val server=if (answer.has("server_ms")) answer.optLong("server_ms",-1).takeIf { it>=0 } else null
            Diagnostics.finish(timer,size,speedOutcome(answer),serverMs=server)
        } }
        catch(e:Exception) {
            Diagnostics.finish(timer,size,when(e) { is ServiceFailure -> "HTTP ${e.status}"; is kotlinx.coroutines.CancellationException,is java.io.InterruptedIOException -> "已取消或超时"; else -> "网络失败" })
            throw e
        }
    }
    private suspend fun timed(call:Call):JSONObject {
        val path=call.request().url.encodedPath
        return suspendCancellableCoroutine { continuation ->
            continuation.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) { if (continuation.isActive) continuation.resumeWithException(e) }
                override fun onResponse(call: Call, response: Response) {
                    try { response.use { r ->
                        // Bound JSON size; no raw response/error text is logged or exposed.
                        val source = r.body?.source() ?: throw IOException("服务未返回内容")
                        if (source.request(8L * 1024 * 1024 + 1)) throw IOException("内容过大，请缩小读取范围")
                        val raw = source.readUtf8()
                        if (!continuation.isActive) return
                        if (!r.isSuccessful) {
                            if (r.code == 401) vault.write(key, null)
                            val error=runCatching { JSONObject(raw) }.getOrDefault(JSONObject())
                            throw ServiceFailure(r.code,error.string("code"),error.string("error"),error.optBoolean("not_submitted"),error.string("draft"))
                        }
                        val json = JSONObject(raw)
                        if (path == "/account/login") {
                            val cookie = Cookie.parseAll(root, r.headers).firstOrNull { it.name == "__Host-ar_account" && it.secure && it.httpOnly && it.hostOnly && it.path == "/" }
                                ?: throw IOException("登录响应缺少有效的账号凭据")
                            vault.write(key, cookie.toString())
                        }
                        if (continuation.isActive) continuation.resume(json)
                    } } catch (e: Exception) { if (continuation.isActive) continuation.resumeWithException(e) }
                }
            })
        }
    }
    override suspend fun config() = request("/account/config").string("version")
    override suspend fun accountConfig() = request("/account/config")
    override suspend fun logout() { try { request("/account/logout", body = JSONObject()) } finally { vault.write(key, null) } }
    override suspend fun renameDevice(device: String, label: String) { devicePath(device, ""); request("/account/rename", body = JSONObject().put("id", device).put("label", label)) }
    override suspend fun revokeDevice(device: String) { devicePath(device, ""); request("/account/revoke", body = JSONObject().put("id", device)) }
    /** Done, the service has ended every sign-in of the account: the cookie here goes too, as for 退出登录. */
    override suspend fun deleteAccount(password: String) { request("/account/delete", body = JSONObject().put("password", password)); vault.write(key, null) }
    // 遥应通知's phone registration (design-2 §1.1). The relay stores only the fingerprint; `platform` tells its records
    // this is not an APNs token, so its iPhone paths never see it.
    override suspend fun pushRegister(token: String, label: String, version: String, language: String): JSONObject = request(
        "/account/push/register",
        body = JSONObject().put("token", token).put("platform", "android").put("environment", "relay").put("label", label.take(40)).put("version", version).put("language", language),
    )
    override suspend fun pushState(token: String): JSONObject = request("/account/push/state", body = JSONObject().put("token", token))
    override suspend fun pushUnregister(token: String): JSONObject = request("/account/push/unregister", body = JSONObject().put("token", token))
    override suspend fun pushTest(token: String): JSONObject = request("/account/push/test", body = JSONObject().put("token", token))
    /**
     * One WebSocket to `wss://<service>/push/android` (design-2 §1.2): the key in `Authorization: Bearer`, the place it
     * reached in `since`, nothing else. No cookie: the relay finds the account by sha256(key) in push_phones.
     */
    fun pushWebSocket(secret: String, since: String?, listener: WebSocketListener): WebSocket {
        require(secret.isNotBlank()) { "推送钥匙为空" }
        // An https address is what OkHttp upgrades to wss; HttpUrl itself only knows http and https.
        val url = root.newBuilder().encodedPath("/push/android").apply { if (!since.isNullOrBlank()) addQueryParameter("since", since) }.build()
        val request = Request.Builder().url(url).header("Authorization", "Bearer $secret").withProtocolHeaders().build()
        return pushClient.newWebSocket(request, listener)
    }
    override suspend fun agents(device: String): List<AgentInfo>? = try {
        val parsed = parseAgentsResponse(request(devicePath(device, "/api/agents")))
        catalog.put(device, parsed)
        parsed
    } catch (e: ServiceFailure) {
        if (e.status == 404) { catalog.put(device, null); null } else throw e
    }
    /** `remote.py` lines 712 & 896 return `404 {"error":"没有这个地址"}` for any unknown route (GET/POST). */
    private fun isMissingRoute404(e: ServiceFailure): Boolean = e.status == 404 && e.detail == "没有这个地址"

    /**
     * Tries the unified `/api/agents/<id>/...` route first; goes directly to [legacy] when [catalog] already knows
     * [device] lacks `/api/agents` or unified routes. Only marks [device] on route-missing 404 (`没有这个地址`), never on
     * conversation-not-found or unknown-source 404s.
     */
    private suspend fun <T> withLegacyFallback(
        device: String,
        allowFallback: Boolean,
        primary: suspend () -> T,
        legacy: suspend () -> T,
    ): T {
        if (allowFallback && catalog.shouldSkipUnified(device)) return legacy()
        return try {
            primary()
        } catch (e: ServiceFailure) {
            if (!allowFallback || e.status != 404) throw e
            when {
                isMissingRoute404(e) -> {
                    catalog.markUnifiedUnsupported(device)
                    legacy()
                }
                e.detail == "没有这个接口" -> legacy()
                else -> throw e
            }
        }
    }

    override suspend fun detail(device:String,route:String,query:Map<String,String?>,body:JSONObject?):JSONObject {
        require(route in DetailRoutes)
        val timeout = SlowRoutes[route] ?: 0L
        return when (route) {
            "status" -> request(devicePath(device, "/api/status"), query, body, timeout = timeout).also { result ->
                val ver = result.string("ui_version").ifBlank { result.string("version") }
                if (ver.isNotBlank()) catalog.updateVersion(device, ver)
            }
            "chat/open" -> {
                val target = body?.string("app")?.takeIf { isValidAgentId(it) } ?: app
                withLegacyFallback(device, true, { request(devicePath(device, "/api/agents/$target/open"), body = body, timeout = timeout) }) {
                    request(devicePath(device, "/api/chat/open"), query, body, timeout = timeout)
                }
            }
            "chat/new" -> {
                val target = body?.string("app")?.takeIf { isValidAgentId(it) } ?: app
                withLegacyFallback(device, true, { request(devicePath(device, "/api/agents/$target/create"), body = body, timeout = timeout) }) {
                    request(devicePath(device, "/api/chat/new"), query, body, timeout = timeout)
                }
            }
            "chat/new/state" -> {
                val target = query["app"]?.takeIf { isValidAgentId(it) } ?: app
                val clean = query.filterKeys { it != "app" }
                withLegacyFallback(device, true, { request(devicePath(device, "/api/agents/$target/create/state"), clean, timeout = timeout) }) {
                    request(devicePath(device, "/api/chat/new/state"), clean, timeout = timeout)
                }
            }
            "chat/new/options" -> {
                val target = query["app"]?.takeIf { isValidAgentId(it) } ?: app
                withLegacyFallback(device, true, { request(devicePath(device, "/api/agents/$target/options"), timeout = timeout) }) {
                    request(devicePath(device, "/api/chat/new/options"), query, timeout = timeout)
                }
            }
            "claude/choose", "claude/next", "claude/task" -> withLegacyFallback(device, true, {
                request(devicePath(device, "/api/agents/claude/answer"), body = body, timeout = timeout)
            }) {
                request(devicePath(device, "/api/$route"), query, body, timeout = timeout)
            }
            "deepseek/approval", "deepseek/answer" -> withLegacyFallback(device, true, {
                request(devicePath(device, "/api/agents/deepseek/answer"), body = body, timeout = timeout)
            }) {
                request(devicePath(device, "/api/$route"), query, body, timeout = timeout)
            }
            else -> request(devicePath(device, "/api/$route"), query, body, timeout = timeout)
        }
    }
    override suspend fun voice(device:String,route:String,query:Map<String,String?>,bytes:ByteArray?,type:String):JSONObject {
        require(route in setOf("voice","voice/stream/start","voice/stream/chunk","voice/stream/end","voice/stream/cancel","voice/stream/cloud"))
        // A whole recording, or the end of one, waits for recognition (and 整理) on the computer.
        val slow=route=="voice" || route=="voice/stream/end" || route=="voice/stream/cloud"
        return request(devicePath(device,"/api/$route"),query,bytes=bytes ?: ByteArray(0),timeout=if(slow) 125 else 35,type=type)
    }
    private companion object {
        val DevicePrefix=Regex("^/d/[0-9a-f]{32}")
        val LegacyApps=setOf("codex","claude","deepseek")
        /** Fields of DeepSeek's state that change on every read while it works and that the phone does not show. */
        val DeepSeekUnshown=listOf("seq","subagents","inbox")
        val DetailRoutes=setOf("chat/new/options","chat/folders","chat/new/draft","chat/new","chat/new/state","chat/new/retry","chat/new/references","composer/references","files/places","files/list","files/image","files/remove","codex/remove-attachment","codex/attachments","chat/files","chat/diff","file/text","file/meta","file/zip","deepseek/models","deepseek/permissions","deepseek/model","deepseek/permission","deepseek/answer","deepseek/approval","claude/catalog","claude/setting","claude/choose","claude/menu","claude/close-menu","chat/projects","chat/open","chat/resolve",
            "claude/next","claude/task","chat/check","chat/archive","chat/unarchive","chat/delete","chat/archived","chats/children","notify","notify/ntfy","notify/automations","notify/test","voice/status","voice/terms","voice/tidy","status","usage","usage/codex-reset")
        /** Seconds the computer may take: Claude's buttons wait for its window (web 65 s), archiving for its records. */
        val SlowRoutes=mapOf("claude/next" to 65L,"claude/task" to 65L,"chat/archive" to 65L,"chat/unarchive" to 95L,"chat/delete" to 125L,"chat/archived" to 25L,"notify" to 35L,"notify/ntfy" to 35L,"notify/automations" to 35L,"notify/test" to 35L,"voice/tidy" to 65L,"status" to 10L,"usage" to 45L,"usage/codex-reset" to 75L)
    }
    override suspend fun upload(device:String,chat:String,name:String,bytes:ByteArray,image:Boolean,draft:Boolean):JSONObject {
        require(bytes.isNotEmpty() && bytes.size <= if(image) 20*1024*1024 else 100*1024*1024) { "文件超过上传上限" }
        val keyParam = if(draft) "draft" else "id"
        if (!image) return request(devicePath(device,"/api/files/upload"),mapOf("app" to app,keyParam to chat,"name" to name),bytes=bytes)
        return withLegacyFallback(device, true, {
            request(devicePath(device,"/api/agents/$app/upload"),mapOf(keyParam to chat,"name" to name),bytes=bytes)
        }) {
            request(devicePath(device,"/api/codex/upload"),mapOf("app" to app,keyParam to chat,"name" to name),bytes=bytes)
        }
    }
    override suspend fun uploadStream(device:String,chat:String,name:String,size:Long,image:Boolean,draft:Boolean,open:()->java.io.InputStream):JSONObject {
        require(size>0 && size<=if(image) 20L*1024*1024 else 100L*1024*1024) { "文件超过上传上限" }
        fun makeBody()=object:RequestBody() {
            override fun contentType()="application/octet-stream".toMediaType()
            override fun contentLength()=size
            override fun writeTo(sink:okio.BufferedSink) { open().use { input -> val buffer=ByteArray(65536);var written=0L;while(true) { val n=input.read(buffer);if(n<0) break;written+=n;if(written>size) throw IOException("所选文件已变化");sink.write(buffer,0,n) };if(written!=size) throw IOException("文件读取不完整") } }
        }
        val keyParam = if(draft) "draft" else "id"
        if (!image) return request(devicePath(device,"/api/files/upload"),mapOf("app" to app,keyParam to chat,"name" to name),stream=makeBody())
        return withLegacyFallback(device, true, {
            request(devicePath(device,"/api/agents/$app/upload"),mapOf(keyParam to chat,"name" to name),stream=makeBody())
        }) {
            request(devicePath(device,"/api/codex/upload"),mapOf("app" to app,keyParam to chat,"name" to name),stream=makeBody())
        }
    }
    override suspend fun downloadTo(device:String,chat:String,file:String,output:java.io.OutputStream) =
        streamTo(root.newBuilder().encodedPath(devicePath(device,"/api/file")).addQueryParameter("app",app).addQueryParameter("id",chat).addQueryParameter("file",file).withProtocolQuery().build(),output)
    override suspend fun sentPicture(device:String,id:String,small:Boolean,output:java.io.OutputStream) =
        streamTo(root.newBuilder().encodedPath(devicePath(device,"/api/codex/image")).apply { if(small) addQueryParameter("thumb","1") }.addQueryParameter("id",id).withProtocolQuery().build(),output)
    /** §5.3: `app`, the conversation's id, the file's id, a width the computer accepts and the file's `v`. */
    override suspend fun thumb(device:String,chat:String,file:String,width:Int,version:String):ByteArray {
        val url=root.newBuilder().encodedPath(devicePath(device,"/api/file/thumb"))
            .addQueryParameter("app",app).addQueryParameter("id",chat).addQueryParameter("file",file)
            .addQueryParameter("w","$width").apply { if(version.isNotBlank()) addQueryParameter("v",version) }
            .withProtocolQuery().build()
        return fetch(url,ThumbLimit,client)
    }
    /** §5.6: the file's own folder, checked by the computer; the same cookie and protocol as every request. */
    override suspend fun fileResource(device:String,chat:String,file:String,path:String):ByteArray {
        val url=root.newBuilder().encodedPath(devicePath(device,"/api/file/resource"))
            .addQueryParameter("app",app).addQueryParameter("id",chat).addQueryParameter("file",file)
            .addQueryParameter("path",path).withProtocolQuery().build()
        return fetch(url,64L*1024*1024,client)
    }
    /** §5.7: only the listing, never the archive's bytes. */
    override suspend fun fileZip(device:String,chat:String,file:String):JSONObject =
        detail(device,"file/zip",mapOf("app" to app,"id" to chat,"file" to file))
    /** §6.2: MediaPlayer/VideoView open this address with these headers, and stream it themselves. */
    override suspend fun mediaSource(device:String,chat:String,file:String,version:String):MediaSource {
        val url=root.newBuilder().encodedPath(devicePath(device,"/api/file"))
            .addQueryParameter("app",app).addQueryParameter("id",chat).addQueryParameter("file",file)
            .apply { if(version.isNotBlank()) addQueryParameter("v",version) }
            .withProtocolQuery().build()
        val headers=mutableMapOf("X-Teleply-Protocol" to "$TeleplyProtocol","X-Teleply-Client" to teleplyClientTag())
        vault.read(key)?.let { raw -> Cookie.parse(root,raw)?.takeIf { it.expiresAt>System.currentTimeMillis() }?.let { headers["Cookie"]="${it.name}=${it.value}" } }
        return MediaSource(url.toString(),headers)
    }
    /**
     * A Word, Excel or PowerPoint file as the computer's Office turns it into PDF (10-27). The first time a version is
     * asked for, Office may take 5-30 s to start before a byte comes, so this waits much longer than other requests;
     * later the computer answers from its copy. The computer's own words when it cannot ({"error": …}).
     */
    override suspend fun filePdf(device:String,chat:String,file:String,limit:Long):ByteArray {
        val url=root.newBuilder().encodedPath(devicePath(device,"/api/file/pdf")).addQueryParameter("app",app).addQueryParameter("id",chat).addQueryParameter("file",file).withProtocolQuery().build()
        val timer=Diagnostics.start(Diagnostics.Labels["/api/file/pdf"])
        return try { fetch(url,limit,client.newBuilder().readTimeout(90,TimeUnit.SECONDS).callTimeout(150,TimeUnit.SECONDS).build()).also { Diagnostics.finish(timer,it.size.toLong(),"请求完成") } }
        catch(e:Exception) { Diagnostics.finish(timer,0,when(e) { is ServiceFailure -> "HTTP ${e.status}"; is kotlinx.coroutines.CancellationException,is java.io.InterruptedIOException -> "已取消或超时"; else -> "网络失败" });throw e }
    }
    /** The bytes of a GET, at most [limit] ([PreviewTooLarge] past it); a refusal carries the computer's words, as the JSON routes do. */
    private suspend fun fetch(url:HttpUrl,limit:Long,caller:OkHttpClient):ByteArray = suspendCancellableCoroutine { continuation ->
        val builder=Request.Builder().url(url).withProtocolHeaders()
        vault.read(key)?.let { Cookie.parse(root,it)?.takeIf { c -> c.expiresAt>System.currentTimeMillis() }?.let { c -> builder.header("Cookie","${c.name}=${c.value}") } }
        val call=caller.newCall(builder.build());continuation.invokeOnCancellation { call.cancel() }
        call.enqueue(object:Callback {
            override fun onFailure(call:Call,e:IOException) { if(continuation.isActive) continuation.resumeWithException(e) }
            override fun onResponse(call:Call,response:Response) {
                try { response.use { r ->
                    val source=r.body?.source() ?: throw IOException("电脑没有返回内容")
                    if(!r.isSuccessful) {
                        val raw=if(source.request(64L*1024+1)) "" else source.readUtf8()
                        val error=runCatching { JSONObject(raw) }.getOrDefault(JSONObject())
                        throw ServiceFailure(r.code,error.string("code"),error.string("error"))
                    }
                    if((r.body?.contentLength() ?: -1L)>limit || source.request(limit+1)) throw PreviewTooLarge(limit)
                    val bytes=source.readByteArray()
                    if(continuation.isActive) continuation.resume(bytes)
                } } catch(e:Exception) { if(continuation.isActive) continuation.resumeWithException(e) }
            }
        })
    }
    /** A file from the computer into [output], at most [DownloadLimit], whole or with an error. */
    private suspend fun streamTo(url:HttpUrl,output:java.io.OutputStream):Unit = suspendCancellableCoroutine { continuation ->
        val builder=Request.Builder().url(url).withProtocolHeaders()
        vault.read(key)?.let { Cookie.parse(root,it)?.takeIf { c -> c.expiresAt>System.currentTimeMillis() }?.let { c -> builder.header("Cookie","${c.name}=${c.value}") } }
        val call=fileClient.newCall(builder.build());continuation.invokeOnCancellation { call.cancel() }
        call.enqueue(object:Callback {
            override fun onFailure(call:Call,e:IOException) { if(continuation.isActive) continuation.resumeWithException(e) }
            override fun onResponse(call:Call,response:Response) {
                try { response.use { r ->
                    if(!r.isSuccessful) throw ServiceFailure(r.code)
                    require((r.body?.contentLength() ?: 0)<=DownloadLimit) { "文件超过500MB，请在电脑上打开" }
                    val input=r.body?.byteStream() ?: throw IOException("文件为空");val buffer=ByteArray(65536);var count=0L
                    while(true) { if(!continuation.isActive) return;val n=input.read(buffer);if(n<0) break;count+=n;require(count<=DownloadLimit) { "文件超过500MB，请在电脑上打开" };output.write(buffer,0,n) }
                    val expected=r.body?.contentLength() ?: -1L
                    require(expected<0 || count==expected) { "文件接收不完整，请重试" }
                    output.flush();if(continuation.isActive) continuation.resume(Unit)
                } } catch(e:Exception) { if(continuation.isActive) continuation.resumeWithException(e) }
            }
        })
    }
    override suspend fun download(device:String,chat:String,file:String):ByteArray = suspendCancellableCoroutine { continuation ->
        val url=root.newBuilder().encodedPath(devicePath(device,"/api/file")).addQueryParameter("app",app).addQueryParameter("id",chat).addQueryParameter("file",file).withProtocolQuery().build()
        val builder=Request.Builder().url(url).withProtocolHeaders()
        vault.read(key)?.let { Cookie.parse(root,it)?.takeIf { c -> c.expiresAt>System.currentTimeMillis() }?.let { c -> builder.header("Cookie","${c.name}=${c.value}") } }
        val call=client.newCall(builder.build());continuation.invokeOnCancellation { call.cancel() }
        call.enqueue(object:Callback {
            override fun onFailure(call:Call,e:IOException) { if(continuation.isActive) continuation.resumeWithException(e) }
            override fun onResponse(call:Call,response:Response) {
                try { response.use { r ->
                    if(!r.isSuccessful) throw ServiceFailure(r.code)
                    val input=r.body?.source() ?: throw IOException("文件为空")
                    require(!input.request(100L*1024*1024+1)) { "文件超过100MB，请在电脑上打开" }
                    val bytes=input.readByteArray()
                    if(continuation.isActive) continuation.resume(bytes)
                } } catch(e:Exception) { if(continuation.isActive) continuation.resumeWithException(e) }
            }
        })
    }
    override suspend fun login(name: String, password: String) { request("/account/login", body = JSONObject().put("name", name).put("password", password)) }
    override suspend fun account(): Account = request("/account/state").let { j -> Account(j.rows("devices") { Computer(it.getString("id"), it.string("label"), it.optBoolean("connectable")) }, j.string("email")) }
    override suspend fun select(device: String) {
        devicePath(device, "")
        val result = request("/account/select", body = JSONObject().put("id", device))
        require(result.string("url") == "/d/$device/") { "服务返回的电脑路径不匹配" }
    }
    override suspend fun chats(device: String, query: String, cursor: String?) = request(devicePath(device,"/api/chats"), mapOf("app" to app, "limit" to "40", "query" to query, "cursor" to cursor)).let { j ->
        Page(j.rows("items") { require(it.string("app") == app) { "来源应用不匹配" }; parseChat(it) }, j.string("next_cursor").ifBlank { null }, j.optBoolean("has_more"))
    }
    override suspend fun chatList(device: String, app: String, query: String, cursor: String?, sort: String, status: String): Page<Chat> {
        require(app == "all" || isValidAgentId(app)) { "来源应用无效" }
        return request(devicePath(device,"/api/chats"), mapOf("app" to app, "limit" to "40", "query" to query, "cursor" to cursor, "sort" to sort, "status" to status)).let { j ->
            Page(j.rows("items") { val c=parseChat(it); require(isValidAgentId(c.app) && (app=="all" || c.app==app)) { "来源应用不匹配" }; c }, j.string("next_cursor").ifBlank { null }, j.optBoolean("has_more"))
        }
    }
    override suspend fun history(device: String, chat: String, before: String?, around: String?, count: Int) = request(devicePath(device,"/api/chat"), mapOf("app" to app, "id" to chat, "n" to "$count", "before" to before, "around" to around, "lite" to "1")).let { j ->
        require(j.string("id") == chat && j.string("app") == app) { "对话身份不匹配" }
        // Title, folder, status and runtime (context ring, 会话状态) travel with the page, not with each message.
        val meta=JSONObject().apply { listOf("title","folder","cwd","status","runtime").forEach { k -> if(j.has(k) && !j.isNull(k)) put(k,j.get(k)) } }
        Page(j.rows("messages", ::parseMessage), j.string("next_cursor").ifBlank { null }, j.optBoolean("has_more"), j.optBoolean("has_newer"), j.optBoolean("reset"), meta.toString())
    }
    override suspend fun message(device: String, chat: String, message: String) = request(devicePath(device,"/api/chat/message"), mapOf("app" to app, "id" to chat, "message" to message)).let { j ->
        parseMessage(j).also { require(it.id == message) { "消息身份不匹配" } }
    }
    override suspend fun search(device: String, chat: String, query: String, cursor: String?) = request(devicePath(device,"/api/chat/search"), mapOf("app" to app, "id" to chat, "query" to query, "cursor" to cursor)).let { j ->
        Page(j.rows("items") { Message(it.getString("id"), it.string("role"), it.string("snippet")) }, j.string("next_cursor").ifBlank { null }, j.optBoolean("has_more"))
    }
    /**
     * The conversation's state. DeepSeek's carries its record's sequence number, its subagents' times and its raw inbox:
     * they change on every read while it works and the phone shows none of them (it uses `queued`). Left out, a poll
     * that finds nothing new is the same state, and the page is not drawn again (10-27, every 2.5 s).
     */
    override suspend fun control(device: String, chat: String, fresh: Boolean): Control {
        val stateTimeout = catalog.forDevice(device).params(app).stateTimeoutS
        val timeout = if (stateTimeout == 40L) 0L else stateTimeout
        val query = mapOf("id" to chat, "fresh" to if (fresh) "1" else null)
        val raw = withLegacyFallback(device, app in LegacyApps, {
            request(devicePath(device, "/api/agents/$app/state"), query, timeout = timeout)
        }) {
            request(devicePath(device, "/api/$app/state"), query, timeout = timeout)
        }
        return parseControl(raw.apply { if (app == "deepseek") { put("queue_available", true); DeepSeekUnshown.forEach { remove(it) } } })
    }
    override suspend fun command(device: String, route: String, body: JSONObject): JSONObject {
        // 11-27 S2 (design §6.4): kill-command ends only the running command, never the turn.
        require(route in setOf("send","stop","queue-action","answer","kill-command"))
        return when (app) {
            "deepseek" -> {
                val outgoing = JSONObject(body.toString())
                val (unifiedAction, legacyAction) = when (route) {
                    "send" -> { if (outgoing.string("intent") == "auto") outgoing.put("intent", "steer"); "send" to "send" }
                    "stop" -> { outgoing.put("expected_turn", body.string("turn_id")); "stop" to "stop" }
                    // 立即补充 is "steer" for DeepSeek, 撤回 is "remove".
                    "queue-action" -> { outgoing.put("item_id", body.string("message_id")).put("action", if (body.string("action") == "promote") "steer" else "remove"); "queue" to "queue" }
                    else -> "answer" to route
                }
                val result = withLegacyFallback(device, true, {
                    request(devicePath(device, "/api/agents/deepseek/$unifiedAction"), body = outgoing)
                }) {
                    request(devicePath(device, "/api/deepseek/$legacyAction"), body = outgoing)
                }
                if (route == "send" && result.optBoolean("accepted")) result.put("delivery_state", if (outgoing.string("intent") == "queue") "queued" else "accepted")
                result
            }
            "claude" -> when (route) {
                "send" -> {
                    val unifiedBody = JSONObject(body.toString()).put("intent", "send").apply { remove("expected_turn") }
                    withLegacyFallback(device, true, {
                        request(devicePath(device, "/api/agents/claude/send"), body = unifiedBody)
                    }) {
                        request(devicePath(device, "/api/chat/send"), body = JSONObject(body.toString()).put("app", "claude"))
                    }
                }
                "stop" -> {
                    require(body.string("token").isNotBlank()) { "Claude 的停止与队列动作需使用当前桌面令牌" }
                    withLegacyFallback(device, true, {
                        request(devicePath(device, "/api/agents/claude/stop"), body = body)
                    }) {
                        request(devicePath(device, "/api/claude/choose"), body = body)
                    }
                }
                else -> throw IllegalArgumentException("Claude 的停止与队列动作需使用当前桌面令牌")
            }
            "codex" -> when (route) {
                "queue-action" -> {
                    val unifiedBody = JSONObject(body.toString())
                        .put("item_id", body.string("message_id"))
                        .put("action", if (body.string("action") == "promote") "promote" else "remove")
                    withLegacyFallback(device, true, {
                        request(devicePath(device, "/api/agents/codex/queue"), body = unifiedBody)
                    }) {
                        request(devicePath(device, "/api/codex/queue-action"), body = body)
                    }
                }
                else -> withLegacyFallback(device, true, {
                    request(devicePath(device, "/api/agents/codex/$route"), body = body)
                }) {
                    request(devicePath(device, "/api/codex/$route"), body = body)
                }
            }
            else -> when (route) {
                "queue-action" -> {
                    val unifiedBody = JSONObject(body.toString())
                        .put("item_id", body.string("message_id"))
                        .put("action", if (body.string("action") == "promote") "promote" else "remove")
                    request(devicePath(device, "/api/agents/$app/queue"), body = unifiedBody)
                }
                else -> request(devicePath(device, "/api/agents/$app/$route"), body = body)
            }
        }
    }
    override suspend fun receipt(device: String, chat: String, request: String):JSONObject {
        val query = mapOf("id" to chat, "request_id" to request)
        val response = withLegacyFallback(device, app in LegacyApps, {
            request(devicePath(device, "/api/agents/$app/receipt"), query)
        }) {
            // 11-26: Claude's unified receipt can say `missing`; a legacy host has no such route, so it answers unknown
            // here and the caller falls back to Claude's own record.
            if (app == "claude") JSONObject().put("state", "unknown")
            else request(devicePath(device, "/api/$app/receipt"), query)
        }
        if (app == "deepseek" && response.string("state") != "unknown") {
            require(response.string("id") == chat) { "回执会话身份不匹配" }
            response.put("request_id", request)
        }
        return response
    }
    override fun events(device: String, chat: String) = kotlinx.coroutines.flow.callbackFlow {
        val reducer=StreamReducer(chat,app,catalog.forDevice(device).cardLayout(app)=="codex.v1")
        val url=root.newBuilder().encodedPath(devicePath(device,"/api/events")).addQueryParameter("app",app).addQueryParameter("id",chat).addQueryParameter("lite","1").withProtocolQuery().build()
        val request=Request.Builder().url(url).header("Accept","text/event-stream").withProtocolHeaders()
        vault.read(key)?.let { Cookie.parse(root,it)?.takeIf { c -> c.expiresAt>System.currentTimeMillis() }?.let { c -> request.header("Cookie","${c.name}=${c.value}") } }
        val streamClient=client.newBuilder().callTimeout(0,TimeUnit.SECONDS).readTimeout(25,TimeUnit.SECONDS).build()
        val source=okhttp3.sse.EventSources.createFactory(streamClient).newEventSource(request.build(),object:okhttp3.sse.EventSourceListener() {
            override fun onEvent(eventSource:okhttp3.sse.EventSource,id:String?,type:String?,data:String) {
                try { require(data.length<=8*1024*1024); reducer.accept(JSONObject(data))?.let { if(!trySend(it).isSuccess) close(IOException("实时缓冲已满")) } }
                catch(e:Exception) { close(e);eventSource.cancel() }
            }
            override fun onClosed(eventSource:okhttp3.sse.EventSource) { close(IOException("实时连接已关闭")) }
            override fun onFailure(eventSource:okhttp3.sse.EventSource,t:Throwable?,response:Response?) {
                if(response?.code==401) vault.write(key,null)
                close(response?.let { ServiceFailure(it.code) } ?: t ?: IOException("实时连接中断"))
            }
        })
        awaitClose { source.cancel() }
    }
}
