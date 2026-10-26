import Foundation
import TeleplyModel

/// The local demo's service (spec 4.6 本地示例; Android FixtureApi), answering the same routes as the relay so the
/// app's own request and parsing code runs on it. Never contacts a service and never sees real credentials.
/// 示例网络 slows or breaks only computer routes (/d/…); the account service answers at once, as on Android.
public struct DemoTransport: RelayFileTransport {
    /// The whole demo service down, for the launch page's "连不上服务器" screenshots.
    public struct Unreachable: Error {}
    /// 示例网络 → 断开: the computer cannot be reached (Android: IOException).
    public struct Offline: UserFacingError {
        public var message: String { "连不上电脑（本地示例：网络已断开）" }
    }

    public let world: DemoWorld
    public var delay: Duration
    public var unreachable: Bool

    public init(world: DemoWorld = DemoWorld(), delay: Duration = .zero, unreachable: Bool = false) {
        self.world = world
        self.delay = delay
        self.unreachable = unreachable
    }

    public func send(_ request: RelayRequest) async throws -> RelayResponse {
        if delay > .zero { try await Task.sleep(for: delay) }
        if unreachable { throw Unreachable() }
        let path = request.url.path
        let query = Self.query(request.url)
        // Voice posts audio, not JSON: its body reads as nothing here.
        let body = request.body.flatMap { try? JSONValue.parse($0) } ?? [:]
        if path.hasPrefix("/account/") { return account(request.method, path, body) }
        guard path.hasPrefix("/d/"), path.count > 35 else { return Self.notFound }
        let device = String(path.dropFirst(3).prefix(32))
        let route = String(path.dropFirst(35))
        let network = world.network
        if network == .offline { throw Offline() }
        if network.delay > .zero { try await Task.sleep(for: network.delay) }
        if let file = request.upload { return uploaded(route, query, file) }
        return computer(device, route, query, request.method, body)
    }

    /// A conversation's file as the demo computer has it: the fixed picture, or a line of text.
    public func download(_ request: RelayRequest, limit: Int64) async throws -> RelayDownload {
        if delay > .zero { try await Task.sleep(for: delay) }
        let network = world.network
        if network == .offline { throw Offline() }
        if network.delay > .zero { try await Task.sleep(for: network.delay) }
        let file = Self.query(request.url)["file"] ?? ""
        let bytes = file == "fixture-png" ? Data(base64Encoded: DemoData.png) ?? Data() : Data(DemoData.textFile(file).utf8)
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("teleply-demo-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let name = DemoData.files.first { $0["id"].string() == file }?["name"].string() ?? "download.txt"
        let saved = folder.appendingPathComponent(name)
        try bytes.write(to: saved)
        return RelayDownload(status: 200, file: saved)
    }

    /// A picture or file taken by the demo computer: its record, as the computer answers (Android FixtureApi upload).
    func uploaded(_ route: String, _ query: [String: String], _ file: URL) -> RelayResponse {
        guard route == "/api/codex/upload" || route == "/api/files/upload" else { return Self.notFound }
        let size = ((try? FileManager.default.attributesOfItem(atPath: file.path))?[.size] as? NSNumber)?.int64Value ?? 0
        let name = query["name"] ?? "文件"
        let image = route == "/api/codex/upload"
        return Self.json(["id": .string(UUID().uuidString.lowercased()), "kind": "file", "app": .string(image ? query["app"] ?? "codex" : "pc"),
                          "name": .string(name), "path": .string("D:/fixture/" + name), "original_size": .number(Double(size)), "size": .number(Double(size))])
    }

    static let notFound = RelayResponse.json(#"{"error":"本地示例没有这个地址"}"#, status: 404)

    static func query(_ url: URL) -> [String: String] {
        var values: [String: String] = [:]
        for item in URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? [] { values[item.name] = item.value ?? "" }
        return values
    }

    static func json(_ value: JSONValue, status: Int = 200) -> RelayResponse {
        RelayResponse(status: status, headers: ["content-type": "application/json"], body: (try? value.encoded()) ?? Data("{}".utf8))
    }

    // MARK: The account service

    func account(_ method: HTTPMethod, _ path: String, _ body: JSONValue) -> RelayResponse {
        switch (method, path) {
        case (.get, "/account/config"):
            return Self.json(["version": "fixture", "email_enabled": false])
        case (.post, "/account/login"):
            world.state.withLock { $0.signedIn = true }
            return RelayResponse(status: 200, headers: ["content-type": "application/json",
                                                        "set-cookie": "__Host-ar_account=demo; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=604800"],
                                 body: Data(#"{"ok":true}"#.utf8))
        case (.post, "/account/logout"):
            world.state.withLock { $0.signedIn = false }
            return Self.json(["ok": true])
        case (.get, "/account/state"):
            let (signedIn, devices) = world.state.withLock { ($0.signedIn, $0.devices) }
            guard signedIn else { return Self.json([:], status: 401) }
            return Self.json(["devices": .array(devices.map { ["id": .string($0.id), "label": .string($0.label), "connectable": .bool($0.connectable)] }),
                              "email": "fixture@example.invalid"])
        case (.post, "/account/select"):
            let id = body["id"].string()
            if id == DemoData.offline { return Self.json(["error": "电脑已离线，请等待上线后再连接", "code": "device_offline"], status: 409) }
            guard world.state.withLock({ $0.devices.contains { $0.id == id } }) else { return Self.json([:], status: 404) }
            return Self.json(["ok": true, "url": .string("/d/\(id)/")])
        case (.post, "/account/rename"):
            world.state.withLock { state in
                if let index = state.devices.firstIndex(where: { $0.id == body["id"].string() }) { state.devices[index].label = body["label"].string() }
            }
            return Self.json(["ok": true])
        case (.post, "/account/revoke"):
            let removed = world.state.withLock { state -> Bool in
                let before = state.devices.count
                state.devices.removeAll { $0.id == body["id"].string() }
                return state.devices.count < before
            }
            return removed ? Self.json(["ok": true]) : Self.json([:], status: 404)
        default:
            return Self.notFound
        }
    }

    // MARK: A demo computer

    func computer(_ device: String, _ route: String, _ query: [String: String], _ method: HTTPMethod = .get, _ body: JSONValue = [:]) -> RelayResponse {
        if method == .post, let answer = action(route, body) { return answer }
        let app = query["app"] ?? "codex"
        let chat = query["id"] ?? ""
        switch route {
        case "/api/chats":
            return chats(device: device, app: app, query: query)
        case "/api/chat":
            return history(app: app, chat: chat, before: query["before"])
        case "/api/chat/message":
            return Self.json(["id": .string(query["message"] ?? ""), "role": "assistant", "text": .string(DemoData.example)])
        case "/api/chat/search":
            return Self.json(["items": [["id": "m2", "role": "assistant", "snippet": "…原生阅读示例…"]]])
        case "/api/codex/state", "/api/claude/state", "/api/deepseek/state":
            let source = String(route.dropFirst(5).prefix { $0 != "/" })
            world.state.withLock { $0.stateReads.append((source, chat, query["fresh"] == "1")) }
            return Self.json(world.control(app: source, chat: chat))
        case "/api/codex/receipt":
            return Self.json(world.receipt(query["request_id"] ?? "") ?? ["state": "unknown"])
        case "/api/deepseek/receipt":
            guard case .object(var fields)? = world.receipt(query["request_id"] ?? "") else { return Self.json(["state": "unknown"]) }
            fields["id"] = .string(chat)
            return Self.json(.object(fields))
        case "/api/deepseek/models":
            return Self.json(DemoData.deepseekModels)
        case "/api/deepseek/permissions":
            return Self.json(DemoData.deepseekPermissions)
        case "/api/chat/projects":
            return Self.json(DemoData.tree(device: device, apps: world.apps(of: device), more: query["more"], rows: world.firstPage()))
        case "/api/chats/children":
            let offset = Int(query["offset"] ?? "") ?? 0
            let kids = chat == "deepseek-demo" ? DemoData.deepseekChildren : []
            return Self.json(["items": .array(Array(kids.dropFirst(offset).prefix(50))), "total": .number(Double(kids.count)), "offset": .number(Double(offset))])
        case "/api/status":
            return Self.json(["ok": true, "ui_version": "fixture"])
        case "/api/chat/folders":
            return Self.json(world.folders(app: app))
        case "/api/chat/new/options":
            return Self.json(DemoData.parse(#"{"models":[{"id":"fixture-model","label":"测试模型","efforts":[{"id":"medium","label":"中"}]}]}"#))
        case "/api/chat/new/state":
            return Self.json(world.newState(query["request_id"] ?? ""))
        case "/api/composer/references", "/api/chat/new/references":
            let kind = query["kind"] ?? "chat"
            return Self.json(["items": [["kind": .string(kind), "id": "fixture-reference", "app": .string(app), "name": "固定引用", "title": "固定引用"]]])
        case "/api/chat/archived":
            return Self.json(world.archivedList())
        case "/api/notify":
            return Self.json(world.notifyState())
        case "/api/voice/status":
            return Self.json(["local": ["ready": true], "cloud": ["ready": true]])
        case "/api/voice/terms":
            return Self.json(world.voiceTerms(nil))
        case "/api/chat/files":
            return Self.json(["items": .array(DemoData.files)])
        case "/api/file/meta":
            let file = DemoData.files.first { $0["id"].string() == query["file"] }
            return Self.json(["kind": file?["kind"] ?? "text", "name": file?["name"] ?? "安全预览.html", "state": "current", "size": file?["size"] ?? 60])
        case "/api/file/text":
            return Self.json(["text": .string(DemoData.textFile(query["file"] ?? ""))])
        case "/api/chat/diff":
            return Self.json(DemoData.parse(#"{"ref":"fixture-diff","path":"测试.txt","hunks":["@@ -1 +1 @@\n-旧内容\n+新内容"],"next":null}"#))
        case "/api/files/places":
            return Self.json(DemoData.parse(#"{"items":[{"name":"固定目录","path":"D:/fixture","kind":"conversation"}]}"#))
        case "/api/files/list":
            return Self.json(DemoData.parse(#"{"path":"D:/fixture","parent":"","folder":{"kind":"folder","app":"pc","id":"fixture-folder-ref","name":"fixture","path":"D:/fixture"},"items":[{"kind":"file","app":"pc","id":"fixture-file-ref","name":"测试.txt","path":"D:/fixture/测试.txt"}]}"#))
        default:
            return Self.notFound
        }
    }

    /// The POST routes of a demo computer: sending, receipts' counterpart, Claude's desktop and the settings.
    func action(_ route: String, _ body: JSONValue) -> RelayResponse? {
        let reply: (status: Int, reply: JSONValue)
        switch route {
        case "/api/codex/send", "/api/codex/stop", "/api/codex/queue-action", "/api/codex/answer":
            reply = world.command(app: "codex", route: String(route.dropFirst("/api/codex/".count)), body: body)
        case "/api/chat/send":
            reply = world.command(app: body["app"].string(), route: "send", body: body)
        case "/api/deepseek/send":
            var fields = body.object
            if body["intent"].string() == "steer" { fields["intent"] = "auto" }
            reply = world.command(app: "deepseek", route: "send", body: .object(fields))
        case "/api/deepseek/stop":
            var fields = body.object
            fields["operation_id"] = .string(body["operation_id"].string())
            reply = world.command(app: "deepseek", route: "stop", body: .object(fields))
        case "/api/deepseek/queue":
            let fields: JSONValue = ["request_id": .string(body["request_id"].string()), "message_id": .string(body["item_id"].string()),
                                     "action": .string(body["action"].string() == "steer" ? "promote" : "cancel")]
            reply = world.command(app: "deepseek", route: "queue-action", body: fields)
        case "/api/chat/check":
            reply = (200, world.claudeCheck(offset: body["offset"].int64()))
        case "/api/claude/choose":
            reply = (200, world.claudeChoose(token: body["token"].string()))
        case "/api/claude/catalog":
            reply = (200, world.claudeCatalog(chat: body["id"].string(), fresh: body["fresh"].bool()))
        case "/api/claude/setting":
            reply = (200, world.claudeSetting(chat: body["id"].string(), kind: body["kind"].string(), name: body["name"].string()))
        case "/api/claude/close-menu":
            reply = (200, ["ok": true])
        case "/api/deepseek/model":
            world.deepseekModel(body["settings"])
            reply = (200, ["ok": true, "text": "本地示例：设置已记录"])
        case "/api/deepseek/permission":
            world.deepseekPermission(body["preset"].string())
            reply = (200, ["ok": true, "text": "本地示例：设置已记录"])
        case "/api/chat/open":
            reply = (200, ["ok": true, "text": "本地示例：没有真的打开电脑上的窗口"])
        case "/api/claude/next":
            reply = world.claudeNext(label: body["label"].string())
        case "/api/claude/task":
            reply = world.claudeTask(title: body["title"].string(), button: body["button"].string())
        case "/api/deepseek/approval":
            reply = (200, world.deepseekApproval(event: body["event_id"].string(), choice: body["choice"].string()))
        case "/api/deepseek/answer":
            reply = (200, ["ok": true])
        case "/api/chat/new/draft":
            reply = (200, world.newDraft())
        case "/api/chat/new":
            reply = (200, world.createNew(body))
        case "/api/chat/new/retry":
            reply = (200, world.retryNew(body["request_id"].string()))
        case "/api/notify":
            reply = (200, world.setBark(body["address"].string()))
        case "/api/notify/test":
            reply = (200, world.notifyTest())
        case "/api/voice/terms":
            reply = (200, world.voiceTerms(body))
        case "/api/voice/tidy":
            reply = (200, ["text": .string(DemoData.tidied)])
        case "/api/voice", "/api/voice/stream/start", "/api/voice/stream/chunk", "/api/voice/stream/end", "/api/voice/stream/cancel", "/api/voice/stream/cloud":
            reply = (200, world.voice(String(route.dropFirst("/api/".count))))
        case "/api/chat/archive":
            reply = world.archive(app: body["app"].string(), id: body["id"].string())
        case "/api/chat/unarchive":
            reply = (200, world.unarchive(app: body["app"].string(), id: body["id"].string()))
        case "/api/chat/delete":
            reply = world.delete(body)
        default:
            return nil
        }
        return Self.json(reply.reply, status: reply.status)
    }

    func chats(device: String, app: String, query: [String: String]) -> RelayResponse {
        let words = query["query"] ?? ""
        switch words {
        case "performance":
            return Self.json(["items": [DemoData.row("performance", "长会话性能示例", "固定数据", "200条消息", "idle", "codex", 0)], "has_more": false])
        case "error":
            return Self.json(["error": "本地示例：服务暂时不可用"], status: 503)
        case "expired":
            return Self.json([:], status: 401)
        default:
            break
        }
        let cursor = query["cursor"]
        let has = world.apps(of: device)
        let status = query["status"] ?? "all"
        let rows = (cursor == nil ? world.firstPage() : [DemoData.older]).filter { row in
            has.contains(row["app"].string()) && (app == "all" || row["app"].string() == app)
                && (words.isEmpty || row["title"].string().contains(words) || row["folder"].string().contains(words))
                && Self.statusMatches(row["status"].string(), status)
        }
        let more = cursor == nil && words.isEmpty
        return Self.json(["items": .array(rows), "next_cursor": more ? "page2" : .null, "has_more": .bool(more)])
    }

    static func statusMatches(_ value: String, _ filter: String) -> Bool {
        switch filter {
        case "running": return value == "running"
        case "waiting": return value == "waiting"
        case "idle", "done": return ["idle", "stopped", "failed"].contains(value)
        default: return true
        }
    }

    func history(app: String, chat: String, before: String?) -> RelayResponse {
        let title = world.firstPage().first { $0["id"].string() == chat }?["title"].string() ?? "固定对话"
        var page: [String: JSONValue] = ["app": .string(app), "id": .string(chat), "title": .string(title),
                                         "folder": .string(app == "deepseek" ? "固定测试项目" : "测试项目"), "runtime": DemoData.runtime(app)]
        if chat == "performance" {
            page["messages"] = .array(DemoData.performance)
        } else if let text = world.createdText(chat) {
            page["messages"] = [DemoData.message(chat + "-1", "user", text.isEmpty ? "请查看这些图片或引用。" : text),
                                DemoData.message(chat + "-2", "assistant", "本地示例：收到，这是固定的回复。")]
        } else if before != nil {
            page["messages"] = [DemoData.message("m0", "user", "更早的测试消息。")]
        } else {
            page["messages"] = .array(DemoData.messages(app: app, chat: chat, nextPressed: world.nextPressed))
            page["next_cursor"] = "m1"
            page["has_more"] = .bool(app == "codex")
        }
        return Self.json(.object(page))
    }
}
