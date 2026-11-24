package com.pocketagentdesk.teleply

import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** The relay side of 遥应通知 as this phone writes it (design-2 §1.1, §1.2): registration bodies and the stream request. */
class RelayApiPushTest {
    private lateinit var server: MockWebServer
    private lateinit var api: RelayApi
    private val token = "60e05bd1b195af2f94112fa7197a5c88289058840ce7c6df9693756bc6250f55"

    @Before fun setup() {
        val cert = HeldCertificate.Builder().addSubjectAlternativeName("localhost").addSubjectAlternativeName("127.0.0.1").build()
        val tls = HandshakeCertificates.Builder().heldCertificate(cert).build()
        val trust = HandshakeCertificates.Builder().addTrustedCertificate(cert.certificate).build()
        server = MockWebServer().apply { useHttps(tls.sslSocketFactory(), false); start() }
        val client = OkHttpClient.Builder().sslSocketFactory(trust.sslSocketFactory(), trust.trustManager).build()
        api = RelayApi(server.url("/").toString(), MemoryCookieVault(), client)
    }

    @After fun cleanup() {
        api.close()
        server.shutdown()
    }

    private fun response(json: String, status: Int = 200) { server.enqueue(MockResponse().setResponseCode(status).setHeader("Content-Type", "application/json").setBody(json)) }

    @Test fun registerSendsTheFingerprintAndThisPhonesFactsAndNothingElse() = runTest {
        response("""{"ok":true}""")
        api.pushRegister(token, "Pixel 9", "1.0.10", "zh-Hans")
        val request = server.takeRequest()
        assertEquals("POST", request.method)
        assertEquals("/account/push/register", request.requestUrl!!.encodedPath)
        val body = JSONObject(request.body.readUtf8())
        assertEquals(token, body.string("token"))
        assertEquals("android", body.string("platform"))
        assertEquals("relay", body.string("environment"))
        assertEquals("Pixel 9", body.string("label"))
        assertEquals("1.0.10", body.string("version"))
        assertEquals("zh-Hans", body.string("language"))
        assertEquals(6, body.length())
        assertFalse("the key itself never travels", body.has("secret"))
        assertEquals(token, pushToken("00".repeat(32)))
    }

    @Test fun stateUnregisterAndTestCarryTheFingerprintToTheirOwnRoutes() = runTest {
        for ((action, call) in listOf<Pair<String, suspend () -> Unit>>(
            "state" to { api.pushState(token) },
            "unregister" to { api.pushUnregister(token) },
            "test" to { api.pushTest(token) },
        )) {
            response("""{"ok":true}""")
            call()
            val request = server.takeRequest()
            assertEquals("/account/push/$action", request.requestUrl!!.encodedPath)
            assertEquals("POST", request.method)
            val body = JSONObject(request.body.readUtf8())
            assertEquals(token, body.string("token"))
            assertEquals(1, body.length())
        }
    }

    @Test fun theStreamIsWssWithBearerAndSinceAndNoCookie() {
        val opened = CountDownLatch(1)
        server.enqueue(MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: okhttp3.Response) { opened.countDown() }
        }))
        val seen = CountDownLatch(1)
        val socket = api.pushWebSocket("00".repeat(32), "1a2b3c4d:42", object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: okhttp3.Response) { seen.countDown() }
        })
        assertTrue("the relay's upgrade reached us", opened.await(5, TimeUnit.SECONDS))
        assertTrue(seen.await(5, TimeUnit.SECONDS))
        val request = server.takeRequest(5, TimeUnit.SECONDS)!!
        assertEquals("/push/android", request.requestUrl!!.encodedPath)
        assertEquals("1a2b3c4d:42", request.requestUrl!!.queryParameter("since"))
        assertEquals("Bearer ${"00".repeat(32)}", request.getHeader("Authorization"))
        assertNull("the stream does not use the account cookie", request.getHeader("Cookie"))
        assertEquals(180_000, api.pushClient.pingIntervalMillis)
        assertEquals(0, api.pushClient.callTimeoutMillis)
        assertEquals(0, api.pushClient.readTimeoutMillis)
        socket.close(1000, "test")
    }

    @Test fun withoutSinceTheStreamAsksFromTheRelaysHello() {
        val opened = CountDownLatch(1)
        server.enqueue(MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: okhttp3.Response) { opened.countDown() }
        }))
        val socket = api.pushWebSocket("00".repeat(32), null, object : WebSocketListener() {})
        assertTrue(opened.await(5, TimeUnit.SECONDS))
        val request = server.takeRequest(5, TimeUnit.SECONDS)!!
        assertNull(request.requestUrl!!.queryParameter("since"))
        socket.close(1000, "test")
    }

    @Test fun aRefusedRegistrationLeavesTheRequestsWordsForThePage() = runTest {
        response("""{"error":"请先登录"}""", 401)
        try {
            api.pushRegister(token, "Pixel 9", "1.0.10", "zh-Hans")
            error("a 401 must not pass")
        } catch (e: ServiceFailure) {
            assertEquals(401, e.status)
            assertEquals("登录已失效，请重新登录后再打开遥应通知", pushFailureText(e))
        }
        server.takeRequest()
    }
}
