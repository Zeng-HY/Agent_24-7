import Foundation
import TeleplyModel

/// -TeleplyDemoSend (debug builds only): the local demo's 发送恢复示例 conversation starts with a send the computer
/// says it never got, so 重发 / 恢复草稿 / 移除, 核对's line and a message that carries its own pictures can be looked at
/// without a computer. Off by default, so the screenshot tour's pages stay as they were. The row and the conversation
/// are in TeleplyDemo's DemoSend.swift, which reads the same launch switch.
enum SendDemoSeed {
    /// The conversation's id; DemoSend.swift has the same one.
    static let chat = "send-demo"
    /// The request id of the demo's 电脑没收到 send; its body's request_id matches it, as a real send's does.
    static let request = "fixture-send-missing"
    /// What the user wrote; the copy's words and the body's text are the same.
    static let text = "把发布说明整理成三条，发我看看。"

    static let on: Bool = {
        #if DEBUG
        return ProcessInfo.processInfo.arguments.contains("-TeleplyDemoSend")
        #else
        return false
        #endif
    }()
}

extension ChatModel {
    /// Puts the demo's 电脑没收到 copy on its conversation, once (handoff 11-26 §3.1; -TeleplyDemoSend).
    func seedSendDemo(_ key: ChatKey) {
        guard SendDemoSeed.on, key.chat == SendDemoSeed.chat, demo[SendDemoSeed.request] == nil else { return }
        let body: [String: JSONValue] = ["id": .string(key.chat), "request_id": .string(SendDemoSeed.request),
                                         "text": .string(SendDemoSeed.text), "intent": "auto"]
        demo[SendDemoSeed.request] = Submission(request: SendDemoSeed.request, key: key, text: SendDemoSeed.text,
                                                action: "send", turn: "", body: jsonText(.object(body)),
                                                label: missingLabel,
                                                created: Int64(Date().timeIntervalSince1970 * 1000))
    }
}
