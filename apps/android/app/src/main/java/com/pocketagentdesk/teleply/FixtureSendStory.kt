package com.pocketagentdesk.teleply

import org.json.JSONArray
import org.json.JSONObject

/**
 * The demo world's 11-26 发送 story (design 3.1/3.2): one send the computer never got, which 核对 shows as 电脑没收到 and
 * which 重发 can send again with its original request id, and one steering message whose picture is only in the
 * message's own `images`. Everything here is made up and stays inside the local demo.
 */
object FixtureSendStory {
    const val CHAT = "send-state-demo"
    const val MISSING_REQUEST = "fixture-send-missing-1"
    const val MISSING_MESSAGE = "send-state-3"
    const val MISSING_TEXT = "帮我把升级步骤补到发布说明里。"

    /** The demo conversation's row; older than the first page's top rows, so the existing screenshots keep their view. */
    fun chat() = Chat(CHAT, "发送状态示例", "测试项目", "电脑没收到和带图插话", "idle", "codex", FixtureWorld.NOW - 480_000)

    /** The conversation: a send that never arrived, and a later steering message with its own picture. */
    fun messages(): List<Message> = listOf(
        Message("send-state-1", "user", "先把发布说明的格式定下来。"),
        Message("send-state-2", "assistant", "好，我按简洁要点写，发布说明一改完就贴给你。", phase = "commentary"),
        // The phone's own copy of the send the computer's record does not have: its receipt label says 电脑没收到.
        Message(MISSING_MESSAGE, "user", MISSING_TEXT, request = MISSING_REQUEST),
        Message("send-state-4", "assistant", "还在读发布说明。", phase = "commentary"),
        // A steering message: no request id the send records could match, the picture is only in the message's `images`.
        Message(
            "send-state-5", "user", "[图片] 插话：顺手看一下这张截图。",
            images = listOf(MessageImage("fixture-send-own-1", "插话截图.png", "/api/codex/image?id=fixture-send-own-1")),
        ),
        Message("send-state-6", "assistant", "截图看到了，图里的两处编号要改。"),
    )

    /** The computer knows its delivery record and has no such request (design §8.1). */
    fun missingReceipt(): JSONObject = JSONObject().put("state", "unknown").put("missing", true)

    /**
     * Seeds the demo's send record once per conversation: the phone had written its copy and the computer never got it,
     * so the record starts as 待确认 and the first 核对 turns it into 电脑没收到. A removed or resent copy is not put back.
     */
    fun seed(records: MutableMap<String, Submission>, key: ChatKey) {
        if (key.chat != CHAT || key.app != "codex" || MISSING_REQUEST in records) return
        val body = JSONObject()
            .put("id", CHAT)
            .put("request_id", MISSING_REQUEST)
            .put("text", MISSING_TEXT)
            .put("intent", "auto")
            .put("attachments", JSONArray())
        records[MISSING_REQUEST] = Submission(
            MISSING_REQUEST, key.scope, key.device, app = key.app, chat = key.chat, text = MISSING_TEXT, action = "send",
            turn = "", body = body.toString(), label = "送达状态待确认", created = FixtureWorld.NOW - 120_000,
        )
    }
}
