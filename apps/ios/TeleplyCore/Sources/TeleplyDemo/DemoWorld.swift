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
        // What sending changes (Android FixtureWorld): a turn per source, its queue, receipts by request id.
        var running: [String: Bool] = [:]
        var turns: [String: String] = [:]
        var turnCount = 0
        var queues: [String: [Queued]] = [:]
        var receipts: [String: JSONValue] = [:]
        // Claude has no receipts: Enter in its box, then its record is looked at (chat/check).
        var claudeOffset: Int64 = 0
        var claudeChecks: [Int64: Int] = [:]
        var claudeModel = "Opus 4.7"
        var claudeEffort = "高"
        var claudeMode = "default"
        /// Claude's model lists the computer keeps, by conversation, oldest first.
        var claudeCatalogs: [(chat: String, catalog: JSONValue)] = []
        var desktopMenuReads = 0
        var deepseekModel = "deepseek-v4"
        var deepseekEffort = "high"
        var deepseekPermission = "workspace"
        // What answering changes (Android FixtureWorld): the cards each source shows until they are dealt with.
        var codexAnswered = false
        var claudeStep = 0
        var deepseekDecided = false
        var nextPressed = ""
        var tasksDone: Set<String> = []
        var planDone = false
        // New conversations: requests by id, and the conversations they made (newest last).
        var newRequests: [String: JSONValue] = [:]
        var drafts = 0
        var created: [(row: JSONValue, text: String)] = []
        // Archived and deleted conversations, as "app:id".
        var archived: [String] = []
        var deleted: Set<String> = []
        // 遥应通知: the phones' tokens the demo service keeps, and whether it could send at all.
        var pushTokens: Set<String> = []
        var pushAvailable = true
        // Notifications (Bark) and voice.
        var bark = ""
        var recent: [JSONValue] = []
        var terms = "遥应\nTeleply\nCodex"
        var voicePieces = 0
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

    /// Times the demo computer opened Claude's menus on its desktop (only 刷新 or a first read should).
    public var desktopMenuReads: Int {
        state.withLock { $0.desktopMenuReads }
    }

    // MARK: What the demo computer does when asked (Android FixtureWorld)

    /// A source's state as /api/{app}/state reports it, with the turn, queue and settings that sending changed.
    func control(app: String, chat: String) -> JSONValue {
        state.withLock { state in Self.control(state, app: app, chat: chat) }
    }

    private static func control(_ state: State, app: String, chat: String) -> JSONValue {
        let queued = state.queues[app] ?? []
        let run = state.running[app] == true
        let turn = state.turns[app] ?? ""
        var fields = DemoData.state(app: app, chat: chat).object
        // The cards as far as they have been answered; a conversation the demo just made has nothing waiting.
        let made = state.created.contains { $0.row["id"].string() == chat }
        switch app {
        case _ where made:
            fields["prompt"] = nil
            fields["interactions"] = []
            fields["questions"] = []
        case "claude" where chat == "claude-next":
            fields["tasks"] = .array([DemoData.taskTitle].filter { !state.tasksDone.contains($0) }.map(JSONValue.string))
        case "claude":
            if state.claudeStep == 1 { fields["prompt"] = DemoData.claudeSecond }
            if state.claudeStep >= 2 { fields["prompt"] = nil }
        case "deepseek":
            if state.deepseekDecided { fields["interactions"] = [] }
        default:
            if chat == "plan-demo" {
                fields["plan"] = ["id": "plan-item-1", "turn_id": "plan-turn", "text": .string(DemoData.plan), "ready": .bool(!state.planDone && !run)]
            } else if state.codexAnswered, case .object(var card)? = fields["questions"]?.array.first {
                card["status"] = "answered"
                card["editable"] = true
                fields["questions"] = [.object(card)]
            }
        }
        fields["running"] = .bool(run)
        fields["active_turn_id"] = .string(run ? turn : "")
        fields["turn_id"] = .string(turn)
        fields["queue_available"] = true
        fields["recent_turns"] = turn.isEmpty ? [] : [["id": .string(turn), "status": .string(run ? "inProgress" : "interrupted")]]
        switch app {
        case "claude":
            var settings = fields["settings"]?.object ?? [:]
            settings["model"] = .string(claudeID(state.claudeModel))
            settings["mode"] = .string(state.claudeMode)
            fields["settings"] = .object(settings)
            fields["model_label"] = .string(state.claudeModel)
            fields["effort_label"] = .string(state.claudeEffort)
            fields["mode_label"] = .string(["default": "默认", "acceptEdits": "自动接受修改", "plan": "计划"][state.claudeMode] ?? state.claudeMode)
            fields["stop_token"] = .string(run ? "t-stop" : "")
            fields["queued"] = .array(queued.map { ["id": .string($0.id), "text": .string($0.text), "token": .string("t-steer-" + $0.id)] })
        case "deepseek":
            var settings = fields["settings"]?.object ?? [:]
            settings["model"] = .string(state.deepseekModel)
            settings["reasoningEffort"] = .string(state.deepseekEffort)
            fields["settings"] = .object(settings)
            fields["permission"] = .string(state.deepseekPermission)
            fields["permission_name"] = .string(["read": "仅可查看", "workspace": "工作区内修改", "full": "完全权限"][state.deepseekPermission] ?? state.deepseekPermission)
            fields["queued"] = .array(queued.map { ["id": .string($0.id), "text": .string($0.text), "status": .string($0.status)] })
        default:
            fields["queued"] = .array(queued.map { ["id": .string($0.id), "text": .string($0.text), "status": .string($0.status)] })
        }
        return .object(fields)
    }

    /// A send, stop or queue action, with the status the computer answers. Claude takes a message by Enter in its
    /// box; "测试电脑草稿" (or "draft") plays a box on the computer that already holds a letter typed there, until it
    /// is replaced.
    func command(app: String, route: String, body: JSONValue) -> (status: Int, reply: JSONValue) {
        state.withLock { state in
            if app == "claude" && route == "send" {
                if ["测试电脑草稿", "draft"].contains(body["text"].string()) && body["replace_draft"].string().isEmpty {
                    return (400, ["error": "电脑上 Claude 的输入框里已经有「e」，没有发出", "code": "desktop_draft", "not_submitted": true, "draft": "e"])
                }
                state.claudeOffset += 100
                state.claudeChecks[state.claudeOffset] = 0
                return (200, ["ok": true, "pressed": true, "offset": .number(Double(state.claudeOffset)),
                              "running": .bool(state.running["claude"] == true), "text": "已提交，等待 Claude 读取"])
            }
            let rid = body[route == "stop" ? "operation_id" : "request_id"].string()
            var queue = state.queues[app] ?? []
            let delivery: String
            if !body["plan_id"].string().isEmpty { state.planDone = true }
            switch route {
            case "answer":
                state.codexAnswered = true
                delivery = "accepted"
            case "stop":
                state.running[app] = false
                delivery = "accepted"
            case "queue-action":
                queue.removeAll { $0.id == body["message_id"].string() }
                delivery = body["action"].string() == "promote" ? "accepted" : "cancelled"
            default:
                if body["intent"].string() == "queue" {
                    queue.append(Queued(id: rid, text: body["text"].string(), status: "queued"))
                    delivery = "queued"
                } else {
                    if state.running[app] != true {
                        state.turnCount += 1
                        state.turns[app] = "fixture-turn-\(state.turnCount)"
                    }
                    state.running[app] = true
                    delivery = "accepted"
                }
            }
            state.queues[app] = queue
            let result: JSONValue = ["request_id": .string(rid), "accepted": true, "delivery_state": .string(delivery)]
            state.receipts[rid] = ["request_id": .string(rid), "state": .string(delivery), "result": result]
            return (200, result)
        }
    }

    func receipt(_ request: String) -> JSONValue? {
        state.withLock { $0.receipts[request] }
    }

    /// Claude read the message on the second look; while it runs, the first two looks find it queued.
    func claudeCheck(offset: Int64) -> JSONValue {
        state.withLock { state in
            let looks = (state.claudeChecks[offset] ?? 0) + 1
            state.claudeChecks[offset] = looks
            let queued = state.running["claude"] == true && looks < 3
            return ["delivered": .bool(!queued && looks >= 2), "queued": .bool(queued)]
        }
    }

    /// A desktop option tapped on the computer: 停止 (t-stop), 立即补充 (t-steer-…), or a choice or 下一题 / 提交 of
    /// its question (t-choice-…, t-nav-…), which moves the question on.
    func claudeChoose(token: String) -> JSONValue {
        state.withLock { state in
            if token == "t-stop" {
                state.running["claude"] = false
            } else if token.hasPrefix("t-steer-") {
                let id = String(token.dropFirst("t-steer-".count))
                state.queues["claude"]?.removeAll { $0.id == id }
            } else if token.hasPrefix("t-choice-") || token.hasPrefix("t-nav-") {
                state.claudeStep = min(state.claudeStep + 1, 2)
            }
            return ["ok": true, "text": "本地示例：已在电脑上点选"]
        }
    }

    /// A button of the next-step box: pressed once; after that the box is gone (409, as the computer says).
    func claudeNext(label: String) -> (status: Int, reply: JSONValue) {
        state.withLock { state in
            guard state.nextPressed.isEmpty else { return (409, ["error": "这个框已经不在了：回复过了，或者已经是新的一轮。刷新看看"]) }
            state.nextPressed = label
            return (200, ["ok": true, "text": .string("本地示例：已在电脑上点了「\(label)」")])
        }
    }

    /// 开始 / 在这里做 / 不要了 on a task card; a card already dealt with is refused.
    func claudeTask(title: String, button: String) -> (status: Int, reply: JSONValue) {
        state.withLock { state in
            guard !state.tasksDone.contains(title) else { return (409, ["error": "电脑上这张任务卡片已经处理过了，或者不在了"]) }
            state.tasksDone.insert(title)
            let done = ["start": "开始了", "here": "点了「Do it here」", "dismiss": "关掉了"][button] ?? "处理了"
            return (200, ["ok": true, "text": .string("本地示例：已在电脑上" + done + (button == "start" ? "，新对话会出现在列表里" : ""))])
        }
    }

    /// 拒绝 / 仅允许本次: the approval is decided; allowed, DeepSeek carries on.
    func deepseekApproval(event: String, choice: String) -> JSONValue {
        state.withLock { state in
            if event == "e-approval-1" {
                state.deepseekDecided = true
                if choice == "allowed-once" { state.running["deepseek"] = true }
            }
            return ["ok": true]
        }
    }

    /// The first list page as things stand: the conversations made here first, then the fixed rows, those whose
    /// state answering changed saying so (Android FixtureWorld.firstPage).
    func firstPage() -> [JSONValue] {
        state.withLock { state in
            (Array(state.created.map(\.row).reversed()) + DemoData.firstPage.map { row in
                var fields = row.object
                switch row["id"].string() {
                case "demo":
                    if state.running["codex"] == true { fields["status"] = "running" }
                case "claude-demo":
                    if state.claudeStep >= 2 {
                        fields["status"] = "idle"
                        fields["preview"] = "已选好格式"
                    }
                case "deepseek-demo":
                    if state.deepseekDecided {
                        fields["status"] = "running"
                        fields["preview"] = "已处理批准"
                    }
                case "plan-demo":
                    if state.planDone {
                        fields["preview"] = "已按计划开始"
                        if state.running["codex"] == true { fields["status"] = "running" }
                    }
                default:
                    break
                }
                return .object(fields)
            }).filter { row in
                let key = row["app"].string() + ":" + row["id"].string()
                return !state.archived.contains(key) && !state.deleted.contains(key)
            }
        }
    }

    // MARK: Notifications and voice (Android FixtureWorld, Bark instead of ntfy)

    func notifyState() -> JSONValue {
        state.withLock { state in
            ["configured": .bool(!state.bark.isEmpty), "server": .string(state.bark.isEmpty ? "" : "api.day.app"), "recent": .array(state.recent)]
        }
    }

    /// A Bark address saved (and one pushed to try it), or cleared with an empty one.
    func setBark(_ address: String) -> JSONValue {
        state.withLock { state in
            state.bark = address.trimmingCharacters(in: .whitespacesAndNewlines)
            if state.bark.isEmpty { return ["ok": true, "text": "本地示例：已关掉"] }
            Self.remember(&state, "本地示例：试推了一条")
            return ["ok": true, "text": "本地示例：已保存，刚推了一条"]
        }
    }

    func notifyTest() -> JSONValue {
        state.withLock { state in
            Self.remember(&state, "本地示例：试推了一条")
            return ["ok": true, "text": "本地示例：刚推了一条，看看手机"]
        }
    }

    private static func remember(_ state: inout State, _ text: String) {
        state.recent.insert(["time": "12:00", "text": .string(text)], at: 0)
        state.recent = Array(state.recent.prefix(5))
    }

    /// The computer's recogniser, played: the words come a few at a time, then the whole sentence.
    func voice(_ route: String) -> JSONValue {
        state.withLock { state in
            switch route {
            case "voice/stream/start":
                state.voicePieces = 0
                return ["sid": "fixture-voice", "rate": .number(Double(voiceRate))]
            case "voice/stream/chunk":
                state.voicePieces += 1
                let words = Array(DemoData.heard)
                let count = min(state.voicePieces * 2, words.count)
                return ["final": .string(String(words[..<count])), "partial": .string(String(words[count..<min(count + 2, words.count)]))]
            case "voice/stream/end":
                return ["text": .string(DemoData.heard)]
            case "voice", "voice/stream/cloud":
                return ["text": .string(DemoData.heard), "raw": .string(DemoData.heard), "tidied": false]
            default:
                return ["ok": true]
            }
        }
    }

    func voiceTerms(_ body: JSONValue?) -> JSONValue {
        state.withLock { state in
            if let body { state.terms = body["text"].string() }
            let count = state.terms.split(separator: "\n").filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }.count
            return body == nil ? ["text": .string(state.terms), "count": .number(Double(count))] : ["ok": true, "count": .number(Double(count))]
        }
    }

    // MARK: Archiving (Android FixtureWorld)

    func archive(app: String, id: String) -> (status: Int, reply: JSONValue) {
        guard let row = firstPage().first(where: { $0["app"].string() == app && $0["id"].string() == id }) else { return (404, [:]) }
        if row["status"].string() == "running" { return (400, ["error": "这个对话正在运行，先停止这一轮再归档"]) }
        state.withLock { $0.archived.append(app + ":" + id) }
        return (200, ["ok": true, "app": .string(app), "id": .string(id), "archived": true])
    }

    func unarchive(app: String, id: String) -> JSONValue {
        state.withLock { $0.archived.removeAll { $0 == app + ":" + id } }
        return ["ok": true, "app": .string(app), "id": .string(id), "archived": false]
    }

    func archivedList() -> JSONValue {
        let (archived, deleted) = state.withLock { ($0.archived, $0.deleted) }
        let order = ["codex", "deepseek", "claude"]
        let all = Array(state.withLock { $0.created.map(\.row) }) + DemoData.firstPage
        let rows = all.filter { archived.contains($0["app"].string() + ":" + $0["id"].string()) && !deleted.contains($0["app"].string() + ":" + $0["id"].string()) }
            .sorted { (order.firstIndex(of: $0["app"].string()) ?? 3) < (order.firstIndex(of: $1["app"].string()) ?? 3) }
        return ["items": .array(rows.map { row in
            ["app": row["app"], "id": row["id"], "title": row["title"], "folder": row["folder"], "archived_at": .number(Double(DemoData.now / 1000 - 120)),
             "can_delete": .bool(row["app"].string() == "codex")]
        }), "problems": [], "apps": ["codex", "deepseek", "claude"], "deletable": ["codex"]]
    }

    func delete(_ body: JSONValue) -> (status: Int, reply: JSONValue) {
        guard body["confirmed"].bool() else { return (400, ["error": "删除要先在手机上确认"]) }
        let results: [JSONValue] = state.withLock { state in
            body["items"].array.map { item in
                let key = item["app"].string() + ":" + item["id"].string()
                if item["app"].string() == "codex" && state.archived.contains(key) {
                    state.deleted.insert(key)
                    state.archived.removeAll { $0 == key }
                    return ["app": item["app"], "id": item["id"], "ok": true]
                }
                return ["app": item["app"], "id": item["id"], "ok": false, "error": "这种对话还不能删除"]
            }
        }
        let done = results.filter { $0["ok"].bool() }.count
        return (200, ["ok": .bool(done == results.count), "results": .array(results), "deleted": .number(Double(done))])
    }

    /// The next-step button pressed so far ("" before), which the conversation then shows as sent.
    var nextPressed: String {
        state.withLock { $0.nextPressed }
    }

    // MARK: New conversations (Android FixtureWorld)

    func folders(app: String) -> JSONValue {
        app == "deepseek"
            ? DemoData.parse(#"{"items":[{"path":"D:/fixture","name":"固定测试项目","sources":["DeepSeek 工作区"]}]}"#)
            : DemoData.parse(#"{"items":[{"path":"D:/fixture","name":"固定测试项目","sources":["Codex 项目"]},{"path":"D:/fixture-docs","name":"文档项目","sources":["Claude 项目"]},{"path":"D:/fixture-site","name":"网站项目","sources":["Codex 对话"]}]}"#)
    }

    func newDraft() -> JSONValue {
        state.withLock { state in
            state.drafts += 1
            let hex = String(state.drafts, radix: 16)
            return ["request_id": .string(String(repeating: "0", count: max(0, 32 - hex.count)) + hex)]
        }
    }

    /// A first message: the demo computer makes it in three looks (opening the app, sending, done). "测试失败" (or
    /// "fail") plays one that did not go out, until 继续发送.
    func createNew(_ body: JSONValue) -> JSONValue {
        state.withLock { state in
            let rid = body["request_id"].string()
            let fail = ["测试失败", "fail"].contains(body["text"].string())
            if state.newRequests[rid] == nil { state.newRequests[rid] = ["body": body, "checks": 0, "fail": .bool(fail)] }
            return fail ? Self.failedNew(rid) : Self.creating(rid)
        }
    }

    private static func creating(_ rid: String) -> JSONValue {
        ["request_id": .string(rid), "state": "creating", "timing": ["active": ["name": "desktop_open"]]]
    }

    private static func failedNew(_ rid: String) -> JSONValue {
        ["request_id": .string(rid), "state": "failed", "not_submitted": true, "can_retry": true, "message": "本地示例：电脑上的应用没有响应，首条消息没有发出"]
    }

    func newState(_ rid: String) -> JSONValue {
        state.withLock { state in
            guard case .object(var row)? = state.newRequests[rid] else { return ["request_id": .string(rid), "state": "draft"] }
            if row["fail"]?.bool() == true { return Self.failedNew(rid) }
            let looks = Int(row["checks"]?.int64() ?? 0) + 1
            row["checks"] = .number(Double(looks))
            state.newRequests[rid] = .object(row)
            if looks == 1 { return Self.creating(rid) }
            if looks == 2 { return ["request_id": .string(rid), "state": "dispatching", "timing": ["active": ["name": "send_text"]]] }
            let body = row["body"] ?? [:]
            var id = row["id"]?.string() ?? ""
            if id.isEmpty {
                id = "fixture-new-\(state.created.count + 1)"
                let words = oneLine(body["text"].string(), limit: 30)
                let folder = body["projectless"].bool() ? "" : Self.lastPart(body["folder"].string())
                let app = body["app"].string().isEmpty ? "codex" : body["app"].string()
                let made = DemoData.row(id, words.isEmpty ? "新对话" : words, folder, String(body["text"].string().prefix(40)), "idle", app, DemoData.now)
                state.created.append((made, body["text"].string()))
                row["id"] = .string(id)
                state.newRequests[rid] = .object(row)
            }
            let chat = state.created.first { $0.row["id"].string() == id }!.row
            return ["request_id": .string(rid), "state": "accepted", "app": chat["app"], "id": .string(id), "title": chat["title"], "folder": chat["folder"]]
        }
    }

    func retryNew(_ rid: String) -> JSONValue {
        state.withLock { state in
            if case .object(var row)? = state.newRequests[rid] {
                row["fail"] = false
                state.newRequests[rid] = .object(row)
            }
            return Self.creating(rid)
        }
    }

    /// What a conversation made here was started with; nil for the fixed ones.
    func createdText(_ chat: String) -> String? {
        state.withLock { state in state.created.first { $0.row["id"].string() == chat }?.text }
    }

    private static func lastPart(_ path: String) -> String {
        path.split(separator: "/").last.map(String.init) ?? path
    }

    static func claudeID(_ name: String) -> String {
        name.hasPrefix("Sonnet") ? "sonnet" : "opus"
    }

    /// Claude's model list as the computer keeps it: kept unless [fresh] or the model changed; a conversation never
    /// read borrows the latest one on the same model, its picks unknown.
    func claudeCatalog(chat: String, fresh: Bool) -> JSONValue {
        state.withLock { state in
            let model = Self.claudeID(state.claudeModel)
            if !fresh, let kept = state.claudeCatalogs.last(where: { $0.chat == chat })?.catalog, kept["model_id"].string() == model {
                var copy = kept.object
                copy["cached"] = true
                return .object(copy)
            }
            if !fresh, let other = state.claudeCatalogs.last(where: { $0.catalog["model_id"].string() == model })?.catalog {
                var copy = other.object
                copy["cached"] = true
                copy["borrowed"] = true
                copy["effort"] = .array(other["effort"].array.map { step in
                    var fields = step.object
                    fields["selected"] = false
                    return .object(fields)
                })
                return .object(copy)
            }
            state.desktopMenuReads += 1
            let now = Self.catalogNow(state)
            state.claudeCatalogs.append((chat, now))
            return now
        }
    }

    private static func catalogNow(_ state: State) -> JSONValue {
        ["model_id": .string(claudeID(state.claudeModel)), "updated_at": .number(Double(DemoData.now)), "cached": false,
         "model": .array(["Opus 4.7", "Sonnet 4.6"].map { ["name": .string($0), "selected": .bool($0 == state.claudeModel)] }),
         "effort": .array(["高", "中", "低"].map { ["name": .string($0), "selected": .bool($0 == state.claudeEffort)] })]
    }

    /// A Claude setting applied "on the computer": the state and the list come back, nothing is read again.
    func claudeSetting(chat: String, kind: String, name: String) -> JSONValue {
        state.withLock { state in
            switch kind {
            case "model":
                state.claudeModel = name
                state.claudeEffort = "高"
            case "effort":
                state.claudeEffort = name
            case "mode":
                state.claudeMode = name
            default:
                break
            }
            var result: [String: JSONValue] = ["ok": true, "text": "本地示例：已在电脑上换好", "state": Self.control(state, app: "claude", chat: chat)]
            if kind != "mode" {
                let now = Self.catalogNow(state)
                state.claudeCatalogs.append((chat, now))
                result["catalog"] = now
            }
            return .object(result)
        }
    }

    func deepseekModel(_ settings: JSONValue) {
        state.withLock { state in
            if settings.has("model") { state.deepseekModel = settings["model"].string() }
            if settings.has("reasoningEffort") { state.deepseekEffort = settings["reasoningEffort"].string() }
        }
    }

    func deepseekPermission(_ preset: String) {
        state.withLock { $0.deepseekPermission = preset }
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

    /// [nextPressed]: the next-step button pressed so far; the box then keeps its recap and the words show as sent.
    static func messages(app: String, chat: String, nextPressed: String = "") -> [JSONValue] {
        if app == "claude" && chat == "claude-next" {
            let plan: JSONValue = .array([("读现有测试", "completed"), ("补发布说明的测试", "completed"), ("跑一遍全部测试", "in_progress"), ("更新说明文档", "pending")]
                .map { ["text": .string($0.0), "status": .string($0.1)] })
            var next: [String: JSONValue] = ["tool_id": "wrap-1", "recap": "补了 3 个测试，全部通过；说明文档还没改。", "ask": "接下来做什么？",
                                             "actions": [["label": "接着改说明文档", "message": "接着改说明文档"], ["label": "先停在这里", "message": "先停在这里"]]]
            if nextPressed.isEmpty { next["open"] = true }
            var rows = [
                message("n1", "user", "把发布说明的测试补齐。", ["origin": "other_chat"]),
                message("n2", "assistant", "先列一下要做的几步。", ["phase": "commentary"]),
                message("n3", "plan", "计划 2/4", ["items": plan]),
                message("n4", "tool", "运行 测试", ["tool": "shell", "title": "运行 npm test", "tool_status": "completed"]),
                message("n5", "assistant", "测试补好了，全部通过。说明文档还没改。"),
                message("n6", "next", "这一轮做完了", next),
            ]
            if !nextPressed.isEmpty { rows.append(message("n7", "user", nextPressed)) }
            rows.append(message("n8", "task", taskTitle, ["tool_id": "task-1", "title": .string(taskTitle), "offer": false,
                                                          "brief": "把这次改动整理成发布清单：列出新增的测试、受影响的页面、需要人工确认的地方，并附上每一项的验证方法。改完发给我看。"]))
            return rows
        }
        switch app {
        case "claude":
            return [
                // Sent with a picture from the phone: the computer's record of that send is in the state (`images`).
                message("c1", "user", "[图片] 帮我把这次的发布说明整理一下。", ["time": "2026-10-20T08:00:00.000Z"]),
                message("c2", "assistant", "我先看一下现有的文档和最近的提交。", ["phase": "commentary"]),
                message("c3", "tool", "读取 docs/release.md", ["tool": "read", "title": "读取 docs/release.md", "tool_status": "completed"]),
                message("c4", "assistant", "有两种写法，请在下面选一种。", ["kind": "question"]),
            ]
        case "deepseek":
            return [
                message("d0", "user", "把发布说明翻译成英文，做成 Word。"),
                message("d0b", "assistant", "成果文件：\n翻译稿.docx", ["kind": "deliverables", "presented_files": [["path": "D:\\fixture\\翻译稿.docx", "description": "英文译稿"]]]),
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

    static func tree(device: String, apps: [String], more: String?, rows: [JSONValue] = firstPage) -> JSONValue {
        func item(_ row: JSONValue) -> JSONValue {
            ["app": row["app"], "id": row["id"], "title": row["title"], "folder": row["folder"], "updated": row["updated"], "status": row["status"]]
        }
        func project(_ key: String, _ name: String, _ items: [JSONValue], projectless: Bool = false) -> JSONValue {
            ["key": .string(key), "name": .string(name), "count": .number(Double(items.count)), "folder": .string(projectless ? "" : "D:/fixture"),
             "projectless": .bool(projectless), "updated": .number(Double(now)), "items": .array(items)]
        }
        func only(_ app: String) -> [JSONValue] {
            rows.filter { $0["app"].string() == app && !$0["group"].bool() }.map(item)
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

    static let claudeState = parse(#"{"available":true,"settings":{"model":"opus","effort":"high","mode":"default"},"model_label":"Opus 4.7","effort_label":"高","mode_label":"默认","mode_options":[{"name":"default","label":"默认"},{"name":"acceptEdits","label":"自动接受修改"},{"name":"plan","label":"计划"}],"action_revision":"r1","prompt":{"title":"发布说明用哪种格式？","progress":"1/2","choices":[{"label":"简洁要点","description":"每条改动一行","token":"t-choice-1","pressed":true},{"label":"完整段落","description":"按版本分节，适合对外发布","token":"t-choice-2"}],"nav":[],"other":{"name":"Other"}},"images":[{"request_id":"fixture-send-1","images":[{"id":"fixture-picture-1","name":"发布说明截图.png","url":"/api/codex/image?id=fixture-picture-1","thumbnail":"/api/codex/image?thumb=1&id=fixture-picture-1"}],"text":"帮我把这次的发布说明整理一下。","created":1792483190,"status":"accepted"}]}"#)

    /// The conversation files of the demo (Android FixtureWorld.FILES): a page, a picture beside it, a Markdown note.
    static let files: [JSONValue] = [
        ["id": "fixture-html", "name": "安全预览.html", "path": "D:\\fixture\\安全预览.html", "kind": "text", "state": "current", "size": 900],
        ["id": "fixture-png", "name": "logo.png", "path": "D:\\fixture\\images\\logo.png", "kind": "image", "state": "current", "size": 462],
        ["id": "fixture-md", "name": "说明.md", "path": "D:\\fixture\\说明.md", "kind": "text", "state": "current", "size": 200],
    ]

    /// What DeepSeek presented as a turn's result (deliverables/presented, Android 1.0.2): a small Word file that
    /// the computer lists for that message only.
    static let deliverable: JSONValue = ["id": "fixture-docx", "name": "翻译稿.docx", "path": "D:\\fixture\\翻译稿.docx", "kind": "download",
                                         "state": "current", "size": .number(Double(docx.count)), "message_id": "d0b"]

    /// 翻译稿.docx: a real Word file (1106 bytes), so Quick Look shows it.
    static let docx = Data(base64Encoded: """
        UEsDBBQAAAAIAAAAWl3JTxqw6wAAAK4BAAATAAAAW0NvbnRlbnRfVHlwZXNdLnhtbH1QvU7DMBDeeQrLK4odGBBCSTrwMwJDeYCTfUks7LPlc0
        v79jht6YAK4933q69b7YIXW8zsIvXyRrVSIJloHU29/Fi/NPdScAGy4CNhL/fIcjVcdet9QhZVTNzLuZT0oDWbGQOwigmpImPMAUo986QTmE+Y
        UN+27Z02kQpSacriIYfuCUfY+CKed/V9LJLRsxSPR+KS1UtIyTsDpeJ6S/ZXSnNKUFV54PDsEl9XgtQXExbk74CT7q0uk51F8Q65vEKoLP0Vs9
        U2mk2oSvW/zYWecRydwbN+cUs5GmSukwevzkgARz/99WHu4RtQSwMEFAAAAAgAAABaXbmBRHGwAAAAKgEAAAsAAABfcmVscy8ucmVsc43POw7C
        MAwG4J1TRN5pWgaEUJMuCKkrKgeIEjeNaB5KwqO3JwMDIAZG278/y233sDO5YUzGOwZNVQNBJ70yTjM4D8f1DkjKwikxe4cMFkzQ8VV7wlnksp
        MmExIpiEsMppzDntIkJ7QiVT6gK5PRRytyKaOmQciL0Eg3db2l8d0A/mGSXjGIvWqADEvAf2w/jkbiwcurRZd/nPhKFFlEjZnB3UdF1atdFRYo
        b+nHi/wJUEsDBBQAAAAIAAAAWl3OeekWXwEAAGwCAAARAAAAd29yZC9kb2N1bWVudC54bWydUr1KA0EQ7n2KYSsFzUaFIEfu0kgq8Tc+wOZukj
        tyt7vsbBLjK1jZp7SwELQTFAz4LGp8DOcuGBG0SfMNs7Pzfd/ObLN1UeQwQkeZ0aHYrtUFoI5Nkul+KM477a09AeSVTlRuNIZigiRa0VpzHCQm
        HhaoPTCDpmAcitR7G0hJcYqFopqxqLnWM65QnlPXl2PjEutMjEQsUORyp15vyEJlWkRM2TXJpIy2BFfBcRW6skS6hHEwUnkodhuCT+SyXpkIyK
        qYLVqHhG6EIjrFHBUhHBqPBOsdpzTlyvNTN8pmv6Co0P7W/YdwPnv+vL+e387g9RE+pnfv04f5zdPby9VqdJ00I+hlOS5GTJBp4HGBguVw9xHt
        GeIAqi7tMQHF9zwB58Pc11ZTPtLgUwSb8lKZDcpdVfInwywewIExg01gS2UtVhq6bFGNWNwbaLNhArZJqXKY/OVAfu9S/vyT6AtQSwECFAAUAA
        AACAAAAFpdyU8asOsAAACuAQAAEwAAAAAAAAAAAAAAgAEAAAAAW0NvbnRlbnRfVHlwZXNdLnhtbFBLAQIUABQAAAAIAAAAWl25gURxsAAAACoB
        AAALAAAAAAAAAAAAAACAARwBAABfcmVscy8ucmVsc1BLAQIUABQAAAAIAAAAWl3OeekWXwEAAGwCAAARAAAAAAAAAAAAAACAAfUBAAB3b3JkL2
        RvY3VtZW50LnhtbFBLBQYAAAAAAwADALkAAACDAwAAAAA=
        """, options: .ignoreUnknownCharacters) ?? Data()

    /// A file picked from the demo computer (从电脑选择文件): its ticket and its text.
    static let computerFile = "固定测试内容"

    static func textFile(_ id: String) -> String {
        switch id {
        case "fixture-md": return markdownFile
        case "fixture-html": return htmlFile
        default: return "固定测试内容"
        }
    }

    static let htmlFile = """
    <script>fetch('https://example.invalid/secret').catch(() => {})</script>
    <h1>固定 HTML 页面</h1>
    <p>这一页在手机上按网页显示：脚本照常运行，网上的资源照常加载。</p>
    <p id="script-state">脚本没有运行</p>
    <script>document.getElementById('script-state').textContent = '脚本已运行'</script>
    <p><img src="images/logo.png" alt="同目录下的图片"></p>
    <table border="1" cellpadding="6"><tr><th>项目</th><th>结果</th></tr><tr><td>脚本</td><td>运行</td></tr><tr><td>同目录的图片</td><td>从电脑上取</td></tr></table>
    <p><a href="https://developer.apple.com/">点链接用浏览器打开</a></p>
    """

    static let markdownFile = "# 说明\n\n这是一个 **Markdown** 文件，默认用阅读视图显示。\n\n- 第一条\n- 第二条\n\n> 也可以切到「查看源码」看原文。"

    static let png = "iVBORw0KGgoAAAANSUhEUgAAAGAAAAAoCAIAAACO8WhuAAABlUlEQVR42u3QhzICAAAGYM9CyB4hMyF7JDOrsreydyIzhczISNll772P4zjHcRzHOY7jOOcNPIe7/3uETys+6Tcu+Sc25ZuT+sVJ+2Snf7Ay3lmZbzFZr9Hcl2jec1T2U2TOY2TuQ0TePTP/jllwG154E1Z0HVZ8FVpyGVJ6EVx2Hlx+FsQ/ZVScMATHgZVH9KpDuvAgoHrPv2bXv3bbr27Tt37Dt2HNR7Tq3bjsLV7ykix4Ns17NM96tMy4S6dorRpam9qtfdy1Y8y1c8Sla5gqU1G7lc49Coq8n9Lb59Qnd+zvcRyQOSi67Ac77JTtdqpW2yEpebiZPCKxGRVbj4msxxusJupI6lqSptpyUmgxVWkxLTCf4ZvNlpnNlZrOF5ssFBkvFhgv5Rst5xqu5Biu8gzWuMT1TOJGuv5mmt5Wit52su5OImE3gbAXp7Mfq33A1j5kaSEIQQhCEIIQhCAEIQhBCEIQghCEIAQhCEEIQhCCEIQgBCEIQQhCEIIQhCAEIQhBCEIQghCEIAQhCEEI+m9BfzQ+a2t+SvdoAAAAAElFTkSuQmCC"

    static let heard = "好的帮我把发布说明里的升级步骤补上"
    static let tidied = "好的，帮我把发布说明里的升级步骤补上。"

    static let claudeSecond = parse(#"{"title":"要不要附上升级步骤？","progress":"2/2","choices":[{"label":"附上","description":"在末尾列出升级步骤","token":"t-choice-3"},{"label":"不附","description":"只写改动","token":"t-choice-4"}],"nav":[{"name":"Submit","label":"提交","token":"t-nav-submit"}],"other":{"name":"Other"}}"#)

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

    static let deepseekModels = parse(#"{"groups":[{"id":"deepseek","name":"DeepSeek","models":[{"id":"deepseek-v4","name":"DeepSeek V4","reasoning":{"efforts":[{"id":"high","name":"高"},{"id":"low","name":"低"}]}}]}]}"#)
    static let deepseekPermissions = parse(#"{"options":[{"value":"read","name":"仅可查看","description":"只读文件，不修改"},{"value":"workspace","name":"工作区内修改","description":"只改工作区里的文件"},{"value":"full","name":"完全权限","description":"可以修改电脑上的任何文件","confirm":true}]}"#)

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
