import Foundation
import Synchronization
import TeleplyModel

/// 开发者选项 → 示例网络 (Android FixtureNetwork): how the demo computer answers, to see the app on a slow or
/// broken connection. Only computer routes (/d/…) wait or fail; the account service answers at once.
public enum DemoNetwork: String, Sendable, CaseIterable {
    case instant, normal, slow, offline

    public var label: String {
        switch self {
        case .instant: return "立即"
        case .normal: return "一般"
        case .slow: return "慢"
        case .offline: return "断开"
        }
    }

    public var delay: Duration {
        switch self {
        case .normal: return .milliseconds(400)
        case .slow: return .milliseconds(2_500)
        case .instant, .offline: return .zero
        }
    }
}

/// The local demo's shared state (Android FixtureWorld): deliberately synthetic, never a real service or real
/// credentials. Phase 1 holds what reading needs; answers, queues and archiving arrive with phases 2 and 3.
public final class DemoWorld: Sendable {
    struct State {
        var signedIn = false
        var network = DemoNetwork.instant
        var devices = [
            Computer(id: DemoData.computerA, label: "测试电脑 A", connectable: true),
            Computer(id: DemoData.computerB, label: "测试电脑 B", connectable: true),
            Computer(id: DemoData.offline, label: "离线电脑", connectable: false),
        ]
        /// State reads asked of the demo computer (source, conversation, fresh): polls must not ask for fresh ones.
        var stateReads: [(app: String, chat: String, fresh: Bool)] = []
    }

    let state = Mutex(State())

    public init() {}

    public var network: DemoNetwork {
        get { state.withLock { $0.network } }
        set { state.withLock { $0.network = newValue } }
    }

    public var stateReads: [(app: String, chat: String, fresh: Bool)] {
        state.withLock { $0.stateReads }
    }

    /// The desktop apps each demo computer has; 测试电脑 B has no Claude, like a tester's (Android 0.9.1).
    func apps(of device: String) -> [String] {
        device == DemoData.computerB ? ["codex", "deepseek"] : sourceOrder
    }
}

/// The demo's fixed content, word for word as Android FixtureApi so screenshots of both apps compare.
enum DemoData {
    /// Fixed clock so the demo reads the same every time (2026-10-24 12:00 UTC), in milliseconds.
    static let now: Int64 = 1_792_843_200_000
    static let computerA = String(repeating: "a", count: 32)
    static let computerB = String(repeating: "b", count: 32)
    static let offline = String(repeating: "c", count: 32)
    static let ungrouped = "ungrouped"
    static let taskTitle = "整理发布清单"

    static func row(_ id: String, _ title: String, _ folder: String, _ preview: String, _ status: String, _ app: String,
                    _ updated: Int64, _ extra: [String: JSONValue] = [:]) -> JSONValue {
        var fields: [String: JSONValue] = ["id": .string(id), "title": .string(title), "folder": .string(folder), "preview": .string(preview),
                                           "status": .string(status), "app": .string(app), "updated": .number(Double(updated))]
        fields.merge(extra) { _, new in new }
        return .object(fields)
    }

    static let deepseekChildren: [JSONValue] = [
        row("sa-1", "检查日志", "", "", "running", "deepseek", now - 1_700_000, ["kind": "subagent", "parent": "deepseek-demo", "parent_title": "DeepSeek 批准示例"]),
        row("ds-run-1", "每日构建（脚本）", "", "", "idle", "deepseek", now - 3_600_000, ["kind": "script", "parent": "deepseek-demo", "parent_title": "DeepSeek 批准示例"]),
        row("ds-run-2", "清理缓存（脚本）", "", "", "idle", "deepseek", now - 7_200_000, ["kind": "script", "parent": "deepseek-demo", "parent_title": "DeepSeek 批准示例"]),
    ]

    /// The first list page (Android FixtureWorld.all()), newest first.
    static let firstPage: [JSONValue] = [
        row("demo", "原生阅读示例", "测试项目", "Markdown、表格和代码", "idle", "codex", now - 60_000),
        row("claude-demo", "Claude 选项示例", "测试项目", "请选择发布说明的格式", "waiting", "claude", now - 600_000),
        row("deepseek-demo", "DeepSeek 批准示例", "固定测试项目", "批准这一步吗？", "waiting", "deepseek", now - 1_800_000,
            ["children": .array(Array(deepseekChildren.prefix(2))), "child_count": 3, "child_running": 1]),
        row("question", "只读问题记录", "测试项目", "问题卡在时间线里作答", "waiting", "codex", now - 7_200_000),
        row("claude-next", "Claude 下一步示例", "测试项目", "下一步按钮和任务卡片", "idle", "claude", now - 9_000_000),
        row("plan-demo", "Codex 计划示例", "测试项目", "计划待确认", "idle", "codex", now - 10_800_000),
        row(ungrouped, "未分组的会话", "", "不在 DeepSeek 工作区里，多是脚本或命令行开的一次性会话", "idle", "deepseek", now - 14_400_000,
            ["group": true, "children": [row("ds-stray-1", "整理下载目录（脚本）", "", "", "idle", "deepseek", now - 14_400_000, ["kind": "script"])], "child_count": 1]),
    ]

    static let older = row("older", "更早的对话", "测试项目", "第二页", "idle", "codex", now - 86_400_000 * 3)

    static func message(_ id: String, _ role: String, _ text: String, _ extra: [String: JSONValue] = [:]) -> JSONValue {
        var fields: [String: JSONValue] = ["id": .string(id), "role": .string(role), "text": .string(text)]
        fields.merge(extra) { _, new in new }
        return .object(fields)
    }

    static func messages(app: String, chat: String) -> [JSONValue] {
        if app == "claude" && chat == "claude-next" {
            let plan: JSONValue = .array([("读现有测试", "completed"), ("补发布说明的测试", "completed"), ("跑一遍全部测试", "in_progress"), ("更新说明文档", "pending")]
                .map { ["text": .string($0.0), "status": .string($0.1)] })
            return [
                message("n1", "user", "把发布说明的测试补齐。", ["origin": "other_chat"]),
                message("n2", "assistant", "先列一下要做的几步。", ["phase": "commentary"]),
                message("n3", "plan", "计划 2/4", ["items": plan]),
                message("n4", "tool", "运行 测试", ["tool": "shell", "title": "运行 npm test", "tool_status": "completed"]),
                message("n5", "assistant", "测试补好了，全部通过。说明文档还没改。"),
                message("n6", "next", "这一轮做完了", ["tool_id": "wrap-1", "recap": "补了 3 个测试，全部通过；说明文档还没改。", "ask": "接下来做什么？",
                                                   "actions": [["label": "接着改说明文档", "message": "接着改说明文档"], ["label": "先停在这里", "message": "先停在这里"]], "open": true]),
                message("n8", "task", taskTitle, ["tool_id": "task-1", "title": .string(taskTitle), "offer": false,
                                                  "brief": "把这次改动整理成发布清单：列出新增的测试、受影响的页面、需要人工确认的地方，并附上每一项的验证方法。改完发给我看。"]),
            ]
        }
        switch app {
        case "claude":
            return [
                message("c1", "user", "帮我把这次的发布说明整理一下。"),
                message("c2", "assistant", "我先看一下现有的文档和最近的提交。", ["phase": "commentary"]),
                message("c3", "tool", "读取 docs/release.md", ["tool": "read", "title": "读取 docs/release.md", "tool_status": "completed"]),
                message("c4", "assistant", "有两种写法，请在下面选一种。", ["kind": "question"]),
            ]
        case "deepseek":
            return [
                message("d1", "user", "清理一下构建缓存。"),
                message("d2", "assistant", "需要运行一个命令删除构建目录，等你批准。", ["phase": "commentary"]),
                message("subagent:sa-1", "subagent", "子智能体：检查日志", ["child": "sa-1", "label": "检查日志", "status": "running"]),
            ]
        default:
            if chat == "plan-demo" {
                return [
                    message("p1", "user", "先给我一个计划，确认后再改。"),
                    message("p2", "assistant", "我先读一下相关代码。", ["phase": "commentary"]),
                    message("plan-item-1", "assistant", plan),
                ]
            }
            return [
                message("m1", "user", "请展示原生 Markdown 阅读。"),
                message("m1b", "assistant", "先读取示例文件，再整理成阅读示例。", ["phase": "commentary"]),
                message("m1c", "tool", "修改 测试.txt", ["tool": "edit", "title": "修改 测试.txt", "tool_status": "completed",
                                                       "changes": [["path": "测试.txt", "ref": "fixture-diff"]]]),
                message("m2", "assistant", example),
                message("m3", "assistant", "请选择后续方案。", ["kind": "question"]),
            ]
        }
    }

    /// 200 messages for scrolling, anchors and large text (list search "performance").
    static let performance: [JSONValue] = (1...200).map { i in
        message("perf-\(i)", i % 4 == 0 ? "user" : "assistant",
                "## 固定消息 \(i)\n" + String(repeating: "这是用于滚动、锚点和字号检查的脱敏测试内容。", count: 16) + "\n```kotlin\nval fixture = \(i)\n```",
                ["order": .number(Double(i))])
    }

    static func runtime(_ app: String) -> JSONValue {
        let seconds = Double(now / 1000)
        switch app {
        case "deepseek":
            return ["model": "deepseek-v4", "effort": "high", "model_time": .number(seconds - 300), "used_tokens": 212_000, "context_window": 256_000,
                    "percent": 83, "context_state": "available", "usage_time": .number(seconds - 120), "source": "session"]
        case "claude":
            return ["model": "opus", "effort": "high", "model_time": .number(seconds - 900), "used_tokens": 61_000, "context_window": 200_000,
                    "percent": 31, "context_state": "available", "usage_time": .number(seconds - 600), "source": "desktop"]
        default:
            return ["model": "fixture-model", "effort": "medium", "model_time": .number(seconds - 60), "used_tokens": 118_000, "context_window": 258_000,
                    "percent": 46, "context_state": "available", "usage_time": .number(seconds - 30), "source": "session"]
        }
    }

    static func tree(device: String, apps: [String], more: String?) -> JSONValue {
        func item(_ row: JSONValue) -> JSONValue {
            ["app": row["app"], "id": row["id"], "title": row["title"], "folder": row["folder"], "updated": row["updated"], "status": row["status"]]
        }
        func project(_ key: String, _ name: String, _ items: [JSONValue], projectless: Bool = false) -> JSONValue {
            ["key": .string(key), "name": .string(name), "count": .number(Double(items.count)), "folder": .string(projectless ? "" : "D:/fixture"),
             "projectless": .bool(projectless), "updated": .number(Double(now)), "items": .array(items)]
        }
        func only(_ app: String) -> [JSONValue] {
            firstPage.filter { $0["app"].string() == app && !$0["group"].bool() }.map(item)
        }
        var codex = only("codex")
        if (more ?? "").contains("p-test") { codex.append(item(older)) }
        let groups: [JSONValue] = [
            ["app": "codex", "name": "Codex", "count": .number(Double(codex.count)),
             "projects": [project("p-test", "测试项目", codex), project("p-none", "其他对话", [], projectless: true)]],
            ["app": "claude", "name": "Claude", "count": .number(Double(only("claude").count)), "projects": [project("p-claude", "测试项目", only("claude"))]],
            ["app": "deepseek", "name": "DeepSeek", "count": .number(Double(only("deepseek").count)), "projects": [project("p-deepseek", "固定测试项目", only("deepseek"))]],
        ]
        // Only the apps this computer has, even with none of their conversations (remote.py filters the same way).
        return ["now": .number(Double(now)), "apps": .array(groups.filter { apps.contains($0["app"].string()) })]
    }

    static func parse(_ text: String) -> JSONValue {
        (try? JSONValue.parse(Data(text.utf8))) ?? [:]
    }

    static let codexState = parse(#"{"available":true,"settings":{"model":"fixture-model","effort":"medium","mode":"default","service_tier":null},"catalog":{"models":[{"id":"fixture-model","name":"测试模型","efforts":["low","medium"],"default_effort":"medium"}]},"questions":[{"id":"fixture-question","answer_revision":"v1","status":"pending","kind":"native","turn_id":"fixture-question-turn","questions":[{"id":"q1","header":"方案","question":"选择固定测试方案","options":[{"label":"方案A","description":"固定选项"},{"label":"方案B","description":"另一选项"}]}]}]}"#)

    static let claudeState = parse(#"{"available":true,"settings":{"model":"opus","effort":"high","mode":"default"},"model_label":"Opus 4.7","effort_label":"高","mode_label":"默认","mode_options":[{"name":"default","label":"默认"},{"name":"acceptEdits","label":"自动接受修改"},{"name":"plan","label":"计划"}],"action_revision":"r1","prompt":{"title":"发布说明用哪种格式？","progress":"1/2","choices":[{"label":"简洁要点","description":"每条改动一行","token":"t-choice-1"},{"label":"完整段落","description":"按版本分节，适合对外发布","token":"t-choice-2"}],"nav":[],"other":true}}"#)

    static let deepseekState = parse(#"{"available":true,"settings":{"provider":"deepseek","model":"deepseek-v4","reasoningEffort":"high"},"permission":"workspace","permission_name":"工作区内修改","interactions":[{"event":"approval/request","eventId":"e-approval-1","request":{"toolName":"shell","reason":"rm -rf build/","displayReason":"删除 build 目录（构建缓存）"}}],"questions":[]}"#)

    static func state(app: String, chat: String) -> JSONValue {
        switch app {
        case "claude":
            guard chat == "claude-next", case .object(var fields) = claudeState else { return claudeState }
            fields["prompt"] = nil
            fields["on_screen"] = true
            fields["tasks"] = [.string(taskTitle)]
            return .object(fields)
        case "deepseek":
            return deepseekState
        default:
            guard chat == "plan-demo", case .object(var fields) = codexState else { return codexState }
            fields["questions"] = []
            fields["plan"] = ["id": "plan-item-1", "turn_id": "plan-turn", "text": .string(plan), "ready": true]
            return .object(fields)
        }
    }

    static let plan = """
    ## 计划：补齐发布说明
    1. 读 `docs/release.md` 和最近 10 次提交，列出缺的条目。
    2. 按版本分节补写，每条改动一行。
    3. 加一节「升级步骤」，写明需要人工确认的地方。
    4. 跑一遍文档检查，确认链接都能打开。

    改动只在 `docs/` 下，不碰代码。
    """

    static let example = """
    # 原生阅读示例
    这是一段**固定测试数据**，用于检查阅读与返回。没有连接真实服务。

    ## 检查项目
    - 中文段落与字号
    - 局部横向滚动
      - 子列表保持层级
    1. 打开对话
    2. 返回列表

    > 引用内容不会改变复制的原文。

    ```kotlin
    val deviceId = "explicit-device-scope"
    val message = "A deliberately long line to verify horizontal scrolling without moving the whole conversation page."
    ```

    | 项目 | 结果 | 说明 |
    | --- | --- | --- |
    | 身份 | 独立 | 账号 / 电脑 / Codex / 会话 |
    | 阅读 | 只读 | 没有发送与批准入口 |

    [Android 开发文档](https://developer.android.com/)
    """
}
