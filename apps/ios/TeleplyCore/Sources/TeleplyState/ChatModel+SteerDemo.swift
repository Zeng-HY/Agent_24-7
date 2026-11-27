import Foundation
import TeleplyModel

/// -TeleplyDemoSteer (debug builds only): the local demo's 插话等待示例 conversation starts with an interjection the
/// computer took and has not delivered, so the grey line 等 Codex 做完这一步再插进去 with its seconds, and the button
/// 结束这条命令，马上插话 next to it, can be looked at without a computer (design 11-27 §4.2, §4.3). Off by default, so the
/// screenshot tour's rows and pages stay as they were. The row, the record and the state are in TeleplyDemo's
/// DemoSteer.swift, which reads the same launch switch.
enum SteerDemoSeed {
    /// The conversation's id; DemoSteer.swift has the same one.
    static let chat = "steer-demo"
    /// The request id of the demo's waiting interjection; its body's request_id matches it, as a real send's does.
    static let request = "fixture-steer-waiting"
    /// What the user wrote; the copy's words and the body's text are the same.
    static let text = "顺便把检查的日志也发我一份。"

    static let on: Bool = {
        #if DEBUG
        return ProcessInfo.processInfo.arguments.contains("-TeleplyDemoSteer")
        #else
        return false
        #endif
    }()
}

extension ChatModel {
    /// Puts the demo's waiting interjection on its conversation, once (design §4.2; -TeleplyDemoSteer). The computer took
    /// it a little while ago, so the line starts at a number of seconds that can be seen counting.
    func seedSteerDemo(_ key: ChatKey) {
        guard SteerDemoSeed.on, key.chat == SteerDemoSeed.chat, demo[SteerDemoSeed.request] == nil else { return }
        let body: [String: JSONValue] = ["id": .string(key.chat), "request_id": .string(SteerDemoSeed.request),
                                         "text": .string(SteerDemoSeed.text), "intent": "steer",
                                         "expected_turn": "steer-turn"]
        demo[SteerDemoSeed.request] = Submission(request: SteerDemoSeed.request, key: key, text: SteerDemoSeed.text,
                                                action: "send", turn: "steer-turn",
                                                body: jsonText(.object(body)),
                                                label: Hints.text("已接收"),
                                                created: Int64(Date().timeIntervalSince1970 * 1000) - 12_000)
    }
}
