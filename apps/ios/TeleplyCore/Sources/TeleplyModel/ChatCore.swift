import Foundation

/// 11-27 (S2; handoff 11-27 §6.3): the command the source runs now, when its state says so —
/// `{"running": true, "since_ms": 1764200000000, "can_kill": true}`. A computer that says nothing has none, and nothing
/// that may be ended.
public struct RunningCommand: Sendable, Equatable {
    public var running: Bool
    /// The computer's own clock, in milliseconds: only ever compared with its other times, never with the phone's.
    public var since: Int64
    /// The command may be ended now: the hooks are trusted and it runs with full access.
    public var canKill: Bool

    public init(running: Bool = false, since: Int64 = 0, canKill: Bool = false) {
        self.running = running
        self.since = since
        self.canKill = canKill
    }

    /// The state's `command`.
    public init(_ json: JSONValue) {
        self.init(running: json["running"].bool(), since: json["since_ms"].int64(), canKill: json["can_kill"].bool())
    }
}

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
    /// 11-27 (S2): the command under way, when the state names one (handoff 11-27 §6.3); nil for an older computer.
    public var command: RunningCommand?
    public var raw: JSONValue = [:]

    public init(available: Bool = false, running: Bool = false, turn: String = "", queueAvailable: Bool = false,
                queued: [Queued] = [], turns: [String: String] = [:], questions: Bool = false, raw: JSONValue = [:],
                turnStarted: Int = 0, turnEnded: Int = 0, step: String = "", compacting: Bool = false, compactStarted: Int = 0,
                command: RunningCommand? = nil) {
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
        self.command = command
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

/// 此刻能力 (handoff 3.4, docs §八): a protocol 2 state may carry `capabilities_now` — the manifest's capabilities with
/// what changed during this turn laid over them — and `capability_notes`, the computer's Chinese reasons.
extension Control {
    public var capabilitiesNow: JSONValue { raw["capabilities_now"] }

    public var capabilityNotes: JSONValue { raw["capability_notes"] }

    /// The manifest's capabilities as they apply to this conversation now: narrowed by `capabilities_now` when the
    /// state has it, the manifest's own values otherwise (an older computer).
    public func narrowed(_ base: AgentCapabilities) -> AgentCapabilities { base.narrowed(by: capabilitiesNow) }

    /// Why [capability] cannot be used now, in the computer's words; "" when it gave none.
    public func note(_ capability: String) -> String {
        capabilityNotes[capability].string().trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// 11-27 (S2; design §4.3 point 1, handoff 11-27 §6.3): 结束这条命令，马上插话 may be offered — a command runs that the
    /// computer says it may end, and its capability table says `kill_command` now. The three's own manifest has no such
    /// key, so that value comes from the state's `capabilities_now`, where Codex says it (handoff §3.3 point 4). A
    /// computer whose state has no `command` never offers it.
    public var canKillCommand: Bool {
        guard let command = self.command, command.running, command.canKill else { return false }
        return capabilitiesNow["kill_command"].bool()
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
        compactStarted: json["compact_started"].int(),
        // 11-27 (S2): a command under way and whether it may be ended (handoff 11-27 §6.3).
        command: json["command"].isObject ? RunningCommand(json["command"]) : nil)
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
    /// 11-16: a snapshot's own pagination, so the phone knows older rows are not read when the first page failed
    /// (the outbox used to take every snapshot for the whole record; older phones get them from /api/chat).
    public var hasMore: Bool = false
    public var nextCursor: String? = nil

    public init(seq: Int64, snapshot: Bool, messages: [Message], control: Control?, meta: JSONValue? = nil,
                hasMore: Bool = false, nextCursor: String? = nil) {
        self.seq = seq
        self.snapshot = snapshot
        self.messages = messages
        self.control = control
        self.meta = meta
        self.hasMore = hasMore
        self.nextCursor = nextCursor
    }
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
        if snapshot {
            // 11-16: the snapshot's page says whether more is on the computer, as /api/chat does.
            frame.hasMore = page["has_more"].bool()
            frame.nextCursor = page["next_cursor"].string().isEmpty ? nil : page["next_cursor"].string()
        }
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

/// A receipt that says nothing either way (spec B03): the words under a send before its result is known.
public let unknownReceiptLabel = "送达状态待确认"

/// 11-26: the computer's delivery records have no such request id (`missing`, handoff 11-26 §8.1), so a send the phone
/// kept never reached it. The same request id may go out again: the computer de-duplicates by it (codex_control._begin).
public let missingLabel = "电脑没收到"

/// The words under a sent message: only real evidence says 已送达 (spec B03, B04). 11-26: `missing` says the computer's
/// delivery records know nothing of the request at all, so the phone can send it again under the same request id.
public func receiptLabel(state: String, result: JSONValue, action: String, missing: Bool = false) -> String {
    if state == "unknown", missing, action == "send" { return missingLabel }
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
    default: words = unknownReceiptLabel
    }
    return Hints.text(words)
}

/// A new assistant's receipt (handoff 3.4): its own address says `delivered` and `queued` itself, so those words
/// carry the same meanings the three's receipts have; everything else reads as before. 11-26: `missing` says the
/// same thing here as for the three (handoff 11-26 §8.1).
public func agentReceiptLabel(state: String, result: JSONValue, action: String, missing: Bool = false) -> String {
    if state == "unknown", missing, action == "send" { return missingLabel }
    if state == "accepted" && result["delivered"].bool() { return Hints.text("已送达") }
    if state == "unknown" && result["queued"].bool() { return Hints.text("已排队") }
    return receiptLabel(state: state, result: result, action: action)
}

/// The one line a finished 核对 leaves for a few seconds (handoff 11-26 §3.1 point 5), from the receipt itself, not
/// from the label a send happened to keep. The words are the same as Android's (ChatCore.kt checkResultText).
public func checkResultText(state: String, missing: Bool, label: String) -> String {
    if state == "unknown", missing { return "已核对：电脑没收到" }
    if state == "unknown" { return "已核对：电脑查不到这条的记录" }
    if state == "dispatching" { return "已核对：电脑收到了，还在处理" }
    return "已核对：" + label
}

/// Claude's 核对 line: the computer's delivery record says nothing useful, so its own record is what was looked at
/// (handoff 11-26 §3.1 point 5).
public func claudeCheckResultText(delivered: Bool, queued: Bool) -> String {
    if delivered { return "已核对：已送达" }
    if queued { return "已核对：已排队" }
    return "已核对：Claude 的记录里还没看到这条"
}

// MARK: 11-27 提速 (design docs/handoff-1127-speed.md §4)

/// 11-27 (design §4.1, S1): what the send key does while the source runs. A tap sends an interjection (插话) when the
/// assistant takes one now; a hold offers 排队到这一轮结束后再发 only when it takes both. With one mode only, a tap and a
/// hold both do that one.
public struct SendKeyModes: Sendable, Equatable {
    /// The running turn takes an interjection now (`steer` among the send modes it may use).
    public var steers: Bool
    /// The running turn takes a queue (`queue_available`, or `queue` among a new assistant's send modes).
    public var queues: Bool

    public init(steers: Bool = false, queues: Bool = false) {
        self.steers = steers
        self.queues = queues
    }

    /// What a tap does: the queue only when the assistant takes no interjection.
    public var tapQueues: Bool { queues && !steers }

    /// A hold on the key offers the queue menu only when both are offered.
    public var holdQueues: Bool { steers && queues }
}

/// 11-27 (design §4.2, S5): the grey line while an interjection waits for the step under way — "等 Codex 做完这一步再插进
/// 去 · 已等 3 秒", with the assistant's own name. The seconds are the phone's own count, from the computer's answer.
public func steerWaitingText(name: String, seconds: Int) -> String {
    "等 " + name + " 做完这一步再插进去 · 已等 " + String(max(0, seconds)) + " 秒"
}

/// 11-27 (design §4.3 point 2): the confirmation before the command is ended.
public func killCommandConfirmText(name: String) -> String {
    name + " 正在跑的这条命令会被结束，它的结果作废；你的话会马上交给 " + name + "。"
}

/// 11-27 (design §4.3 point 3): what is said once the command stopped and the words are on their way in.
public let killCommandStartedText = "已结束命令，正在插话…"

/// A send's `intent` from its stored request body ("" when it has none: 执行计划, and copies of an older build).
public func sendIntent(_ body: String) -> String {
    ((try? JSONValue.parse(Data(body.utf8))) ?? [:])["intent"].string()
}

/// 11-27 (design §4.2, S5): a send the computer took as an interjection while the source was working — 已接收 with
/// `intent: steer` — and has not delivered yet. A queued send waits in the queue tray instead, and an answer that is
/// already 已送达 has nothing to wait for.
public func steerWaiting(_ record: Submission) -> Bool {
    record.action == "send" && record.label == Hints.text("已接收") && sendIntent(record.body) == "steer"
}

/// 11-27 (S3; handoff 11-27 §6.1, §6.2): one request as the phone measured it. [roundtripMs] is the phone's own
/// `ContinuousClock` from the request going out to the answer; [serverMs] is what the computer said it used, nil when it
/// did not say (an older one); [networkMs] is the round trip less that, never below zero — the two clocks are never
/// compared.
public struct PhoneTiming: Sendable, Equatable {
    public var request: String
    public var roundtripMs: Int
    public var serverMs: Int?
    public var networkMs: Int?

    public init(request: String, roundtripMs: Int, serverMs: Int?) {
        self.request = request
        self.roundtripMs = max(0, roundtripMs)
        self.serverMs = serverMs.map { max(0, $0) }
        if let server = self.serverMs {
            self.networkMs = max(0, self.roundtripMs - server)
        } else {
            self.networkMs = nil
        }
    }
}

/// A duration as whole milliseconds (nearest), never below zero.
public func milliseconds(_ elapsed: Duration) -> Int {
    let parts = elapsed.components
    let value = Double(parts.seconds) * 1_000 + Double(parts.attoseconds) / 1e15
    guard value.isFinite, value < 9.0e15, value > -9.0e15 else { return 0 }
    return max(0, Int(value.rounded()))
}

/// 11-27 (S3; handoff 11-27 §6.1): a request's timing from the time it took and the answer it got.
public func phoneTiming(request: String, elapsed: Duration, reply: JSONValue) -> PhoneTiming {
    PhoneTiming(request: request, roundtripMs: milliseconds(elapsed),
                serverMs: reply.has("server_ms") ? reply["server_ms"].int() : nil)
}

/// 11-27 (design §4.4.2; handoff 11-27 §6.2): the numbers of the request before this one, as the next send carries them
/// (`client_prev`). Nothing when the computer did not say its own time: an older one, and then nothing is measured
/// against a guess.
public func clientPrev(_ timing: PhoneTiming?) -> JSONValue? {
    guard let timing, let server = timing.serverMs else { return nil }
    return ["request_id": .string(timing.request), "roundtrip_ms": .number(Double(timing.roundtripMs)),
            "server_ms": .number(Double(server))]
}

/// 11-27 (design §4.4.3): the extra words the speed toast shows for a send — "手机→电脑 0.6 秒 · 电脑处理 3.2 秒". Nothing
/// for a computer that did not say its own time, so the toast reads exactly as it did.
public func timingWords(_ timing: PhoneTiming?) -> String {
    guard let timing, let network = timing.networkMs, let server = timing.serverMs else { return "" }
    return "手机→电脑 " + secondsWords(network) + " 秒 · 电脑处理 " + secondsWords(server) + " 秒"
}

/// Milliseconds as the one-decimal seconds the toast and the log read ("0.6").
func secondsWords(_ value: Int) -> String {
    String(format: "%.1f", Double(value) / 1_000)
}
