import Foundation
import Testing
@testable import TeleplyDemo
import TeleplyModel
@testable import TeleplyState

/// A Codex whose turn runs one command it may end: the state says so (handoff 11-27 §6.3), a send is taken with the
/// computer's own `server_ms` (or without it, as an older one), 结束命令 ends that one command or refuses with its
/// sentence, and every request is kept so a test can look at what went out.
final class SteerComputer: RelayStreamingTransport, @unchecked Sendable {
    let log = RequestLog()
    /// The computer's own count of the time it used, in milliseconds; nil plays an older computer that does not say.
    let serverMs: Int?
    /// When set, 结束命令 is refused with this status and sentence, and nothing is ended.
    let killRefusal: (status: Int, text: String)?
    /// What a receipt says: `state`, and whether the delivery records have no such request id.
    let receipt: (state: String, missing: Bool)
    /// Receipts answered in turn when a test wants them to change (the last one repeated); nil plays `receipt` alone.
    let receiptSequence: [JSONValue]?

    private let turn = Mutexed(true)
    private let ended = Mutexed(false)
    private let receiptStep = Mutexed(0)
    private let streams = Mutexed<[AsyncThrowingStream<[UInt8], any Error>.Continuation]>([])

    init(serverMs: Int? = 310, killRefusal: (status: Int, text: String)? = nil,
         receipt: (state: String, missing: Bool) = (state: "accepted", missing: false),
         receiptSequence: [JSONValue]? = nil) {
        self.serverMs = serverMs
        self.killRefusal = killRefusal
        self.receipt = receipt
        self.receiptSequence = receiptSequence
    }

    /// The turn runs, and the command with it, until a test ends it.
    var running: Bool { turn.withLock { $0 } }

    /// The one command was ended by 结束这条命令，马上插话.
    var killed: Bool { ended.withLock { $0 } }

    func endTurn() { turn.withLock { $0 = false } }

    func send(_ request: RelayRequest) async throws -> RelayResponse {
        await log.add(request)
        let path = request.url.path
        let body = (try? JSONValue.parse(request.body ?? Data())) ?? [:]
        var timing: [String: JSONValue] = [:]
        if let said = serverMs { timing["server_ms"] = .number(Double(said)) }
        if path.hasSuffix("/state") {
            var state: [String: JSONValue] = ["available": true, "running": .bool(running),
                                              "active_turn_id": .string(running ? "turn-1" : ""), "turn_id": "turn-1",
                                              "queue_available": true, "capabilities_now": ["kill_command": true]]
            if running, !killed {
                state["command"] = ["running": true, "since_ms": .number(1_764_000_000_000), "can_kill": true]
            }
            return .json(Self.text(.object(state)))
        }
        if path.hasSuffix("/kill-command") {
            if let killRefusal {
                return .json(Self.text(["error": .string(killRefusal.text), "not_submitted": true]), status: killRefusal.status)
            }
            ended.withLock { $0 = true }
            var reply: [String: JSONValue] = ["ok": true, "killed": true, "killed_pids": .array([.number(4_242)]),
                                              "text": "已结束命令，这一轮继续"]
            reply.merge(timing) { _, new in new }
            return .json(Self.text(.object(reply)))
        }
        if path.hasSuffix("/send") || path.hasSuffix("/queue-action") {
            var reply: [String: JSONValue] = ["request_id": .string(body["request_id"].string()), "accepted": true,
                                              "delivery_state": .string(body["intent"].string() == "queue" ? "queued" : "accepted")]
            reply.merge(timing) { _, new in new }
            return .json(Self.text(.object(reply)))
        }
        if path.hasSuffix("/receipt") {
            var reply: [String: JSONValue]
            if let sequence = receiptSequence, !sequence.isEmpty {
                let taken = receiptStep.withLock { step -> Int in
                    defer { step += 1 }
                    return min(step, sequence.count - 1)
                }
                reply = sequence[taken].object
            } else {
                reply = ["state": .string(receipt.state)]
                if receipt.missing { reply["missing"] = true }
            }
            reply["request_id"] = .string(queryValue(request, "request_id") ?? "")
            return .json(Self.text(.object(reply)))
        }
        return RelayResponse(status: 404)
    }

    func stream(_ request: RelayRequest) async throws -> RelayStream {
        let (chunks, continuation) = AsyncThrowingStream<[UInt8], any Error>.makeStream()
        streams.withLock { $0.append(continuation) }
        return RelayStream(status: 200, chunks: chunks)
    }

    static func text(_ value: JSONValue) -> String {
        String(decoding: (try? value.encoded()) ?? Data("{}".utf8), as: UTF8.self)
    }
}

/// 11-27 提速, line B (design §4.1 to §4.4): while the source runs a tap sends an interjection and a hold may queue; the
/// grey line says what an interjection waits for and counts the phone's own seconds; 结束这条命令，马上插话 shows only
/// when the state allows it; and each request is measured, the last numbers carried on for the computer's log.
@MainActor
struct SteerSpeedTests {
    let key = ChatKey(scope: "account", device: String(repeating: "a", count: 32), app: "codex", chat: "chat")

    /// A model on [computer], with a clock the test moves itself and request ids request-1, request-2…
    func open(_ computer: SteerComputer, clock: Mutexed<Int64>, store: LocalStore? = nil) async -> ChatModel {
        let ids = Mutexed(0)
        let model = ChatModel(pacer: IdlePacer(), store: store,
                              newID: { ids.withLock { $0 += 1; return "request-\($0)" } },
                              now: { clock.withLock { $0 } })
        model.bind(key, client: RelayClient(origin: .default, transport: computer), clientGeneration: 0, active: true,
                   synthetic: false) { _, _ in }
        await until { model.ready && model.control.available }
        return model
    }

    /// Lets the model's tasks run until [done] holds (or gives up after a while), as ChatModelTests.until does.
    func until(_ done: @MainActor () -> Bool) async {
        for _ in 0..<2_000 {
            if done() { return }
            await Task.yield()
        }
    }

    func control(_ text: String) -> Control {
        parseControl((try? JSONValue.parse(Data(text.utf8))) ?? [:])
    }

    func posted(_ requests: [RelayRequest], _ suffix: String) -> JSONValue {
        let found = requests.first { $0.url.path.hasSuffix(suffix) }
        return (try? JSONValue.parse(found?.body ?? Data())) ?? [:]
    }

    // MARK: §4.1 — a tap steers, a hold queues

    @Test func aTapWhileRunningSteersAndAHoldQueues() async {
        let computer = SteerComputer()
        let clock = Mutexed<Int64>(10_000)
        let model = await open(computer, clock: clock)
        #expect(model.control.running)
        // Codex takes both now, so a tap sends the interjection and a hold offers the queue.
        #expect(model.sendKey == SendKeyModes(steers: true, queues: true))
        #expect(!model.sendKey.tapQueues && model.sendKey.holdQueues)
        model.edit("顺便说一句")
        model.send()  // a tap
        await model.settleSends()
        model.edit("等这一轮完了再说")
        model.send(queue: true)  // the row under 按住
        await model.settleSends()
        let requests = await computer.log.items
        // Both go to the same route; only their `intent` tells the interjection from the queue.
        let sends = requests.filter { $0.url.path.hasSuffix("/api/codex/send") }
        guard sends.count == 2 else {
            Issue.record("a tap and a hold should have sent twice, not \(sends.count)")
            return
        }
        let tap = posted([sends[0]], "/api/codex/send")
        let held = posted([sends[1]], "/api/codex/send")
        #expect(tap["intent"].string() == "steer")
        #expect(tap["expected_turn"].string() == "turn-1")
        #expect(held["intent"].string() == "queue")
        #expect(model.submissions.first?.label == "已排队")
    }

    /// Only one of the two modes: a tap and a hold both do that one (design §4.1 point 4).
    @Test func oneModeOnlyIsWhatTheKeyDoes() {
        let queuesOnly = SendKeyModes(steers: false, queues: true)
        #expect(queuesOnly.tapQueues && !queuesOnly.holdQueues)
        let steersOnly = SendKeyModes(steers: true, queues: false)
        #expect(!steersOnly.tapQueues && !steersOnly.holdQueues)
        let idle = SendKeyModes()
        #expect(!idle.tapQueues && !idle.holdQueues)
        #expect(!idle.steers && !idle.queues)
    }

    // MARK: §4.2 — the grey line

    /// The line is only for an interjection the computer took: not for a queued one, not for an answer, not for a copy
    /// already delivered or taken off the list.
    @Test func theWaitingLineIsOnlyForAnInterjectionTheComputerTook() {
        func copy(_ label: String, intent: String = "steer", action: String = "send") -> Submission {
            let body: JSONValue = ["id": .string(key.chat), "request_id": "r", "text": "插一句", "intent": .string(intent)]
            return Submission(request: "r", key: key, text: "插一句", action: action, turn: "t",
                              body: SteerComputer.text(body), label: label, created: 1_000)
        }
        #expect(steerWaiting(copy("已接收")))
        #expect(!steerWaiting(copy("已排队")))
        #expect(!steerWaiting(copy("已送达")))
        #expect(!steerWaiting(copy(removedLabel)))
        #expect(!steerWaiting(copy("已接收", intent: "auto")))
        #expect(!steerWaiting(copy("已接收", intent: "queue")))
        #expect(!steerWaiting(copy("已接收", action: "queue-action")))
        #expect(steerWaitingText(name: "Codex", seconds: 3) == "等 Codex 做完这一步再插进去 · 已等 3 秒")
        #expect(steerWaitingText(name: "Claude", seconds: -2) == "等 Claude 做完这一步再插进去 · 已等 0 秒")
    }

    /// The seconds are the phone's own, from the computer's answer; the line goes when the send is delivered, taken off
    /// the list, or the turn is over (handoff 11-27 §6.1: the phone's clock is never compared with the computer's).
    @Test func theWaitingLineCountsFromTheAnswerAndGoesWithTheTurn() async {
        let computer = SteerComputer()
        let clock = Mutexed<Int64>(10_000)
        let model = await open(computer, clock: clock)
        model.edit("插一句")
        model.send()
        await model.settleSends()
        guard let waiting = model.steerWait else {
            Issue.record("the interjection the computer took should be waiting")
            return
        }
        #expect(waiting.text == "插一句")
        #expect(model.steerWaitSeconds(waiting) == 0)
        clock.withLock { $0 = 13_400 }
        #expect(model.steerWaitSeconds(waiting) == 3)
        // Taken off the list: nothing waits any more.
        model.dismiss(waiting)
        await until { model.steerWait == nil }
        #expect(model.steerWait == nil)
        // A turn that is over waits for nothing either.
        computer.endTurn()
        model.refreshControl()
        await until { !model.control.running }
        #expect(model.steerWait == nil)
        #expect(model.sendKey == SendKeyModes())
    }

    /// 11-27 (S5; design §4.2 point 1): while an interjection waits, its receipt is read again every few seconds, so a
    /// send the computer's records now hold (accepted with `conversation_record`) turns into 已送达 and the line and the
    /// watch both stop — without waiting for the turn to end (the 11-27 morning's fifth and sixth messages went in at
    /// 7:54:47 while their turn ran past 8:01).
    @Test func aWaitingInterjectionIsDeliveredByTheReceiptWatch() async {
        let computer = SteerComputer(receiptSequence: [
            ["state": "accepted", "result": ["accepted": true, "evidence": ["source": "app_tools_ack"]]],
            ["state": "accepted", "result": ["accepted": true, "evidence": ["source": "conversation_record"]]],
        ])
        let pacer = CountingPacer(free: 8)
        let ids = Mutexed(0)
        let clock = Mutexed<Int64>(10_000)
        let model = ChatModel(pacer: pacer, newID: { ids.withLock { $0 += 1; return "request-\($0)" } },
                              now: { clock.withLock { $0 } })
        model.bind(key, client: RelayClient(origin: .default, transport: computer), clientGeneration: 0, active: true,
                   synthetic: false) { _, _ in }
        await until { model.ready && model.control.available }
        model.edit("插一句")
        model.send()
        await model.settleSends()
        // The first receipt still says app_tools_ack, the second one has the words in Codex's own record.
        await until { model.submissions.first?.label == "已送达" }
        #expect(model.submissions.first?.label == "已送达")
        #expect(model.steerWait == nil)
        #expect(pacer.waits.contains(.seconds(3)))
        // One at a time, and stopped once delivered: two receipts, then no more.
        let asked = await computer.log.items.filter { $0.url.path.hasSuffix("/receipt") }.count
        #expect(asked == 2)
        for _ in 0..<500 { await Task.yield() }
        #expect(await computer.log.items.filter { $0.url.path.hasSuffix("/receipt") }.count == asked)
    }

    // MARK: §4.3 — 结束这条命令，马上插话

    /// The button shows only while a command runs that the computer says it may end, and its capability table says
    /// `kill_command` now; an older computer, whose state has no `command`, never shows it (design §4.3 point 4).
    @Test func theKillButtonOnlyShowsWhileACommandMayBeEnded() {
        #expect(control(#"{"running":true,"command":{"running":true,"since_ms":1,"can_kill":true},"capabilities_now":{"kill_command":true}}"#).canKillCommand)
        #expect(!control(#"{"running":true,"command":{"running":true,"since_ms":1,"can_kill":false},"capabilities_now":{"kill_command":true}}"#).canKillCommand)
        #expect(!control(#"{"running":true,"command":{"running":false,"can_kill":true},"capabilities_now":{"kill_command":true}}"#).canKillCommand)
        #expect(!control(#"{"running":true,"capabilities_now":{"kill_command":true}}"#).canKillCommand)
        #expect(!control(#"{"running":true,"command":{"running":true,"since_ms":1,"can_kill":true}}"#).canKillCommand)
        #expect(!control(#"{"running":true,"command":{"running":true,"since_ms":1,"can_kill":true},"capabilities_now":{"kill_command":false}}"#).canKillCommand)
        #expect(control(#"{"command":{"running":true,"since_ms":1,"can_kill":true}}"#).command == RunningCommand(running: true, since: 1, canKill: true))
        #expect(killCommandConfirmText(name: "Codex") == "Codex 正在跑的这条命令会被结束，它的结果作废；你的话会马上交给 Codex。")
    }

    /// 结束命令 ends the one command and nothing else: the turn goes on, the words keep waiting, and the button goes.
    @Test func endingTheCommandEndsOnlyThatCommandAndSaysSo() async {
        let computer = SteerComputer()
        let model = await open(computer, clock: Mutexed<Int64>(10_000))
        #expect(model.control.canKillCommand)
        model.killCommand()
        await until { model.killNote != nil && !model.killing && !model.control.canKillCommand }
        #expect(model.killNote == killCommandStartedText)
        #expect(!model.killing)
        #expect(computer.killed)
        #expect(model.control.running)
        let requests = await computer.log.items
        let sent = posted(requests, "/api/agents/codex/kill-command")
        #expect(sent["id"].string() == key.chat)
        #expect(sent["turn_id"].string() == "turn-1")
    }

    @Test func aRefusedKillShowsTheComputersReason() async {
        let computer = SteerComputer(killRefusal: (409, "这条命令在沙盒里跑，不能结束"))
        let model = await open(computer, clock: Mutexed<Int64>(10_000))
        model.killCommand()
        await until { model.killNote != nil }
        #expect(model.killNote == "这条命令在沙盒里跑，不能结束")
        #expect(!computer.killed)
        #expect(model.control.canKillCommand)
    }

    // MARK: §4.4 — the phone's half of the timing

    @Test func theRoundTripAndTheNetworkAreWorkedOut() {
        let good = phoneTiming(request: "r1", elapsed: .milliseconds(820), reply: ["server_ms": .number(310)])
        #expect(good.roundtripMs == 820)
        #expect(good.serverMs == 310)
        #expect(good.networkMs == 510)
        #expect(timingWords(good) == "手机→电脑 0.5 秒 · 电脑处理 0.3 秒")
        // The phone's own count is never below zero, whatever the computer says.
        let behind = phoneTiming(request: "r2", elapsed: .milliseconds(200), reply: ["server_ms": 900])
        #expect(behind.networkMs == 0)
        // An older computer says nothing: no network time, nothing for the next send to carry on, the toast unchanged.
        let old = phoneTiming(request: "r3", elapsed: .milliseconds(500), reply: [:])
        #expect(old.serverMs == nil && old.networkMs == nil)
        #expect(timingWords(old) == "")
        #expect(clientPrev(old) == nil)
        let prev = clientPrev(good)
        #expect(prev?["request_id"].string() == "r1")
        #expect(prev?["roundtrip_ms"].int() == 820)
        #expect(prev?["server_ms"].int() == 310)
    }

    @Test func theNextSendCarriesTheLastRequestsNumbers() async {
        let computer = SteerComputer()
        let clock = Mutexed<Int64>(10_000)
        let model = await open(computer, clock: clock)
        model.edit("第一条")
        model.send()
        await model.settleSends()
        clock.withLock { $0 = 11_000 }
        model.edit("第二条")
        model.send()
        await model.settleSends()
        let requests = await computer.log.items.filter { $0.url.path.hasSuffix("/api/codex/send") }
        guard requests.count == 2 else {
            Issue.record("two sends should have gone out, not \(requests.count)")
            return
        }
        let first = posted(requests, "/api/codex/send")
        let second = posted([requests[1]], "/api/codex/send")
        #expect(first["client_sent_ms"].int64() == 10_000)
        #expect(!first.has("client_prev"))
        #expect(second["client_sent_ms"].int64() == 11_000)
        #expect(second["client_prev"]["request_id"].string() == first["request_id"].string())
        #expect(second["client_prev"]["server_ms"].int() == 310)
        #expect(second["client_prev"]["roundtrip_ms"].int() >= 0)
    }

    /// Handoff 11-27 §6.2, which the design stresses: 重发 must carry the request body as it first went out — the same
    /// `client_sent_ms` and `client_prev` — or the computer's fingerprint makes it a different request.
    @Test func aResendKeepsTheFirstRequestsNumbers() async {
        let store = LocalStore(folder: temporaryFolder())
        let computer = SteerComputer(receipt: (state: "unknown", missing: true))
        let body: JSONValue = ["id": .string(key.chat), "request_id": "sent-before", "text": "原样重发", "intent": "steer",
                               "client_sent_ms": .number(1_700_000_000_123),
                               "client_prev": ["request_id": "earlier", "roundtrip_ms": 820, "server_ms": 310]]
        let copy = Submission(request: "sent-before", key: key, text: "原样重发", action: "send", turn: "",
                              body: SteerComputer.text(body), label: missingLabel, created: 1_000)
        await store.saveSubmission(copy)
        let ids = Mutexed(0)
        let model = ChatModel(pacer: IdlePacer(), store: store, newID: { ids.withLock { $0 += 1; return "new-\($0)" } },
                              now: { 12_000 })
        model.bind(key, client: RelayClient(origin: .default, transport: computer), clientGeneration: 0, active: true,
                   synthetic: false) { _, _ in }
        await until { model.ready && model.submissions.first?.label == missingLabel }
        guard let kept = model.submissions.first else {
            Issue.record("the copy should still be on the list")
            return
        }
        model.resend(kept)
        await model.settleSends()
        let requests = await computer.log.items
        let sent = posted(requests, "/api/codex/send")
        #expect(sent["request_id"].string() == "sent-before")
        #expect(sent["client_sent_ms"].int64() == 1_700_000_000_123)
        #expect(sent["client_prev"]["request_id"].string() == "earlier")
        #expect(sent["client_prev"]["server_ms"].int() == 310)
    }

    // MARK: The demo behind -TeleplyDemoSteer

    /// 插话等待示例 shows both halves of §4.2 and §4.3 without a computer: a turn running one command it may end, and a
    /// state that says `kill_command`. Off by default, so the screenshot tour's rows and pages stay as they were.
    @Test func theDemoHasACommandItMayEndOnlyBehindItsSwitch() {
        let world = DemoWorld(steerDemo: true)
        let state = world.control(app: "codex", chat: SteerDemo.chat)
        let control = parseControl(state)
        #expect(control.running)
        #expect(control.canKillCommand)
        #expect(state["command"]["running"].bool() && state["command"]["can_kill"].bool())
        #expect(world.firstPage().contains { $0["id"].string() == SteerDemo.chat })
        #expect(!DemoWorld().firstPage().contains { $0["id"].string() == SteerDemo.chat })
        #expect(DemoData.messages(app: "codex", chat: SteerDemo.chat, steer: true).count == 3)
    }

    @Test func theDemoEndsItsOneCommandAndTheTurnGoesOn() {
        let world = DemoWorld(steerDemo: true)
        let transport = DemoTransport(world: world)
        let device = String(repeating: "a", count: 32)
        let reply = transport.computer(device, "/api/agents/codex/kill-command", [:], .post, ["id": .string(SteerDemo.chat)])
        #expect(reply.status == 200)
        #expect((try? JSONValue.parse(reply.body))?["killed"].bool() == true)
        let after = parseControl(world.control(app: "codex", chat: SteerDemo.chat))
        #expect(after.running && !after.canKillCommand)
        // A conversation with no command is refused the way the computer refuses.
        #expect(transport.computer(device, "/api/agents/codex/kill-command", [:], .post, ["id": .string("demo")]).status == 409)
    }
}
