import Foundation
import TeleplyModel

/// -TeleplyDemoSteer: 插话等待示例, a demo conversation whose turn runs a command while an interjection the computer took
/// waits for it — the grey line 等 Codex 做完这一步再插进去 and the button 结束这条命令，马上插话 of 11-27 (design §4.2 and
/// §4.3). Off by default, so the screenshot tour's rows and pages stay as they were. The waiting copy itself lives on the
/// phone, so TeleplyState's ChatModel+SteerDemo.swift seeds it from the same launch switch. Every name and word here is
/// made up.
public enum SteerDemo {
    /// The conversation's id; ChatModel+SteerDemo.swift has the same one.
    public static let chat = "steer-demo"

    public static let on: Bool = {
        #if DEBUG
        return ProcessInfo.processInfo.arguments.contains("-TeleplyDemoSteer")
        #else
        return false
        #endif
    }()

    /// The list row, listed only with the switch.
    static let row: JSONValue = DemoData.row(chat, "插话等待示例", "测试项目", "等 Codex 做完这一步再插进去", "running", "codex",
                                             DemoData.now - 20_000,
                                             ["turn_started": .number(Double(DemoData.startedSeconds)), "step": "run"])

    /// The record: a turn under way and the check it is running. The interjection is not here yet — it waits on the
    /// phone, as ChatModel+SteerDemo.swift puts it, so the timeline shows it as the light bubble of a send not yet in the
    /// record, and the grey line over the input says what it waits for.
    static let messages: [JSONValue] = [
        DemoData.message("sw-1", "user", "把发布说明里的升级步骤补上，然后跑一遍检查。"),
        DemoData.message("sw-2", "assistant", "先看一下现在的发布说明。", ["phase": "commentary"]),
        DemoData.message("sw-3", "tool", "运行 npm run check", ["tool": "shell", "title": "运行 npm run check",
                                                                "tool_status": "running"]),
    ]
}
