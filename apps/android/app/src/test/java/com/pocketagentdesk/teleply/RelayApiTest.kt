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
        val upload=server.takeRequest();assertEquals("/d/$device/api/codex/upload",upload.requestUrl!!.encodedPath);assertEquals("deepseek",upload.requestUrl!!.queryParameter("app"));assertEquals(server.url("/").toString().removeSuffix("/"),upload.getHeader("Origin"));assertArrayEquals(byteArrayOf(1,2,3),upload.body.readByteArray())
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
        val post=server.takeRequest();assertEquals("/d/$device/api/codex/send",post.requestUrl!!.encodedPath);assertEquals(server.url("/").toString().removeSuffix("/"),post.getHeader("Origin"))
        response("""{"state":"unknown"}""");api.receipt(device,"chat","r")
        val get=server.takeRequest();assertEquals("r",get.requestUrl!!.queryParameter("request_id"));assertEquals("GET",get.method)
    }
    @Test fun mixedListKeepsEachRowSourceAndRejectsUnknownSources()=runTest {
        response("""{"items":[{"id":"a","app":"codex","title":"A"},{"id":"b","app":"claude","title":"B"},{"id":"c","app":"deepseek","title":"C"}],"has_more":false}""")
        val page=api.chatList(device,"all","",null,"created","waiting")
        assertEquals(listOf("codex","claude","deepseek"),page.items.map { it.app })
        val request=server.takeRequest().requestUrl!!
        assertEquals("all",request.queryParameter("app"));assertEquals("created",request.queryParameter("sort"));assertEquals("waiting",request.queryParameter("status"))
        response("""{"items":[{"id":"x","app":"other","title":"X"}]}""")
        assertTrue(runCatching { api.chatList(device,"all","",null) }.isFailure)
        response("""{"items":[{"id":"x","app":"claude","title":"X"}]}""")
        assertTrue("a Codex-only list must not accept a Claude row",runCatching { api.chatList(device,"codex","",null) }.isFailure)
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
}
