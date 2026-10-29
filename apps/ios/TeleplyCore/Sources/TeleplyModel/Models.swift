/// A computer on the account (GET /account/state devices).
public struct Computer: Sendable, Equatable, Identifiable {
    public let id: String
    public var label: String
    public var connectable: Bool

    public init(id: String, label: String, connectable: Bool) {
        self.id = id
        self.label = label
        self.connectable = connectable
    }
}

public struct Account: Sendable, Equatable {
    public var devices: [Computer]
    public var email: String

    public init(devices: [Computer], email: String) {
        self.devices = devices
        self.email = email
    }
}

/// A conversation row (Android Models.kt Chat). [app] is the source ("" when a single-source list did not say);
/// [updated] is milliseconds. A row may carry [children] that fold under it (DeepSeek subagents, one-shot sessions
/// a script started from it), [childCount] in all; a [group] row (DeepSeek's 未分组的会话) only folds and opens
/// nothing. A child row has a [kind] ("subagent" or another) and its [parent].
public struct Chat: Sendable, Equatable, Identifiable {
    public let id: String
    public var title: String
    public var folder: String = ""
    public var preview: String = ""
    public var status: String = ""
    public var app: String = ""
    public var updated: Int64 = 0
    public var group: Bool = false
    public var kind: String = ""
    public var parent: String = ""
    public var parentTitle: String = ""
    public var children: [Chat] = []
    public var childCount: Int = 0
    public var childRunning: Int = 0
    /// 0.6.4: the running turn's own start and end, Unix seconds (0 when the computer does not know).
    public var turnStarted: Int64 = 0
    public var turnEnded: Int64 = 0
    /// 0.6.4: what it is doing (edit | run | search | read).
    public var step: String = ""

    public init(id: String, title: String) {
        self.id = id
        self.title = title
    }
}

/// One message. [phase] is commentary / final_answer / thinking for assistant text; [request] is a user message's
/// client_request_id; [details] keeps the fields the timeline cards read (Android MessageDetails).
public struct Message: Sendable, Equatable, Identifiable {
    public let id: String
    public var role: String
    public var text: String
    public var truncated: Bool = false
    /// The whole message's length as the computer counts it; with [truncated], what 展开全文 says.
    public var length: Int = 0
    public var kind: String = ""
    public var status: String = ""
    public var order: Double? = nil
    public var aliases: [String] = []
    public var details: JSONValue = [:]
    public var phase: String = ""
    public var request: String = ""
    /// 0.6.4: the turn this message belongs to, Unix seconds of its start and end.
    public var turnStarted: Int64 = 0
    public var turnEnded: Int64 = 0

    public init(id: String, role: String, text: String) {
        self.id = id
        self.role = role
        self.text = text
    }
}

/// [meta] carries page-level fields, e.g. a conversation's title, folder, status and runtime.
public struct Page<Item: Sendable & Equatable>: Sendable, Equatable {
    public var items: [Item]
    public var cursor: String?
    public var hasMore: Bool
    public var hasNewer: Bool = false
    public var reset: Bool = false
    public var meta: JSONValue = [:]

    public init(items: [Item], cursor: String?, hasMore: Bool, hasNewer: Bool = false, reset: Bool = false, meta: JSONValue = [:]) {
        self.items = items
        self.cursor = cursor
        self.hasMore = hasMore
        self.hasNewer = hasNewer
        self.reset = reset
        self.meta = meta
    }
}

/// Which conversation something belongs to (Android ChatKey): sign-in scope, computer, source and conversation.
/// Drafts, sends and reading positions never cross from one key to another (spec B01).
public struct ChatKey: Hashable, Sendable {
    public var scope: String
    public var device: String
    public var app: String
    public var chat: String

    public init(scope: String, device: String, app: String, chat: String) {
        self.scope = scope
        self.device = device
        self.app = app
        self.chat = chat
    }
}

/// A row's key in the list: its source and id.
public func rowKey(_ chat: Chat) -> String {
    chat.app + ":" + chat.id
}

/// The computer broke the contract (wrong identity, source or path), with Android's words for it.
public struct ReadFailure: Error, Sendable, Equatable {
    public let message: String

    public init(_ message: String) {
        self.message = message
    }
}

/// The desktop apps in the order the web and the sidebar show them.
public let sourceOrder = ["codex", "claude", "deepseek"]

/// org.json getString: present and not null, or the read fails.
func requiredString(_ json: JSONValue, _ key: String) throws -> String {
    guard json.has(key) else { throw RelayError.unreadable }
    return json[key].string()
}

public func parseChat(_ json: JSONValue) throws -> Chat {
    var chat = Chat(id: try requiredString(json, "id"), title: json["title"].string().isEmpty ? "未命名对话" : json["title"].string())
    chat.folder = json["folder"].string()
    chat.preview = json["preview"].string()
    chat.status = json["status"].string()
    chat.app = json["app"].string()
    chat.updated = json["updated"].int64()
    chat.group = json["group"].bool()
    chat.kind = json["kind"].string()
    chat.parent = json["parent"].string()
    chat.parentTitle = json["parent_title"].string()
    chat.children = try json["children"].array.map(parseChat)
    chat.childCount = json["child_count"].int()
    chat.childRunning = json["child_running"].int()
    chat.turnStarted = json["turn_started"].int64()
    chat.turnEnded = json["turn_ended"].int64()
    chat.step = json["step"].string()
    return chat
}

/// Fields a message keeps besides its text: a tool step's title and changes; Claude's checklist (plan: items),
/// next-step box (next: tool_id, recap, ask, actions, open) and proposed task (task: title, brief, offer); a
/// DeepSeek subagent (subagent: child, label, status); a message from another conversation (origin) and thinking;
/// when the record wrote it (time), which ties a Claude send's pictures to it (sentPictures).
let messageDetails = ["tool", "title", "changes", "activity_turn", "items", "tool_id", "recap", "ask", "actions", "blocked", "open",
                      "brief", "offer", "label", "child", "status", "mode", "origin", "thinking", "source_id", "time"]

public func parseMessage(_ json: JSONValue) throws -> Message {
    var message = Message(id: try requiredString(json, "id"), role: json["role"].string(), text: json["text"].string())
    message.truncated = json["truncated"].bool()
    message.length = json["length"].int()
    message.kind = json["kind"].string()
    message.status = json["tool_status"].string()
    message.order = json.has("order") ? json["order"].double() : nil
    message.aliases = json["projection_aliases"].array.map { $0.string() }
    var details: [String: JSONValue] = [:]
    for key in messageDetails where json.object[key] != nil { details[key] = json[key] }
    message.details = .object(details)
    message.phase = json["phase"].string()
    message.request = json["client_request_id"].string()
    message.turnStarted = json["turn_started"].int64()
    message.turnEnded = json["turn_ended"].int64()
    return message
}

/// Server transcript order is authoritative: never sort by arrival time or merge by equal text (spec B02).
public func mergeMessages(_ old: [Message], _ incoming: [Message], prepend: Bool) -> [Message] {
    let replacements = Dictionary(incoming.map { ($0.id, $0) }, uniquingKeysWith: { _, last in last })
    let seen = Set(old.map(\.id))
    var added = Set<String>()
    let fresh = incoming.filter { !seen.contains($0.id) && added.insert($0.id).inserted }
    let existing = old.map { replacements[$0.id] ?? $0 }
    return prepend ? fresh + existing : existing + fresh
}

/// Messages 展开全文 made whole stay whole when a later read brings them cut short again, unless one has grown
/// since (web reading-ui.js merge).
public func keepWhole(_ messages: [Message], _ whole: [String: Message]) -> [Message] {
    guard !whole.isEmpty else { return messages }
    return messages.map { message in
        guard message.truncated, let full = whole[message.id], full.length >= message.length else { return message }
        var kept = message
        kept.text = full.text
        kept.truncated = false
        return kept
    }
}

/// The words of 展开全文 (web reading-ui.js): with the whole length when the computer gave it.
public func expandLabel(_ message: Message) -> String {
    message.length > 0 ? "展开全文（\(message.length) 字）" : "展开全文"
}
