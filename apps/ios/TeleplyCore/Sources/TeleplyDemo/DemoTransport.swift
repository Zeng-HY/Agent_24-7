import Foundation
import TeleplyModel

/// The local demo's service (spec 4.6 本地示例; Android FixtureApi), answering the same routes as the relay so the
/// app's own request and parsing code runs on it. Never contacts a service and never sees real credentials.
/// 示例网络 slows or breaks only computer routes (/d/…); the account service answers at once, as on Android.
public struct DemoTransport: RelayTransport {
    /// The whole demo service down, for the launch page's "连不上服务器" screenshots.
    public struct Unreachable: Error {}
    /// 示例网络 → 断开: the computer cannot be reached (Android: IOException).
    public struct Offline: Error {
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
        let body = request.body.flatMap { try? JSONValue.parse($0) } ?? [:]
        if path.hasPrefix("/account/") { return account(request.method, path, body) }
        guard path.hasPrefix("/d/"), path.count > 35 else { return Self.notFound }
        let device = String(path.dropFirst(3).prefix(32))
        let route = String(path.dropFirst(35))
        let network = world.network
        if network == .offline { throw Offline() }
        if network.delay > .zero { try await Task.sleep(for: network.delay) }
        return computer(device, route, query)
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

    func computer(_ device: String, _ route: String, _ query: [String: String]) -> RelayResponse {
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
            return Self.json(DemoData.state(app: source, chat: chat))
        case "/api/chat/projects":
            return Self.json(DemoData.tree(device: device, apps: world.apps(of: device), more: query["more"]))
        case "/api/chats/children":
            let offset = Int(query["offset"] ?? "") ?? 0
            let kids = chat == "deepseek-demo" ? DemoData.deepseekChildren : []
            return Self.json(["items": .array(Array(kids.dropFirst(offset).prefix(50))), "total": .number(Double(kids.count)), "offset": .number(Double(offset))])
        case "/api/status":
            return Self.json(["ok": true, "ui_version": "fixture"])
        default:
            return Self.notFound
        }
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
        let rows = (cursor == nil ? DemoData.firstPage : [DemoData.older]).filter { row in
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
        let title = DemoData.firstPage.first { $0["id"].string() == chat }?["title"].string() ?? "固定对话"
        var page: [String: JSONValue] = ["app": .string(app), "id": .string(chat), "title": .string(title),
                                         "folder": .string(app == "deepseek" ? "固定测试项目" : "测试项目"), "runtime": DemoData.runtime(app)]
        if chat == "performance" {
            page["messages"] = .array(DemoData.performance)
        } else if before != nil {
            page["messages"] = [DemoData.message("m0", "user", "更早的测试消息。")]
        } else {
            page["messages"] = .array(DemoData.messages(app: app, chat: chat))
            page["next_cursor"] = "m1"
            page["has_more"] = .bool(app == "codex")
        }
        return Self.json(.object(page))
    }
}
