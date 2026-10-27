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
fun serviceOrigin(value: String): HttpUrl {
    val url = value.trim().toHttpUrl()
    require(url.scheme == "https" && url.username.isEmpty() && url.password.isEmpty() && url.query == null && url.fragment == null && url.encodedPath == "/") { "请输入 HTTPS 服务根地址，不含账号、路径或参数。" }
    return url
}
interface ReadApi {
    fun forSource(app:String):ReadApi = this
    suspend fun detail(device:String,route:String,query:Map<String,String?> = emptyMap(),body:JSONObject?=null):JSONObject = error("当前服务不支持此功能")
    suspend fun upload(device:String,chat:String,name:String,bytes:ByteArray,image:Boolean,draft:Boolean=false):JSONObject = error("上传不可用")
    suspend fun uploadStream(device:String,chat:String,name:String,size:Long,image:Boolean,draft:Boolean=false,open:()->java.io.InputStream):JSONObject = error("流式上传不可用")
    suspend fun download(device:String,chat:String,file:String):ByteArray = error("下载不可用")
    suspend fun downloadTo(device:String,chat:String,file:String,output:java.io.OutputStream) { output.write(download(device,chat,file)) }
    /** A picture the computer kept of a send (GET /api/codex/image by its id; [small]: its copy of at most 320 px). */
    suspend fun sentPicture(device:String,id:String,small:Boolean,output:java.io.OutputStream) { error("下载不可用") }
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
class RelayApi(origin: String, private val vault: CookieVault, baseClient: OkHttpClient = OkHttpClient(),private val app:String="codex") : ReadApi {
    init { require(app in setOf("codex","claude","deepseek")) }
    override fun forSource(app:String):ReadApi = RelayApi(root.toString(),vault,client,app)
    val root = serviceOrigin(origin)
    private val key = root.toString()
    // No automatic redirects (including same-host HTTPS -> HTTP), no browser CookieJar.
    private val client = baseClient.newBuilder().cookieJar(CookieJar.NO_COOKIES)
        .followRedirects(false).followSslRedirects(false).retryOnConnectionFailure(false)
        .connectTimeout(15, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS).callTimeout(40, TimeUnit.SECONDS).build()
    override fun close() { client.dispatcher.cancelAll() }
    private fun devicePath(device: String, route: String): String {
        require(Regex("[0-9a-f]{32}").matches(device)) { "电脑标识无效" }
        return "/d/$device$route"
    }
    /** [timeout] in seconds, for the actions the computer takes long over (Claude's buttons, archiving, voice). */
    private suspend fun request(path: String, query: Map<String,String?> = emptyMap(), body: JSONObject? = null, bytes:ByteArray?=null,stream:RequestBody?=null,timeout:Long=0,type:String="application/octet-stream"): JSONObject = withContext(Dispatchers.IO) {
        val url = root.newBuilder().encodedPath(path).apply { query.forEach { (k,v) -> if (v != null) addQueryParameter(k,v) } }.build()
        val builder = Request.Builder().url(url).header("Accept", "application/json")
        vault.read(key)?.let { raw -> Cookie.parse(root, raw)?.takeIf { it.expiresAt > System.currentTimeMillis() }?.let { builder.header("Cookie", "${it.name}=${it.value}") } }
        if (body != null) builder.header("Origin", key.removeSuffix("/")).post(body.toString().toRequestBody("application/json; charset=utf-8".toMediaType()))
        if(bytes!=null) builder.header("Origin",key.removeSuffix("/")).post(bytes.toRequestBody(type.toMediaType()))
        if(stream!=null) builder.header("Origin",key.removeSuffix("/")).post(stream)
        val caller = if(timeout>0) client.newBuilder().callTimeout(timeout,TimeUnit.SECONDS).readTimeout(timeout,TimeUnit.SECONDS).build() else client
        val call = caller.newCall(builder.build())
        // 诊断测速 times the requests that carry a message or a file (web: the same routes, POST only).
        val timer = if(body!=null || bytes!=null || stream!=null) Diagnostics.start(Diagnostics.Labels[path.replace(DevicePrefix,"")]) else null
        val size = bytes?.size?.toLong() ?: stream?.contentLength() ?: 0L
        try { timed(call).also { Diagnostics.finish(timer,size,speedOutcome(it)) } }
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
    override suspend fun detail(device:String,route:String,query:Map<String,String?>,body:JSONObject?):JSONObject {
        require(route in DetailRoutes)
        return request(devicePath(device,"/api/$route"),query,body,timeout=SlowRoutes[route] ?: 0)
    }
    override suspend fun voice(device:String,route:String,query:Map<String,String?>,bytes:ByteArray?,type:String):JSONObject {
        require(route in setOf("voice","voice/stream/start","voice/stream/chunk","voice/stream/end","voice/stream/cancel","voice/stream/cloud"))
        // A whole recording, or the end of one, waits for recognition (and 整理) on the computer.
        val slow=route=="voice" || route=="voice/stream/end" || route=="voice/stream/cloud"
        return request(devicePath(device,"/api/$route"),query,bytes=bytes ?: ByteArray(0),timeout=if(slow) 125 else 35,type=type)
    }
    private companion object {
        val DevicePrefix=Regex("^/d/[0-9a-f]{32}")
        val DetailRoutes=setOf("chat/new/options","chat/folders","chat/new/draft","chat/new","chat/new/state","chat/new/retry","chat/new/references","composer/references","files/places","files/list","files/image","files/remove","codex/remove-attachment","codex/attachments","chat/files","chat/diff","file/text","file/meta","deepseek/models","deepseek/permissions","deepseek/model","deepseek/permission","deepseek/answer","deepseek/approval","claude/catalog","claude/setting","claude/choose","claude/menu","claude/close-menu","chat/projects","chat/open","chat/resolve",
            "claude/next","claude/task","chat/check","chat/archive","chat/unarchive","chat/delete","chat/archived","chats/children","notify","notify/ntfy","notify/test","voice/status","voice/terms","voice/tidy","status")
        /** Seconds the computer may take: Claude's buttons wait for its window (web 65 s), archiving for its records. */
        val SlowRoutes=mapOf("claude/next" to 65L,"claude/task" to 65L,"chat/archive" to 65L,"chat/unarchive" to 95L,"chat/delete" to 125L,"chat/archived" to 25L,"notify" to 35L,"notify/ntfy" to 35L,"notify/test" to 35L,"voice/tidy" to 65L,"status" to 10L)
    }
    override suspend fun upload(device:String,chat:String,name:String,bytes:ByteArray,image:Boolean,draft:Boolean):JSONObject {
        require(bytes.isNotEmpty() && bytes.size <= if(image) 20*1024*1024 else 100*1024*1024) { "文件超过上传上限" }
        return request(devicePath(device,if(image) "/api/codex/upload" else "/api/files/upload"),mapOf("app" to app,(if(draft) "draft" else "id") to chat,"name" to name),bytes=bytes)
    }
    override suspend fun uploadStream(device:String,chat:String,name:String,size:Long,image:Boolean,draft:Boolean,open:()->java.io.InputStream):JSONObject {
        require(size>0 && size<=if(image) 20L*1024*1024 else 100L*1024*1024) { "文件超过上传上限" }
        val body=object:RequestBody() {
            override fun contentType()="application/octet-stream".toMediaType()
            override fun contentLength()=size
            override fun writeTo(sink:okio.BufferedSink) { open().use { input -> val buffer=ByteArray(65536);var written=0L;while(true) { val n=input.read(buffer);if(n<0) break;written+=n;if(written>size) throw IOException("所选文件已变化");sink.write(buffer,0,n) };if(written!=size) throw IOException("文件读取不完整") } }
        }
        return request(devicePath(device,if(image) "/api/codex/upload" else "/api/files/upload"),mapOf("app" to app,(if(draft) "draft" else "id") to chat,"name" to name),stream=body)
    }
    override suspend fun downloadTo(device:String,chat:String,file:String,output:java.io.OutputStream) =
        streamTo(root.newBuilder().encodedPath(devicePath(device,"/api/file")).addQueryParameter("app",app).addQueryParameter("id",chat).addQueryParameter("file",file).build(),output)
    override suspend fun sentPicture(device:String,id:String,small:Boolean,output:java.io.OutputStream) =
        streamTo(root.newBuilder().encodedPath(devicePath(device,"/api/codex/image")).apply { if(small) addQueryParameter("thumb","1") }.addQueryParameter("id",id).build(),output)
    /** A file from the computer into [output], at most 100 MB, whole or with an error. */
    private suspend fun streamTo(url:HttpUrl,output:java.io.OutputStream):Unit = suspendCancellableCoroutine { continuation ->
        val builder=Request.Builder().url(url)
        vault.read(key)?.let { Cookie.parse(root,it)?.takeIf { c -> c.expiresAt>System.currentTimeMillis() }?.let { c -> builder.header("Cookie","${c.name}=${c.value}") } }
        val call=client.newCall(builder.build());continuation.invokeOnCancellation { call.cancel() }
        call.enqueue(object:Callback {
            override fun onFailure(call:Call,e:IOException) { if(continuation.isActive) continuation.resumeWithException(e) }
            override fun onResponse(call:Call,response:Response) {
                try { response.use { r ->
                    if(!r.isSuccessful) throw ServiceFailure(r.code)
                    require((r.body?.contentLength() ?: 0)<=100L*1024*1024) { "文件超过100MB，请在电脑上打开" }
                    val input=r.body?.byteStream() ?: throw IOException("文件为空");val buffer=ByteArray(65536);var count=0L
                    while(true) { if(!continuation.isActive) return;val n=input.read(buffer);if(n<0) break;count+=n;require(count<=100L*1024*1024) { "文件超过100MB" };output.write(buffer,0,n) }
                    val expected=r.body?.contentLength() ?: -1L
                    require(expected<0 || count==expected) { "文件接收不完整，请重试" }
                    output.flush();if(continuation.isActive) continuation.resume(Unit)
                } } catch(e:Exception) { if(continuation.isActive) continuation.resumeWithException(e) }
            }
        })
    }
    override suspend fun download(device:String,chat:String,file:String):ByteArray = suspendCancellableCoroutine { continuation ->
        val url=root.newBuilder().encodedPath(devicePath(device,"/api/file")).addQueryParameter("app",app).addQueryParameter("id",chat).addQueryParameter("file",file).build()
        val builder=Request.Builder().url(url)
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
        require(app == "all" || app in setOf("codex","claude","deepseek")) { "来源应用无效" }
        return request(devicePath(device,"/api/chats"), mapOf("app" to app, "limit" to "40", "query" to query, "cursor" to cursor, "sort" to sort, "status" to status)).let { j ->
            Page(j.rows("items") { val c=parseChat(it); require(c.app in setOf("codex","claude","deepseek") && (app=="all" || c.app==app)) { "来源应用不匹配" }; c }, j.string("next_cursor").ifBlank { null }, j.optBoolean("has_more"))
        }
    }
    override suspend fun history(device: String, chat: String, before: String?, around: String?, count: Int) = request(devicePath(device,"/api/chat"), mapOf("app" to app, "id" to chat, "n" to "$count", "before" to before, "around" to around)).let { j ->
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
    override suspend fun control(device: String, chat: String, fresh: Boolean) = parseControl(request(devicePath(device,"/api/$app/state"),mapOf("id" to chat,"fresh" to if(fresh) "1" else null),timeout=if(app=="claude") 20 else 0).apply { if(app=="deepseek") put("queue_available",true) })
    override suspend fun command(device: String, route: String, body: JSONObject): JSONObject {
        require(route in setOf("send","stop","queue-action","answer"))
        if(app=="deepseek") {
            val outgoing=JSONObject(body.toString())
            val actual=when(route) {
                "send" -> { if(outgoing.string("intent")=="auto") outgoing.put("intent","steer");"send" }
                "stop" -> { outgoing.put("expected_turn",body.string("turn_id"));"stop" }
                // 立即补充 is "steer" for DeepSeek, 撤回 is "remove".
                "queue-action" -> { outgoing.put("item_id",body.string("message_id")).put("action",if(body.string("action")=="promote") "steer" else "remove");"queue" }
                else -> route
            }
            val result=request(devicePath(device,"/api/deepseek/$actual"),body=outgoing)
            if(route=="send" && result.optBoolean("accepted")) result.put("delivery_state",if(outgoing.string("intent")=="queue") "queued" else "accepted")
            return result
        }
        if(app=="claude") {
            require(route=="send") { "Claude 的停止与队列动作需使用当前桌面令牌" }
            return request(devicePath(device,"/api/chat/send"),body=JSONObject(body.toString()).put("app","claude"))
        }
        return request(devicePath(device,"/api/codex/$route"),body=body)
    }
    override suspend fun receipt(device: String, chat: String, request: String):JSONObject {
        if(app=="claude") return JSONObject().put("state","unknown")
        val response=request(devicePath(device,"/api/$app/receipt"),mapOf("id" to chat,"request_id" to request))
        if(app=="deepseek" && response.string("state")!="unknown") {
            require(response.string("id")==chat) { "回执会话身份不匹配" }
            response.put("request_id",request)
        }
        return response
    }
    override fun events(device: String, chat: String) = kotlinx.coroutines.flow.callbackFlow {
        val reducer=StreamReducer(chat,app)
        val url=root.newBuilder().encodedPath(devicePath(device,"/api/events")).addQueryParameter("app",app).addQueryParameter("id",chat).build()
        val request=Request.Builder().url(url).header("Accept","text/event-stream")
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
