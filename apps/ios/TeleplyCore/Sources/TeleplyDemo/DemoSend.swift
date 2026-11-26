import Foundation
import TeleplyModel

/// -TeleplyDemoSend: 发送恢复示例, a demo conversation that starts with a send the computer says it never got, and has
/// a message carrying its own pictures (an interjection while the source worked), for the 发送 fixes of 11-26. Off by
/// default, so the screenshot tour's rows and pages stay as they were. The 电脑没收到 copy itself lives on the phone,
/// so TeleplyState's ChatModel+SendDemo.swift seeds it, reading the same launch switch.
enum SendDemo {
    /// The conversation's id; ChatModel+SendDemo.swift has the same one.
    static let chat = "send-demo"

    static let on: Bool = {
        #if DEBUG
        return ProcessInfo.processInfo.arguments.contains("-TeleplyDemoSend")
        #else
        return false
        #endif
    }()

    /// The list row, listed only with the switch.
    static let row: JSONValue = DemoData.row(chat, "发送恢复示例", "测试项目", "电脑没收到，可以重发", "idle", "codex",
                                             DemoData.now - 30_000)

    /// The pictures the interjection carries (`images`, handoff 11-26 §8.2). Ids, names and addresses are made up; the
    /// demo computer answers any /api/codex/image with its fixed picture.
    static let pictures: [JSONValue] = [
        ["id": "fixture-own-picture-1", "name": "插话截图一.png",
         "url": "/api/codex/image?id=fixture-own-picture-1", "thumbnail": "/api/codex/image?thumb=1&id=fixture-own-picture-1"],
        ["id": "fixture-own-picture-2", "name": "插话截图二.png",
         "url": "/api/codex/image?id=fixture-own-picture-2", "thumbnail": "/api/codex/image?thumb=1&id=fixture-own-picture-2"],
    ]

    /// The conversation: a turn under way, the user's own message with two pictures in the middle of it (the way an
    /// interjection reaches the record), then the answer.
    static let messages: [JSONValue] = [
        DemoData.message("sd-1", "user", "把发布说明整理成三条。"),
        DemoData.message("sd-2", "assistant", "先读一下现有的发布说明。", ["phase": "commentary"]),
        DemoData.message("sd-3", "user", "顺便看一下这两张图。", ["images": .array(pictures)]),
        DemoData.message("sd-4", "assistant", "两张图都看到了。发布说明整理成三条，写在下面。"),
    ]
}
