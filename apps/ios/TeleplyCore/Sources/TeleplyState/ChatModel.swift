import Foundation
import Observation
import TeleplyModel

/// Notes a send's local copy keeps in its body and never sends (Android ChatController): where Claude's record
/// stood when the computer pressed Enter and the words to look for there (web chat/check), and, for a send the
/// computer turned away, what was in Claude's box and why.
public enum SendNote {
    public static let claudeOffset = "_claude_offset"
    public static let claudeCheckText = "_claude_check_text"
    public static let desktopDraft = "_desktop_draft"
    public static let sendError = "_send_error"
    static let all = [claudeOffset, claudeCheckText, desktopDraft, sendError]
}

/// Labels of sends still to be settled, and of a send taken off the list by the user.
let unsettledLabels: Set<String> = ["提交中", "送达状态待确认", "已接收", "已排队"]
public let removedLabel = "已移除"

/// What a timed request came to, by the web's rules: not done on the computer, delivery unconfirmed, or done.
public func speedOutcome(_ reply: JSONValue) -> String {
    let refused = !reply["error"].string().isEmpty || reply.has("ok") && !reply["ok"].bool(or: true)
        || reply.has("accepted") && !reply["accepted"].bool(or: true) || reply["state"].string() == "failed"
    if refused { return "服务端未成功" }
    if reply["state"].string() == "unconfirmed" { return "送达未确认" }
    return "请求完成"
}

func jsonText(_ value: JSONValue) -> String {
    String(decoding: (try? value.encoded()) ?? Data("{}".utf8), as: UTF8.self)
}

func jsonValue(_ text: String) -> JSONValue {
    (try? JSONValue.parse(Data(text.utf8))) ?? [:]
}

/// The open conversation's live side and its composer (Android ChatController). Bound to one conversation: a
/// fresh state read on entering, receipts of unsettled sends checked (never sent again), then the live stream;
/// Claude and DeepSeek also poll their state (every 5 s and 2.5 s, without fresh, never while a tap waits on the
/// computer). A dropped connection is tried again after 1 s, doubling up to 15 s; a 401, 403 or 404 stops it. In
/// the background nothing runs.
///
/// Sending (spec B03–B06): every send gets a request id; its local copy is kept and the draft cleared before the
/// request goes out; after that only receipts change its label. A source that is running takes a send as queued
/// (发送并排队); 立即补充 hands a queued one to the running turn.
@Observable
public final class ChatModel {
    public internal(set) var key: ChatKey?
    public internal(set) var control = Control()
    public internal(set) var connection = "实时连接未启动"
    /// Goes up when a frame brings messages, so the page can follow new output.
    public internal(set) var revision = 0

    // The composer
    public internal(set) var draft = ""
    /// The draft and the sends of this conversation are read; until then nothing can be typed or sent.
    public internal(set) var ready = false
    public internal(set) var submitting = false
    /// This conversation's sends, newest first.
    public internal(set) var submissions: [Submission] = []
    public var error: String?
    /// Goes up when the draft changed from outside the text field (恢复草稿, 常用提示语), so the field takes it.
    public internal(set) var draftReset = 0
    /// Goes up when the input should take the keyboard; [hint] then shows in the empty box.
    public internal(set) var focus = 0
    public internal(set) var hint = ""
    /// Goes up when a send is first taken by the computer (已接收, 已送达 or 已排队): a light tap (spec 3).
    public internal(set) var acknowledged = 0

    /// True while a tap waits on the computer (web claude-ui.js `choosing`): no state poll then.
    @ObservationIgnored public var pollPaused: () -> Bool = { false }
    /// The source's state was read for a conversation (entering, a poll, after an action): a Claude desktop option
    /// left unconfirmed may be settled by it (WorkspaceModel.settleStaleChoice).
    @ObservationIgnored public var controlRead: (ChatKey) -> Void = { _ in }
    /// Attachments, references and settings bound to the next message; throws why a send cannot go yet.
    @ObservationIgnored public var extras: () throws -> JSONValue = { [:] }
    /// The settings bound to the next message (Codex), what a plan is carried out with.
    @ObservationIgnored public var boundSettings: () -> JSONValue = { [:] }
    @ObservationIgnored public var sentExtras: (ChatKey, JSONValue) -> Void = { _, _ in }
    @ObservationIgnored public var restoreExtras: (ChatKey, JSONValue) throws -> Void = { _, _ in }
    /// A conversation was left with these words in its box (the list's 草稿 follows; not on every key).
    @ObservationIgnored public var draftLeft: (ChatKey, String) -> Void = { _, _ in }
    /// A send was first taken by the computer (已接收 / 已送达 / 已排队): the island for it starts (AppModel+Island).
    @ObservationIgnored public var acknowledgedSend: (Submission) -> Void = { _ in }
    /// Asks the phone for a little time in the background while a send is under way (spec 6.10); [expired] runs
    /// when that time is up. Returns the call that gives the time back.
    /// 诊断测速 (开发者选项): a send's time and what it came to, as the web words it.
    @ObservationIgnored public var timed: (_ label: String, _ elapsed: Duration, _ outcome: String) -> Void = { _, _, _ in }
    @ObservationIgnored public var backgroundTime: (_ expired: @escaping @MainActor @Sendable () -> Void) -> (@MainActor () -> Void) = { _ in {} }

    @ObservationIgnored let pacer: any Pacer
    @ObservationIgnored let store: LocalStore?
    @ObservationIgnored let newID: @Sendable () -> String
    @ObservationIgnored let now: @Sendable () -> Int64
    @ObservationIgnored var client: RelayClient?
    @ObservationIgnored var clientGeneration = -1
    @ObservationIgnored var foreground = false
    @ObservationIgnored var synthetic = false
    @ObservationIgnored var task: Task<Void, Never>?
    @ObservationIgnored var token = 0
    @ObservationIgnored var retryDelay: Duration = .seconds(1)
    @ObservationIgnored var onFrame: (LiveFrame, ChatKey) -> Void = { _, _ in }
    /// Drafts by conversation, as typed (Android memory); the store gets them about 0.3 s later.
    @ObservationIgnored var memory: [ChatKey: String] = [:]
    @ObservationIgnored var draftVersions: [ChatKey: Int] = [:]
    @ObservationIgnored var pendingDraft: (key: ChatKey, text: String)?
    @ObservationIgnored var draftSave: Task<Void, Never>?
    /// Draft writes under way, one after another.
    @ObservationIgnored var flushing: Task<Void, Never>?
    /// The local demo keeps its sends here, never in the store.
    @ObservationIgnored var demo: [String: Submission] = [:]
    @ObservationIgnored var inFlight: Set<ChatKey> = []
    @ObservationIgnored var confirming: Set<String> = []
    @ObservationIgnored var sends: [String: Task<Void, Never>] = [:]
    /// A state read after an action (refreshControl), so tests can wait for it.
    @ObservationIgnored var refreshing: Task<Void, Never>?

    init(pacer: any Pacer, store: LocalStore? = nil, newID: @escaping @Sendable () -> String = { UUID().uuidString.lowercased() },
         now: @escaping @Sendable () -> Int64 = { Int64(Date().timeIntervalSince1970 * 1000) }) {
        self.pacer = pacer
        self.store = store
        self.newID = newID
        self.now = now
    }

    /// Waits for the current round, the sends under way and a state read after an action to stop (tests; a round
    /// waiting to reconnect never does).
    public func settle() async {
        await task?.value
        await settleSends()
        await refreshing?.value
    }

    /// Waits for the sends under way only (the live round may stay open).
    public func settleSends() async {
        while let send = sends.values.first {
            await send.value
            if sends.values.first == send { break }
        }
    }

    // MARK: Binding and the live side

    func bind(_ next: ChatKey?, client: RelayClient, clientGeneration: Int, active: Bool, synthetic: Bool,
              onFrame: @escaping (LiveFrame, ChatKey) -> Void) {
        if next == key && clientGeneration == self.clientGeneration && active == foreground && synthetic == self.synthetic { return }
        task?.cancel()
        token += 1
        let t = token
        let changed = next != key || clientGeneration != self.clientGeneration
        // Leaving the conversation or going to the background writes the draft now.
        if changed || !active { flushDraftSoon() }
        // The list's 草稿 follows the box just left; one whose draft was not read yet stays as the list has it.
        if next != key, let left = key, let words = memory[left] { draftLeft(left, words) }
        key = next
        self.client = client
        self.clientGeneration = clientGeneration
        foreground = active
        self.synthetic = synthetic
        self.onFrame = onFrame
        if changed {
            control = Control()
            connection = "实时连接未启动"
            revision = 0
            draft = next.flatMap { memory[$0] } ?? ""
            ready = false
            submitting = next.map { inFlight.contains($0) } ?? false
            submissions = []
            error = nil
            hint = ""
        }
        guard let next else { return }
        let restore = changed || !ready
        task = Task { [weak self] in await self?.run(next, client, t, restore: restore, active: active) }
    }

    func run(_ key: ChatKey, _ client: RelayClient, _ t: Int, restore: Bool, active: Bool) async {
        if restore {
            let draft = synthetic ? memory[key] ?? "" : await store?.draft(key) ?? ""
            let records = synthetic ? demo.values.filter { $0.key == key }.sorted { $0.created > $1.created }
                : await store?.submissions(key) ?? []
            guard t == token else { return }
            // A send that was under way when the app stopped is unknown now (B04).
            let shown = records.map { record -> Submission in
                var record = record
                if record.label == "提交中" && !inFlight.contains(key) { record.label = "送达状态待确认" }
                return record
            }
            if memory[key] == nil || memory[key] == "" { memory[key] = draft }
            self.draft = memory[key] ?? draft
            draftReset += 1
            ready = true
            submissions = shown
        }
        guard active else {
            connection = "已暂停实时连接"
            control.available = false
            return
        }
        retryDelay = .seconds(1)
        while !Task.isCancelled && t == token {
            do {
                connection = "正在核对实时状态"
                control.available = false
                let state = try await client.control(device: key.device, app: key.app, chat: key.chat)
                guard t == token else { return }
                take(state, key)
                // Recovery reads receipts only; nothing is sent again.
                for record in submissions where unsettledLabels.contains(record.label) || record.action == "stop" {
                    try? await reconcile(record, client)
                }
                guard t == token else { return }
                // The local demo has no live stream (Android: an empty flow).
                if synthetic {
                    connection = "本地固定场景"
                    return
                }
                try await withThrowingTaskGroup(of: Void.self) { group in
                    if key.app != "codex" {
                        let every: Duration = key.app == "claude" ? .seconds(5) : .milliseconds(2_500)
                        group.addTask { [weak self] in try await self?.poll(key, client, t, every) }
                    }
                    group.addTask { [weak self] in try await self?.listen(key, client, t) }
                    // The stream ending (or failing) ends the round; polling stops with it.
                    _ = try await group.next()
                    group.cancelAll()
                }
                guard t == token else { return }
                connection = "实时连接已结束"
                return
            } catch is CancellationError {
                return
            } catch {
                guard t == token else { return }
                let status = (error as? ServiceFailure)?.status
                connection = status == 401 ? "登录失效，请返回账号页重新登录" : "连接中断，正在重连"
                control.available = false
                if let status, [401, 403, 404].contains(status) { return }
                do { try await pacer.wait(retryDelay) } catch { return }
                retryDelay = min(retryDelay * 2, .seconds(15))
            }
        }
    }

    func listen(_ key: ChatKey, _ client: RelayClient, _ t: Int) async throws {
        for try await frame in try client.events(device: key.device, app: key.app, chat: key.chat) {
            guard t == token else { return }
            onFrame(frame, key)
            if connection != "实时连接正常" { connection = "实时连接正常" }
            if let incoming = frame.control {
                take(incoming, key)
                // A stop waiting on its turn, or a queued send that left the queue: its receipt says what happened.
                for record in submissions where record.action == "stop" && record.label.contains("等待")
                    || record.label == "已排队" && !incoming.queued.contains(where: { $0.id == record.request }) {
                    try? await reconcile(record, client)
                }
            }
            if !frame.messages.isEmpty { revision += 1 }
            retryDelay = .seconds(1)
        }
    }

    func poll(_ key: ChatKey, _ client: RelayClient, _ t: Int, _ every: Duration) async throws {
        while !Task.isCancelled {
            try await pacer.wait(every)
            if pollPaused() { continue }
            let state = try await client.control(device: key.device, app: key.app, chat: key.chat, fresh: false)
            if t == token { take(state, key) }
            // Claude keeps no receipts: its queued and unconfirmed sends are looked for in its record (web pollReceipts).
            if key.app == "claude" {
                for record in claudePending(key) { try? await reconcile(record, client) }
            }
        }
    }

    /// Claude sends of the last half hour still queued or unconfirmed, newest eight.
    func claudePending(_ key: ChatKey) -> [Submission] {
        Array(submissions.filter { record in
            record.app == "claude" && record.chat == key.chat && record.action == "send" && ["已排队", "送达状态待确认"].contains(record.label)
                && !confirming.contains(record.request) && now() - record.created < 30 * 60_000 && jsonValue(record.body).has(SendNote.claudeOffset)
        }.prefix(8))
    }

    /// Reads the source's state once, e.g. after a question was answered or a setting changed.
    public func refreshControl() {
        guard let key, let client else { return }
        let t = token
        refreshing = Task { [weak self] in
            guard let fresh = try? await client.control(device: key.device, app: key.app, chat: key.chat), let self, t == self.token else { return }
            self.take(fresh, key)
        }
    }

    /// A state the computer sent back with an action (Claude settings): shown as read, no second request.
    public func applyState(_ key: ChatKey, _ raw: JSONValue) {
        guard self.key == key else { return }
        take(parseControl(raw), key)
    }

    /// A state read for the conversation on screen ([key]) is kept and handed on. A read that brings nothing new (most
    /// of the polls, DeepSeek's every 2.5 s) writes nothing, so the page is not told of it: a long page is costly to
    /// redraw. (@Observable as Swift 6.4 expands it already skips an equal value; this keeps it so whatever compiles it.)
    func take(_ incoming: Control, _ key: ChatKey) {
        let merged = mergeControl(previous: control, incoming: incoming)
        if merged != control { control = merged }
        controlRead(key)
    }

    // MARK: The draft (spec B10)

    public func edit(_ text: String) {
        guard let key, ready else { return }
        memory[key] = text
        draftVersions[key, default: 0] += 1
        draft = text
        if !text.isEmpty { hint = "" }
        guard !synthetic else { return }
        pendingDraft = (key, text)
        draftSave?.cancel()
        draftSave = Task { [weak self] in
            guard let pacer = self?.pacer else { return }
            do { try await pacer.wait(.milliseconds(300)) } catch { return }
            self?.flushDraftSoon()
        }
    }

    /// Writes a draft typed in the last 0.3 s now and waits for the writes under way (going to the background).
    public func flushDraft() async {
        flushDraftSoon()
        await flushing?.value
    }

    /// Starts writing the draft typed in the last 0.3 s, after the writes already under way.
    func flushDraftSoon() {
        draftSave?.cancel()
        draftSave = nil
        guard let pending = pendingDraft else { return }
        pendingDraft = nil
        let store = store
        let previous = flushing
        flushing = Task {
            await previous?.value
            await store?.setDraft(pending.key, pending.text)
        }
    }

    /// Replaces the draft and pushes it into the text field (常用提示语).
    public func replaceDraft(_ text: String) {
        guard ready else { return }
        edit(text)
        draftReset += 1
    }

    /// A new conversation's page became the conversation: what was written there goes to the conversation's draft,
    /// after anything already there.
    public func moveDraft(from: ChatKey, to: ChatKey) async {
        await flushDraft()
        let synthetic = synthetic
        let stored = synthetic ? "" : await store?.draft(from) ?? ""
        let text = (memory[from] ?? stored).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        let storedThere = synthetic ? "" : await store?.draft(to) ?? ""
        let there = memory[to] ?? storedThere
        let kept = there.replacingOccurrences(of: "\\s+$", with: "", options: .regularExpression)
        let next = kept.isEmpty ? text : kept + "\n" + text
        memory[to] = next
        memory[from] = nil
        guard !synthetic else { return }
        await store?.setDraft(to, next)
        await store?.setDraft(from, "")
    }

    /// Voice's words where the cursor was (web voice-ui.js insert), into the conversation they were said for only.
    public func insertVoice(_ expected: ChatKey, _ text: String, start: Int, end: Int? = nil) -> VoicePlacement? {
        guard key == expected, ready, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        let placed = placeDictation(draft, text, start: start, end: end)
        edit(placed.draft)
        draftReset += 1
        return placed
    }

    /// Swaps voice's words for others (整理, or its 撤销), only while they are still there as they were.
    public func swapVoice(_ expected: ChatKey, _ placed: VoicePlacement, with text: String) -> VoicePlacement? {
        guard key == expected, ready, let next = swapDictation(draft, placed, with: text) else { return nil }
        edit(next.draft)
        draftReset += 1
        return next
    }

    /// Puts the cursor in the box with [hint] showing (继续修改 a Codex plan).
    public func focusInput(hint: String) {
        focus += 1
        self.hint = hint
    }

    /// 恢复草稿 / 恢复提交快照: a send's words (and what went with it) back in an empty box.
    public func restore(_ record: Submission) {
        guard let key, key == record.key, draft.isEmpty else { return }
        do {
            try restoreExtras(key, jsonValue(record.body))
            edit(record.text)
            draftReset += 1
        } catch {
            self.error = describe(error)
        }
    }

    // MARK: Sending, stopping and the queue (spec B03–B06)

    public func send(queue: Bool = false) { submit("send", queue: queue) }

    /// 执行计划: Codex carries out the plan it made, in normal mode (web codex-ui.js send(planId)); the draft stays.
    public func executePlan(_ plan: String) { submit("send", plan: plan) }

    public func stop() { submit("stop") }

    /// 撤回 a queued send.
    public func cancel(_ message: String) { submit("queue-action", message: message) }

    /// 立即补充: hands a queued send to the running turn (B05). Claude does this with a desktop token instead.
    public func promote(_ message: String) { submit("queue-action", message: message, promote: true) }

    func submit(_ action: String, queue: Bool = false, message: String = "", promote: Bool = false, plan: String? = nil) {
        guard let key, let client else { return }
        let planned = plan != nil
        let words = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        if action == "send", !planned, submissions.contains(where: { $0.action == "send" && $0.text.trimmingCharacters(in: .whitespacesAndNewlines) == words && ["提交中", "送达状态待确认"].contains($0.label) }) {
            error = "相同内容的原提交尚待确认，请先核对状态，不能重复发送。"
            return
        }
        let extra: JSONValue
        do {
            extra = action == "send" && !planned ? try extras() : [:]
        } catch {
            self.error = describe(error)
            return
        }
        let hasExtras = !extra["attachments"].array.isEmpty || !extra["references"].array.isEmpty
        // Claude's message goes while the computer shows another conversation: the computer opens it (web sendConv).
        let reachable = control.available || action == "send" && !planned && !promote && sendsWhileAway(key.app)
        guard foreground, ready, reachable, !inFlight.contains(key) else { return }
        if action == "send" && !planned && (words.isEmpty && !hasExtras || words.count > 20_000 || queue && !control.queueAvailable)
            || action == "stop" && !control.running || promote && !control.running || planned && (key.app != "codex" || control.running) {
            return
        }
        inFlight.insert(key)
        let rid = newID()
        var body: [String: JSONValue] = ["id": .string(key.chat)]
        switch action {
        case "send":
            if let plan {
                // The settings bound to the next message, or the conversation's own, in normal mode; Codex checks
                // the plan is still its latest.
                let bound = boundSettings()
                let current = control.raw["settings"].isObject ? control.raw["settings"] : [:]
                var settings = (bound["settings"].isObject ? bound["settings"] : current).object
                settings["mode"] = "default"
                body["request_id"] = .string(rid)
                body["text"] = "请执行这份计划。"
                body["intent"] = "auto"
                body["plan_id"] = .string(plan)
                body["attachments"] = []
                body["settings"] = .object(settings)
                body["expected_settings"] = bound["expected_settings"].isObject ? bound["expected_settings"] : current
            } else {
                body["request_id"] = .string(rid)
                body["text"] = .string(words)
                body["intent"] = .string(queue ? "queue" : control.running ? "steer" : "auto")
                if control.running { body["expected_turn"] = .string(control.turn) }
                for (name, value) in extra.object { body[name] = value }
            }
        case "stop":
            body["operation_id"] = .string(rid)
            body["turn_id"] = .string(control.turn)
        default:
            body["request_id"] = .string(rid)
            body["message_id"] = .string(message)
            body["action"] = .string(promote ? "promote" : "cancel")
            if promote { body["expected_turn"] = .string(control.turn) }
        }
        let text = planned ? "执行计划" : action == "send" ? draft : action == "stop" ? "停止当前轮次" : promote ? "立即补充" : "取消排队"
        let record = Submission(request: rid, key: key, text: text, action: action, turn: control.turn, body: jsonText(.object(body)), created: now())
        // The draft version and the binding are taken now: edits made while the request starts are newer than it.
        let binding = token
        let version = draftVersions[key] ?? 0
        let clearDraft = action == "send" && !planned
        if clearDraft, pendingDraft?.key == key {
            // The copy's write clears the draft; an older draft must not land after it.
            draftSave?.cancel()
            pendingDraft = nil
        }
        submitting = true
        error = nil
        if planned { hint = "" }
        // Spelled out: in `c ? v : nil` the nil is JSONValue.null, a value.
        let sent: JSONValue?
        if clearDraft {
            sent = extra
        } else if planned {
            sent = ["settings": [:]]
        } else {
            sent = nil
        }
        let synthetic = synthetic
        let give = backgroundTime { [weak self] in self?.sends[rid]?.cancel() }
        sends[rid] = Task { [weak self] in
            await self?.dispatch(key, client, action, .object(body), record, synthetic: synthetic, binding: binding, version: version,
                                 clearDraft: clearDraft, extra: sent)
            self?.sends[rid] = nil
            give()
        }
    }

    /// Keeps the copy first, then posts once; never posts again by itself (B03, B04). Cut off (no background time
    /// left), the send becomes 送达状态待确认.
    func dispatch(_ key: ChatKey, _ client: RelayClient, _ action: String, _ body: JSONValue, _ record: Submission, synthetic: Bool,
                  binding: Int, version: Int, clearDraft: Bool, extra: JSONValue?) async {
        var began = false
        defer {
            inFlight.remove(key)
            if self.key == key { submitting = false }
        }
        do {
            if synthetic {
                demo[record.request] = record
            } else {
                // A draft write already under way lands first, so the copy's cleared draft is the last word.
                await flushing?.value
                await store?.begin(record)
            }
            began = true
            if let extra { sentExtras(key, extra) }
            // Only the exact draft that was sent is cleared; newer edits stay.
            let clear = clearDraft && (draftVersions[key] ?? 0) == version
            if clear { memory[key] = "" }
            if self.key == key {
                if clear {
                    draft = ""
                    draftReset += 1
                }
                submissions = [record] + submissions.filter { $0.request != record.request }
            }
            try Task.checkCancellation()
            let started = ContinuousClock.now
            let result: JSONValue
            do {
                result = try await client.command(device: key.device, app: key.app, route: action, body: body)
            } catch {
                if action == "send" { timed("消息提交", ContinuousClock.now - started, (error as? ServiceFailure).map { "HTTP \($0.status)" } ?? "网络失败") }
                throw error
            }
            if action == "send" { timed("消息提交", ContinuousClock.now - started, speedOutcome(result)) }
            if action != "stop", key.app == "codex", result["request_id"].string() != record.request { throw ReadFailure("回执身份不匹配") }
            if action == "send", key.app == "claude", result["pressed"].bool() {
                // The computer pressed Enter in Claude's box; whether Claude read it is looked for in its record.
                var notes = jsonValue(record.body).object
                notes[SendNote.claudeOffset] = .number(Double(result["offset"].int64()))
                let check = result["check_text"].string()
                notes[SendNote.claudeCheckText] = .string(check.isEmpty ? body["text"].string() : check)
                var pressed = record
                pressed.label = "已接收"
                pressed.body = jsonText(.object(notes))
                await save(pressed, synthetic)
                Task { [weak self] in await self?.confirmClaude(pressed, client, synthetic) }
            } else {
                var done = record
                if action == "stop" && result["ended"].bool() {
                    done.label = "该轮已结束"
                } else {
                    let state = result["delivery_state"].string()
                    done.label = receiptLabel(state: state.isEmpty ? (result["accepted"].bool() ? "accepted" : "unknown") : state, result: result, action: action)
                }
                await save(done, synthetic)
            }
            if let fresh = try? await client.control(device: key.device, app: key.app, chat: key.chat), binding == token, foreground, self.key == key {
                take(fresh, key)
            }
        } catch {
            if began {
                let failure = error as? ServiceFailure
                var kept = record
                if let failure, failure.notSubmitted {
                    var notes = jsonValue(record.body).object
                    notes[SendNote.sendError] = .string(failure.message)
                    if !failure.draft.isEmpty { notes[SendNote.desktopDraft] = .string(failure.draft) }
                    kept.body = jsonText(.object(notes))
                    kept.label = "未接收"
                } else {
                    kept.label = "送达状态待确认"
                }
                await save(kept, synthetic)
            } else if self.key == key {
                self.error = "无法保存提交快照，尚未发送。"
            }
        }
    }

    /// Looks for a Claude send in its record for about 25 s, as the web does after Enter: read, queued, or still
    /// unconfirmed. A real computer is asked every 1.5 s; the demo answers at once.
    func confirmClaude(_ record: Submission, _ client: RelayClient, _ synthetic: Bool) async {
        guard confirming.insert(record.request).inserted else { return }
        defer { confirming.remove(record.request) }
        var queued = false
        for _ in 0..<17 {
            if !synthetic {
                do { try await pacer.wait(.milliseconds(1_500)) } catch { return }
            }
            guard let found = try? await claudeCheck(record, client) else { continue }
            if found["delivered"].bool() {
                var delivered = record
                delivered.label = "已送达"
                await save(delivered, synthetic)
                return
            }
            if found["queued"].bool() && !queued {
                queued = true
                var waiting = record
                waiting.label = "已排队"
                await save(waiting, synthetic)
            }
        }
        var last = record
        last.label = queued ? "已排队" : "送达状态待确认"
        await save(last, synthetic)
    }

    func claudeCheck(_ record: Submission, _ client: RelayClient) async throws -> JSONValue? {
        let body = jsonValue(record.body)
        guard body.has(SendNote.claudeOffset) else { return nil }
        return try await client.detail(device: record.device, route: "chat/check",
                                       body: ["app": "claude", "id": .string(record.chat), "offset": .number(Double(body[SendNote.claudeOffset].int64())),
                                              "text": .string(body[SendNote.claudeCheckText].string())])
    }

    func save(_ record: Submission, _ synthetic: Bool) async {
        if synthetic { demo[record.request] = record } else { await store?.saveSubmission(record) }
        guard key == record.key else { return }
        let before = submissions.first { $0.request == record.request }?.label
        submissions = ([record] + submissions.filter { $0.request != record.request }).sorted { $0.created > $1.created }
        if before == "提交中" || before == nil, ["已接收", "已送达", "已排队"].contains(record.label), record.action == "send" {
            acknowledged += 1
            acknowledgedSend(record)
        }
    }

    /// 核对: reads the receipt of [record] again; never sends it again.
    public func check(_ record: Submission) {
        guard let client, key == record.key else { return }
        Task { [weak self] in
            do {
                try await self?.reconcile(record, client)
            } catch {
                if self?.key == record.key { self?.error = "核对失败，原提交仍保留；不会自动重发。" }
            }
        }
    }

    func reconcile(_ record: Submission, _ client: RelayClient) async throws {
        let synthetic = synthetic
        if record.app == "claude" && record.action == "send" {
            // No receipts for Claude: what its record shows decides, and nothing is sent again.
            guard let found = try await claudeCheck(record, client) else { return }
            let label = found["delivered"].bool() ? "已送达" : found["queued"].bool() ? "已排队" : record.label
            if label != record.label {
                var next = record
                next.label = label
                await save(next, synthetic)
            }
            return
        }
        let response = try await client.receipt(device: record.device, app: record.app, chat: record.chat, request: record.request)
        let echoed = response["request_id"].string()
        guard echoed == record.request || echoed.isEmpty && response["state"].string() == "unknown" else { throw ReadFailure("回执身份不匹配") }
        var label = receiptLabel(state: response["state"].string(), result: response["result"], action: record.action)
        if record.action == "stop" {
            let state = try await client.control(device: record.device, app: record.app, chat: record.chat)
            switch state.turns[record.turn] {
            case "interrupted": label = "已停止"
            case "completed": label = "该轮已完成"
            case "failed": label = "该轮失败"
            default: break
            }
        }
        var next = record
        next.label = label
        await save(next, synthetic)
    }

    /// 移除: takes a send that went nowhere off the list; the computer is not asked anything.
    public func dismiss(_ record: Submission) {
        guard record.label != "提交中" else { return }
        var removed = record
        removed.label = removedLabel
        let synthetic = synthetic
        Task { [weak self] in await self?.save(removed, synthetic) }
    }

    /// 换掉电脑上的「…」再发 (web resendReplacing): Claude turned the message away because its box on the computer
    /// held other text. The same message goes again, naming exactly that text to replace; nothing else is touched.
    public func resendReplacing(_ record: Submission) {
        guard let key, let client else { return }
        let old = jsonValue(record.body)
        let box = old[SendNote.desktopDraft].string()
        guard key.app == "claude", key == record.key, !box.isEmpty, record.label == "未接收" else { return }
        guard foreground, ready, control.available, !inFlight.contains(key) else { return }
        inFlight.insert(key)
        let rid = newID()
        var body = old.object
        for note in SendNote.all { body[note] = nil }
        body["request_id"] = .string(rid)
        body["replace_draft"] = .string(String(box.prefix(2_000)))
        let next = Submission(request: rid, key: key, text: record.text, action: "send", turn: control.turn, body: jsonText(.object(body)), created: now())
        submitting = true
        error = nil
        let synthetic = synthetic
        let binding = token
        let version = draftVersions[key] ?? 0
        var removed = record
        removed.label = removedLabel
        let give = backgroundTime { [weak self] in self?.sends[rid]?.cancel() }
        sends[rid] = Task { [weak self] in
            await self?.save(removed, synthetic)
            await self?.dispatch(key, client, "send", .object(body), next, synthetic: synthetic, binding: binding, version: version,
                                 clearDraft: false, extra: nil)
            self?.sends[rid] = nil
            give()
        }
    }
}
