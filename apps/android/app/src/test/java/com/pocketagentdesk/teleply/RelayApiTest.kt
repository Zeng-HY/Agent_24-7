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
        assertThrows(IllegalArgumentException::class.java) { serviceOrigin("https://example.invalid/private") }
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
    private val device="a".repeat(32)
    @Before fun setup() {
        val cert=HeldCertificate.Builder().addSubjectAlternativeName("localhost").addSubjectAlternativeName("127.0.0.1").build()
        val tls=HandshakeCertificates.Builder().heldCertificate(cert).build()
        val trust=HandshakeCertificates.Builder().addTrustedCertificate(cert.certificate).build()
        server=MockWebServer().apply { useHttps(tls.sslSocketFactory(),false);start() }
        vault=MemoryCookieVault()
        api=RelayApi(server.url("/").toString(),vault,OkHttpClient.Builder().sslSocketFactory(trust.sslSocketFactory(),trust.trustManager).build())
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
        response("""{"id":"x/y","app":"codex","messages":[{"id":"m1","role":"assistant","text":"原文\n","truncated":true}],"next_cursor":"m1","has_more":true,"has_newer":true}""")
        val page=api.history(device,"x/y",before="opaque + / ?")
        val request=server.takeRequest()
        assertEquals("x/y",request.requestUrl!!.queryParameter("id"));assertEquals("opaque + / ?",request.requestUrl!!.queryParameter("before"))
        assertEquals("原文\n",page.items.single().text);assertTrue(page.items.single().truncated);assertTrue(page.hasNewer)
    }
    @Test fun selectRejectsMismatchedDevicePath()=runTest {
        response("""{"url":"/d/${"b".repeat(32)}/"}""")
        try { api.select(device);fail() } catch(_:IllegalArgumentException) { }
    }
    @Test fun offlineHasSpecificError()=runTest {
        response("""{"code":"device_offline"}""",409)
        try { api.select(device);fail() } catch(e:ServiceFailure) { assertEquals(409,e.status);assertEquals("device_offline",e.code) }
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
