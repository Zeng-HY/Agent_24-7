/// A source's state as /api/{app}/state reports it (Android ChatCore.kt Control).
public struct Control: Sendable, Equatable {
    public var available = false
    public var running = false
    public var turn = ""
    public var queueAvailable = false
    public var queued: [Queued] = []
    /// Recent turns by id: inProgress, completed, interrupted, failed.
    public var turns: [String: String] = [:]
    /// Something waits for the user's answer: a question still open, Claude's prompt, DeepSeek's requests.
    public var questions = false
    /// 0.6.4: the running turn's start and end from the computer, Unix seconds; 0 when it does not know.
    public var turnStarted = 0
    public var turnEnded = 0
    /// 0.6.4: edit | run | search | read; 0.6.6: compact while the context is compacted.
    public var step = ""
    /// 0.6.6: a compaction under way (/compact, or the source out of room), and since when (Unix seconds, 0 unknown).
    /// DeepSeek compacts outside a turn too, so this does not wait for `running`.
    public var compacting = false
    public var compactStarted = 0
    public var raw: JSONValue = [:]

    public init(available: Bool = false, running: Bool = false, turn: String = "", queueAvailable: Bool = false,
                queued: [Queued] = [], turns: [String: String] = [:], questions: Bool = false, raw: JSONValue = [:],
                turnStarted: Int = 0, turnEnded: Int = 0, step: String = "", compacting: Bool = false, compactStarted: Int = 0) {
        self.available = available
        self.running = running
        self.turn = turn
        self.queueAvailable = queueAvailable
        self.queued = queued
        self.turns = turns
        self.questions = questions
        self.raw = raw
        self.turnStarted = turnStarted
        self.turnEnded = turnEnded
        self.step = step
        self.compacting = compacting
        self.compactStarted = compactStarted
    }
}

public struct Queued: Sendable, Equatable {
    public var id: String
    public var text: String
    public var status: String

    public init(id: String, text: String, status: String) {
        self.id = id
        self.text = text
        self.status = status
    }
}

private let terminalTurns: Set<String> = ["completed", "interrupted", "failed"]

/// A reconnect never brings a finished turn back to running; a new turn may run (spec B11).
public func mergeControl(previous: Control, incoming: Control) -> Control {
    var merged = incoming
    merged.turns = incoming.turns.reduce(into: [:]) { result, entry in
        let earlier = previous.turns[entry.key]
        result[entry.key] = earlier.map { terminalTurns.contains($0) } == true ? earlier! : entry.value
    }
    let staleRunning = incoming.running && previous.turns[incoming.turn].map { terminalTurns.contains($0) } == true
    merged.running = incoming.running && !staleRunning
    merged.turn = staleRunning ? "" : incoming.turn
    return merged
}

public func parseControl(_ json: JSONValue) -> Control {
    let active = json["active_turn_id"].string()
    var turns: [String: String] = [:]
    for turn in json["recent_turns"].array where turn.has("id") { turns[turn["id"].string()] = turn["status"].string() }
    return Control(
        available: json["available"].bool(),
        running: json["running"].bool(),
        turn: active.isEmpty ? json["turn_id"].string() : active,
        queueAvailable: json["queue_available"].bool(),
        queued: json["queued"].array.map { Queued(id: $0["id"].string(), text: $0["text"].string(), status: $0["status"].string()) },
        turns: turns,
        // 0.6.6: Codex also lists its last answered cards (they can still be changed). Counted, they made every new
        // turn of such a conversation say 需要你回答 in yellow and hid 正在思考 (user 10-31).
        questions: json["questions"].array.contains { $0["status"].string() != "answered" } || json["prompt"].isObject
            || !json["interactions"].array.isEmpty,
        raw: json,
        turnStarted: json["turn_started"].int(),
        turnEnded: json["turn_ended"].int(),
        step: json["step"].string(),
        compacting: json["compacting"].bool() || json["step"].string() == "compact",
        compactStarted: json["compact_started"].int())
}

/// One frame of the live stream: the snapshot (seq 1) or an update with only the changed messages.
public struct LiveFrame: Sendable, Equatable {
    public var seq: Int64
    public var snapshot: Bool
    public var messages: [Message]
    /// Codex sends its state inside the stream; nil for the other sources.
    public var control: Control?
    /// 0.6.6: an update's page fields (status, runtime, title…), nil when it brought none. Dropped before, so the
    /// context ring kept the number the page opened with, through a compaction too (user 10-31).
    public var meta: JSONValue? = nil
}

/// Checks the live stream (live_events.py protocol 1): the first frame is the snapshot, then consecutive updates;
/// repeats are dropped, a gap or another conversation's frame fails so the caller reconnects for a new snapshot.
public struct StreamReducer: Sendable {
    public let chat: String
    public let app: String
    private var seq: Int64 = 0

    public init(chat: String, app: String = "codex") {
        self.chat = chat
        self.app = app
    }

    public mutating func accept(_ json: JSONValue) throws -> LiveFrame? {
        guard json["protocol"].int() == 1, json["app"].string() == app, json["id"].string() == chat else {
            throw ReadFailure("实时协议或会话身份不匹配")
        }
        guard json.has("seq") else { throw RelayError.unreadable }
        let number = json["seq"].int64()
        if number <= seq { return nil }
        let type = json["type"].string()
        let snapshot = type == "snapshot"
        let inOrder = seq == 0 ? snapshot && number == 1 : !snapshot && type == "update" && number == seq + 1
        guard inOrder else { throw ReadFailure("实时序号不连续") }
        let page = snapshot ? json["chat"] : json
        if snapshot, page["id"].string() != chat || page["app"].string() != app { throw ReadFailure("实时协议或会话身份不匹配") }
        let control: Control? = app == "codex" && json.object["control"] != nil ? (json["control"].isObject ? parseControl(json["control"]) : Control()) : nil
        var frame = LiveFrame(seq: number, snapshot: snapshot, messages: try page["messages"].array.map(parseMessage), control: control)
        if !snapshot, json["meta"].isObject { frame.meta = json["meta"] }
        seq = number
        return frame
    }
}

/// Live messages replace what they stand for (projection_aliases), then follow the source's order when every
/// message has one.
public func mergeLive(_ old: [Message], _ incoming: [Message]) -> [Message] {
    let aliases = Set(incoming.flatMap(\.aliases))
    let merged = mergeMessages(old.filter { !aliases.contains($0.id) }, incoming, prepend: false)
    guard merged.allSatisfy({ $0.order != nil }) else { return merged }
    return merged.enumerated().sorted { ($0.element.order!, $0.offset) < ($1.element.order!, $1.offset) }.map(\.element)
}

/// The words under a sent message: only real evidence says 已送达 (spec B03, B04).
public func receiptLabel(state: String, result: JSONValue, action: String) -> String {
    let words: String
    switch state {
    case "cancelled": words = "已取消排队"
    case "rejected": words = "未接收"
    case "queued": words = "已排队"
    case "accepted" where action == "stop": words = "停止请求已接收，等待轮次确认"
    case "accepted" where result["evidence"]["source"].string() == "conversation_record": words = "已送达"
    // 0.6.6: a command the source ran itself (/compact); no message of it will ever be in the record to confirm it.
    case "accepted" where !result["command"].string().isEmpty: words = "已送达"
    case "accepted": words = "已接收"
    default: words = "送达状态待确认"
    }
    return Hints.text(words)
}
