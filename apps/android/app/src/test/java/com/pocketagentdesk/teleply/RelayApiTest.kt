package com.pocketagentdesk.teleply

import kotlinx.coroutines.*
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.flow.first
import org.json.JSONObject
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.*
import org.junit.Assert.*
import java.util.concurrent.TimeUnit

class RelayApiTest {
    @Test fun sourceIdentityUploadAndDownloadStayDeviceBound()=runTest {
        val ds=api.forSource("deepseek")
        response("""{"app":"deepseek","id":"chat","messages":[]}""");ds.history(device,"chat")
        assertEquals("deepseek",server.takeRequest().requestUrl!!.queryParameter("app"))
        response("""{"id":"image"}""");ds.uploadStream(device,"chat","测试.png",3L,true) { java.io.ByteArrayInputStream(byteArrayOf(1,2,3)) }
        val upload=server.takeRequest();assertEquals("/d/$device/api/agents/deepseek/upload",upload.requestUrl!!.encodedPath);assertEquals("chat",upload.requestUrl!!.queryParameter("id"));assertEquals(server.url("/").toString().removeSuffix("/"),upload.getHeader("Origin"));assertArrayEquals(byteArrayOf(1,2,3),upload.body.readByteArray())
        server.enqueue(MockResponse().setBody("fixture"));assertEquals("fixture",String(ds.download(device,"chat","file")))
        val download=server.takeRequest();assertEquals("/d/$device/api/file",download.requestUrl!!.encodedPath);assertEquals("deepseek",download.requestUrl!!.queryParameter("app"))
        server.enqueue(MockResponse().setBody("streamed-file"));val out=java.io.ByteArrayOutputStream();ds.downloadTo(device,"chat","file",out);assertEquals("streamed-file",out.toString());assertEquals("file",server.takeRequest().requestUrl!!.queryParameter("file"))
        // A picture sent with a message (web renderImages): its small copy, then the whole one, by its id.
        for(small in listOf(true,false)) {
            server.enqueue(MockResponse().setBody("png"));val picture=java.io.ByteArrayOutputStream();ds.sentPicture(device,"a".repeat(32),small,picture);assertEquals("png",picture.toString())
            val url=server.takeRequest().requestUrl!!;assertEquals("/d/$device/api/codex/image",url.encodedPath);assertEquals("a".repeat(32),url.queryParameter("id"));assertEquals(if(small) "1" else null,url.queryParameter("thumb"))
        }
        server.enqueue(MockResponse().setResponseCode(404))
        try { ds.sentPicture(device,"gone",false,java.io.ByteArrayOutputStream());fail() } catch(e:ServiceFailure) { assertEquals(404,e.status) }
        server.takeRequest()
        assertThrows(IllegalArgumentException::class.java) { serviceOrigin("https://example.invalid/private") }
    }
    /** 11-15: a file goes down to the phone up to 500 MB (was 100 MB); one said to be bigger is refused before it comes. */
    @Test fun aFileOverTheDownloadLimitIsRefusedBeforeItComes()=runTest {
        assertEquals(500L*1024*1024,DownloadLimit)
        server.enqueue(MockResponse().setBody("small").setHeader("Content-Length",DownloadLimit+1))
        try { api.downloadTo(device,"chat","file",java.io.ByteArrayOutputStream());fail() } catch(e:IllegalArgumentException) { assertEquals("文件超过500MB，请在电脑上打开",e.message) }
        server.takeRequest()
    }
    /** 11-15: saving a file had the 40 s of every call in all, so a big one on a slow line never finished: an hour now. */
    @Test fun aFileDownloadHasAnHourAndAMinuteOfSilence() {
        assertEquals(3_600_000,api.fileClient.callTimeoutMillis)
        assertEquals(60_000,api.fileClient.readTimeoutMillis)
    }
    /** 10-27: Word, Excel and PowerPoint as PDF: the device-bound route, the computer's own words when it cannot, 20 MB at most. */
    @Test fun officeFilesComeAsPdfWithTheComputersWords()=runTest {
        val claude=api.forSource("claude")
        server.enqueue(MockResponse().setHeader("Content-Type","application/pdf").setBody("%PDF-1.4 fixture"))
        assertEquals("%PDF-1.4 fixture",String(claude.filePdf(device,"chat","file-1",1024)))
        val url=server.takeRequest().requestUrl!!
        assertEquals("/d/$device/api/file/pdf",url.encodedPath);assertEquals("claude",url.queryParameter("app"))
        assertEquals("chat",url.queryParameter("id"));assertEquals("file-1",url.queryParameter("file"))
        for(status in listOf(404,500)) {
            response("""{"error":"电脑上没有可用的 Word"}""",status)
            try { claude.filePdf(device,"chat","file-1",1024);fail() } catch(e:ServiceFailure) { assertEquals(status,e.status);assertEquals("电脑上没有可用的 Word",e.detail) }
            server.takeRequest()
            assertEquals("没能转成 PDF：电脑上没有可用的 Word",pdfFailure(ServiceFailure(status,detail="电脑上没有可用的 Word")))
        }
        server.enqueue(MockResponse().setHeader("Content-Type","application/pdf").setBody("x".repeat(2048)))
        try { claude.filePdf(device,"chat","file-1",1024);fail() } catch(e:PreviewTooLarge) { assertEquals(1024L,e.limit) }
        server.takeRequest()
        assertEquals("转成的 PDF 超过20MB预览上限，可保存后使用系统应用打开。",pdfFailure(PreviewTooLarge(PreviewLimit)))
    }
    @Test fun sseUsesBoundPathAndParsesSnapshot()=runTest {
        server.enqueue(MockResponse().setHeader("Content-Type","text/event-stream").setBody("event: update\ndata: {\"protocol\":1,\"seq\":1,\"type\":\"snapshot\",\"app\":\"codex\",\"id\":\"chat\",\"chat\":{\"app\":\"codex\",\"id\":\"chat\",\"messages\":[{\"id\":\"m\",\"role\":\"assistant\",\"text\":\"stream\",\"order\":1}]}}\n\n"))
        val frame=api.events(device,"chat").first()
        assertEquals("stream",frame.messages.single().text)
        val request=server.takeRequest();assertEquals("/d/$device/api/events",request.requestUrl!!.encodedPath);assertEquals("text/event-stream",request.getHeader("Accept"))
    }
    @Test fun commandAndReceiptBindDeviceOriginAndOriginalRequest()=runTest {
        response("""{"request_id":"r","delivery_state":"accepted"}""")
        api.command(device,"send",JSONObject().put("id","chat").put("request_id","r").put("text","fixture"))
        val post=server.takeRequest();assertEquals("/d/$device/api/agents/codex/send",post.requestUrl!!.encodedPath);assertEquals(server.url("/").toString().removeSuffix("/"),post.getHeader("Origin"))
        response("""{"state":"unknown"}""");api.receipt(device,"chat","r")
        val get=server.takeRequest();assertEquals("/d/$device/api/agents/codex/receipt",get.requestUrl!!.encodedPath);assertEquals("r",get.requestUrl!!.queryParameter("request_id"));assertEquals("GET",get.method)
    }
    @Test fun mixedListKeepsUnknownValidSourcesAndRejectsCrossSourceOrMalformed()=runTest {
        response("""{"items":[{"id":"a","app":"codex","title":"A","updated":2000,"created":1000},{"id":"b","app":"claude","title":"B"},{"id":"c","app":"deepseek","title":"C"},{"id":"t","app":"testing","title":"T"},{"id":"u","app":"unknown_new","title":"U"}],"has_more":false}""")
        val page=api.chatList(device,"all","",null,"created","waiting")
        assertEquals(listOf("codex","claude","deepseek","testing","unknown_new"),page.items.map { it.app })
        assertEquals(2000L to 1000L,page.items[0].updated to page.items[0].created)
        val request=server.takeRequest().requestUrl!!
        assertEquals("all",request.queryParameter("app"));assertEquals("created",request.queryParameter("sort"));assertEquals("waiting",request.queryParameter("status"))
        // Malformed ids are still refused.
        response("""{"items":[{"id":"x","app":"../bad","title":"X"}]}""")
        assertTrue(runCatching { api.chatList(device,"all","",null) }.isFailure)
        server.takeRequest()
        // Cross-source rows in a single-source list are still refused.
        response("""{"items":[{"id":"x","app":"claude","title":"X"}]}""")
        assertTrue("a Codex-only list must not accept a Claude row",runCatching { api.chatList(device,"codex","",null) }.isFailure)
        server.takeRequest()
        // Valid custom source can be queried directly.
        response("""{"items":[{"id":"t1","app":"testing","title":"测试对话"}]}""")
        val custom=api.chatList(device,"testing","",null)
        assertEquals(listOf("testing"),custom.items.map { it.app })
        assertEquals("testing",server.takeRequest().requestUrl!!.queryParameter("app"))
    }
    @Test fun protocolHeadersAndQueryParamsAreSentOnEveryRequest()=runTest {
        val clientTag=teleplyClientTag()
        assertTrue(clientTag.startsWith("android/"))
        // JSON GET
        response("""{"devices":[],"email":""}""");api.account()
        val acc=server.takeRequest()
        assertEquals("2",acc.getHeader("X-Teleply-Protocol"));assertEquals(clientTag,acc.getHeader("X-Teleply-Client"))
        // Stream (SSE): both headers and query params
        server.enqueue(MockResponse().setHeader("Content-Type","text/event-stream").setBody("event: update\ndata: {\"protocol\":1,\"seq\":1,\"type\":\"snapshot\",\"app\":\"codex\",\"id\":\"chat\",\"chat\":{\"app\":\"codex\",\"id\":\"chat\",\"messages\":[]}}\n\n"))
        api.events(device,"chat").first()
        val sse=server.takeRequest()
        assertEquals("2",sse.getHeader("X-Teleply-Protocol"));assertEquals(clientTag,sse.getHeader("X-Teleply-Client"))
        assertEquals("2",sse.requestUrl!!.queryParameter("protocol"));assertEquals(clientTag,sse.requestUrl!!.queryParameter("client"))
        // File download, stream download, sent picture, and Office PDF: both headers and query params
        server.enqueue(MockResponse().setBody("bin"));api.download(device,"chat","f1")
        val dl=server.takeRequest()
        assertEquals("2",dl.getHeader("X-Teleply-Protocol"));assertEquals(clientTag,dl.getHeader("X-Teleply-Client"))
        assertEquals("2",dl.requestUrl!!.queryParameter("protocol"));assertEquals(clientTag,dl.requestUrl!!.queryParameter("client"))
        server.enqueue(MockResponse().setBody("bin"));api.downloadTo(device,"chat","f1",java.io.ByteArrayOutputStream())
        val dlTo=server.takeRequest()
        assertEquals("2",dlTo.requestUrl!!.queryParameter("protocol"));assertEquals(clientTag,dlTo.requestUrl!!.queryParameter("client"))
        server.enqueue(MockResponse().setBody("png"));api.sentPicture(device,"a".repeat(32),true,java.io.ByteArrayOutputStream())
        val pic=server.takeRequest()
        assertEquals("2",pic.requestUrl!!.queryParameter("protocol"));assertEquals(clientTag,pic.requestUrl!!.queryParameter("client"))
        server.enqueue(MockResponse().setHeader("Content-Type","application/pdf").setBody("%PDF"));api.filePdf(device,"chat","f1",1024)
        val pdf=server.takeRequest()
        assertEquals("2",pdf.getHeader("X-Teleply-Protocol"));assertEquals(clientTag,pdf.getHeader("X-Teleply-Client"))
        assertEquals("2",pdf.requestUrl!!.queryParameter("protocol"));assertEquals(clientTag,pdf.requestUrl!!.queryParameter("client"))
    }
    @Test fun agentsEndpointParsesManifestsAndFallsBackOn404()=runTest {
        response("""{"schema":1,"protocol":2,"agents":[
            {"id":"codex","name":{"zh":"Codex","en":"Codex"},"order":10,"color":"#1E222A","color_dark":"#FFFFFF","icon":{"kind":"builtin","key":"codex"},"legacy":true,"min_protocol":1,"capabilities":{"list":true,"read":true,"stop":true,"send_modes":["send","steer","queue"]}},
            {"id":"testing","name":{"zh":"测试助手","en":"Test Helper"},"order":99,"color":"#7C3AED","color_dark":"#A78BFA","icon":{"kind":"builtin","key":"generic"},"legacy":false,"min_protocol":2,"capabilities":{"list":true,"read":true,"stop":true,"usage":true,"send_modes":["send"]},"params":{"state_timeout_s":5,"refresh_ms":1000}}
        ]}""")
        val list=api.agents(device)
        val req=server.takeRequest()
        assertEquals("/d/$device/api/agents",req.requestUrl!!.encodedPath)
        assertEquals("2",req.getHeader("X-Teleply-Protocol"))
        assertEquals(listOf("codex","testing"),list!!.map { it.id })
        // Shared catalog is updated and accessible via forSource("testing").
        val testingApi=api.forSource("testing") as RelayApi
        assertEquals("测试助手",testingApi.catalog.forDevice(device).name("testing",java.util.Locale.CHINA))
        assertEquals(5L,testingApi.catalog.forDevice(device).params("testing").stateTimeoutS)
        // Legacy computer returns 404 -> null and falls back to built-in 3.
        val legacyDevice="b".repeat(32)
        response("""{"error":"没有这个地址"}""",404)
        assertNull(api.agents(legacyDevice))
        server.takeRequest()
        assertEquals(listOf("codex","claude","deepseek"),api.catalog.forDevice(legacyDevice).order)
        assertFalse(api.catalog.forDevice(legacyDevice).fromServer)
    }
    @Test fun historyCarriesRuntimeAsPageMeta()=runTest {
        response("""{"app":"codex","id":"chat","title":"标题","folder":"项目","status":"idle","runtime":{"percent":46,"context_state":"available"},"messages":[{"id":"m","role":"assistant","text":"t","phase":"commentary"},{"id":"u","role":"user","text":"q","client_request_id":"r1"}]}""")
        val page=api.history(device,"chat")
        val meta=JSONObject(page.meta)
        assertEquals("标题",meta.string("title"));assertEquals(46,meta.getJSONObject("runtime").getInt("percent"))
        assertEquals("commentary",page.items.first().phase);assertEquals("r1",page.items.last().request)
    }
    /** 10-27: DeepSeek's state without what changes on every read and shows nowhere, so a poll with nothing new is the same state. */
    @Test fun deepSeekStateLeavesOutWhatChangesOnEveryRead()=runTest {
        val ds=api.forSource("deepseek")
        response("""{"available":true,"running":true,"seq":41,"subagents":[{"id":"s","updated":1}],"inbox":{"items":[]},"queued":[{"id":"q","text":"排队"}],"interactions":[]}""")
        val first=ds.control(device,"chat",false);server.takeRequest()
        response("""{"available":true,"running":true,"seq":42,"subagents":[{"id":"s","updated":2}],"inbox":{"items":[],"at":2},"queued":[{"id":"q","text":"排队"}],"interactions":[]}""")
        val second=ds.control(device,"chat",false);server.takeRequest()
        assertEquals(first,second);assertFalse(JSONObject(first.raw).has("seq"))
        assertEquals("q",first.queued.single().id);assertTrue(first.queueAvailable);assertTrue(first.running)
    }
    @Test fun deepSeekPromoteIsSteerAndCancelIsRemove()=runTest {
        val ds=api.forSource("deepseek")
        response("""{"ok":true}""");ds.command(device,"queue-action",JSONObject().put("id","chat").put("request_id","r").put("message_id","q1").put("action","promote"))
        val promote=JSONObject(server.takeRequest().body.readUtf8());assertEquals("steer",promote.string("action"));assertEquals("q1",promote.string("item_id"))
        response("""{"ok":true}""");ds.command(device,"queue-action",JSONObject().put("id","chat").put("request_id","r2").put("message_id","q1").put("action","cancel"))
        assertEquals("remove",JSONObject(server.takeRequest().body.readUtf8()).string("action"))
    }
    private lateinit var server:MockWebServer
    private lateinit var api:RelayApi
    private lateinit var vault:MemoryCookieVault
    private lateinit var client:OkHttpClient
    private val device="a".repeat(32)
    @Before fun setup() {
        val cert=HeldCertificate.Builder().addSubjectAlternativeName("localhost").addSubjectAlternativeName("127.0.0.1").build()
        val tls=HandshakeCertificates.Builder().heldCertificate(cert).build()
        val trust=HandshakeCertificates.Builder().addTrustedCertificate(cert.certificate).build()
        server=MockWebServer().apply { useHttps(tls.sslSocketFactory(),false);start() }
        vault=MemoryCookieVault()
        client=OkHttpClient.Builder().sslSocketFactory(trust.sslSocketFactory(),trust.trustManager).build()
        api=RelayApi(server.url("/").toString(),vault,client)
    }
    @After fun cleanup() { api.close();server.shutdown() }
    private fun response(json:String,status:Int=200) { server.enqueue(MockResponse().setResponseCode(status).setHeader("Content-Type","application/json").setBody(json)) }
    @Test fun loginUsesOriginAndDevicePaths()=runTest {
        server.enqueue(MockResponse().setBody("{\"ok\":true}").addHeader("Set-Cookie","__Host-ar_account=synthetic; Path=/; Secure; HttpOnly; Max-Age=3600"))
        api.login("fixture","test-only")
        val login=server.takeRequest();assertEquals("POST",login.method);assertEquals(server.url("/").toString().removeSuffix("/"),login.getHeader("Origin"))
        response("""{"items":[{"id":"chat","app":"codex","title":"测试"}],"has_more":true,"next_cursor":"p2"}""")
        val page=api.chats(device,"中文 & ?",null)
        val request=server.takeRequest()
        assertEquals("/d/$device/api/chats",request.requestUrl!!.encodedPath)
        assertEquals("中文 & ?",request.requestUrl!!.queryParameter("query"))
        assertEquals("__Host-ar_account=synthetic",request.getHeader("Cookie"))
        assertTrue(page.hasMore);assertEquals("p2",page.cursor)
    }
    @Test fun historyRetainsIdentityAndOpaqueCursor()=runTest {
        response("""{"id":"x/y","app":"codex","messages":[{"id":"m1","role":"assistant","text":"原文\n","truncated":true,"length":7545}],"next_cursor":"m1","has_more":true,"has_newer":true}""")
        val page=api.history(device,"x/y",before="opaque + / ?")
        val request=server.takeRequest()
        assertEquals("x/y",request.requestUrl!!.queryParameter("id"));assertEquals("opaque + / ?",request.requestUrl!!.queryParameter("before"))
        assertEquals("原文\n",page.items.single().text);assertTrue(page.items.single().truncated);assertTrue(page.hasNewer)
        assertEquals(7545,page.items.single().length);assertEquals("展开全文（7545 字）",expandLabel(page.items.single()))
    }
    @Test fun selectRejectsMismatchedDevicePath()=runTest {
        response("""{"url":"/d/${"b".repeat(32)}/"}""")
        try { api.select(device);fail() } catch(_:IllegalArgumentException) { }
    }
    @Test fun offlineHasSpecificError()=runTest {
        response("""{"code":"device_offline"}""",409)
        try { api.select(device);fail() } catch(e:ServiceFailure) { assertEquals(409,e.status);assertEquals("device_offline",e.code) }
    }
    /** 删除账号: the password in a POST with this service's Origin; turned down, the sign-in stays; done, only this one goes. */
    @Test fun deleteAccountPostsThePasswordAndDropsOnlyThisSignIn()=runTest {
        val here=server.url("/").toString()
        vault.write(here,"__Host-ar_account=synthetic; Path=/; Secure; HttpOnly");vault.write("https://another.invalid/","other")
        response("""{"error":"当前密码错误"}""",400)
        try { api.deleteAccount("wrong");fail() } catch(e:ServiceFailure) { assertEquals(400,e.status);assertEquals("当前密码错误",e.message) }
        response("""{"error":"请在 31 秒后重试","code":"rate_limited","retry_after":31}""",429)
        try { api.deleteAccount("wrong");fail() } catch(e:ServiceFailure) { assertEquals(429,e.status);assertEquals("请在 31 秒后重试",e.message) }
        repeat(2) { server.takeRequest() }
        assertNotNull(vault.read(here))
        server.enqueue(MockResponse().setHeader("Content-Type","application/json").setBody("""{"ok":true}""").addHeader("Set-Cookie","__Host-ar_account=; Path=/; Secure; HttpOnly; Max-Age=0"))
        api.deleteAccount("test-only")
        val post=server.takeRequest()
        assertEquals("POST",post.method);assertEquals("/account/delete",post.requestUrl!!.encodedPath);assertEquals(here.removeSuffix("/"),post.getHeader("Origin"))
        assertEquals("__Host-ar_account=synthetic",post.getHeader("Cookie"));assertEquals("test-only",JSONObject(post.body.readUtf8()).string("password"))
        assertNull(vault.read(here));assertEquals("other",vault.read("https://another.invalid/"))
    }
    /** 10-31: a sign-in made on the old default's IP and moved (moveService) is what the domain is sent, with its own Origin. */
    @Test fun aSignInMovedOffTheIpIsSentToTheDomain()=runTest {
        val ip=serviceOrigin(OldDefaultOrigin)
        vault.write(ip.toString(),okhttp3.Cookie.parse(ip,"__Host-ar_account=synthetic; Path=/; Secure; HttpOnly; Max-Age=3600")!!.toString())
        moveService(TestStore(),vault)
        // The domain's requests come to this test server instead.
        val here=client.newBuilder().addInterceptor { chain -> chain.proceed(chain.request().newBuilder().url(chain.request().url.newBuilder().host(server.hostName).port(server.port).build()).build()) }.build()
        val domain=RelayApi(DefaultOrigin,vault,here)
        try {
            response("""{"devices":[],"email":""}""");domain.account()
            assertEquals("__Host-ar_account=synthetic",server.takeRequest().getHeader("Cookie"))
            response("""{"ok":true}""");domain.deleteAccount("test-only")
            assertEquals(DefaultOrigin,server.takeRequest().getHeader("Origin"))
        } finally { domain.close() }
    }
    @Test fun expirationClearsOnlyCurrentOrigin()=runTest {
        vault.write(server.url("/").toString(),"__Host-ar_account=synthetic; Path=/; Secure; HttpOnly")
        vault.write("https://another.invalid/","other")
        response("{}",401)
        try { api.account();fail() } catch(e:ServiceFailure) { assertEquals(401,e.status) }
        assertNull(vault.read(server.url("/").toString()));assertEquals("other",vault.read("https://another.invalid/"))
    }
    @Test fun redirectsNeverForwardCredentials()=runTest {
        val other=MockWebServer();other.start()
        try {
            vault.write(server.url("/").toString(),"__Host-ar_account=synthetic; Path=/; Secure; HttpOnly")
            server.enqueue(MockResponse().setResponseCode(302).setHeader("Location",other.url("/leak")))
            try { api.account();fail() } catch(e:ServiceFailure) { assertEquals(302,e.status) }
            assertNull(other.takeRequest(100,TimeUnit.MILLISECONDS))
        } finally { other.shutdown() }
    }
    @Test fun fullMessageValidatesIdentity()=runTest {
        response("""{"id":"wrong","role":"assistant","text":"no"}""")
        try { api.message(device,"chat","expected");fail() } catch(_:IllegalArgumentException) { }
    }
    @Test fun wrongSourceCannotEnterCodexList()=runTest {
        response("""{"items":[{"id":"chat","app":"claude"}]}""")
        try { api.chats(device,"",null);fail() } catch(_:IllegalArgumentException) { }
    }
    @Test fun searchPaginatesWithExplicitDevice()=runTest {
        response("""{"items":[{"id":"m","role":"user","snippet":"match"}],"has_more":true,"next_cursor":"next"}""")
        assertEquals("next",api.search(device,"chat","match","p2").cursor)
        val r=server.takeRequest();assertEquals("/d/$device/api/chat/search",r.requestUrl!!.encodedPath);assertEquals("p2",r.requestUrl!!.queryParameter("cursor"))
    }
    @Test fun malformedJsonFailsWithoutExposingBody()=runTest {
        response("<html>upstream error</html>")
        try { api.account();fail() } catch(_:org.json.JSONException) { }
    }
    @Test fun insecureOrNonRootServicesRejected() {
        listOf("http://example.com","https://user:password@example.com","https://example.com/d/abc","https://example.com/?token=x","https://example.com/#x").forEach { try { serviceOrigin(it);fail(it) } catch(_:IllegalArgumentException) { } }
    }
    @Test fun invalidDeviceNeverCreatesRequest()=runTest {
        try { api.chats("../account","",null);fail() } catch(_:IllegalArgumentException) { }
        assertEquals(0,server.requestCount)
    }
    /** 用量 (11-17): the read is a GET with live=1, the reset a POST carrying the request id and the confirmation. */
    @Test fun usageReadsLiveWithAGet()=runTest {
        response("""{"codex":{"available":true,"source":"live"},"claude":{"available":false},"now":1}""")
        assertEquals(true,api.detail(device,"usage",mapOf("live" to "1")).optJSONObject("codex")!!.getBoolean("available"))
        val request=server.takeRequest()
        assertEquals("GET",request.method);assertEquals("/d/$device/api/usage",request.requestUrl!!.encodedPath)
        assertEquals("1",request.requestUrl!!.queryParameter("live"))
    }
    @Test fun aCodexResetPostsTheRequestIdAndTheConfirmation()=runTest {
        response("""{"ok":true,"outcome":"reset","text":"已用掉 1 次重置，Codex 用量恢复了","usage":null}""")
        val answer=api.detail(device,"usage/codex-reset",body=JSONObject().put("request_id","reset-request-0001").put("credit_id","credit-available").put("confirmed",true))
        assertEquals("已用掉 1 次重置，Codex 用量恢复了",answer.string("text"))
        val post=server.takeRequest()
        assertEquals("POST",post.method);assertEquals("/d/$device/api/usage/codex-reset",post.requestUrl!!.encodedPath)
        val body=JSONObject(post.body.readUtf8())
        assertEquals("reset-request-0001",body.string("request_id"));assertEquals("credit-available",body.string("credit_id"))
        assertEquals(true,body.getBoolean("confirmed"))
    }
    /** Step 7 (unified-routes.md): unified `/api/agents/<id>/...` routes work for all three built-ins and the fake testing helper. */
    @Test fun unifiedRoutesWorkForBuiltinsAndTestingHelper()=runTest {
        val testing=api.forSource("testing")
        response("""{"available":true,"running":true,"turn_id":"t1"}""")
        val state=testing.control(device,"test-running",true)
        assertTrue(state.running)
        val stateReq=server.takeRequest()
        assertEquals("/d/$device/api/agents/testing/state",stateReq.requestUrl!!.encodedPath)
        assertEquals("test-running",stateReq.requestUrl!!.queryParameter("id"))
        assertEquals("1",stateReq.requestUrl!!.queryParameter("fresh"))

        response("""{"ok":true,"accepted":true,"request_id":"r1","delivery_state":"accepted"}""")
        testing.command(device,"send",JSONObject().put("id","test-running").put("request_id","r1").put("text","hi"))
        assertEquals("/d/$device/api/agents/testing/send",server.takeRequest().requestUrl!!.encodedPath)

        response("""{"ok":true}""")
        testing.command(device,"stop",JSONObject().put("id","test-running").put("turn_id","t1"))
        assertEquals("/d/$device/api/agents/testing/stop",server.takeRequest().requestUrl!!.encodedPath)

        response("""{"ok":true}""")
        testing.command(device,"queue-action",JSONObject().put("id","test-running").put("message_id","q1").put("action","cancel"))
        val queueReq=server.takeRequest()
        assertEquals("/d/$device/api/agents/testing/queue",queueReq.requestUrl!!.encodedPath)
        val queueBody=JSONObject(queueReq.body.readUtf8())
        assertEquals("q1",queueBody.string("item_id"));assertEquals("remove",queueBody.string("action"))

        response("""{"ok":true}""")
        testing.command(device,"answer",JSONObject().put("id","test-waiting").put("answers",JSONObject()))
        assertEquals("/d/$device/api/agents/testing/answer",server.takeRequest().requestUrl!!.encodedPath)

        response("""{"state":"accepted","id":"test-running","request_id":"r1"}""")
        assertEquals("accepted",testing.receipt(device,"test-running","r1").string("state"))
        assertEquals("/d/$device/api/agents/testing/receipt",server.takeRequest().requestUrl!!.encodedPath)

        response("""{"ok":true}""")
        testing.detail(device,"chat/open",body=JSONObject().put("app","testing").put("id","test-running"))
        assertEquals("/d/$device/api/agents/testing/open",server.takeRequest().requestUrl!!.encodedPath)

        response("""{"request_id":"rid1","state":"accepted","id":"test-new-1"}""")
        testing.detail(device,"chat/new",body=JSONObject().put("request_id","rid1").put("app","testing").put("text","hi"))
        assertEquals("/d/$device/api/agents/testing/create",server.takeRequest().requestUrl!!.encodedPath)

        response("""{"request_id":"rid1","state":"accepted","id":"test-new-1"}""")
        testing.detail(device,"chat/new/state",mapOf("request_id" to "rid1","app" to "testing"))
        val createState=server.takeRequest().requestUrl!!
        assertEquals("/d/$device/api/agents/testing/create/state",createState.encodedPath)
        assertEquals("rid1",createState.queryParameter("request_id"))
        assertNull(createState.queryParameter("app"))

        response("""{"models":[]}""")
        testing.detail(device,"chat/new/options",mapOf("app" to "testing"))
        assertEquals("/d/$device/api/agents/testing/options",server.takeRequest().requestUrl!!.encodedPath)

        // Diagnostics labels recognize unified routes too.
        assertEquals("消息提交",Diagnostics.labelFor("/api/agents/testing/send"))
        assertEquals("新对话提交",Diagnostics.labelFor("/api/agents/codex/create"))
        assertEquals("图片上传",Diagnostics.labelFor("/api/agents/claude/upload"))
    }
    /**
     * Step 7 (prompt §三.7): when a legacy computer returns 404 for `/api/agents/<id>/...`,
     * every action for Codex, Claude, and DeepSeek falls back to the exact original legacy route,
     * query parameters, and request body; non-404 errors and non-legacy 404s never fall back.
     */
    @Test fun legacyHost404FallsBackToExactOriginalRoutesForAllThreeBuiltins()=runTest {
        fun enqueue404Then(json:String) { api.catalog.clear(device);response("""{"error":"没有这个地址"}""",404);response(json) }

        // --- Codex ---
        val codex=api.forSource("codex")
        enqueue404Then("""{"available":true,"running":false}""")
        assertTrue(codex.control(device,"c1",true).available)
        assertEquals("/d/$device/api/agents/codex/state",server.takeRequest().requestUrl!!.encodedPath)
        val cxState=server.takeRequest().requestUrl!!
        assertEquals("/d/$device/api/codex/state",cxState.encodedPath);assertEquals("c1",cxState.queryParameter("id"));assertEquals("1",cxState.queryParameter("fresh"))

        enqueue404Then("""{"request_id":"r1","delivery_state":"accepted"}""")
        val cxSendBody=JSONObject().put("id","c1").put("request_id","r1").put("text","hello").put("intent","auto")
        codex.command(device,"send",cxSendBody)
        assertEquals("/d/$device/api/agents/codex/send",server.takeRequest().requestUrl!!.encodedPath)
        val cxSendLegacy=server.takeRequest()
        assertEquals("/d/$device/api/codex/send",cxSendLegacy.requestUrl!!.encodedPath)
        assertEquals(cxSendBody.toString(),cxSendLegacy.body.readUtf8())

        enqueue404Then("""{"ok":true}""")
        val cxStopBody=JSONObject().put("id","c1").put("operation_id","op1").put("turn_id","t1")
        codex.command(device,"stop",cxStopBody)
        assertEquals("/d/$device/api/agents/codex/stop",server.takeRequest().requestUrl!!.encodedPath)
        val cxStopLegacy=server.takeRequest()
        assertEquals("/d/$device/api/codex/stop",cxStopLegacy.requestUrl!!.encodedPath)
        assertEquals(cxStopBody.toString(),cxStopLegacy.body.readUtf8())

        enqueue404Then("""{"ok":true}""")
        val cxQueueBody=JSONObject().put("id","c1").put("request_id","rq1").put("message_id","m1").put("action","cancel")
        codex.command(device,"queue-action",cxQueueBody)
        val cxQueueUnified=server.takeRequest()
        assertEquals("/d/$device/api/agents/codex/queue",cxQueueUnified.requestUrl!!.encodedPath)
        assertEquals("remove",JSONObject(cxQueueUnified.body.readUtf8()).string("action"))
        val cxQueueLegacy=server.takeRequest()
        assertEquals("/d/$device/api/codex/queue-action",cxQueueLegacy.requestUrl!!.encodedPath)
        // Legacy Codex receives original "cancel" and "message_id" untouched.
        assertEquals(cxQueueBody.toString(),cxQueueLegacy.body.readUtf8())

        enqueue404Then("""{"request_id":"ra1","accepted":true}""")
        val cxAnswerBody=JSONObject().put("id","c1").put("request_id","ra1").put("question_id","q1").put("answers",JSONObject())
        codex.command(device,"answer",cxAnswerBody)
        assertEquals("/d/$device/api/agents/codex/answer",server.takeRequest().requestUrl!!.encodedPath)
        val cxAnswerLegacy=server.takeRequest()
        assertEquals("/d/$device/api/codex/answer",cxAnswerLegacy.requestUrl!!.encodedPath)
        assertEquals(cxAnswerBody.toString(),cxAnswerLegacy.body.readUtf8())

        enqueue404Then("""{"state":"accepted"}""")
        assertEquals("accepted",codex.receipt(device,"c1","r1").string("state"))
        assertEquals("/d/$device/api/agents/codex/receipt",server.takeRequest().requestUrl!!.encodedPath)
        val cxRcpt=server.takeRequest().requestUrl!!
        assertEquals("/d/$device/api/codex/receipt",cxRcpt.encodedPath);assertEquals("c1",cxRcpt.queryParameter("id"));assertEquals("r1",cxRcpt.queryParameter("request_id"))

        enqueue404Then("""{"ok":true}""")
        codex.detail(device,"chat/open",body=JSONObject().put("app","codex").put("id","c1"))
        assertEquals("/d/$device/api/agents/codex/open",server.takeRequest().requestUrl!!.encodedPath)
        val cxOpenLegacy=server.takeRequest()
        assertEquals("/d/$device/api/chat/open",cxOpenLegacy.requestUrl!!.encodedPath)
        assertEquals("codex",JSONObject(cxOpenLegacy.body.readUtf8()).string("app"))

        enqueue404Then("""{"request_id":"n1","state":"creating"}""")
        codex.detail(device,"chat/new",body=JSONObject().put("request_id","n1").put("app","codex").put("text","hi"))
        assertEquals("/d/$device/api/agents/codex/create",server.takeRequest().requestUrl!!.encodedPath)
        assertEquals("/d/$device/api/chat/new",server.takeRequest().requestUrl!!.encodedPath)

        enqueue404Then("""{"request_id":"n1","state":"accepted"}""")
        codex.detail(device,"chat/new/state",mapOf("request_id" to "n1","app" to "codex"))
        assertEquals("/d/$device/api/agents/codex/create/state",server.takeRequest().requestUrl!!.encodedPath)
        val cxNewStateLegacy=server.takeRequest().requestUrl!!
        assertEquals("/d/$device/api/chat/new/state",cxNewStateLegacy.encodedPath)
        assertEquals("n1",cxNewStateLegacy.queryParameter("request_id"));assertNull(cxNewStateLegacy.queryParameter("app"))

        enqueue404Then("""{"models":[]}""")
        codex.detail(device,"chat/new/options",mapOf("app" to "codex"))
        assertEquals("/d/$device/api/agents/codex/options",server.takeRequest().requestUrl!!.encodedPath)
        val cxOptLegacy=server.takeRequest().requestUrl!!
        assertEquals("/d/$device/api/chat/new/options",cxOptLegacy.encodedPath);assertEquals("codex",cxOptLegacy.queryParameter("app"))

        enqueue404Then("""{"id":"img1"}""")
        codex.upload(device,"c1","a.png",byteArrayOf(7,8),image=true)
        assertEquals("/d/$device/api/agents/codex/upload",server.takeRequest().requestUrl!!.encodedPath)
        val cxUpLegacy=server.takeRequest()
        assertEquals("/d/$device/api/codex/upload",cxUpLegacy.requestUrl!!.encodedPath)
        assertEquals("codex",cxUpLegacy.requestUrl!!.queryParameter("app"))
        assertArrayEquals(byteArrayOf(7,8),cxUpLegacy.body.readByteArray())

        // --- Claude ---
        val claude=api.forSource("claude")
        enqueue404Then("""{"available":true,"running":false}""")
        assertTrue(claude.control(device,"c2",true).available)
        assertEquals("/d/$device/api/agents/claude/state",server.takeRequest().requestUrl!!.encodedPath)
        assertEquals("/d/$device/api/claude/state",server.takeRequest().requestUrl!!.encodedPath)

        // Claude receipt on legacy host returns unknown locally after 404 without a second HTTP call.
        api.catalog.clear(device)
        response("""{"error":"没有这个地址"}""",404)
        assertEquals("unknown",claude.receipt(device,"c2","r2").string("state"))
        assertEquals("/d/$device/api/agents/claude/receipt",server.takeRequest().requestUrl!!.encodedPath)

        enqueue404Then("""{"ok":true,"pressed":true,"offset":10}""")
        claude.command(device,"send",JSONObject().put("id","c2").put("request_id","r2").put("text","hi").put("intent","steer").put("expected_turn","t2"))
        val clSendUnified=server.takeRequest()
        assertEquals("/d/$device/api/agents/claude/send",clSendUnified.requestUrl!!.encodedPath)
        val clSendUnifiedJson=JSONObject(clSendUnified.body.readUtf8())
        assertEquals("send",clSendUnifiedJson.string("intent"));assertFalse(clSendUnifiedJson.has("expected_turn"))
        val clSendLegacy=server.takeRequest()
        assertEquals("/d/$device/api/chat/send",clSendLegacy.requestUrl!!.encodedPath)
        assertEquals("claude",JSONObject(clSendLegacy.body.readUtf8()).string("app"))

        enqueue404Then("""{"ok":true}""")
        claude.command(device,"stop",JSONObject().put("id","c2").put("token","t-stop"))
        assertEquals("/d/$device/api/agents/claude/stop",server.takeRequest().requestUrl!!.encodedPath)
        val clStopLegacy=server.takeRequest()
        assertEquals("/d/$device/api/claude/choose",clStopLegacy.requestUrl!!.encodedPath)
        assertEquals("t-stop",JSONObject(clStopLegacy.body.readUtf8()).string("token"))

        for(route in listOf("claude/choose","claude/next","claude/task")) {
            enqueue404Then("""{"ok":true}""")
            claude.detail(device,route,body=JSONObject().put("id","c2").put("token","t1"))
            assertEquals("/d/$device/api/agents/claude/answer",server.takeRequest().requestUrl!!.encodedPath)
            assertEquals("/d/$device/api/$route",server.takeRequest().requestUrl!!.encodedPath)
        }

        // --- DeepSeek ---
        val ds=api.forSource("deepseek")
        enqueue404Then("""{"available":true,"running":true,"seq":9,"queued":[]}""")
        val dsCtrl=ds.control(device,"c3",false)
        assertTrue(dsCtrl.queueAvailable);assertFalse(JSONObject(dsCtrl.raw).has("seq"))
        assertEquals("/d/$device/api/agents/deepseek/state",server.takeRequest().requestUrl!!.encodedPath)
        assertEquals("/d/$device/api/deepseek/state",server.takeRequest().requestUrl!!.encodedPath)

        enqueue404Then("""{"accepted":true}""")
        val dsSendRes=ds.command(device,"send",JSONObject().put("id","c3").put("request_id","r3").put("text","hi").put("intent","auto"))
        assertEquals("accepted",dsSendRes.string("delivery_state"))
        assertEquals("/d/$device/api/agents/deepseek/send",server.takeRequest().requestUrl!!.encodedPath)
        val dsSendLegacy=server.takeRequest()
        assertEquals("/d/$device/api/deepseek/send",dsSendLegacy.requestUrl!!.encodedPath)
        assertEquals("steer",JSONObject(dsSendLegacy.body.readUtf8()).string("intent"))

        enqueue404Then("""{"ok":true}""")
        ds.command(device,"stop",JSONObject().put("id","c3").put("turn_id","t3"))
        assertEquals("/d/$device/api/agents/deepseek/stop",server.takeRequest().requestUrl!!.encodedPath)
        val dsStopLegacy=server.takeRequest()
        assertEquals("/d/$device/api/deepseek/stop",dsStopLegacy.requestUrl!!.encodedPath)
        assertEquals("t3",JSONObject(dsStopLegacy.body.readUtf8()).string("expected_turn"))

        enqueue404Then("""{"ok":true}""")
        ds.command(device,"queue-action",JSONObject().put("id","c3").put("message_id","q3").put("action","promote"))
        assertEquals("/d/$device/api/agents/deepseek/queue",server.takeRequest().requestUrl!!.encodedPath)
        val dsQueueLegacy=server.takeRequest()
        assertEquals("/d/$device/api/deepseek/queue",dsQueueLegacy.requestUrl!!.encodedPath)
        assertEquals("steer",JSONObject(dsQueueLegacy.body.readUtf8()).string("action"))

        for(route in listOf("deepseek/approval","deepseek/answer")) {
            enqueue404Then("""{"ok":true}""")
            ds.detail(device,route,body=JSONObject().put("id","c3").put("event_id","e1").put("choice","allowed-once"))
            assertEquals("/d/$device/api/agents/deepseek/answer",server.takeRequest().requestUrl!!.encodedPath)
            assertEquals("/d/$device/api/$route",server.takeRequest().requestUrl!!.encodedPath)
        }

        enqueue404Then("""{"state":"accepted","id":"c3"}""")
        assertEquals("r3",ds.receipt(device,"c3","r3").string("request_id"))
        assertEquals("/d/$device/api/agents/deepseek/receipt",server.takeRequest().requestUrl!!.encodedPath)
        assertEquals("/d/$device/api/deepseek/receipt",server.takeRequest().requestUrl!!.encodedPath)

        // --- Non-404 errors and non-legacy agent 404s do NOT fall back ---
        api.catalog.clear(device)
        response("""{"error":"轮次已变化"}""",409)
        try { codex.command(device,"stop",JSONObject().put("id","c1"));fail() } catch(e:ServiceFailure) { assertEquals(409,e.status) }
        assertEquals("/d/$device/api/agents/codex/stop",server.takeRequest().requestUrl!!.encodedPath)

        val testing=api.forSource("testing")
        response("""{"error":"没有这个来源"}""",404)
        try { testing.control(device,"test-running",false);fail() } catch(e:ServiceFailure) { assertEquals(404,e.status) }
        assertEquals("/d/$device/api/agents/testing/state",server.takeRequest().requestUrl!!.encodedPath)
    }
    /**
     * When `/api/agents` returns 404 (legacy computer such as dev.41), every control read and action skips unified
     * routes and sends only ONE request directly to the exact legacy route, query, and body.
     */
    @Test fun legacyHostWith404AgentsGoesDirectlyToLegacyRouteInOneRequest()=runTest {
        response("""{"error":"没有这个地址"}""",404)
        assertNull(api.agents(device))
        assertEquals("/d/$device/api/agents",server.takeRequest().requestUrl!!.encodedPath)
        assertTrue(api.catalog.shouldSkipUnified(device))

        suspend fun assertSingle(block:suspend ()->Unit):okhttp3.mockwebserver.RecordedRequest {
            val before=server.requestCount
            block()
            assertEquals("must send exactly one request directly to legacy route",before+1,server.requestCount)
            return server.takeRequest()
        }

        // --- Codex ---
        val codex=api.forSource("codex")
        response("""{"available":true,"running":false}""")
        val cxState=assertSingle { assertTrue(codex.control(device,"c1",true).available) }.requestUrl!!
        assertEquals("/d/$device/api/codex/state",cxState.encodedPath);assertEquals("c1",cxState.queryParameter("id"));assertEquals("1",cxState.queryParameter("fresh"))

        response("""{"request_id":"r1","delivery_state":"accepted"}""")
        val cxSendBody=JSONObject().put("id","c1").put("request_id","r1").put("text","hello").put("intent","auto")
        val cxSend=assertSingle { codex.command(device,"send",cxSendBody) }
        assertEquals("/d/$device/api/codex/send",cxSend.requestUrl!!.encodedPath);assertEquals(cxSendBody.toString(),cxSend.body.readUtf8())

        response("""{"ok":true}""")
        val cxStopBody=JSONObject().put("id","c1").put("operation_id","op1").put("turn_id","t1")
        val cxStop=assertSingle { codex.command(device,"stop",cxStopBody) }
        assertEquals("/d/$device/api/codex/stop",cxStop.requestUrl!!.encodedPath);assertEquals(cxStopBody.toString(),cxStop.body.readUtf8())

        response("""{"ok":true}""")
        val cxQueueBody=JSONObject().put("id","c1").put("request_id","rq1").put("message_id","m1").put("action","cancel")
        val cxQueue=assertSingle { codex.command(device,"queue-action",cxQueueBody) }
        assertEquals("/d/$device/api/codex/queue-action",cxQueue.requestUrl!!.encodedPath);assertEquals(cxQueueBody.toString(),cxQueue.body.readUtf8())

        response("""{"request_id":"ra1","accepted":true}""")
        val cxAnswerBody=JSONObject().put("id","c1").put("request_id","ra1").put("question_id","q1").put("answers",JSONObject())
        val cxAnswer=assertSingle { codex.command(device,"answer",cxAnswerBody) }
        assertEquals("/d/$device/api/codex/answer",cxAnswer.requestUrl!!.encodedPath);assertEquals(cxAnswerBody.toString(),cxAnswer.body.readUtf8())

        response("""{"state":"accepted"}""")
        val cxRcpt=assertSingle { assertEquals("accepted",codex.receipt(device,"c1","r1").string("state")) }.requestUrl!!
        assertEquals("/d/$device/api/codex/receipt",cxRcpt.encodedPath);assertEquals("c1",cxRcpt.queryParameter("id"));assertEquals("r1",cxRcpt.queryParameter("request_id"))

        response("""{"ok":true}""")
        val cxOpen=assertSingle { codex.detail(device,"chat/open",body=JSONObject().put("app","codex").put("id","c1")) }
        assertEquals("/d/$device/api/chat/open",cxOpen.requestUrl!!.encodedPath)

        response("""{"request_id":"n1","state":"creating"}""")
        val cxNew=assertSingle { codex.detail(device,"chat/new",body=JSONObject().put("request_id","n1").put("app","codex").put("text","hi")) }
        assertEquals("/d/$device/api/chat/new",cxNew.requestUrl!!.encodedPath)

        response("""{"request_id":"n1","state":"accepted"}""")
        val cxNewState=assertSingle { codex.detail(device,"chat/new/state",mapOf("request_id" to "n1","app" to "codex")) }.requestUrl!!
        assertEquals("/d/$device/api/chat/new/state",cxNewState.encodedPath);assertEquals("n1",cxNewState.queryParameter("request_id"));assertNull(cxNewState.queryParameter("app"))

        response("""{"models":[]}""")
        val cxOpt=assertSingle { codex.detail(device,"chat/new/options",mapOf("app" to "codex")) }.requestUrl!!
        assertEquals("/d/$device/api/chat/new/options",cxOpt.encodedPath);assertEquals("codex",cxOpt.queryParameter("app"))

        response("""{"id":"img1"}""")
        val cxUp=assertSingle { codex.upload(device,"c1","a.png",byteArrayOf(7,8),image=true) }
        assertEquals("/d/$device/api/codex/upload",cxUp.requestUrl!!.encodedPath);assertEquals("codex",cxUp.requestUrl!!.queryParameter("app"))

        // --- Claude ---
        val claude=api.forSource("claude")
        response("""{"available":true,"running":false}""")
        assertEquals("/d/$device/api/claude/state",assertSingle { assertTrue(claude.control(device,"c2",true).available) }.requestUrl!!.encodedPath)

        // Claude receipt on legacy host sends 0 HTTP requests.
        val beforeClaudeRcpt=server.requestCount
        assertEquals("unknown",claude.receipt(device,"c2","r2").string("state"))
        assertEquals(beforeClaudeRcpt,server.requestCount)

        response("""{"ok":true,"pressed":true,"offset":10}""")
        val clSend=assertSingle { claude.command(device,"send",JSONObject().put("id","c2").put("request_id","r2").put("text","hi")) }
        assertEquals("/d/$device/api/chat/send",clSend.requestUrl!!.encodedPath);assertEquals("claude",JSONObject(clSend.body.readUtf8()).string("app"))

        response("""{"ok":true}""")
        val clStop=assertSingle { claude.command(device,"stop",JSONObject().put("id","c2").put("token","t-stop")) }
        assertEquals("/d/$device/api/claude/choose",clStop.requestUrl!!.encodedPath);assertEquals("t-stop",JSONObject(clStop.body.readUtf8()).string("token"))

        for(route in listOf("claude/choose","claude/next","claude/task")) {
            response("""{"ok":true}""")
            assertEquals("/d/$device/api/$route",assertSingle { claude.detail(device,route,body=JSONObject().put("id","c2").put("token","t1")) }.requestUrl!!.encodedPath)
        }

        // --- DeepSeek ---
        val ds=api.forSource("deepseek")
        response("""{"available":true,"running":true,"seq":9,"queued":[]}""")
        val dsStateReq=assertSingle {
            val ctrl=ds.control(device,"c3",false)
            assertTrue(ctrl.queueAvailable);assertFalse(JSONObject(ctrl.raw).has("seq"))
        }
        assertEquals("/d/$device/api/deepseek/state",dsStateReq.requestUrl!!.encodedPath)

        response("""{"accepted":true}""")
        val dsSend=assertSingle {
            assertEquals("accepted",ds.command(device,"send",JSONObject().put("id","c3").put("request_id","r3").put("text","hi").put("intent","auto")).string("delivery_state"))
        }
        assertEquals("/d/$device/api/deepseek/send",dsSend.requestUrl!!.encodedPath);assertEquals("steer",JSONObject(dsSend.body.readUtf8()).string("intent"))

        response("""{"ok":true}""")
        val dsStop=assertSingle { ds.command(device,"stop",JSONObject().put("id","c3").put("turn_id","t3")) }
        assertEquals("/d/$device/api/deepseek/stop",dsStop.requestUrl!!.encodedPath);assertEquals("t3",JSONObject(dsStop.body.readUtf8()).string("expected_turn"))

        response("""{"ok":true}""")
        val dsQueue=assertSingle { ds.command(device,"queue-action",JSONObject().put("id","c3").put("message_id","q3").put("action","promote")) }
        assertEquals("/d/$device/api/deepseek/queue",dsQueue.requestUrl!!.encodedPath);assertEquals("steer",JSONObject(dsQueue.body.readUtf8()).string("action"))

        for(route in listOf("deepseek/approval","deepseek/answer")) {
            response("""{"ok":true}""")
            assertEquals("/d/$device/api/$route",assertSingle { ds.detail(device,route,body=JSONObject().put("id","c3").put("event_id","e1").put("choice","allowed-once")) }.requestUrl!!.encodedPath)
        }

        response("""{"state":"accepted","id":"c3"}""")
        assertEquals("/d/$device/api/deepseek/receipt",assertSingle { assertEquals("r3",ds.receipt(device,"c3","r3").string("request_id")) }.requestUrl!!.encodedPath)
    }
    /**
     * When a computer has `/api/agents` (such as dev.43) but returns `404 {"error":"没有这个地址"}` for unified routes,
     * the first call falls back and caches that this computer has no unified routes; subsequent calls go straight to
     * legacy routes in 1 request; when `/api/status` reports a new version, unified routes are tried again.
     */
    @Test fun routeMissing404RemembersLegacyAndRetriesAfterStatusVersionChange()=runTest {
        // Host starts as dev.43: has /api/agents, does NOT have /api/agents/<id>/...
        response("""{"schema":1,"protocol":2,"agents":[{"id":"codex","name":{"zh":"Codex","en":"Codex"},"order":10,"color":"#1E222A","color_dark":"#FFFFFF","icon":{"kind":"builtin","key":"codex"},"legacy":true,"min_protocol":1}]}""")
        assertNotNull(api.agents(device));server.takeRequest()
        response("""{"ok":true,"ui_version":"0.27.0-dev.43"}""")
        api.detail(device,"status");server.takeRequest()
        assertFalse(api.catalog.shouldSkipUnified(device))

        // First call tries unified -> 404 "没有这个地址" -> falls back to legacy (2 requests) and remembers.
        response("""{"error":"没有这个地址"}""",404);response("""{"available":true,"running":false}""")
        assertTrue(api.control(device,"c1",false).available)
        assertEquals("/d/$device/api/agents/codex/state",server.takeRequest().requestUrl!!.encodedPath)
        assertEquals("/d/$device/api/codex/state",server.takeRequest().requestUrl!!.encodedPath)
        assertTrue(api.catalog.shouldSkipUnified(device))

        // Subsequent calls on Codex AND DeepSeek go straight to legacy (1 request each).
        val beforeSecond=server.requestCount
        response("""{"available":true,"running":false}""")
        api.control(device,"c1",false)
        assertEquals(beforeSecond+1,server.requestCount)
        assertEquals("/d/$device/api/codex/state",server.takeRequest().requestUrl!!.encodedPath)

        val beforeDs=server.requestCount
        response("""{"available":true,"running":false}""")
        api.forSource("deepseek").control(device,"c3",false)
        assertEquals(beforeDs+1,server.requestCount)
        assertEquals("/d/$device/api/deepseek/state",server.takeRequest().requestUrl!!.encodedPath)

        // Same status version keeps the cache.
        response("""{"ok":true,"ui_version":"0.27.0-dev.43"}""")
        api.detail(device,"status");server.takeRequest()
        assertTrue(api.catalog.shouldSkipUnified(device))

        // Computer upgrades to dev.44 -> /api/status reports new version -> cache cleared -> unified routes tried again!
        response("""{"ok":true,"ui_version":"0.27.0-dev.44"}""")
        api.detail(device,"status");server.takeRequest()
        assertFalse(api.catalog.shouldSkipUnified(device))

        val beforeUpgraded=server.requestCount
        response("""{"available":true,"running":true}""")
        assertTrue(api.control(device,"c1",false).running)
        assertEquals(beforeUpgraded+1,server.requestCount)
        assertEquals("/d/$device/api/agents/codex/state",server.takeRequest().requestUrl!!.encodedPath)
    }
    /**
     * A 404 caused by a missing conversation or unknown source must NOT be confused with a missing route and must NOT
     * disable unified routes for the computer.
     */
    @Test fun conversationNotFound404DoesNotDisableUnifiedRoutes()=runTest {
        response("""{"error":"找不到这个对话（可能已归档或删掉了）"}""",404)
        val before=server.requestCount
        try { api.control(device,"gone",false);fail() } catch(e:ServiceFailure) { assertEquals(404,e.status);assertTrue(e.detail.contains("找不到这个对话")) }
        assertEquals(before+1,server.requestCount)
        assertEquals("/d/$device/api/agents/codex/state",server.takeRequest().requestUrl!!.encodedPath)
        assertFalse(api.catalog.shouldSkipUnified(device))

        // Unknown-source 404 also never disables unified routes.
        response("""{"error":"没有这个来源"}""",404)
        try { api.control(device,"c1",false);fail() } catch(e:ServiceFailure) { assertEquals(404,e.status) }
        server.takeRequest()
        assertFalse(api.catalog.shouldSkipUnified(device))

        // Next call still uses the unified route directly.
        response("""{"available":true,"running":false}""")
        assertTrue(api.control(device,"alive",false).available)
        assertEquals("/d/$device/api/agents/codex/state",server.takeRequest().requestUrl!!.encodedPath)
    }
}
