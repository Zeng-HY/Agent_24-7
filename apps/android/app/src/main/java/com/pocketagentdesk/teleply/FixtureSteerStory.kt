package com.pocketagentdesk.teleply

import org.json.JSONArray
import org.json.JSONObject

/**
 * The demo world's 11-27 story (design 4.2/4.3): Codex is running a command, a steer has been accepted and is waiting for
 * the step to finish. The input card shows the waiting line and 结束这条命令，马上插话; the demo computer's kill-command
 * ends only that command, so the line's result is 已结束命令，正在插话… All of it is made up and stays in the demo.
 */
object FixtureSteerStory {
    const val CHAT = "steer-wait-demo"
    const val REQUEST = "fixture-steer-wait-1"
    const val TEXT = "这条命令跑完以后，顺手把错误处理也补上。"

    /** The demo conversation's row: running, so the send button offers 发送（插话）. */
    fun chat() = Chat(CHAT, "插话等待示例", "测试项目", "等 Codex 做完这一步再插进去", "running", "codex", FixtureWorld.NOW - 900_000)

    /** What the record shows: a running command step, and the steer the phone says the computer accepted. */
    fun messages(): List<Message> = listOf(
        Message("steer-1", "user", "把下载目录里过期的安装包列出来。"),
        Message("steer-2", "assistant", "好，我先列一下再删。", phase = "commentary"),
        Message("steer-3", "tool", "运行 列目录", details = """{"tool":"shell","title":"列下载目录"}""", status = "running"),
    )

    /** The computer took the steer and has not delivered it: state accepted, no delivery evidence after all. */
    fun steerReceipt(): JSONObject = JSONObject().put("request_id", REQUEST).put("state", "accepted")

    /**
     * Seeds the phone's copy once per demo conversation: label 已接收 with `intent: steer`, so the waiting line shows as
     * soon as the conversation opens. [Submission.created] is the phone's time, a little in the past, so 已等 starts at
     * once rather than at 0.
     */
    fun seed(records: MutableMap<String, Submission>, key: ChatKey) {
        if (key.chat != CHAT || key.app != "codex" || REQUEST in records) return
        val body = JSONObject()
            .put("id", CHAT)
            .put("request_id", REQUEST)
            .put("text", TEXT)
            .put("intent", "steer")
            .put("expected_turn", "steer-turn")
            .put("attachments", JSONArray())
        records[REQUEST] = Submission(
            REQUEST, key.scope, key.device, app = key.app, chat = key.chat, text = TEXT, action = "send",
            turn = "steer-turn", body = body.toString(), label = "已接收", created = System.currentTimeMillis() - 12_000,
        )
    }
}
