import Foundation

public enum HTTPMethod: String, Sendable {
    case get = "GET"
    case post = "POST"
}

/// One call to the relay, built here and carried out by a RelayTransport (URLSession on the phone, a fake in
/// tests and the local demo).
public struct RelayRequest: Sendable, Equatable {
    public var method: HTTPMethod
    public var url: URL
    public var headers: [String: String]
    public var body: Data?
    /// Seconds the whole call may take (Android callTimeout: 40 s, longer for the slow routes).
    public var deadline: TimeInterval
    /// A file whose bytes are the body, sent with its length and never in chunks (the computer cannot read
    /// chunked bodies); the file stays where it is.
    public var upload: URL?

    public init(method: HTTPMethod, url: URL, headers: [String: String], body: Data? = nil, deadline: TimeInterval, upload: URL? = nil) {
        self.method = method
        self.url = url
        self.headers = headers
        self.body = body
        self.deadline = deadline
        self.upload = upload
    }
}

public struct RelayResponse: Sendable, Equatable {
    public var status: Int
    /// Header names in lower case.
    public var headers: [String: String]
    public var body: Data

    public init(status: Int, headers: [String: String] = [:], body: Data = Data()) {
        self.status = status
        self.headers = headers
        self.body = body
    }

    public static func json(_ text: String, status: Int = 200) -> RelayResponse {
        RelayResponse(status: status, headers: ["content-type": "application/json"], body: Data(text.utf8))
    }
}

public protocol RelayTransport: Sendable {
    func send(_ request: RelayRequest) async throws -> RelayResponse
}

/// A response read as it arrives: the live stream (GET /api/events).
public struct RelayStream: Sendable {
    public var status: Int
    public var chunks: AsyncThrowingStream<[UInt8], any Error>

    public init(status: Int, chunks: AsyncThrowingStream<[UInt8], any Error>) {
        self.status = status
        self.chunks = chunks
    }
}

public protocol RelayStreamingTransport: RelayTransport {
    func stream(_ request: RelayRequest) async throws -> RelayStream
}

/// A response written to a file instead of memory (GET /api/file). [file] is set for a 2xx answer and then
/// belongs to the caller; any other answer keeps its (short) body to say why.
public struct RelayDownload: Sendable {
    public var status: Int
    public var file: URL?
    public var body: Data

    public init(status: Int, file: URL? = nil, body: Data = Data()) {
        self.status = status
        self.file = file
        self.body = body
    }
}

/// Downloads to a file, at most [limit] bytes; a bigger file is refused rather than cut short, and one that came
/// short of its stated length too. [progress] hears the bytes so far and the whole (-1 when the answer does not say).
public protocol RelayFileTransport: RelayTransport {
    func download(_ request: RelayRequest, limit: Int64, progress: (@Sendable (Int64, Int64) -> Void)?) async throws -> RelayDownload
}

/// Builds requests the way the relay's guard wants them (relay_service.py): every call asks for JSON, a GET
/// carries no body and no Origin, a POST carries Origin equal to the service address. Only the sign-in's name
/// and value go out as a cookie. Nothing is followed or retried here; writes are never sent twice (Android
/// RelayApi). Computer routes go under /d/{32 hex}/; the source is passed with each call.
public struct RelayClient: Sendable {
    public static let jsonLimit = 8 * 1024 * 1024
    public static let defaultDeadline: TimeInterval = 40
    /// Seconds the computer may take: Claude's buttons wait for its window (web 65 s), archiving for its records.
    public static let slowRoutes: [String: TimeInterval] = [
        "claude/next": 65, "claude/task": 65, "chat/archive": 65, "chat/unarchive": 95, "chat/delete": 125,
        "chat/archived": 25, "notify": 35, "notify/ntfy": 35, "notify/test": 35, "voice/tidy": 65, "status": 10,
    ]

    public let origin: ServiceOrigin
    public let transport: any RelayTransport
    public let vault: (any CookieVault)?
    let now: @Sendable () -> Date

    public init(origin: ServiceOrigin, transport: any RelayTransport, vault: (any CookieVault)? = nil,
                now: @escaping @Sendable () -> Date = { Date() }) {
        self.origin = origin
        self.transport = transport
        self.vault = vault
        self.now = now
    }

    /// "/d/{device}{route}"; anything but a 32-hex computer id is refused before a request exists.
    public static func devicePath(_ device: String, _ route: String) throws -> String {
        guard device.utf8.count == 32, device.utf8.allSatisfy({ (0x30...0x39).contains($0) || (0x61...0x66).contains($0) }) else {
            throw ReadFailure("电脑标识无效")
        }
        return "/d/\(device)\(route)"
    }

    /// Throws when the keychain cannot be read now (phone locked), so nothing goes out without the sign-in and
    /// a resulting 401 cannot sign the user out.
    func signed(_ headers: [String: String]) throws -> [String: String] {
        var headers = headers
        if let header = try vault?.read(origin.key)?.header(at: now()) { headers["Cookie"] = header }
        return headers
    }

    public func get(_ path: String, query: [(String, String?)] = [], deadline: TimeInterval = defaultDeadline) throws -> RelayRequest {
        RelayRequest(method: .get, url: origin.url(path, query: query), headers: try signed(["Accept": "application/json"]), deadline: deadline)
    }

    public func post(_ path: String, json: JSONValue, query: [(String, String?)] = [], deadline: TimeInterval = defaultDeadline) throws -> RelayRequest {
        RelayRequest(method: .post, url: origin.url(path, query: query),
                     headers: try signed(["Accept": "application/json", "Content-Type": "application/json; charset=utf-8", "Origin": origin.header]),
                     body: try json.encoded(), deadline: deadline)
    }

    /// Sends; a status outside 2xx (redirects included) becomes a ServiceFailure, and a 401 forgets this service's
    /// sign-in only (another address keeps its own).
    public func send(_ request: RelayRequest) async throws -> RelayResponse {
        let response = try await transport.send(request)
        guard response.body.count <= Self.jsonLimit else { throw RelayError.tooLarge }
        if response.status == 401 { try? vault?.write(origin.key, nil) }
        guard (200..<300).contains(response.status) else { throw ServiceFailure(status: response.status, body: response.body) }
        return response
    }

    public func json(_ request: RelayRequest) async throws -> JSONValue {
        let response = try await send(request)
        do { return try JSONValue.parse(response.body) } catch { throw RelayError.unreadable }
    }

    // MARK: Account (no computer prefix)

    /// The service version and whether email sign-up and resets are open (web account page).
    public func accountConfig() async throws -> AccountConfig {
        AccountConfig(try await json(get("/account/config")))
    }

    /// POST /account/login; keeps the relay's `__Host-ar_account` from the answer. The password is not kept.
    public func login(name: String, password: String) async throws {
        let response = try await send(post("/account/login", json: ["name": .string(name), "password": .string(password)]))
        guard let header = response.headers["set-cookie"], let cookie = SessionCookie.fromSetCookie(header, now: now()) else {
            throw ReadFailure("登录响应缺少有效的账号凭据")
        }
        try vault?.write(origin.key, cookie)
    }

    /// 退出登录: the service ends the sign-in, and it is dropped here either way.
    public func logout() async throws {
        defer { try? vault?.write(origin.key, nil) }
        _ = try await json(post("/account/logout", json: [:]))
    }

    public func account() async throws -> Account {
        let state = try await json(get("/account/state"))
        let devices = try state["devices"].array.map {
            Computer(id: try requiredString($0, "id"), label: $0["label"].string(), connectable: $0["connectable"].bool())
        }
        return Account(devices: devices, email: state["email"].string())
    }

    /// Asks the relay to route to [device]; the answer must name exactly that computer's path.
    public func select(device: String) async throws {
        _ = try Self.devicePath(device, "")
        let result = try await json(post("/account/select", json: ["id": .string(device)]))
        guard result["url"].string() == "/d/\(device)/" else { throw ReadFailure("服务返回的电脑路径不匹配") }
    }

    public func renameDevice(_ device: String, label: String) async throws {
        _ = try Self.devicePath(device, "")
        _ = try await json(post("/account/rename", json: ["id": .string(device), "label": .string(label)]))
    }

    /// 移除: the computer loses remote access (its files stay).
    public func revokeDevice(_ device: String) async throws {
        _ = try Self.devicePath(device, "")
        _ = try await json(post("/account/revoke", json: ["id": .string(device)]))
    }

    // MARK: Reading a computer

    /// The web list (spec 4.1): [app] is "all" or one source; [sort] updated / created; [status] all / running /
    /// waiting / idle. Every row must belong to a known source, and to [app] when it is one.
    public func chatList(device: String, app: String, query: String = "", cursor: String? = nil,
                         sort: String = "updated", status: String = "all") async throws -> Page<Chat> {
        guard app == "all" || sourceOrder.contains(app) else { throw ReadFailure("来源应用无效") }
        let page = try await json(get(Self.devicePath(device, "/api/chats"),
                                      query: [("app", app), ("limit", "40"), ("query", query), ("cursor", cursor), ("sort", sort), ("status", status)]))
        let items = try page["items"].array.map { row -> Chat in
            let chat = try parseChat(row)
            guard sourceOrder.contains(chat.app), app == "all" || chat.app == app else { throw ReadFailure("来源应用不匹配") }
            return chat
        }
        return Page(items: items, cursor: Self.cursor(page), hasMore: page["has_more"].bool())
    }

    /// A page of one conversation; title, folder, cwd, status and runtime (the context ring) travel as meta.
    public func history(device: String, app: String, chat: String, before: String? = nil, around: String? = nil) async throws -> Page<Message> {
        let page = try await json(get(Self.devicePath(device, "/api/chat"),
                                      query: [("app", app), ("id", chat), ("n", "60"), ("before", before), ("around", around)]))
        guard page["id"].string() == chat, page["app"].string() == app else { throw ReadFailure("对话身份不匹配") }
        var meta: [String: JSONValue] = [:]
        for key in ["title", "folder", "cwd", "status", "runtime", "turn_started", "turn_ended", "turn_status", "step"]
            where page.has(key) { meta[key] = page[key] }
        return Page(items: try page["messages"].array.map(parseMessage), cursor: Self.cursor(page), hasMore: page["has_more"].bool(),
                    hasNewer: page["has_newer"].bool(), reset: page["reset"].bool(), meta: .object(meta))
    }

    /// The whole of a message the page cut short (展开完整消息).
    public func message(device: String, app: String, chat: String, message: String) async throws -> Message {
        let found = try parseMessage(try await json(get(Self.devicePath(device, "/api/chat/message"),
                                                        query: [("app", app), ("id", chat), ("message", message)])))
        guard found.id == message else { throw ReadFailure("消息身份不匹配") }
        return found
    }

    /// 查找消息 inside one conversation.
    public func search(device: String, app: String, chat: String, query: String, cursor: String? = nil) async throws -> Page<Message> {
        let page = try await json(get(Self.devicePath(device, "/api/chat/search"),
                                      query: [("app", app), ("id", chat), ("query", query), ("cursor", cursor)]))
        let items = try page["items"].array.map { Message(id: try requiredString($0, "id"), role: $0["role"].string(), text: $0["snippet"].string()) }
        return Page(items: items, cursor: Self.cursor(page), hasMore: page["has_more"].bool())
    }

    /// The source's state. [fresh] reads the desktop now; without it the computer may answer from a read of the
    /// last 4 s (the web's state polls). Claude's read holds its window, so it gets 20 s.
    public func control(device: String, app: String, chat: String, fresh: Bool = true) async throws -> Control {
        var state = try await json(get(Self.devicePath(device, "/api/\(app)/state"), query: [("id", chat), ("fresh", fresh ? "1" : nil)],
                                       deadline: app == "claude" ? 20 : Self.defaultDeadline))
        if app == "deepseek", case .object(var fields) = state {
            fields["queue_available"] = true
            state = .object(fields)
        }
        return parseControl(state)
    }

    // MARK: Acting on a computer

    /// The computer routes the phone calls besides reading (Android RelayApi DetailRoutes).
    public static let detailRoutes: Set<String> = [
        "chat/new/options", "chat/folders", "chat/new/draft", "chat/new", "chat/new/state", "chat/new/retry", "chat/new/references",
        "composer/references", "composer/commands", "files/places", "files/list", "files/image", "files/remove", "codex/remove-attachment", "codex/attachments",
        "chat/files", "chat/diff", "file/text", "file/meta", "deepseek/models", "deepseek/permissions", "deepseek/model", "deepseek/permission",
        "deepseek/answer", "deepseek/approval", "claude/catalog", "claude/setting", "claude/choose", "claude/menu", "claude/close-menu",
        "chat/projects", "chat/open", "chat/resolve", "claude/next", "claude/task", "chat/check", "chat/archive", "chat/unarchive",
        "chat/delete", "chat/archived", "chats/children", "notify", "notify/ntfy", "notify/test", "voice/status", "voice/terms",
        "voice/tidy", "status",
    ]

    /// A computer route outside the read set (Android detail): a GET with [query] when there is no [body], a POST
    /// otherwise. Slow routes get their own deadline.
    public func detail(device: String, route: String, query: [(String, String?)] = [], body: JSONValue? = nil) async throws -> JSONValue {
        guard Self.detailRoutes.contains(route) else { throw ReadFailure("当前服务不支持此功能") }
        let path = try Self.devicePath(device, "/api/" + route)
        let deadline = Self.slowRoutes[route] ?? Self.defaultDeadline
        if let body { return try await json(post(path, json: body, query: query, deadline: deadline)) }
        return try await json(get(path, query: query, deadline: deadline))
    }

    /// A send, stop, queue action or answer, the way each source takes it (Android RelayApi.command): DeepSeek
    /// names its routes and fields its own way; Claude sends through chat/send and does the rest with desktop
    /// tokens; Codex takes them as they are. Posted once; never again by itself.
    public func command(device: String, app: String, route: String, body: JSONValue) async throws -> JSONValue {
        guard ["send", "stop", "queue-action", "answer"].contains(route) else { throw ReadFailure("当前来源不支持操作") }
        switch app {
        case "deepseek":
            var outgoing = body.object
            let actual: String
            switch route {
            case "send":
                if body["intent"].string() == "auto" { outgoing["intent"] = "steer" }
                actual = "send"
            case "stop":
                outgoing["expected_turn"] = .string(body["turn_id"].string())
                actual = "stop"
            case "queue-action":
                // 立即补充 is "steer" for DeepSeek, 撤回 is "remove".
                outgoing["item_id"] = .string(body["message_id"].string())
                outgoing["action"] = .string(body["action"].string() == "promote" ? "steer" : "remove")
                actual = "queue"
            default:
                actual = route
            }
            let result = try await json(post(Self.devicePath(device, "/api/deepseek/" + actual), json: .object(outgoing)))
            guard route == "send", result["accepted"].bool(), case .object(var fields) = result else { return result }
            fields["delivery_state"] = .string(outgoing["intent"]?.string() == "queue" ? "queued" : "accepted")
            return .object(fields)
        case "claude":
            guard route == "send" else { throw ReadFailure("Claude 的停止与队列动作需使用当前桌面令牌") }
            var outgoing = body.object
            outgoing["app"] = "claude"
            return try await json(post(Self.devicePath(device, "/api/chat/send"), json: .object(outgoing)))
        default:
            return try await json(post(Self.devicePath(device, "/api/codex/" + route), json: body))
        }
    }

    /// A send's receipt by its request id (Codex, DeepSeek); Claude keeps none, its record is checked instead.
    public func receipt(device: String, app: String, chat: String, request: String) async throws -> JSONValue {
        guard app != "claude" else { return ["state": "unknown"] }
        let response = try await json(get(Self.devicePath(device, "/api/\(app)/receipt"), query: [("id", chat), ("request_id", request)]))
        guard app == "deepseek", response["state"].string() != "unknown", case .object(var fields) = response else { return response }
        guard response["id"].string() == chat else { throw ReadFailure("回执会话身份不匹配") }
        fields["request_id"] = .string(request)
        return .object(fields)
    }

    // MARK: Files and voice

    /// Pictures go up to 20 MB (the computer's limit), other files to 64 MiB: the relay takes no request bigger
    /// (relay_transport.py), so a bigger one is refused here with why instead of failing halfway.
    public static let imageLimit: Int64 = 20 * 1024 * 1024
    public static let fileLimit: Int64 = 64 * 1024 * 1024
    public static let downloadLimit: Int64 = 100 * 1024 * 1024
    /// A picture, a PDF or another file a file's page shows itself is shown up to 20 MB (web artifact-preview).
    public static let previewLimit: Int64 = 20 * 1024 * 1024

    /// A picture (codex/upload) or another file (files/upload) for [app]'s conversation [chat], or for a new
    /// conversation's draft by its request id ([draft]), sent from [file] with its length (Android uploadStream).
    public func upload(device: String, app: String, chat: String, draft: Bool, name: String, file: URL, size: Int64, image: Bool) async throws -> JSONValue {
        guard size > 0 else { throw ReadFailure("文件是空的，没有上传") }
        guard size <= (image ? Self.imageLimit : Self.fileLimit) else {
            throw ReadFailure(image ? "图片超过 20MB，传不上去" : "文件超过 64MB，中转一次最多传 64MB")
        }
        let path = try Self.devicePath(device, image ? "/api/codex/upload" : "/api/files/upload")
        let request = RelayRequest(method: .post, url: origin.url(path, query: [("app", app), (draft ? "draft" : "id", chat), ("name", name)]),
                                   headers: try signed(["Accept": "application/json", "Content-Type": "application/octet-stream", "Origin": origin.header]),
                                   deadline: 300, upload: file)
        return try await json(request)
    }

    /// One of a conversation's files (GET /api/file), or a computer file by its ticket (pc.…), to a file on this
    /// phone, at most 100 MB; the caller owns it. [progress] hears the bytes so far and the whole.
    public func download(device: String, app: String, chat: String, file: String,
                         progress: (@Sendable (Int64, Int64) -> Void)? = nil) async throws -> URL {
        guard let files = transport as? any RelayFileTransport else { throw ReadFailure("当前服务不支持下载文件") }
        var request = try get(Self.devicePath(device, "/api/file"), query: [("app", app), ("id", chat), ("file", file)], deadline: 300)
        request.headers["Accept"] = "*/*"
        let answer = try await files.download(request, limit: Self.downloadLimit, progress: progress)
        if answer.status == 401 { try? vault?.write(origin.key, nil) }
        guard (200..<300).contains(answer.status), let saved = answer.file else { throw ServiceFailure(status: answer.status, body: answer.body) }
        return saved
    }

    /// A picture the computer kept of a send (GET /api/codex/image by its id; [small]: its copy of at most 320 px), to
    /// a file on this phone; the caller owns it.
    public func sentPicture(device: String, id: String, small: Bool) async throws -> URL {
        guard let files = transport as? any RelayFileTransport else { throw ReadFailure("当前服务不支持下载文件") }
        var request = try get(Self.devicePath(device, "/api/codex/image"), query: [("thumb", small ? "1" : nil), ("id", id)], deadline: small ? 40 : 120)
        request.headers["Accept"] = "*/*"
        let answer = try await files.download(request, limit: Self.downloadLimit, progress: nil)
        if answer.status == 401 { try? vault?.write(origin.key, nil) }
        guard (200..<300).contains(answer.status), let saved = answer.file else { throw ServiceFailure(status: answer.status, body: answer.body) }
        return saved
    }

    /// The computer's voice service (web voice-ui.js): raw audio up, recognised text back. A whole recording, or the
    /// end of one, waits for recognition (and 整理) on the computer.
    public static let voiceRoutes: Set<String> = ["voice", "voice/stream/start", "voice/stream/chunk", "voice/stream/end", "voice/stream/cancel", "voice/stream/cloud"]

    public func voice(device: String, route: String, query: [(String, String?)] = [], audio: Data = Data(), type: String = "application/octet-stream") async throws -> JSONValue {
        guard Self.voiceRoutes.contains(route) else { throw ReadFailure("当前服务不支持此功能") }
        let slow = route == "voice" || route == "voice/stream/end" || route == "voice/stream/cloud"
        let request = RelayRequest(method: .post, url: origin.url(try Self.devicePath(device, "/api/" + route), query: query),
                                   headers: try signed(["Accept": "application/json", "Content-Type": type, "Origin": origin.header]),
                                   body: audio, deadline: slow ? 125 : 35)
        return try await json(request)
    }

    /// The sidebar tree (GET /api/chat/projects): apps → projects → conversations. Only the apps this computer
    /// has are in it, so it also says which source chips to show (spec 4.1, 0.8).
    public func projects(device: String) async throws -> JSONValue {
        try await json(get(Self.devicePath(device, "/api/chat/projects")))
    }

    /// The live stream of one conversation, checked frame by frame; it ends with an error when the connection
    /// closes, so the caller reconnects for a new snapshot.
    public func events(device: String, app: String, chat: String) throws -> AsyncThrowingStream<LiveFrame, any Error> {
        guard let streaming = transport as? any RelayStreamingTransport else { throw ReadFailure("当前服务不支持实时连接") }
        var request = try get(Self.devicePath(device, "/api/events"), query: [("app", app), ("id", chat)])
        request.headers["Accept"] = "text/event-stream"
        let opening = request, vault = vault, key = origin.key
        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let response = try await streaming.stream(opening)
                    if response.status == 401 { try? vault?.write(key, nil) }
                    guard (200..<300).contains(response.status) else { throw ServiceFailure(status: response.status) }
                    var parser = ServerSentEventParser()
                    var reducer = StreamReducer(chat: chat, app: app)
                    for try await chunk in response.chunks {
                        for event in try parser.feed(chunk) {
                            if let frame = try reducer.accept(JSONValue.parse(Data(event.data.utf8))) { continuation.yield(frame) }
                        }
                    }
                    continuation.finish(throwing: ReadFailure("实时连接已关闭"))
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    static func cursor(_ page: JSONValue) -> String? {
        let next = page["next_cursor"].string()
        return next.isEmpty ? nil : next
    }
}

/// The apps of a sidebar tree, each group one app this computer has, in the web's order.
public func treeApps(_ tree: JSONValue) -> [String] {
    let found = Set(tree["apps"].array.map { $0["app"].string() })
    return sourceOrder.filter { found.contains($0) }
}

public enum RelayError: Error, Sendable, Equatable {
    case tooLarge
    case unreadable

    public var message: String {
        switch self {
        case .tooLarge: return "内容过大，请缩小读取范围"
        case .unreadable: return "服务返回的内容读不出来，请稍后重试。"
        }
    }
}

/// An answer outside 2xx, with the computer's own error text when it gave one (Android ServiceFailure).
/// [draft] is the text found in Claude's box on the computer when that turned a send away (desktop_draft).
public struct ServiceFailure: Error, Sendable, Equatable {
    public let status: Int
    public let code: String
    public let detail: String
    public let notSubmitted: Bool
    public let draft: String

    public init(status: Int, code: String = "", detail: String = "", notSubmitted: Bool = false, draft: String = "") {
        self.status = status
        self.code = code
        self.detail = detail
        self.notSubmitted = notSubmitted
        self.draft = draft
    }

    public init(status: Int, body: Data) {
        let error = (try? JSONValue.parse(body)) ?? .null
        self.init(status: status, code: error["code"].string(), detail: error["error"].string(),
                  notSubmitted: error["not_submitted"].bool(), draft: error["draft"].string())
    }

    public var message: String {
        if status == 401 { return "登录已失效，请重新登录；当前阅读位置已保留。" }
        if (status == 409 && code == "device_offline") || status == 503 { return "电脑已离线，请稍后刷新电脑列表。" }
        if status == 403 { return "服务拒绝访问，请核对服务地址或账号权限。" }
        if status == 404 { return "记录或电脑已不可用，请刷新列表。" }
        if (300...399).contains(status) { return "服务返回了跳转，请在设置中填写正确的 HTTPS 服务地址。" }
        let shown = String(detail.prefix(500))
        return shown.isEmpty ? "请求失败（HTTP \(status)），请核对后重试。" : shown
    }
}
