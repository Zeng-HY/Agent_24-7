package com.pocketagentdesk.teleply

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/**
 * Pictures sent with messages, matched to them as the computer kept the sends (user 10-27: a sent picture showed only
 * as "[图片]"; web message-projection.js decorate; the iPhone's SentPicturesTests).
 */
class SentPicturesTest {
    private fun user(id: String, text: String, request: String = "", time: String? = null) =
        Message(id, "user", text, request = request, details = if (time == null) "{}" else JSONObject().put("time", time).toString())

    private fun record(request: String, pictures: List<String>, text: String = "", created: Double = 0.0) =
        JSONObject().put("request_id", request).put("text", text).put("created", created).put("status", "accepted")
            .put("images", JSONArray(pictures.map { JSONObject().put("id", it).put("name", "$it.png") }))

    @Test fun codexSendsGoByTheRequestIdOnTheirMessage() {
        val found = sentPictures(listOf(user("m1", "看这张", request = "r1"), user("m2", "别的", request = "r2")), listOf(record("r1", listOf("a"), text = "看这张")))
        assertEquals(mapOf("m1" to listOf(SentPicture("a", "a.png"))), found)
    }

    /** Claude keeps no request id: by the words after the [图片] mark and the time, newest first. */
    @Test fun claudeSendsGoByTheirWordsAndTimeNewestFirst() {
        // 2026-10-20T08:00:00Z is 1792483200 s; a picture sent without words reached Claude as 请查看这些图片。
        val messages = listOf(user("m1", "[图片] 请查看这些图片。", time = "2026-10-20T08:00:00.000Z"), user("m2", "你好"), user("m3", "[图片] 请查看这些图片。", time = "2026-10-20T09:00:00Z"))
        val records = listOf(record("c1", listOf("a"), created = 1_792_483_198.0), record("c2", listOf("b", "c"), created = 1_792_486_798.0))
        val found = sentPictures(messages, records)
        assertEquals(listOf("a"), found["m1"]?.map { it.id })
        assertEquals(listOf("b", "c"), found["m3"]?.map { it.id })
        assertNull(found["m2"])
        // The older send's message not loaded: it takes none, not the newer one's.
        assertEquals(mapOf("m3" to listOf("b", "c")), sentPictures(listOf(messages[2]), records).mapValues { (_, v) -> v.map { it.id } })
        // A message written before the send is not that send's.
        assertTrue(sentPictures(listOf(messages[0]), listOf(record("c3", listOf("d"), created = 1_792_483_300.0))).isEmpty())
    }

    @Test fun onlyAMessageWithTheMarkAndTheSameWordsTakesPictures() {
        val records = listOf(record("c1", listOf("a"), text = "看 这张图"))
        assertTrue(sentPictures(listOf(user("m1", "看这张图")), records).isEmpty())
        assertEquals(1, sentPictures(listOf(user("m1", "[图片] 看这张 图")), records)["m1"]?.size)
        assertTrue(sentPictures(listOf(user("m1", "[图片] 别的话")), records).isEmpty())
        assertTrue(sentPictures(listOf(user("m1", "[图片] 看这张图")), listOf(record("c1", emptyList(), text = "看这张图"))).isEmpty())
        assertTrue(sentPictures(listOf(user("m1", "[图片] 看这张图")), listOf(record("c1", listOf("../x"), text = "看这张图"))).isEmpty())
        assertEquals("两张", picturedWords("[图片] [图片] 两张"))
        assertNull(picturedWords("没有图"))
        // The time comes with the message from the computer (parseMessage keeps it).
        assertEquals("2026-10-20T08:00:00.000Z", JSONObject(parseMessage(JSONObject("""{"id":"m","role":"user","text":"[图片] x","time":"2026-10-20T08:00:00.000Z"}""")).details).string("time"))
    }
}
