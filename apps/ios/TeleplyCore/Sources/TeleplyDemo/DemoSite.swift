import Foundation
import TeleplyModel

/// The website's pictures (pocketagentdesk.com): a demo computer with DeepSeek alone, its words in Chinese or English.
/// The site names no other AI product (user 11-04), so nothing here may either; DemoServiceTests looks. Only debug
/// builds reach this, through the launch switch -TeleplyDemoSite (ScreenshotTour.siteShots).
public struct DemoSite: Sendable {
    public let english: Bool
    /// When the demo opened: rows read as a moment ago, not as the fixed demo date.
    let now = Int64(Date().timeIntervalSince1970 * 1000)

    public init(english: Bool) {
        self.english = english
    }

    func word(_ chinese: String, _ other: String) -> String {
        english ? other : chinese
    }

    var computers: [Computer] {
        [Computer(id: DemoData.computerA, label: word("书房的电脑", "Home PC"), connectable: true),
         Computer(id: DemoData.computerB, label: word("公司的电脑", "Office PC"), connectable: true),
         Computer(id: DemoData.offline, label: word("旧笔记本", "Old Laptop"), connectable: false)]
    }

    var project: String { word("示例项目", "Sample Project") }

    var rows: [JSONValue] {
        let docs = word("文档", "Docs")
        return [
            DemoData.row("site-question", word("重做登录页的样式", "Restyle the login page"), project,
                         word("登录页用哪种做法？", "Which approach for the login page?"), "waiting", "deepseek", now - 60_000),
            DemoData.row("running-demo", word("把接口文档做成 Word", "Turn the API notes into a Word file"), docs,
                         word("正在跑命令", "Running a command"), "running", "deepseek", now - 120_000,
                         ["turn_started": .number(Double(DemoData.startedSeconds)), "step": "run"]),
            DemoData.row("site-approval", word("清理构建缓存", "Clear the build cache"), project,
                         word("批准这一步吗？", "Approve this step?"), "waiting", "deepseek", now - 600_000),
            DemoData.row("site-done", word("修复列表排序", "Fix the list order"), project,
                         word("改好了，测试全部通过", "Fixed. All tests pass."), "idle", "deepseek", now - 1_800_000),
            DemoData.row("site-tests", word("补齐单元测试", "Add the missing unit tests"), project,
                         word("补了 12 个测试", "Added 12 tests"), "idle", "deepseek", now - 7_200_000),
            DemoData.row("site-notes", word("整理发布说明", "Write the release notes"), docs,
                         word("发布说明写好了", "The release notes are ready"), "idle", "deepseek", now - 28_800_000),
        ]
    }

    func messages(chat: String) -> [JSONValue] {
        switch chat {
        case "site-question":
            return [
                DemoData.message("q1", "user", word("登录页太旧了，帮我重做一下样式。", "The login page looks dated. Please restyle it.")),
                DemoData.message("q2", "assistant", word("我先看看现在的样式和用到的组件。", "Let me look at the current styles and components first."), ["phase": "commentary"]),
                DemoData.message("q3", "tool", word("读取 web/login.css", "Read web/login.css"),
                                 ["tool": "read", "title": .string(word("读取 web/login.css", "Read web/login.css")), "tool_status": "completed"]),
                DemoData.message("q4", "assistant", word("有两种做法，请选一种。", "There are two ways to do this. Please pick one."), ["kind": "question"]),
            ]
        case "site-approval":
            return [
                DemoData.message("a1", "user", word("清理一下构建缓存，再跑一遍测试。", "Clear the build cache and run the tests again.")),
                DemoData.message("a2", "assistant", word("要删除构建目录才能继续，等你批准。", "I need to delete the build folder to continue. Waiting for your approval."), ["phase": "commentary"]),
            ]
        case "running-demo":
            return [
                DemoData.message("r1", "user", word("把接口文档做成 Word，每个接口一节。", "Turn the API notes into a Word file, one section per endpoint.")),
                DemoData.message("r2", "assistant", word("我先读一遍文档，再逐节生成。", "I will read the notes first, then build it section by section."), ["phase": "commentary"]),
                DemoData.message("r3", "tool", word("运行 python make_docx.py", "Run python make_docx.py"),
                                 ["tool": "shell", "title": .string(word("运行 python make_docx.py", "Run python make_docx.py")), "tool_status": "in_progress"]),
            ]
        default:
            return [
                DemoData.message("d1", "user", word("列表排序不对，新对话跑到后面去了。", "The list order is wrong: new conversations end up at the bottom.")),
                DemoData.message("d2", "assistant", word("我先看一下排序的代码。", "Let me look at the sorting code first."), ["phase": "commentary"]),
                DemoData.message("d3", "tool", word("修改 list.py", "Edit list.py"),
                                 ["tool": "edit", "title": .string(word("修改 list.py", "Edit list.py")), "tool_status": "completed",
                                  "changes": [["path": "list.py", "ref": "fixture-diff"]]]),
                DemoData.message("d4", "assistant", word(
                    "修好了。原因是排序时用了创建时间，不是最后更新时间。\n\n| 文件 | 改动 |\n|---|---|\n| `list.py` | 按最后更新时间排序 |\n| `test_list.py` | 加了 3 个测试 |\n\n```python\nrows.sort(key=lambda r: r.updated, reverse=True)\n```\n\n全部测试都通过了。",
                    "Fixed. The list was sorted by creation time instead of the last update.\n\n| File | Change |\n|---|---|\n| `list.py` | Sort by last update |\n| `test_list.py` | 3 new tests |\n\n```python\nrows.sort(key=lambda r: r.updated, reverse=True)\n```\n\nAll tests pass.")),
            ]
        }
    }

    /// /api/deepseek/state for a conversation: only its own card is waiting.
    func state(chat: String) -> JSONValue {
        var fields = DemoData.deepseekState.object
        let approval: JSONValue = ["event": "approval/request", "eventId": "site-approval-1",
                                   "request": ["toolName": "shell", "reason": "rm -rf build/",
                                               "displayReason": .string(word("删除 build 目录（构建缓存）", "Delete the build folder (build cache)"))]]
        let question: JSONValue = ["callId": "site-question-1", "questions": [[
            "id": "q1", "question": .string(word("登录页用哪种做法？", "Which approach for the login page?")),
            "options": [["label": .string(word("保留现在的布局", "Keep the layout")),
                         "description": .string(word("只换颜色和字号，改动小", "Only colors and type change. A small edit."))],
                        ["label": .string(word("重新设计布局", "Redesign the layout")),
                         "description": .string(word("效果更好，要多花一点时间", "Looks better, takes a little longer."))]],
        ]]]
        fields["interactions"] = chat == "site-approval" ? [approval] : []
        fields["questions"] = chat == "site-question" ? [question] : []
        return .object(fields)
    }

    var permissionName: String { word("工作区内修改", "Workspace edits") }

    var models: JSONValue {
        english
            ? DemoData.parse(#"{"groups":[{"id":"deepseek","name":"DeepSeek","models":[{"id":"deepseek-v4","name":"DeepSeek V4","reasoning":{"efforts":[{"id":"high","name":"High"},{"id":"low","name":"Low"}]}}]}]}"#)
            : DemoData.deepseekModels
    }

    /// 对话文件: what a turn left behind, of the kinds the phone opens by itself.
    var files: [JSONValue] {
        func file(_ id: String, _ chinese: String, _ other: String, _ kind: String, _ size: Double) -> JSONValue {
            let name = word(chinese, other)
            return ["id": .string(id), "name": .string(name), "path": .string("D:\\projects\\sample\\" + name), "kind": .string(kind),
                    "state": "current", "size": .number(size)]
        }
        return [file("fixture-html", "登录页预览.html", "login-preview.html", "text", 900),
                file("fixture-png", "登录页截图.png", "login-screenshot.png", "image", 462),
                file("fixture-md", "修改说明.md", "change-notes.md", "text", 200),
                file("fixture-report", "发布说明.docx", "release-notes.docx", "download", 48_000),
                file("site-xlsx", "测试报告.xlsx", "test-report.xlsx", "download", 21_000),
                file("site-pdf", "使用手册.pdf", "user-guide.pdf", "download", 320_000)]
    }
}
