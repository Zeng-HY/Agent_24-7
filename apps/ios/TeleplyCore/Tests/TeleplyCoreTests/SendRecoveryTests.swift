import Foundation
import Testing
@testable import TeleplyDemo
import TeleplyModel
@testable import TeleplyState

/// A computer whose receipt answers what a test chose and whose send is accepted under the request id it was given;
/// keeps every request, so a test can look at what went out. Its live stream stays open, as CommandComputer's does.
final class RecoveryComputer: RelayStreamingTransport, @unchecked Sendable {
    /// The receipt's answer (`state`, and `missing` when the test wants it).
    let receipt: JSONValue
    /// When set, /send fails with this status and the computer's own sentence instead of accepting.
    let sendFailure: (status: Int, text: String)?
    let log = RequestLog()

    private let streams = Mutexed<[AsyncThrowingStream<[UInt8], any Error>.Continuation]>([])

    init(receipt: JSONValue, sendFailure: (status: Int, text: String)? = nil) {
        self.receipt = receipt
        self.sendFailure = sendFailure
    }

    func send(_ request: RelayRequest) async throws -> RelayResponse {
        await log.add(request)
        let path = request.url.path
        if path.hasSuffix("/state") {
            return .json(#"{"available":true,"running":false,"active_turn_id":"","queue_available":true}"#)
        }
        if path.hasSuffix("/api/chat/send") {
            // Claude takes a send by pressing Enter in its box; 11-26 its resend goes the same way.
            if let sendFailure {
                return .json(Self.text(["error": .string(sendFailure.text), "code": "already_submitted"]), status: sendFailure.status)
            }
            let body = (try? JSONValue.parse(request.body ?? Data())) ?? [:]
            return .json(Self.text(["request_id": .string(body["request_id"].string()), "pressed": true,
                                    "offset": .number(100), "check_text": .string(body["text"].string()),
                                    "accepted_at": .number(1_700_000_000_000)]))
        }
        if path.hasSuffix("/send") {
            if let sendFailure {
                return .json(Self.text(["error": .string(sendFailure.text), "code": "already_submitted"]), status: sendFailure.status)
            }
            let body = (try? JSONValue.parse(request.body ?? Data())) ?? [:]
            return .json(Self.text(["request_id": .string(body["request_id"].string()), "delivery_state": "accepted",
                                    "accepted_at": .number(1_700_000_000_000)]))
        }
        if path.hasSuffix("/receipt") {
            return .json(Self.text(receipt))
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

/// 11-26 (handoff §3.1): a send the computer's delivery records know nothing of can be sent again under its own
/// request id; a send whose result is unknown can go back in the box as a new request, or off the list. Nothing is
/// resent by itself.
@MainActor
struct SendRecoveryTests {
    let key = ChatKey(scope: "account", device: String(repeating: "a", count: 32), app: "codex", chat: "chat")
    let request = "request-to-send-again"
    let words = "重发这一条"

    func sendRecord(label: String = missingLabel) -> Submission {
        let body: [String: JSONValue] = ["id": .string(key.chat), "request_id": .string(request), "text": .string(words),
                                         "intent": "auto", "expected_turn": .string("turn-1")]
        return Submission(request: request, key: key, text: words, action: "send", turn: "turn-1",
                          body: RecoveryComputer.text(.object(body)), label: label, created: 1_000)
    }

    func open(_ computer: RecoveryComputer, store: LocalStore, copy: Submission) async -> ChatModel {
        await store.saveSubmission(copy)
        let chat = ChatModel(pacer: IdlePacer(), store: store, newID: { "a-new-request" }, now: { 2_000 })
        chat.bind(key, client: RelayClient(origin: .default, transport: computer), clientGeneration: 0, active: true, synthetic: false) { _, _ in }
        return chat
    }

    /// Lets the model's tasks run until [done] holds (or gives up after a while), as ChatModelTests.until does.
    func until(_ done: @MainActor () -> Bool) async {
        for _ in 0..<2_000 {
            if done() { return }
            await Task.yield()
        }
    }

    @Test func aMissingReceiptMeansTheComputerNeverGotTheSend() {
        #expect(receiptLabel(state: "unknown", result: [:], action: "send", missing: true) == missingLabel)
        // Only an unknown answer without `missing` is no news yet (an older computer, or one that cannot read the
        // delivery records).
        #expect(receiptLabel(state: "unknown", result: [:], action: "send") == unknownReceiptLabel)
        // Every other answer keeps its own words, `missing` or not; only a send can be sent again, so only it says
        // 电脑没收到 (Android's receiptLabel reads it the same way).
        #expect(receiptLabel(state: "accepted", result: [:], action: "send", missing: true) == "已接收")
        #expect(receiptLabel(state: "queued", result: [:], action: "send") == "已排队")
        #expect(receiptLabel(state: "rejected", result: [:], action: "send") == "未接收")
        #expect(receiptLabel(state: "unknown", result: [:], action: "stop", missing: true) == unknownReceiptLabel)
        #expect(agentReceiptLabel(state: "unknown", result: ["delivered": false], action: "send", missing: true) == missingLabel)
        #expect(agentReceiptLabel(state: "unknown", result: ["queued": true], action: "send") == "已排队")
    }

    /// 11-26 (handoff §3.1 point 5): the one line 核对 leaves is worded from the receipt's own state and `missing`,
    /// not from the label a send kept; Claude's own record words its line (the same words Android uses).
    @Test func theCheckLineFollowsTheReceiptItself() {
        #expect(checkResultText(state: "unknown", missing: true, label: missingLabel) == "已核对：电脑没收到")
        #expect(checkResultText(state: "unknown", missing: false, label: unknownReceiptLabel) == "已核对：电脑查不到这条的记录")
        #expect(checkResultText(state: "dispatching", missing: false, label: unknownReceiptLabel) == "已核对：电脑收到了，还在处理")
        #expect(checkResultText(state: "accepted", missing: false, label: "已停止") == "已核对：已停止")
        #expect(checkResultText(state: "accepted", missing: false, label: "已送达") == "已核对：已送达")
        #expect(claudeCheckResultText(delivered: true, queued: false) == "已核对：已送达")
        #expect(claudeCheckResultText(delivered: false, queued: true) == "已核对：已排队")
        #expect(claudeCheckResultText(delivered: false, queued: false) == "已核对：Claude 的记录里还没看到这条")
    }

    /// 11-26: Claude's sends share the computer's delivery record with Codex, so its receipt can say `missing` too;
    /// then the same request id and body go again, and the answer goes through Claude's Enter (`pressed`) path.
    @Test func aClaudeSendTheComputerNeverGotIsMissingAndCanGoAgain() async {
        var claude = key
        claude.app = "claude"
        claude.chat = "claude-chat"
        let store = LocalStore(folder: temporaryFolder())
        let computer = RecoveryComputer(receipt: ["state": "unknown", "missing": true])
        let copy = Submission(request: request, key: claude, text: words, action: "send", turn: "turn-1",
                              body: RecoveryComputer.text(.object(["id": .string(claude.chat), "request_id": .string(request),
                                                                  "text": .string(words), "intent": "auto"])),
                              label: unknownReceiptLabel, created: 1_000)
        await store.saveSubmission(copy)
        let chat = ChatModel(pacer: IdlePacer(), store: store, newID: { "a-new-request" }, now: { 2_000 })
        chat.bind(claude, client: RelayClient(origin: .default, transport: computer), clientGeneration: 0, active: true, synthetic: false) { _, _ in }
        await until { chat.ready && chat.control.available }
        // The receipt comes first, at Claude's own address, and its `missing` makes the copy 电脑没收到.
        await until { chat.submissions.first?.label == missingLabel }
        #expect(chat.submissions.first?.label == missingLabel)
        let asked = await computer.log.items
        #expect(asked.contains { $0.url.path.hasSuffix("/api/agents/claude/receipt") })
        chat.resend(chat.submissions.first { $0.request == request }!)
        await chat.settleSends()
        let requests = await computer.log.items
        let posted = requests.first { $0.url.path.hasSuffix("/api/chat/send") }
        let body = (try? JSONValue.parse(posted?.body ?? Data())) ?? [:]
        #expect(body["request_id"].string() == request)
        #expect(body["text"].string() == words)
        #expect(chat.submissions.first?.label == "已接收")
    }

    @Test func resendingGoesOutUnderTheSameRequestIdAndContent() async {
        let store = LocalStore(folder: temporaryFolder())
        let computer = RecoveryComputer(receipt: ["state": "unknown", "missing": true])
        let chat = await open(computer, store: store, copy: sendRecord())
        await until { chat.ready && chat.control.available }
        await until { chat.submissions.contains(where: { $0.request == request && $0.label == missingLabel }) }
        // Opening the conversation checks the copy; it never sends anything again by itself.
        let before = await computer.log.items
        #expect(!before.contains { $0.url.path.hasSuffix("/send") })
        chat.resend(chat.submissions.first { $0.request == request }!)
        await chat.settleSends()
        let requests = await computer.log.items
        let posted = requests.first { $0.url.path.hasSuffix("/send") }
        let body = (try? JSONValue.parse(posted?.body ?? Data())) ?? [:]
        #expect(body["request_id"].string() == request)
        #expect(body["text"].string() == words)
        #expect(body["expected_turn"].string() == "turn-1")
        // The same copy, not a second one.
        #expect(chat.submissions.filter { $0.request == request }.count == 1)
        await until { chat.submissions.first?.label == "已接收" }
        #expect(chat.submissions.first?.label == "已接收")
    }

    @Test func anOldComputerThatCannotTellLeavesTheCopyAndSaysSo() async {
        let store = LocalStore(folder: temporaryFolder())
        let computer = RecoveryComputer(receipt: ["state": "unknown"])
        let chat = await open(computer, store: store, copy: sendRecord(label: unknownReceiptLabel))
        await until { chat.ready && chat.control.available }
        await until {
            guard let copy = chat.submissions.first else { return false }
            return chat.mayBeMissing(copy)
        }
        #expect(chat.submissions.first?.label == unknownReceiptLabel)
        #expect(chat.mayBeMissing(chat.submissions.first!))
    }

    @Test func restoringTheDraftTakesTheCopyOffTheList() async {
        let store = LocalStore(folder: temporaryFolder())
        let computer = RecoveryComputer(receipt: ["state": "unknown", "missing": true])
        let chat = await open(computer, store: store, copy: sendRecord())
        await until { chat.ready }
        chat.restoreAndRemove(chat.submissions.first { $0.request == request }!)
        #expect(chat.draft == words)
        await until { chat.submissions.first(where: { $0.request == request })?.label == removedLabel }
        #expect(chat.submissions.first { $0.request == request }?.label == removedLabel)
    }

    @Test func aComputerStillSettlingTheOldRequestPutsTheResendBackToWaiting() async {
        let store = LocalStore(folder: temporaryFolder())
        let sentence = "这次请求已提交过，结果尚未确认；请检查对话，不会重复发送"
        let computer = RecoveryComputer(receipt: ["state": "unknown", "missing": true], sendFailure: (409, sentence))
        let chat = await open(computer, store: store, copy: sendRecord())
        await until { chat.ready && chat.control.available }
        chat.resend(chat.submissions.first { $0.request == request }!)
        await chat.settleSends()
        #expect(chat.submissions.first?.label == unknownReceiptLabel)
        #expect(chat.error == sentence)
    }
}
